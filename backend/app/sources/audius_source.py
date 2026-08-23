"""Audius source adapter - public API, free streaming MP3s, no credentials required."""

import asyncio
from pathlib import Path

import httpx

from ..config import settings
from ..schemas import SpotifyTrack
from ..utils import parse_duration_seconds
from .base import Candidate, ProgressCallback, SourceAdapter, SourceError

APP_NAME = "PlaylistDownloader"


class AudiusSource(SourceAdapter):
    name = "audius"
    human_name = "Audius"
    supports_download = True

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=True)

    def query_for_track(self, track: SpotifyTrack) -> str:
        return f"{track.artists.split(',')[0].strip()} {strip_tags(track.title)}"

    async def search(self, query: str, limit: int = 8) -> list[Candidate]:
        last_err: Exception | None = None
        for host in settings.audius_hosts:
            try:
                r = await self._client.get(
                    f"{host}/v1/tracks/search",
                    params={"query": query, "app_name": APP_NAME, "limit": max(limit, 4)},
                )
                r.raise_for_status()
                data = r.json().get("data") or []
                if data:
                    return [self._to_candidate(t) for t in data[:limit]]
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
        raise SourceError(f"audius search failed: {last_err}")

    def _to_candidate(self, t: dict) -> Candidate:
        user = t.get("user") or {}
        artwork = t.get("artwork") or {}
        return Candidate(
            source=self.name,
            source_id=t.get("id", ""),
            title=t.get("title", ""),
            artist=user.get("name", ""),
            artists_all=user.get("name", ""),
            album=t.get("album_backlink", {}).get("playlist_name") if isinstance(t.get("album_backlink"), dict) else None,
            duration_s=parse_duration_seconds(t.get("duration")),
            url=t.get("permalink") or "",
            download_url=f"stream:{t.get('id', '')}",
            bitrate_kbps=320,
            ext="mp3",
            artwork_url=(artwork.get("480x480") or artwork.get("1000x1000") or artwork.get("150x150")),
            play_count=t.get("play_count") or 0,
            extra={"genre": t.get("genre"), "is_downloadable": t.get("is_downloadable")},
        )

    async def download(self, candidate: Candidate, dest_dir: Path,
                       progress: ProgressCallback | None = None) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        track_id = candidate.source_id
        last_err: Exception | None = None
        for host in settings.audius_hosts:
            try:
                async with self._client.stream(
                    "GET", f"{host}/v1/tracks/{track_id}/stream", params={"app_name": APP_NAME}
                ) as resp:
                    if resp.status_code in (403, 404):
                        last_err = SourceError(f"audius stream HTTP {resp.status_code}")
                        continue
                    resp.raise_for_status()
                    out = dest_dir / f"audius_{track_id}.mp3"
                    total = int(resp.headers.get("content-length") or 0)
                    done = 0
                    with open(out, "wb") as fh:
                        async for chunk in resp.aiter_bytes(64 * 1024):
                            fh.write(chunk)
                            done += len(chunk)
                            if progress and total:
                                await progress(done, total)
                    return out
            except httpx.HTTPStatusError as exc:
                last_err = exc
                continue
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
        raise SourceError(f"audius download failed: {last_err}")


_TAGS = ("official audio", "official video", "lyric video", "visualizer")


def strip_tags(title: str) -> str:
    t = title.lower()
    for tag in _TAGS:
        t = t.replace(tag, "")
    return t.strip() or title
