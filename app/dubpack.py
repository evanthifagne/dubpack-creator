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
import threading
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


def write_ini(path: Path, data: dict[str, Any], section: str = "data",
              keep_empty: tuple[str, ...] = ()) -> Path:
    """Écrit un fichier au format ConfigFile de Godot.

    Fins de ligne CRLF et clés vides conservées quand demandé: on s'aligne sur
    les packs produits par la communauté, qui sont la référence de ce qui
    fonctionne réellement dans le jeu.
    """
    lines = [f"[{section}]", ""]
    for key, value in data.items():
        empty = value is None or (isinstance(value, (list, tuple, str)) and len(value) == 0)
        if empty and key not in keep_empty:
            continue
        lines.append(f"{key}={ini_value('' if value is None else value)}")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
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

# Caracteres interdits par Windows, plus ceux qui n'ont rien a faire dans un nom
# de dossier lu par le jeu.
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_folder_name(name: str, fallback: str = "Dub Pack") -> str:
    """Nom de dossier sûr pour le pack.

    Un titre YouTube peut contenir des emoji ou des symboles exotiques. Ils
    passent souvent, mais pas toujours, selon le système de fichiers et le
    moteur du jeu: on les retire du nom de dossier. Le titre complet reste
    intact dans `_pack_info.ini`, qui est ce que le joueur voit.
    """
    cleaned = _FORBIDDEN.sub("", name or "")
    # On garde lettres, chiffres, espaces et ponctuation simple; le reste part.
    cleaned = "".join(
        ch for ch in unicodedata.normalize("NFC", cleaned)
        if ch.isalnum() or ch in " -_.,'()[]&+!" or unicodedata.category(ch) == "Lm"
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    # Noms reserves par Windows.
    if cleaned.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        cleaned = f"{cleaned} pack"
    return cleaned[:80].strip() or fallback


def project_dir(project_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", project_id)
    if not safe:
        raise ValueError("Identifiant de projet invalide")
    return PROJECTS_DIR / safe


# L'attribution d'un identifiant doit être atomique: deux imports lancés dans la
# même seconde se retrouveraient sinon dans le même dossier et s'écraseraient.
_ID_LOCK = threading.Lock()


def _claim_id(stamp: datetime) -> str:
    base = stamp.strftime("%Y%m%d-%H%M%S")
    with _ID_LOCK:
        candidate = base
        suffix = 1
        while (PROJECTS_DIR / candidate).exists():
            suffix += 1
            candidate = f"{base}-{suffix}"
        # On réserve le dossier tout de suite: le prochain appel le verra occupé.
        (PROJECTS_DIR / candidate).mkdir(parents=True)
    return candidate


def new_project(name: str) -> dict:
    stamp = datetime.now(timezone.utc)
    pid = _claim_id(stamp)
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
    assets = project.get("assets", {})
    if not assets.get("backing_track"):
        issues.append({
            "level": "warning",
            "message": ("Aucun fond sonore: le pack n'aura ni musique ni bruitages "
                        "derrière ta voix. Utilise « Séparer les voix » dans l'onglet Export."),
        })
    elif assets.get("backing_mode") == "original":
        issues.append({
            "level": "warning",
            "message": ("Le fond sonore contient encore les dialogues d'origine: "
                        "tu t'entendras doubler par-dessus la voix originale. "
                        "« Séparer les voix » donne un bien meilleur résultat."),
        })

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
                overwrite: bool = False,
                zip_dir: str | Path | None = None) -> dict:
    """Construit le pack, éventuellement livré dans `dest_dir`.

    Le pack est toujours assemblé dans le dossier du projet puis recopié à
    destination: si l'encodage échoue en route, on n'a pas laissé un pack à
    moitié écrit dans les fichiers du jeu.
    """
    folder = project_dir(project["id"])
    options = project.get("options", {})
    pack_info = project.get("pack", {})
    pack_name = (pack_info.get("title") or project.get("name") or "Dub Pack").strip()
    safe_pack = safe_folder_name(pack_name)

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

    # Les images de réplique reprennent la taille exacte de la vidéo exportée,
    # comme le fait le pack de référence. On la mesure au lieu de la déduire:
    # l'encodage ne fait que réduire, jamais agrandir.
    image_width = int(options.get("image_width", 0)) or None
    if image_width is None:
        produced = media.probe(video_out)
        image_width = int(produced.get("width") or 0) or 640

    # 2) Fond sonore --------------------------------------------------------
    backing = project.get("assets", {}).get("backing_track")
    if backing and Path(backing).exists():
        # Le pack de référence utilise `_backing_track.mp3`: on s'y aligne, c'est
        # le seul format dont on sait qu'il est lu pour cette piste.
        target = pack_dir / "_backing_track.mp3"
        if Path(backing).suffix.lower() == ".mp3":
            shutil.copy2(backing, target)
        else:
            media.encode_mp3(backing, target)
        written.append("_backing_track.mp3")
    if cb:
        cb(0.4, "Découpage des répliques")

    # 3) Clips + métadonnées ------------------------------------------------
    normalize = bool(options.get("normalize_clips", True))
    with_images = bool(options.get("clip_images", True))
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

        # Une image par réplique, prise au milieu de celle-ci: c'est ce que le
        # jeu affiche pendant la séquence. Le milieu montre le personnage en
        # train de parler, alors que le tout début tombe souvent sur un plan
        # de transition.
        image_name: str | None = None
        if with_images:
            at = start + (end - start) / 2
            if media.extract_thumbnail(source, pack_dir / f"{base}.png",
                                       at=at, width=image_width):
                image_name = f"{base}.png"
                written.append(image_name)

        data: dict[str, Any] = {
            "caption": (line.get("text") or "").strip(),
        }
        if image_name:
            data["image"] = image_name
        data["dub_timestamps"] = [round(start, 3)]
        data["dub_characters"] = [who]
        tags = [t for t in (line.get("tags") or []) if str(t).strip()]
        if tags:
            data["tags"] = tags
        if dub_only or line.get("dub_only"):
            data["dub_only"] = True
        write_ini(pack_dir / f"{base}.txt", data)

        written += [f"{base}.ogg", f"{base}.txt"]
        manifest.append({"file": f"{base}.ogg", "character": who, "start": round(start, 3),
                         "end": round(end, 3), "caption": data["caption"]})
        if cb:
            cb(0.4 + 0.45 * idx / max(len(lines), 1), f"Réplique {idx}/{len(lines)}")

    # 4) Icône --------------------------------------------------------------
    icon_name = None
    icon_src = project.get("assets", {}).get("icon")
    if icon_src and Path(icon_src).exists():
        shutil.copy2(icon_src, pack_dir / "icon.png")
        icon_name = "icon.png"
    else:
        at = float(lines[0]["start"]) + 0.2 if lines else 1.0
        if media.extract_thumbnail(source, pack_dir / "icon.png", at=at):
            icon_name = "icon.png"
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
    # Ordre des clés repris du pack de référence.
    info: dict[str, Any] = {"title": pack_name}
    if icon_name:
        info["icon"] = icon_name
    authors = [a for a in (pack_info.get("authors") or []) if str(a).strip()]
    if authors:
        info["authors"] = authors
    if pack_info.get("subtitle"):
        info["subtitle"] = pack_info["subtitle"]
    # Le pack de référence porte `readme`, et le conserve même vide.
    info["readme"] = pack_info.get("description") or ""
    write_ini(pack_dir / "_pack_info.ini", info, keep_empty=("readme",))
    written.append("_pack_info.ini")

    # 7) Copie à destination -------------------------------------------------
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

    # 8) Archive ZIP ---------------------------------------------------------
    zip_path = None
    if make_zip:
        if cb:
            cb(0.9, "Création du ZIP")
        zip_root = Path(zip_dir).expanduser() if zip_dir else out_root
        zip_root.mkdir(parents=True, exist_ok=True)
        zip_path = zip_root / f"{safe_pack}.zip"
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
