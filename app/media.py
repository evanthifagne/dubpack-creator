"""Enveloppes ffmpeg: sondage, extraction audio, découpe des clips, encodage OGV."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from .config import ffmpeg_path, ffprobe_path, has_encoder

ProgressCb = Callable[[float, str], None] | None

_CREATE_NO_WINDOW = 0x08000000  # évite une fenêtre CMD sur Windows


def _popen_kwargs() -> dict:
    import os

    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = _CREATE_NO_WINDOW
    return kw


def run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        errors="replace", **_popen_kwargs(),
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-12:]
        raise RuntimeError(f"Échec de la commande {Path(cmd[0]).name}:\n" + "\n".join(tail))
    return proc


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d\.\d+)")


def probe(path: str | Path) -> dict:
    """Retourne {duration, width, height, fps, has_video, has_audio}."""
    path = str(path)
    probe_exe = ffprobe_path()
    if probe_exe:
        proc = subprocess.run(
            [probe_exe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, errors="replace", **_popen_kwargs(),
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout or "{}")
            streams = data.get("streams", [])
            video = next((s for s in streams if s.get("codec_type") == "video"), None)
            audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
            duration = float(data.get("format", {}).get("duration") or 0.0)
            if not duration and video:
                duration = float(video.get("duration") or 0.0)
            fps = 0.0
            if video and video.get("r_frame_rate", "0/0") != "0/0":
                num, _, den = video["r_frame_rate"].partition("/")
                try:
                    fps = float(num) / float(den or 1)
                except ZeroDivisionError:
                    fps = 0.0
            return {
                "duration": duration,
                "width": int(video.get("width") or 0) if video else 0,
                "height": int(video.get("height") or 0) if video else 0,
                "fps": round(fps, 3),
                "has_video": video is not None,
                "has_audio": audio is not None,
                "vcodec": (video or {}).get("codec_name"),
                "acodec": (audio or {}).get("codec_name"),
            }
    # Fallback: lire l'en-tête via ffmpeg.
    proc = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", path],
        capture_output=True, text=True, errors="replace", **_popen_kwargs(),
    )
    err = proc.stderr or ""
    match = _DUR_RE.search(err)
    duration = 0.0
    if match:
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    size = re.search(r",\s(\d{2,5})x(\d{2,5})", err)
    return {
        "duration": duration,
        "width": int(size.group(1)) if size else 0,
        "height": int(size.group(2)) if size else 0,
        "fps": 0.0,
        "has_video": "Video:" in err,
        "has_audio": "Audio:" in err,
        "vcodec": None,
        "acodec": None,
    }


def _run_with_progress(cmd: list[str], total: float, cb: ProgressCb, label: str) -> None:
    """Lance ffmpeg en lisant -progress pour remonter l'avancement."""
    full = [cmd[0], "-hide_banner", "-nostdin", "-progress", "pipe:1", "-nostats", *cmd[1:]]
    proc = subprocess.Popen(
        full, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace", **_popen_kwargs(),
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if cb and total > 0 and line.startswith("out_time_ms="):
            try:
                done = int(line.split("=", 1)[1]) / 1_000_000.0
            except ValueError:
                continue
            cb(min(done / total, 1.0), label)
    proc.wait()
    if proc.returncode != 0:
        tail = (proc.stderr.read() if proc.stderr else "").strip().splitlines()[-12:]
        raise RuntimeError(f"Échec ffmpeg ({label}):\n" + "\n".join(tail))
    if cb:
        cb(1.0, label)


def extract_audio(src: str | Path, dst: str | Path, sr: int = 16000, mono: bool = True,
                  cb: ProgressCb = None) -> Path:
    """Extrait une piste WAV PCM 16 bits (entrée de la transcription)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    duration = probe(src).get("duration", 0.0)
    cmd = [
        ffmpeg_path(), "-y", "-i", str(src), "-vn",
        "-ac", "1" if mono else "2", "-ar", str(sr),
        "-c:a", "pcm_s16le", str(dst),
    ]
    _run_with_progress(cmd, duration, cb, "Extraction de l'audio")
    return dst


def read_pcm(path: str | Path, sr: int = 16000) -> np.ndarray:
    """Décode n'importe quel média en float32 mono normalisé, via un pipe ffmpeg."""
    proc = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
         "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"],
        capture_output=True, **_popen_kwargs(),
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", "replace")[-500:])
    return np.frombuffer(proc.stdout, dtype=np.float32)


