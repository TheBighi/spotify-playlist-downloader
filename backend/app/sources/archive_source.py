"""Internet Archive source adapter - advancedsearch + metadata APIs, direct MP3 downloads."""

import asyncio
import urllib.parse
from pathlib import Path

import httpx

from ..schemas import SpotifyTrack
from ..utils import parse_duration_seconds
from .base import Candidate, ProgressCallback, SourceAdapter, SourceError


class InternetArchiveSource(SourceAdapter):
    name = "internetarchive"
    human_name = "Internet Archive"
    supports_download = True

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=True)

    def query_for_track(self, track: SpotifyTrack) -> str:
        return f'"{track.title}" AND mediatype:(audio)'

    async def search(self, query: str, limit: int = 8) -> list[Candidate]:
        try:
            r = await self._client.get(
                "https://archive.org/advancedsearch.php",
                params={
                    "q": query,
                    "fl[]": ["identifier", "title", "creator", "downloads"],
                    "rows": str(min(limit // 2 or 4, 6)),
                    "page": "1",
                    "output": "json",
                    "sort[]": "-downloads",
                },
            )
            r.raise_for_status()
            docs = (r.json().get("response", {}).get("docs")) or []
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"archive search failed: {exc}") from exc

        sem = asyncio.Semaphore(4)
        results: list[Candidate] = []

        async def fetch_meta(doc: dict) -> None:
            ident = doc.get("identifier")
            if not ident:
                return
            async with sem:
                try:
                    m = await self._client.get(f"https://archive.org/metadata/{ident}")
                    m.raise_for_status()
                    data = m.json()
                except Exception:  # noqa: BLE001
                    return
            files = data.get("files") or []
            best: dict | None = None
            for f in files:
                name = f.get("name", "")
                if not name.lower().endswith(".mp3"):
                    continue
                fmt = (f.get("format") or "").lower()
                if "mp3" in fmt:
                    if best is None or int(f.get("size") or 0) > int(best.get("size") or 0):
                        best = f
            if not best:
                return
            title = best.get("title") or doc.get("title") or ident
            creator = doc.get("creator") or ""
            if isinstance(creator, list):
                creator = ", ".join(creator)
            length = parse_duration_seconds(best.get("length"))
            dl_url = f"https://archive.org/download/{urllib.parse.quote(ident)}/{urllib.parse.quote(best['name'])}"
            results.append(Candidate(
                source=self.name,
                source_id=f"{ident}/{best['name']}",
                title=str(title),
                artist=creator or ident,
                artists_all=creator or "",
                album=(doc.get("title") if isinstance(doc.get("title"), str) else None),
                duration_s=length,
                url=f"https://archive.org/details/{ident}",
                download_url=dl_url,
                bitrate_kbps=None,
                ext="mp3",
                play_count=int(doc.get("downloads") or 0),
                extra={"item": ident},
            ))

        await asyncio.gather(*(fetch_meta(d) for d in docs))
        return results

    async def download(self, candidate: Candidate, dest_dir: Path,
                       progress: ProgressCallback | None = None) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / f"ia_{abs(hash(candidate.source_id)) % 10**10}.mp3"
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
            raise SourceError(f"archive download failed: {exc}") from exc
        return out
