"""Source registry: discovers adapters and fans searches out concurrently."""

import asyncio
import logging

from .audius_source import AudiusSource
from .archive_source import InternetArchiveSource
from .base import Candidate, SourceAdapter, SourceError
from .jamendo_source import JamendoSource
from .youtube_source import YouTubeSource

log = logging.getLogger("sources")


def build_sources() -> list[SourceAdapter]:
    sources: list[SourceAdapter] = [YouTubeSource(), AudiusSource(), InternetArchiveSource()]
    jam = JamendoSource()
    if jam.enabled:
        sources.append(jam)
    return sources


class SourceRegistry:
    def __init__(self) -> None:
        self.sources: list[SourceAdapter] = build_sources()

    def names(self) -> list[dict]:
        return [{"name": s.name, "human_name": s.human_name} for s in self.sources]

    async def search_all(self, query: str, limit: int = 8,
                         timeout_s: float = 25.0) -> tuple[list[Candidate], dict[str, str]]:
        return await self._fan_out([(s, query) for s in self.sources], limit, timeout_s)

    async def search_for_track(self, track, limit: int = 8,
                               timeout_s: float = 25.0) -> tuple[list[Candidate], dict[str, str]]:
        """Each source searches with its own query built from spotify metadata."""
        pairs = [(s, s.query_for_track(track)) for s in self.sources]
        return await self._fan_out(pairs, limit, timeout_s)

    async def _fan_out(self, pairs: list[tuple[SourceAdapter, str]], limit: int,
                       timeout_s: float) -> tuple[list[Candidate], dict[str, str]]:
        """Search every source concurrently. Returns (candidates, per-source errors)."""
        async def run_one(src: SourceAdapter, query: str) -> tuple[str, list[Candidate], str | None]:
            try:
                results = await asyncio.wait_for(src.search(query, limit), timeout=timeout_s)
                return src.name, results or [], None
            except asyncio.TimeoutError:
                return src.name, [], f"timeout after {timeout_s:.0f}s"
            except SourceError as exc:
                return src.name, [], str(exc)
            except Exception as exc:  # noqa: BLE001
                log.warning("source %s crashed on '%s': %s", src.name, query, exc)
                return src.name, [], str(exc)

        outcomes = await asyncio.gather(*(run_one(s, q) for s, q in pairs))
        candidates: list[Candidate] = []
        errors: dict[str, str] = {}
        for name, cands, err in outcomes:
            if err:
                errors[name] = err
            candidates.extend(cands)
        return candidates, errors


registry = SourceRegistry()
