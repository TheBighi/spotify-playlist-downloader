"""FFmpeg helpers: probing and MP3 conversion."""

import asyncio
import json
import shutil
import subprocess

from .config import settings


class FFmpegError(Exception):
    pass


def _resolve(binary: str, configured: str) -> str:
    return shutil.which(configured) or binary


async def probe(path) -> dict:
    ffprobe = _resolve("ffprobe", settings.ffprobe_path)
    proc = await asyncio.create_subprocess_exec(
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed: {err.decode(errors='ignore')[:300]}")
    return json.loads(out.decode() or "{}")


async def probe_audio_info(path) -> tuple[float | None, int | None]:
    """Return (duration_s, bitrate_kbps)."""
    try:
        data = await probe(path)
        fmt = data.get("format") or {}
        duration = float(fmt["duration"]) if fmt.get("duration") else None
        bitrate = int(int(fmt.get("bit_rate") or 0) / 1000) or None
        if not bitrate:
            for s in data.get("streams") or []:
                if s.get("codec_type") == "audio" and s.get("bit_rate"):
                    bitrate = int(int(s["bit_rate"]) / 1000)
                    break
        return duration, bitrate
    except Exception:  # noqa: BLE001
        return None, None


async def convert_to_mp3(src, dst: str | None = None,
                         quality: str = "320k", progress=None) -> str:
    """Convert any audio container/codecs to MP3. Returns destination path."""
    src = str(src)
    if dst is None:
        p = __import__("pathlib").Path(src)
        dst = str(p.with_suffix(".mp3"))

    ffmpeg = _resolve("ffmpeg", settings.ffmpeg_path)
    cmd = [
        ffmpeg, "-y", "-i", src,
        "-vn",
        "-codec:a", "libmp3lame",
        "-b:a", quality if quality.endswith("k") else None or quality,
        "-ar", "44100",
        dst,
    ]
    cmd = [c for c in cmd if c is not None]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg conversion failed: {err.decode(errors='ignore')[-400:]}")
    return str(dst)


def has_ffmpeg() -> bool:
    return bool(shutil.which(settings.ffmpeg_path))
