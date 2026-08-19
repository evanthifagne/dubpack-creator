"""Détection du dossier d'installation de Choicer Voicer.

Le jeu se distribue sur itch.io (Windows et Linux) et son dossier `packs_voice`
se trouve soit à côté de l'exécutable, soit dans les données utilisateur Godot.
Plutôt que de deviner un chemin exact, on balaie une liste bornée de racines
plausibles à faible profondeur et on cherche les indices concrets:
un dossier `packs_voice`, un exécutable du jeu, ou un nom de dossier évocateur.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import ROOT

SETTINGS_FILE = ROOT / "settings.json"

PACKS_DIRNAME = "packs_voice"
# Un dossier de jeu contient généralement ces frères et sœurs.
SIBLING_HINTS = {"packs_voice", "packs_sound", "packs_music", "packs_dub", "user", "logs"}
NAME_HINTS = ("choicer", "voicer")
MAX_DEPTH = 4
MAX_DIRS_SCANNED = 40_000
# Dossiers qu'il ne faut jamais parcourir: lents, énormes ou sans intérêt.
SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".venv", "venv", "windows", "winsxs",
    "system32", "syswow64", "$recycle.bin", "system volume information",
    "appdata\\local\\temp", "library/caches", "onedrive - ", ".cache",
    "steamapps/downloading", "dubpackcreator",
}


@dataclass
class Candidate:
    path: str                     # dossier du jeu (parent de packs_voice)
    packs_voice: str | None       # dossier packs_voice s'il existe déjà
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    source: str = "scan"

    def to_dict(self) -> dict:
        return {
            "path": self.path, "packs_voice": self.packs_voice,
            "score": self.score, "reasons": self.reasons, "source": self.source,
            "exists": Path(self.path).is_dir(),
        }


# ---------------------------------------------------------------------------
# Réglages persistants
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    """Lit les réglages. Un fichier illisible est mis de côté, pas ignoré.

    Sans cela, un settings.json abîmé (édition à la main, antislashs Windows non
    échappés) ferait silencieusement oublier le dossier du jeu, sans que
    personne comprenne pourquoi.
    """
    if not SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        broken = SETTINGS_FILE.with_suffix(".json.bad")
        try:
            SETTINGS_FILE.replace(broken)
            print(f"  settings.json illisible ({exc}); mis de cote dans {broken.name}. "
                  "Les reglages repartent de zero.", flush=True)
        except OSError:
            pass
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data: dict) -> dict:
    current = load_settings()
    current.update(data)
    SETTINGS_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return current


# ---------------------------------------------------------------------------
# Racines à explorer
# ---------------------------------------------------------------------------

def _windows_roots() -> list[tuple[Path, int]]:
    """(racine, profondeur max). L'app itch.io et les données Godot en premier."""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
    roots: list[tuple[Path, int]] = [
        (appdata / "itch/apps", 3),
        (local / "itch/apps", 3),
        (appdata / "Godot/app_userdata", 2),
        (local / "Godot/app_userdata", 2),
        (home / "Downloads", 3),
        (home / "Desktop", 3),
        (home / "Documents", 3),
        (home / "Games", 3),
        (appdata, 2),
    ]
    for letter in "CDEFG":
        drive = Path(f"{letter}:/")
        if not drive.exists():
            continue
        roots.append((drive, 2))
        for folder in ("Games", "Jeux", "Program Files", "Program Files (x86)",
                       "SteamLibrary/steamapps/common", "itch"):
            target = drive / folder
            if target.exists():
                roots.append((target, 3))
    return roots


def _unix_roots() -> list[tuple[Path, int]]:
    home = Path.home()
    roots: list[tuple[Path, int]] = [
        (home / "Library/Application Support/Godot/app_userdata", 2),
        (home / ".local/share/godot/app_userdata", 2),
        (home / "Library/Application Support/itch/apps", 3),
        (home / ".config/itch/apps", 3),
        (home / "Downloads", 3),
        (home / "Desktop", 3),
        (home / "Documents", 3),
        (home / "Games", 3),
        (home / "Applications", 2),
        (Path("/Applications"), 2),
        (home / ".steam/steam/steamapps/common", 3),
    ]
    return roots


def candidate_roots() -> list[tuple[Path, int]]:
    roots = _windows_roots() if os.name == "nt" else _unix_roots()
    seen: set[str] = set()
    out = []
    for path, depth in roots:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            continue
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        out.append((path, depth))
    return out


def _skip(path: Path) -> bool:
    lowered = path.name.lower()
    if lowered.startswith(".") and lowered not in {".steam", ".local", ".config"}:
        return True
    full = str(path).lower().replace("\\", "/")
    return any(token.replace("\\", "/") in full for token in SKIP_DIRS)


