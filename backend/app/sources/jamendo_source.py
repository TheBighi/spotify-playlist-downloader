"""Jamendo source adapter - free music catalog, requires a client id via JAMENDO_CLIENT_ID."""

from pathlib import Path

import httpx

from ..config import settings
from ..schemas import SpotifyTrack
from ..utils import parse_duration_seconds
from .base import Candidate, ProgressCallback, SourceAdapter, SourceError


class JamendoSource(SourceAdapter):
    name = "jamendo"
    human_name = "Jamendo"
    supports_download = True

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=True)

    @property
    def enabled(self) -> bool:
        return bool(settings.jamendo_client_id)

    def query_for_track(self, track: SpotifyTrack) -> str:
        return f"{track.title} {track.artists.split(',')[0].strip()}"

    async def search(self, query: str, limit: int = 8) -> list[Candidate]:
        if not settings.jamendo_client_id:
            raise SourceError("jamendo disabled: missing client id")
        try:
            r = await self._client.get(
                "https://api.jamendo.com/v3.0/tracks/",
                params={
                    "client_id": settings.jamendo_client_id,
                    "format": "json",
                    "search": query,
                    "limit": str(limit),
                    "include": "licenses",
                },
            )
            r.raise_for_status()
            rows = (r.json().get("results")) or []
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"jamendo search failed: {exc}") from exc

        out: list[Candidate] = []
        for t in rows:
            artist = t.get("artist_name") or ""
            out.append(Candidate(
                source=self.name,
                source_id=str(t.get("id", "")),
                title=t.get("name") or "",
                artist=artist,
                artists_all=artist,
                album=t.get("album_name"),
                duration_s=parse_duration_seconds(t.get("duration")),
                url=t.get("shareurl") or "",
                download_url=t.get("audiodownload") or t.get("audio"),
                bitrate_kbps=192 if t.get("audiodownload") else 128,
                ext="mp3",
                artwork_url=t.get("image"),
                play_count=0,
                extra={"license": (t.get("license_ccurl") or "")},
            ))
        return out

    async def download(self, candidate: Candidate, dest_dir: Path,
                       progress: ProgressCallback | None = None) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / f"jam_{candidate.source_id}.mp3"
        try:
            async with self._client.stream("GET", candidate.download_url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                done = 0
                with open(out, "wb") as fh:
                    async for chunk in resp.aiter_bytes(128 * 1024):
                        fh.write(chunk)
                        done += len(chunk)
                        if progress and total:
                            await progress(done, total)
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"jamendo download failed: {exc}") from exc
        return out
