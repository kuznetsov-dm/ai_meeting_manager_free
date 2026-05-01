from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from aimn.core.app_paths import get_app_root

_SUPPORTED_EXTS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".flac",
    ".ogg",
    ".webm",
}


def _subprocess_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def is_supported_media(path: Path | str) -> bool:
    return Path(path).suffix.lower() in _SUPPORTED_EXTS


def _resolve_binary_candidate(raw: str, *, repo_root: Path | None = None) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        if repo_root is not None:
            candidates.append(repo_root / path)
        candidates.append(path)
    if path.suffix == ".exe":
        for candidate in list(candidates):
            candidates.append(candidate.with_suffix(""))
    if path.suffix == "" and os.name == "nt":
        for candidate in list(candidates):
            candidates.append(candidate.with_suffix(".exe"))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    system_match = shutil.which(str(raw))
    if not system_match:
        system_match = shutil.which(Path(raw).name)
    if system_match:
        return Path(system_match)
    return candidates[0] if candidates else None


def get_ffmpeg_path(explicit: Path | str | None = None) -> Path:
    repo_root = get_app_root()
    if explicit:
        resolved = _resolve_binary_candidate(str(explicit), repo_root=repo_root)
        return resolved if resolved else Path(explicit)
    env_path = os.environ.get("AIMN_FFMPEG_PATH", "").strip()
    if env_path:
        resolved = _resolve_binary_candidate(env_path, repo_root=repo_root)
        return resolved if resolved else Path(env_path)
    resolved = _resolve_binary_candidate("bin/ffmpeg/ffmpeg", repo_root=repo_root)
    if resolved:
        return resolved
    fallback = "bin/ffmpeg/ffmpeg.exe" if os.name == "nt" else "bin/ffmpeg/ffmpeg"
    return repo_root / fallback


def convert_to_wav(
    input_path: Path | str,
    output_path: Path | str,
    ffmpeg_path: Path | str | None = None,
    *,
    channels: int = 1,
    sample_rate_hz: int = 16000,
    normalize: bool = False,
) -> None:
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if input_path.suffix.lower() == ".wav":
        shutil.copy2(input_path, output_path)
        return

    ffmpeg = get_ffmpeg_path(ffmpeg_path)
    timeout_seconds = int(os.environ.get("AIMN_FFMPEG_TIMEOUT_SECONDS", "300") or 300)
    channels = max(1, min(8, int(channels)))
    sample_rate_hz = max(8000, min(192000, int(sample_rate_hz)))
    cmd = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate_hz),
    ]
    if normalize:
        cmd.extend(["-af", "loudnorm=I=-16:LRA=11:TP=-1.5"])
    cmd.append(str(output_path))
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="ignore",
            timeout=timeout_seconds,
            creationflags=_subprocess_creationflags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg_timeout") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        message = f"ffmpeg_failed:{exc.returncode}"
        if stderr:
            message = f"{message}:{stderr[:200]}"
        raise RuntimeError(message) from exc