def cut_audio(src: str | Path, dst: str | Path, start: float, end: float,
              fmt: str = "ogg", normalize: bool = True) -> Path:
    """Extrait [start, end] vers un clip audio (ogg/vorbis par défaut)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    duration = max(round(end - start, 3), 0.05)
    filters = []
    if normalize:
        # Normalisation douce: le scoring du jeu n'aime pas les formes d'onde trop faibles.
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    cmd = [
        ffmpeg_path(), "-y", "-v", "error", "-nostdin",
        "-ss", f"{max(start, 0):.3f}", "-i", str(src), "-t", f"{duration:.3f}", "-vn",
    ]
    if filters:
        cmd += ["-af", ",".join(filters)]
    if fmt == "ogg":
        codec = "libvorbis" if has_encoder("libvorbis") else "vorbis"
        cmd += ["-c:a", codec, "-q:a", "5", "-ar", "44100", "-ac", "1"]
    elif fmt == "wav":
        cmd += ["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1"]
    else:
        cmd += ["-ar", "44100", "-ac", "1"]
    if filters:
        cmd += ["-strict", "-2"]
    cmd.append(str(dst))
    run(cmd, timeout=300)
    return dst


def encode_ogv(src: str | Path, dst: str | Path, height: int = 720,
               video_quality: int = 7, audio_quality: int = 4,
               fps_cap: float | None = 30.0, cb: ProgressCb = None) -> Path:
    """Encode la vidéo de référence en Ogg Theora — seul format lu par Godot."""
    if not has_encoder("libtheora"):
        raise RuntimeError(
            "Ton ffmpeg n'a pas l'encodeur libtheora, indispensable pour produire dub_video.ogv. "
            "macOS: `brew install ffmpeg`. Windows: prends une build complète (gyan.dev)."
        )
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    info = probe(src)
    duration = info.get("duration", 0.0)
    scale = f"scale=-2:{height}:flags=lanczos" if height and info.get("height", 0) > height else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    vf = [scale]
    if fps_cap:
        vf.append(f"fps={fps_cap}")
    cmd = [
        ffmpeg_path(), "-y", "-i", str(src),
        "-c:v", "libtheora", "-q:v", str(video_quality),
        "-vf", ",".join(vf),
        "-c:a", "libvorbis", "-q:a", str(audio_quality), "-ar", "44100", "-ac", "2",
        "-f", "ogv", str(dst),
    ]
    _run_with_progress(cmd, duration, cb, "Encodage de dub_video.ogv")
    return dst


def encode_ogg(src: str | Path, dst: str | Path, quality: int = 5,
               cb: ProgressCb = None) -> Path:
    """Encode une piste audio complète en Ogg Vorbis (ex: _backing_track.ogg)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    duration = probe(src).get("duration", 0.0)
    cmd = [
        ffmpeg_path(), "-y", "-i", str(src), "-vn",
        "-c:a", "libvorbis", "-q:a", str(quality), "-ar", "44100", "-ac", "2", str(dst),
    ]
    _run_with_progress(cmd, duration, cb, "Encodage du backing track")
    return dst


def extract_thumbnail(src: str | Path, dst: str | Path, at: float = 1.0,
                      width: int = 512) -> Path | None:
    """Vignette PNG (utilisée comme Icon.png ou image de personnage)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        run([
            ffmpeg_path(), "-y", "-v", "error", "-nostdin",
            "-ss", f"{max(at, 0):.3f}", "-i", str(src), "-frames:v", "1",
            "-vf", f"scale={width}:-2", str(dst),
        ], timeout=120)
        return dst if dst.exists() else None
    except RuntimeError:
        return None


def waveform_peaks(path: str | Path, buckets: int = 2000, sr: int = 8000) -> list[float]:
    """Enveloppe de crêtes normalisée, pour dessiner la timeline dans l'UI."""
    samples = read_pcm(path, sr=sr)
    if samples.size == 0:
        return []
    buckets = max(int(buckets), 1)
    chunk = max(samples.size // buckets, 1)
    usable = (samples.size // chunk) * chunk
    frames = np.abs(samples[:usable]).reshape(-1, chunk)
    peaks = frames.max(axis=1)
    top = float(peaks.max()) or 1.0
    return [round(float(v) / top, 4) for v in peaks]
