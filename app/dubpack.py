"""Modèle de projet et export au format attendu par Choicer Voicer.

Structure produite (dossier à déposer dans `packs_voice` du jeu):

    Mon Dub Pack/
        _pack_info.ini          titre, sous-titre, auteurs, icône
        Icon.png                vignette du pack
        dub_video.ogv           vidéo de référence (Theora: seul format lu par Godot)
        _backing_track.ogg      fond sonore sans les voix (facultatif)
        01_marco_bonjour.ogg    audio d'origine de la réplique
        01_marco_bonjour.ini    caption + dub_timestamps + dub_characters
        ...

Les fichiers .ini suivent la syntaxe ConfigFile de Godot: chaînes entre
guillemets, tableaux entre crochets.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import media
from .config import PROJECTS_DIR

ProgressCb = Callable[[float, str], None] | None

PALETTE = ["#f97316", "#38bdf8", "#a3e635", "#e879f9", "#facc15", "#fb7185", "#2dd4bf", "#c084fc"]


# ---------------------------------------------------------------------------
# Écriture des .ini (syntaxe ConfigFile de Godot)
# ---------------------------------------------------------------------------

def ini_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        # Toujours 3 décimales: Godot lirait « 0 » comme un entier, or les
        # timestamps doivent rester des flottants.
        return f"{value:.3f}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(ini_value(v) for v in value) + "]"
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return f'"{text}"'


def write_ini(path: Path, data: dict[str, Any], section: str = "data") -> Path:
    lines = [f"[{section}]", ""]
    for key, value in data.items():
        if value is None or (isinstance(value, (list, tuple, str)) and len(value) == 0):
            continue
        lines.append(f"{key}={ini_value(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Noms de fichiers
# ---------------------------------------------------------------------------

def ascii_slug(text: str, max_len: int = 28) -> str:
    """Slug ASCII: les noms de fichiers doivent survivre à Windows et à Godot."""
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-")


def clip_basename(index: int, line: dict, character: str, include_timestamp: bool = False) -> str:
    """Ex: `03_marco_on-y-va` — préfixe numéroté pour garder l'ordre du jeu."""
    who = ascii_slug(character, 14) or "voix"
    words = ascii_slug(line.get("text", ""), 26) or "replique"
    name = f"{index:02d}_{who}_{words}".strip("_")
    if include_timestamp:
        stamp = f"{float(line.get('start', 0.0)):.3f}".replace(".", "-")
        name = f"{name}_{stamp}"
    return re.sub(r"-+", "-", name)


# ---------------------------------------------------------------------------
# Projet
# ---------------------------------------------------------------------------

def project_dir(project_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", project_id)
    if not safe:
        raise ValueError("Identifiant de projet invalide")
    return PROJECTS_DIR / safe


def new_project(name: str) -> dict:
    stamp = datetime.now(timezone.utc)
    pid = stamp.strftime("%Y%m%d-%H%M%S")
    return {
        "id": pid,
        "created": stamp.isoformat(timespec="seconds"),
        "name": name or "Dub Pack",
        "source": {},
        "pack": {
            "title": name or "Dub Pack",
            "subtitle": "",
            "authors": [],
            "description": "",
        },
        "asr": {},
        "characters": [],
        "lines": [],
        "options": {
            "include_timestamp_in_name": False,
            "dub_only": False,
            "video_height": 720,
            "video_quality": 7,
            "normalize_clips": True,
        },
        "assets": {},
    }


def save_project(project: dict) -> Path:
    folder = project_dir(project["id"])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "project.json"
    tmp = folder / "project.json.tmp"
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_project(project_id: str) -> dict:
    path = project_dir(project_id) / "project.json"
    if not path.exists():
        raise FileNotFoundError(f"Projet introuvable: {project_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_projects() -> list[dict]:
    out = []
    for folder in sorted(PROJECTS_DIR.iterdir(), reverse=True):
        marker = folder / "project.json"
        if not marker.exists():
            continue
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "id": data.get("id", folder.name),
            "name": data.get("name", folder.name),
            "created": data.get("created", ""),
            "lines": len(data.get("lines", [])),
            "characters": [c.get("name") for c in data.get("characters", [])],
            "has_source": bool(data.get("source", {}).get("file")),
        })
    return out


def character_name(project: dict, speaker_id: str | None) -> str:
    for char in project.get("characters", []):
        if char.get("id") == speaker_id:
            return char.get("name") or speaker_id or "Personnage"
    return speaker_id or "Personnage"


