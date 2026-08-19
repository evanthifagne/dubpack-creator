"""Serveur local de DubPack Creator (API + interface web)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import asr, dubpack, gamedir, media, picker, pipeline, separate, sources
from .config import (DEFAULT_MODEL, PROJECTS_DIR, WEB_DIR, capabilities)
from .jobs import manager

app = FastAPI(title="DubPack Creator", docs_url=None, redoc_url=None)

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = WEB_DIR / "index.html"
    if not page.exists():
        return HTMLResponse("<h1>Interface manquante</h1>", status_code=500)
    html = page.read_text(encoding="utf-8")
    # Empreinte des assets: après une mise à jour, le navigateur ne doit pas
    # rejouer l'ancien CSS/JS gardé en cache.
    for asset in ("styles.css", "app.js"):
        target = WEB_DIR / asset
        if target.exists():
            html = html.replace(f"/static/{asset}",
                                f"/static/{asset}?v={int(target.stat().st_mtime)}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/api/capabilities")
def get_capabilities() -> dict:
    caps = capabilities()
    caps["asr_engines"] = asr.available_engines()
    caps["demucs"] = separate.available()
    # find_spec ne suffit pas pour tkinter: l'extension C peut manquer.
    caps["picker"] = picker.available()
    return caps


# ---------------------------------------------------------------------------
# Projets
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def api_list_projects() -> list[dict]:
    return dubpack.list_projects()


def _load(project_id: str) -> dict:
    try:
        return dubpack.load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}")
def api_get_project(project_id: str) -> dict:
    project = _load(project_id)
    job = manager.active_for(project_id)
    project["_job"] = job.to_dict() if job else None
    return project


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: str) -> dict:
    folder = dubpack.project_dir(project_id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return {"deleted": project_id}


@app.put("/api/projects/{project_id}")
def api_update_project(project_id: str, payload: dict = Body(...)) -> dict:
    project = _load(project_id)
    for key in ("name", "pack", "characters", "lines", "options"):
        if key in payload:
            project[key] = payload[key]
    dubpack.save_project(project)
    return {"saved": True, "lines": len(project.get("lines", []))}


def _settings(payload: dict) -> dict:
    speakers = payload.get("speakers")
    try:
        speakers = int(speakers) if speakers not in (None, "", "auto", 0) else None
    except (TypeError, ValueError):
        speakers = None
    return {
        "model": payload.get("model") or DEFAULT_MODEL,
        "language": (payload.get("language") or "").strip() or None,
        "engine": payload.get("engine") or None,
        "speakers": speakers,
        "max_line": float(payload.get("max_line") or 9.0),
        "use_embeddings": bool(payload.get("use_embeddings", True)),
    }


@app.post("/api/projects/import")
async def api_import(
    request: Request,
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
    settings: str | None = Form(None),
) -> dict:
    """Crée un projet depuis un lien ou un fichier, puis lance toute la chaîne."""
    import json as _json

    payload: dict[str, Any] = {}
    if settings:
        try:
            payload = _json.loads(settings)
        except ValueError:
            payload = {}
    if url is None and file is None:
        body = await request.json()
        url = (body.get("url") or "").strip() or None
        payload = body.get("settings") or {}

    opts = _settings(payload)
    name = (payload.get("name") or "").strip()
    project = dubpack.new_project(name or "Dub Pack")
    folder = dubpack.project_dir(project["id"])
    folder.mkdir(parents=True, exist_ok=True)

    upload_path: Path | None = None
    if file is not None and file.filename:
        ext = Path(file.filename).suffix.lower() or ".mp4"
        upload_path = folder / f"upload{ext}"
        with upload_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
        await file.close()
        if not project["name"] or project["name"] == "Dub Pack":
            project["name"] = sources.safe_name(Path(file.filename).stem, "Dub Pack")
            project["pack"]["title"] = project["name"]
    elif not url:
        raise HTTPException(status_code=400, detail="Fournis un lien vidéo ou un fichier.")
    elif not sources.is_url(url):
        raise HTTPException(status_code=400, detail="Ce lien n'est pas une URL http(s) valide.")

    dubpack.save_project(project)
    job = manager.create("import", project["id"])

    def work(job_ref, progress):
        proj = dubpack.load_project(project["id"])
        progress(0.01, "Récupération de la source")
        proj = pipeline.ingest(proj, url, upload_path, pipeline._scaled(progress, 0.01, 0.35))
        dubpack.save_project(proj)
        progress(0.36, "Transcription")
        proj = pipeline.analyze(proj, pipeline._scaled(progress, 0.36, 0.99), **opts)
        dubpack.save_project(proj)
        if upload_path and upload_path.exists():
            upload_path.unlink(missing_ok=True)
        return {"project_id": proj["id"], "lines": len(proj["lines"]),
                "characters": [c["name"] for c in proj["characters"]]}

    manager.run(job, work)
    return {"project_id": project["id"], "job": job.to_dict()}


@app.post("/api/projects/{project_id}/analyze")
def api_analyze(project_id: str, payload: dict = Body(default={})) -> dict:
    project = _load(project_id)
    if not project.get("source", {}).get("file"):
        raise HTTPException(status_code=400, detail="Ce projet n'a pas de source vidéo.")
    if manager.active_for(project_id):
        raise HTTPException(status_code=409, detail="Une tâche est déjà en cours sur ce projet.")
    opts = _settings(payload)
    keep = bool(payload.get("keep_names", True))
    job = manager.create("analyze", project_id)

    def work(job_ref, progress):
        proj = dubpack.load_project(project_id)
        proj = pipeline.analyze(proj, progress, keep_edits=keep, **opts)
        dubpack.save_project(proj)
        return {"lines": len(proj["lines"]),
                "characters": [c["name"] for c in proj["characters"]]}

    manager.run(job, work)
    return {"job": job.to_dict()}


@app.post("/api/projects/{project_id}/backing")
def api_backing(project_id: str, payload: dict = Body(default={})) -> dict:
    """Génère _backing_track.ogg (Demucs si dispo, sinon audio d'origine)."""
    project = _load(project_id)
    source = Path(project["source"]["file"])
    mode = payload.get("mode") or ("demucs" if separate.available() else "original")
    if mode == "demucs" and not separate.available():
        raise HTTPException(status_code=400, detail=separate.install_hint())
    if manager.active_for(project_id):
        raise HTTPException(status_code=409, detail="Une tâche est déjà en cours sur ce projet.")
    job = manager.create("backing", project_id)
    folder = dubpack.project_dir(project_id)

    def work(job_ref, progress):
        if mode == "demucs":
            path = separate.separate_backing(source, folder, cb=progress)
        else:
            path = separate.backing_from_source(source, folder, cb=progress)
        proj = dubpack.load_project(project_id)
        proj["assets"] = {**proj.get("assets", {}), "backing_track": str(path),
                          "backing_mode": mode}
        dubpack.save_project(proj)
        return {"backing_track": path.name, "mode": mode}

    manager.run(job, work)
    return {"job": job.to_dict()}


@app.delete("/api/projects/{project_id}/backing")
def api_drop_backing(project_id: str) -> dict:
    project = _load(project_id)
    assets = project.get("assets", {})
    assets.pop("backing_track", None)
    assets.pop("backing_mode", None)
    project["assets"] = assets
    dubpack.save_project(project)
    return {"removed": True}


@app.get("/api/projects/{project_id}/validate")
def api_validate(project_id: str) -> dict:
    project = _load(project_id)
    return {"issues": dubpack.validate(project)}


@app.post("/api/projects/{project_id}/export")
def api_export(project_id: str, payload: dict = Body(default={})) -> dict:
    project = _load(project_id)
    if payload:
        for key in ("pack", "options", "lines", "characters", "name"):
            if key in payload:
                project[key] = payload[key]
        dubpack.save_project(project)
    blocking = [i for i in dubpack.validate(project) if i["level"] == "error"]
    if blocking:
        raise HTTPException(status_code=400,
                            detail="; ".join(i["message"] for i in blocking))
    if manager.active_for(project_id):
        raise HTTPException(status_code=409, detail="Une tâche est déjà en cours sur ce projet.")
    destination = (payload.get("destination") or "zip").lower()
    if destination not in {"zip", "folder", "game"}:
        raise HTTPException(status_code=400, detail="Destination inconnue.")

    target: str | None = None
    if destination == "game":
        target = payload.get("target_path") or gamedir.load_settings().get("game_dir")
        if not target:
            raise HTTPException(
                status_code=400,
                detail="Aucun dossier de jeu sélectionné: lance la détection ou indique le chemin.",
            )
        try:
            target = str(gamedir.resolve_packs_voice(target, create=True))
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif destination == "folder":
        target = payload.get("target_path")
        if not target:
            raise HTTPException(status_code=400, detail="Indique le dossier de destination.")
        if not Path(target).expanduser().is_dir():
            raise HTTPException(status_code=400, detail=f"Dossier introuvable: {target}")
        target = str(Path(target).expanduser())

    job = manager.create("export", project_id)
    reuse = bool(payload.get("reuse_video", True))
    overwrite = bool(payload.get("overwrite", False))
    # Un ZIP n'a d'intérêt que si on ne dépose pas déjà le dossier dans le jeu.
    make_zip = destination != "game" or bool(payload.get("make_zip", False))

    def work(job_ref, progress):
        proj = dubpack.load_project(project_id)
        result = dubpack.export_pack(
            proj, cb=progress, reuse_video=reuse, dest_dir=target,
            overwrite=overwrite, make_zip=make_zip,
        )
        result["destination"] = destination
        proj["last_export"] = result
        dubpack.save_project(proj)
        return result

    manager.run(job, work)
    return {"job": job.to_dict()}


@app.get("/api/projects/{project_id}/download")
def api_download(project_id: str):
    project = _load(project_id)
    zip_path = (project.get("last_export") or {}).get("zip")
    if not zip_path or not Path(zip_path).exists():
        raise HTTPException(status_code=404, detail="Aucun export disponible: lance d'abord l'export.")
    return FileResponse(zip_path, media_type="application/zip",
                        filename=Path(zip_path).name)


@app.post("/api/projects/{project_id}/reveal")
def api_reveal(project_id: str) -> dict:
    """Ouvre le dossier d'export dans le Finder / l'Explorateur."""
    project = _load(project_id)
    target = (project.get("last_export") or {}).get("folder") or str(dubpack.project_dir(project_id))
    path = Path(target)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Dossier introuvable.")
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Impossible d'ouvrir le dossier: {exc}")
    return {"opened": str(path)}


# ---------------------------------------------------------------------------
# Médias du projet
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/media")
def api_media(project_id: str):
    project = _load(project_id)
    path = Path(project.get("source", {}).get("file", ""))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Vidéo source introuvable.")
    types = {".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
             ".mov": "video/quicktime", ".ogv": "video/ogg", ".m4v": "video/mp4"}
    return FileResponse(path, media_type=types.get(path.suffix.lower(), "video/mp4"))


@app.get("/api/projects/{project_id}/waveform")
def api_waveform(project_id: str) -> dict:
    folder = dubpack.project_dir(project_id)
    path = folder / "waveform.json"
    if not path.exists():
        return {"peaks": []}
    import json as _json

    return {"peaks": _json.loads(path.read_text(encoding="utf-8"))}


@app.get("/api/projects/{project_id}/thumb")
def api_thumb(project_id: str):
    project = _load(project_id)
    path = (project.get("assets") or {}).get("thumbnail")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Pas de vignette.")
    return FileResponse(path, media_type="image/png")


@app.post("/api/projects/{project_id}/character-image")
def api_character_image(project_id: str, payload: dict = Body(...)) -> dict:
    """Capture l'image courante de la vidéo comme portrait d'un personnage."""
    project = _load(project_id)
    speaker = payload.get("speaker_id")
    at = float(payload.get("at") or 0.0)
    char = next((c for c in project.get("characters", []) if c.get("id") == speaker), None)
    if not char:
        raise HTTPException(status_code=404, detail="Personnage inconnu.")
    source = Path(project["source"]["file"])
    name = dubpack.ascii_slug(char.get("name") or speaker, 20) or "perso"
    target = dubpack.project_dir(project_id) / f"{name}.png"
    if not media.extract_thumbnail(source, target, at=at, width=512):
        raise HTTPException(status_code=500, detail="Impossible d'extraire l'image.")
    char["image"] = str(target)
    dubpack.save_project(project)
    return {"image": target.name}


@app.delete("/api/projects/{project_id}/character-image/{speaker_id}")
def api_drop_character_image(project_id: str, speaker_id: str) -> dict:
    project = _load(project_id)
    for char in project.get("characters", []):
        if char.get("id") == speaker_id:
            char["image"] = None
    dubpack.save_project(project)
    return {"removed": True}


@app.get("/api/projects/{project_id}/character-image/{speaker_id}")
def api_get_character_image(project_id: str, speaker_id: str):
    project = _load(project_id)
    char = next((c for c in project.get("characters", []) if c.get("id") == speaker_id), None)
    if not char or not char.get("image") or not Path(char["image"]).exists():
        raise HTTPException(status_code=404, detail="Pas de portrait.")
    return FileResponse(char["image"], media_type="image/png")


@app.get("/api/projects/{project_id}/preview")
def api_preview(project_id: str, start: float, end: float):
    """Extrait audio d'une réplique, pour l'écouter isolément dans l'éditeur."""
    project = _load(project_id)
    source = Path(project["source"]["file"])
    if not source.exists():
        raise HTTPException(status_code=404, detail="Vidéo source introuvable.")
    if end <= start:
        raise HTTPException(status_code=400, detail="Bornes invalides.")
    folder = dubpack.project_dir(project_id) / "previews"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{start:.3f}-{end:.3f}.ogg"
    if not out.exists():
        media.cut_audio(source, out, start, min(end, start + 60), fmt="ogg", normalize=False)
    return FileResponse(out, media_type="audio/ogg")


# ---------------------------------------------------------------------------
# Dossier du jeu, réglages, sélecteur de dossier
# ---------------------------------------------------------------------------

@app.get("/api/game/detect")
def api_game_detect(extra: str | None = None) -> dict:
    """Cherche les installations de Choicer Voicer sur cette machine."""
    roots = [extra] if extra else None
    candidates = gamedir.detect(roots)
    settings = gamedir.load_settings()
    return {
        "candidates": candidates,
        "selected": settings.get("game_dir"),
        "picker": picker.available(),
    }


@app.post("/api/game/validate")
def api_game_validate(payload: dict = Body(...)) -> dict:
    try:
        return gamedir.validate_game_dir(payload.get("path") or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/game/select")
def api_game_select(payload: dict = Body(...)) -> dict:
    path = payload.get("path")
    if not path:
        gamedir.save_settings({"game_dir": None})
        return {"game_dir": None}
    try:
        info = gamedir.validate_game_dir(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    gamedir.save_settings({"game_dir": info["path"]})
    return {"game_dir": info["path"], **info}


@app.get("/api/settings")
def api_get_settings() -> dict:
    return gamedir.load_settings()


@app.put("/api/settings")
def api_put_settings(payload: dict = Body(...)) -> dict:
    allowed = {"game_dir", "export_destination", "export_folder", "make_zip"}
    return gamedir.save_settings({k: v for k, v in payload.items() if k in allowed})


@app.post("/api/pick-folder")
def api_pick_folder(payload: dict = Body(default={})) -> dict:
    """Ouvre la boîte de dialogue système pour choisir un dossier."""
    try:
        path = picker.ask_directory(
            title=payload.get("title") or "Choisir un dossier",
            initial=payload.get("initial") or "",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {"path": path}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Tâche inconnue.")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel(job_id: str) -> dict:
    return {"cancelled": manager.cancel(job_id)}


@app.exception_handler(RuntimeError)
def runtime_error_handler(request: Request, exc: RuntimeError):
    return JSONResponse(status_code=500, content={"detail": str(exc)})