# ---------------------------------------------------------------------------
# Détection
# ---------------------------------------------------------------------------

def _inspect(folder: Path) -> Candidate | None:
    """Le dossier ressemble-t-il à une installation du jeu ?"""
    try:
        entries = list(folder.iterdir())
    except (OSError, PermissionError):
        return None

    names = {e.name.lower() for e in entries}
    packs = next((e for e in entries if e.is_dir() and e.name.lower() == PACKS_DIRNAME), None)
    executables = [
        e for e in entries
        if e.is_file() and e.suffix.lower() in {".exe", ".x86_64", ".sh", ".app", ""}
        and any(hint in e.name.lower() for hint in NAME_HINTS)
    ]
    named = any(hint in folder.name.lower() for hint in NAME_HINTS)
    siblings = len(names & SIBLING_HINTS)

    score, reasons = 0, []
    if packs is not None:
        score += 60
        reasons.append("dossier packs_voice présent")
    if executables:
        score += 30
        reasons.append(f"exécutable du jeu ({executables[0].name})")
    if named:
        score += 20
        reasons.append("nom de dossier correspondant")
    if siblings >= 2:
        score += 15
        reasons.append(f"{siblings} dossiers de packs")
    if any(e.name.lower().endswith(".pck") for e in entries):
        score += 10
        reasons.append("données Godot (.pck)")

    # Il faut au moins packs_voice, ou un nom/exécutable qui colle.
    if score < 30 or (packs is None and not executables and not named):
        return None
    return Candidate(
        path=str(folder),
        packs_voice=str(packs) if packs else None,
        score=score, reasons=reasons,
    )


def detect(extra_roots: list[str] | None = None) -> list[dict]:
    """Renvoie les installations plausibles, la plus probable en premier."""
    found: dict[str, Candidate] = {}
    scanned = 0

    roots: list[tuple[Path, int]] = [(Path(r), 3) for r in (extra_roots or []) if Path(r).is_dir()]
    roots += candidate_roots()

    for root, max_depth in roots:
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            folder, depth = stack.pop()
            scanned += 1
            if scanned > MAX_DIRS_SCANNED:
                break
            candidate = _inspect(folder)
            if candidate:
                previous = found.get(candidate.path.lower())
                if not previous or candidate.score > previous.score:
                    found[candidate.path.lower()] = candidate
                # Inutile de descendre dans une installation déjà identifiée.
                if candidate.packs_voice:
                    continue
            if depth >= max_depth:
                continue
            try:
                for entry in folder.iterdir():
                    if entry.is_dir() and not entry.is_symlink() and not _skip(entry):
                        stack.append((entry, depth + 1))
            except (OSError, PermissionError):
                continue

    # Un chemin choisi à la main passe devant, sans perdre les indices trouvés.
    saved = load_settings().get("game_dir")
    if saved and Path(saved).is_dir():
        key = saved.lower()
        existing = found.get(key)
        packs = Path(saved) / PACKS_DIRNAME
        reasons = list(existing.reasons) if existing else []
        if not reasons:
            inspected = _inspect(Path(saved))
            reasons = inspected.reasons if inspected else []
        found[key] = Candidate(
            path=saved,
            packs_voice=str(packs) if packs.is_dir() else None,
            score=200,
            reasons=["déjà sélectionné", *reasons],
            source="manual",
        )

    return [c.to_dict() for c in sorted(found.values(), key=lambda c: -c.score)]


def validate_game_dir(path: str) -> dict:
    """Vérifie un dossier fourni à la main et indique s'il faut créer packs_voice."""
    folder = Path(path).expanduser()
    if not folder.is_dir():
        raise ValueError(f"Ce dossier n'existe pas: {folder}")
    # L'utilisateur a pu désigner packs_voice lui-même.
    if folder.name.lower() == PACKS_DIRNAME:
        game, packs = folder.parent, folder
    else:
        game, packs = folder, folder / PACKS_DIRNAME
    inspected = _inspect(game)
    return {
        "path": str(game),
        "packs_voice": str(packs) if packs.is_dir() else None,
        "packs_voice_target": str(packs),
        "looks_like_game": inspected is not None,
        "reasons": inspected.reasons if inspected else [],
    }


def resolve_packs_voice(path: str, create: bool = True) -> Path:
    """Renvoie le `packs_voice` d'un dossier de jeu, en le créant au besoin."""
    folder = Path(path).expanduser()
    packs = folder if folder.name.lower() == PACKS_DIRNAME else folder / PACKS_DIRNAME
    if not packs.is_dir():
        if not create:
            raise ValueError(f"Dossier packs_voice absent: {packs}")
        packs.mkdir(parents=True, exist_ok=True)
    return packs
