"""YouTube source adapter powered by yt-dlp (search + bestaudio download)."""

import asyncio
import re
from pathlib import Path

import yt_dlp

from ..schemas import SpotifyTrack
from ..utils import parse_duration_seconds
from .base import Candidate, ProgressCallback, SourceAdapter, SourceError


class YouTubeSource(SourceAdapter):
    name = "youtube"
    human_name = "YouTube"
    supports_download = True

    def query_for_track(self, track: SpotifyTrack) -> str:
        return f"{track.artists.split(',')[0].strip()} - {strip_version_tags(track.title)} audio"

    async def search(self, query: str, limit: int = 8) -> list[Candidate]:
        def _search() -> list[dict]:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "skip_download": True,
                "extract_flat": "in_playlist",
                "default_search": "ytsearch",
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{max(limit, 4)}:{query}", download=False)
            return list(info.get("entries") or []) if info else []

        try:
            entries = await asyncio.wait_for(asyncio.to_thread(_search), timeout=30)
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"yt-dlp search failed: {exc}") from exc

        candidates: list[Candidate] = []
        for e in entries or []:
            if not e:
                continue
            video_id = e.get("id")
            if not video_id:
                continue
            title = e.get("title") or ""
            channel = e.get("uploader") or e.get("channel") or ""
            candidates.append(Candidate(
                source=self.name,
                source_id=video_id,
                title=title,
                artist=channel,
                artists_all=channel,
                url=f"https://www.youtube.com/watch?v={video_id}",
                duration_s=parse_duration_seconds(e.get("duration")),
                ext="m4a",
                play_count=e.get("view_count") or 0,
                extra={"channel": channel},
            ))
        return candidates

    async def download(self, candidate: Candidate, dest_dir: Path,
                       progress: ProgressCallback | None = None) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()

        last_reported = {"pct": -1}

        def hook(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                if progress and total:
                    pct = int(done * 100 / total)
                    if pct != last_reported["pct"] and pct % 2 == 0:
                        last_reported["pct"] = pct
                        loop.create_task(progress(done, total))

        def _download() -> Path:
            outtmpl = str(dest_dir / f"yt_{candidate.source_id}.%(ext)s")
            opts = {
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "outtmpl": outtmpl,
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "noplaylist": True,
                "progress_hooks": [hook],
                "retries": 3,
                "socket_timeout": 20,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(candidate.url, download=True)
                if info is None:
                    raise SourceError("yt-dlp returned no info")
                requested = info.get("requested_downloads") or []
                if requested and requested[0].get("filepath"):
                    return Path(requested[0]["filepath"])
                # fallback: find newest file matching prefix
                matches = sorted(dest_dir.glob(f"yt_{candidate.source_id}.*"), key=lambda p: p.stat().st_mtime)
                if not matches:
                    raise SourceError("downloaded file not found")
                return matches[-1]

        try:
            return await asyncio.wait_for(asyncio.to_thread(_download), timeout=300)
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"yt-dlp download failed: {exc}") from exc


_VERSION_TAGS = re.compile(
    r"\b(lyrics?|lyric video|official (music )?video|official audio|visualizer|hd|hq|4k|mv|m/v)\b",
    re.IGNORECASE,
)


def strip_version_tags(title: str) -> str:
    t = _VERSION_TAGS.sub(" ", title)
    return re.sub(r"\s*[\(\[\{]\s*\)\s*\]|\s+", " ", t).strip()