def build_characters(speakers: Sequence[str], existing: Sequence[dict] = ()) -> list[dict]:
    known = {c.get("id"): c for c in existing}
    out = []
    for idx, speaker in enumerate(speakers):
        previous = known.get(speaker, {})
        out.append({
            "id": speaker,
            "name": previous.get("name") or speaker,
            "color": previous.get("color") or PALETTE[idx % len(PALETTE)],
            "image": previous.get("image"),
        })
    return out


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def validate(project: dict) -> list[dict]:
    """Contrôles avant export, dans l'esprit du validateur de packs du jeu."""
    issues: list[dict] = []
    lines = [ln for ln in project.get("lines", []) if ln.get("enabled", True)]
    if not lines:
        issues.append({"level": "error", "message": "Aucune réplique active: le pack serait vide."})
    source = project.get("source", {}).get("file")
    if not source or not Path(source).exists():
        issues.append({"level": "error", "message": "La vidéo source est introuvable."})
    if not project.get("pack", {}).get("title"):
        issues.append({"level": "warning", "message": "Le pack n'a pas de titre."})

    for idx, line in enumerate(lines, start=1):
        duration = float(line.get("end", 0)) - float(line.get("start", 0))
        label = f"Réplique {idx}"
        if duration <= 0.05:
            issues.append({"level": "error", "message": f"{label}: durée nulle ou négative.",
                           "line": line.get("id")})
        elif duration > 60:
            issues.append({"level": "error",
                           "message": f"{label}: {duration:.1f} s — le jeu refuse les clips de plus de 60 s.",
                           "line": line.get("id")})
        elif duration > 12:
            issues.append({"level": "warning",
                           "message": f"{label}: {duration:.1f} s, c'est long à imiter d'une traite.",
                           "line": line.get("id")})
        if not (line.get("text") or "").strip():
            issues.append({"level": "warning", "message": f"{label}: sous-titre vide.",
                           "line": line.get("id")})

    ordered = sorted(lines, key=lambda l: float(l.get("start", 0)))
    for prev, nxt in zip(ordered, ordered[1:]):
        if float(nxt.get("start", 0)) < float(prev.get("end", 0)) - 0.02:
            issues.append({
                "level": "warning",
                "message": "Deux répliques se chevauchent: le jeu les jouera l'une sur l'autre.",
                "line": nxt.get("id"),
            })
            break
    return issues


def export_pack(project: dict, cb: ProgressCb = None,
                make_zip: bool = True, reuse_video: bool = True,
                dest_dir: str | Path | None = None,
                overwrite: bool = False) -> dict:
    """Construit le pack, éventuellement livré dans `dest_dir`.

    Le pack est toujours assemblé dans le dossier du projet puis recopié à
    destination: si l'encodage échoue en route, on n'a pas laissé un pack à
    moitié écrit dans les fichiers du jeu.
    """
    folder = project_dir(project["id"])
    options = project.get("options", {})
    pack_info = project.get("pack", {})
    pack_name = (pack_info.get("title") or project.get("name") or "Dub Pack").strip()
    safe_pack = re.sub(r'[<>:"/\\|?*]', "", pack_name).strip(" .") or "Dub Pack"

    out_root = folder / "export"
    pack_dir = out_root / safe_pack
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    source = Path(project["source"]["file"])
    lines = [ln for ln in project.get("lines", []) if ln.get("enabled", True)]
    lines.sort(key=lambda l: float(l.get("start", 0.0)))

    written: list[str] = []

    # 1) Vidéo de référence -------------------------------------------------
    video_out = pack_dir / "dub_video.ogv"
    cached = folder / "dub_video.ogv"
    if reuse_video and cached.exists() and cached.stat().st_mtime >= source.stat().st_mtime:
        shutil.copy2(cached, video_out)
        if cb:
            cb(0.35, "Vidéo Theora réutilisée depuis le cache")
    else:
        media.encode_ogv(
            source, cached,
            height=int(options.get("video_height", 720)),
            video_quality=int(options.get("video_quality", 7)),
            cb=(lambda frac, label: cb(0.02 + frac * 0.33, label)) if cb else None,
        )
        shutil.copy2(cached, video_out)
    written.append("dub_video.ogv")

    # 2) Fond sonore --------------------------------------------------------
    backing = project.get("assets", {}).get("backing_track")
    if backing and Path(backing).exists():
        target = pack_dir / "_backing_track.ogg"
        if Path(backing).suffix.lower() == ".ogg":
            shutil.copy2(backing, target)
        else:
            media.encode_ogg(backing, target)
        written.append("_backing_track.ogg")
    if cb:
        cb(0.4, "Découpage des répliques")

    # 3) Clips + métadonnées ------------------------------------------------
    normalize = bool(options.get("normalize_clips", True))
    include_ts = bool(options.get("include_timestamp_in_name", False))
    dub_only = bool(options.get("dub_only", False))
    used: set[str] = set()
    manifest: list[dict] = []

    for idx, line in enumerate(lines, start=1):
        who = character_name(project, line.get("speaker"))
        base = clip_basename(idx, line, who, include_ts)
        while base in used:
            base = f"{base}-b"
        used.add(base)

        start, end = float(line["start"]), float(line["end"])
        media.cut_audio(source, pack_dir / f"{base}.ogg", start, end,
                        fmt="ogg", normalize=normalize)

        data: dict[str, Any] = {
            "caption": (line.get("text") or "").strip(),
            "dub_timestamps": [round(start, 3)],
            "dub_characters": [who],
        }
        tags = [t for t in (line.get("tags") or []) if str(t).strip()]
        if tags:
            data["tags"] = tags
        if dub_only or line.get("dub_only"):
            data["dub_only"] = True
        image = line.get("image") or _character_image(project, line.get("speaker"))
        if image:
            data["images"] = [image]
        write_ini(pack_dir / f"{base}.ini", data)

        written += [f"{base}.ogg", f"{base}.ini"]
        manifest.append({"file": f"{base}.ogg", "character": who, "start": round(start, 3),
                         "end": round(end, 3), "caption": data["caption"]})
        if cb:
            cb(0.4 + 0.45 * idx / max(len(lines), 1), f"Réplique {idx}/{len(lines)}")

    # 4) Icône --------------------------------------------------------------
    icon_name = None
    icon_src = project.get("assets", {}).get("icon")
    if icon_src and Path(icon_src).exists():
        shutil.copy2(icon_src, pack_dir / "Icon.png")
        icon_name = "Icon.png"
    else:
        at = float(lines[0]["start"]) + 0.2 if lines else 1.0
        if media.extract_thumbnail(source, pack_dir / "Icon.png", at=at):
            icon_name = "Icon.png"
    if icon_name:
        written.append(icon_name)

    # 5) Images de personnages ---------------------------------------------
    for char in project.get("characters", []):
        image = char.get("image")
        if image and Path(image).exists():
            target = pack_dir / Path(image).name
            shutil.copy2(image, target)
            written.append(target.name)

    # 6) _pack_info.ini ------------------------------------------------------
    info: dict[str, Any] = {"title": pack_name}
    if pack_info.get("subtitle"):
        info["subtitle"] = pack_info["subtitle"]
    authors = [a for a in (pack_info.get("authors") or []) if str(a).strip()]
    if authors:
        info["authors"] = authors
    if pack_info.get("description"):
        info["description"] = pack_info["description"]
    if icon_name:
        info["icon"] = icon_name
    write_ini(pack_dir / "_pack_info.ini", info)
    written.append("_pack_info.ini")

    # 7) Note d'installation + ZIP -----------------------------------------
    (pack_dir / "README.txt").write_text(
        f"{pack_name}\n"
        f"{'=' * len(pack_name)}\n\n"
        "Installation dans Choicer Voicer:\n"
        f"  1. Copier le dossier « {safe_pack} » dans le dossier packs_voice du jeu.\n"
        "  2. Ne pas ajouter de niveau de dossier supplémentaire:\n"
        f"     packs_voice/{safe_pack}/dub_video.ogv doit exister.\n"
        "  3. Lancer le jeu et choisir le pack en mode Dub.\n\n"
        f"Répliques: {len(lines)}\n"
        f"Personnages: {', '.join(sorted({m['character'] for m in manifest})) or '—'}\n"
        "Généré avec DubPack Creator.\n",
        encoding="utf-8",
    )
    written.append("README.txt")

    # 8) Livraison à destination -------------------------------------------
    delivered = None
    if dest_dir:
        destination = Path(dest_dir).expanduser()
        destination.mkdir(parents=True, exist_ok=True)
        final = destination / safe_pack
        if final.exists():
            if not overwrite:
                raise RuntimeError(
                    f"Un pack « {safe_pack} » existe déjà dans {destination}. "
                    "Coche l'écrasement pour le remplacer."
                )
            if final.resolve() == pack_dir.resolve():
                raise RuntimeError("La destination est le dossier de travail du projet.")
            shutil.rmtree(final)
        if cb:
            cb(0.88, f"Copie vers {destination}")
        shutil.copytree(pack_dir, final)
        delivered = str(final)

    zip_path = None
    if make_zip:
        if cb:
            cb(0.9, "Création du ZIP")
        zip_path = out_root / f"{safe_pack}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for item in sorted(pack_dir.rglob("*")):
                if item.is_file() and item.name not in {".DS_Store", "Thumbs.db", "desktop.ini"}:
                    zf.write(item, arcname=str(Path(safe_pack) / item.relative_to(pack_dir)))
    if cb:
        cb(1.0, "Export terminé")

    return {
        "pack_name": safe_pack,
        "folder": delivered or str(pack_dir),
        "staging": str(pack_dir),
        "delivered": delivered,
        "zip": str(zip_path) if zip_path else None,
        "files": len(written),
        "clips": len(lines),
        "characters": sorted({m["character"] for m in manifest}),
        "manifest": manifest,
    }


def _character_image(project: dict, speaker_id: str | None) -> str | None:
    for char in project.get("characters", []):
        if char.get("id") == speaker_id and char.get("image"):
            return Path(char["image"]).name
    return None
