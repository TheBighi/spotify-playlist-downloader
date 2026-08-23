"""Per-track processing pipeline: search -> rank -> download -> convert -> tag."""

import asyncio
import logging
import shutil
from pathlib import Path

import httpx
from mutagen.id3 import APIC, COMM, ID3, TALB, TIT2, TPE1, TRCK, TDRC

from . import matching
from .config import settings
from .ffmpeg_utils import convert_to_mp3, probe_audio_info
from .schemas import SpotifyTrack
from .sources.base import Candidate
from .sources.registry import SourceError, registry
from .utils import sanitize_filename

log = logging.getLogger("pipeline")


class PipelineCallbacks:
    """Abstraction so the pipeline can report progress without knowing about jobs."""

    async def on_stage(self, track_id: int, status: str, message: str = "") -> None: ...
    async def on_progress(self, track_id: int, pct: int, message: str = "") -> None: ...


async def _download_artwork(url: str | None, client: httpx.AsyncClient) -> bytes | None:
    if not url:
        return None
    try:
        r = await client.get(url, timeout=20)
        r.raise_for_status()
        if len(r.content) > 50 * 1024 * 1024:
            return None
        ctype = r.headers.get("content-type", "")
        if not ctype.startswith("image/") and not url.endswith((".jpg", ".jpeg", ".png")):
            return None
        return r.content
    except Exception:  # noqa: BLE001
        return None


def _tag_mp3(path: Path, track: SpotifyTrack, source_url: str | None, artwork: bytes | None) -> None:
    try:
        audio = ID3(str(path))
    except Exception:  # noqa: BLE001
        audio = ID3()

    audio.setall("TIT2", [TIT2(encoding=3, text=track.title)])
    audio.setall("TPE1", [TPE1(encoding=3, text=track.artists)])
    if track.album:
        audio.setall("TALB", [TALB(encoding=3, text=track.album)])
    if track.track_number:
        total = ""
        audio.setall("TRCK", [TRCK(encoding=3, text=f"{track.track_number}/{total}".strip("/"))])
    date = track.release_date or ""
    if date:
        audio.setall("TDRC", [TDRC(encoding=3, text=date)])
    if source_url:
        audio.setall("COMM", [COMM(encoding=3, lang="eng", desc="Source",
                                   text=f"Downloaded via {source_url}")])
    if artwork:
        audio.setall("APIC", [APIC(encoding=3, mime="image/jpeg", type=3,
                                   desc="Cover", data=artwork)])
    audio.save(str(path), v2_version=3)


def unique_path(directory: Path, name: str) -> Path:
    base = directory / name
    if not base.exists():
        return base
    stem, suffix = base.stem, base.suffix
    i = 2
    while True:
        cand = directory / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


class TrackProcessor:
    def __init__(self, callbacks: PipelineCallbacks):
        self.cb = callbacks
        self._http = httpx.AsyncClient(timeout=30, follow_redirects=True)

    async def close(self):
        await self._http.aclose()

    def candidate_payload(self, ranked: list) -> list[dict]:
        """Serializable info for the top ranked candidates (for manual review UI)."""
        out = []
        for i, s in enumerate(ranked[:6]):
            c = s.candidate
            out.append({
                "index": i,
                "source": c.source,
                "title": c.title,
                "artist": c.artist or c.artists_all,
                "album": c.album,
                "duration_s": c.duration_s,
                "url": c.url,
                "confidence": round(s.score, 3),
                # fields needed to re-instantiate the candidate for a specific download
                "source_id": c.source_id,
                "download_url": c.download_url,
                "needs_stream_download": c.needs_stream_download,
                "bitrate_kbps": c.bitrate_kbps,
                "ext": c.ext,
                "artwork_url": c.artwork_url,
                "artists_all": c.artists_all,
            })
        return out

    @staticmethod
    def candidate_from_payload(p: dict) -> Candidate:
        return Candidate(
            source=p["source"], source_id=p["source_id"], title=p["title"],
            artist=p.get("artist") or "", url=p.get("url") or "",
            artists_all=p.get("artists_all") or "", album=p.get("album"),
            duration_s=p.get("duration_s"), download_url=p.get("download_url"),
            needs_stream_download=bool(p.get("needs_stream_download")),
            bitrate_kbps=p.get("bitrate_kbps"), ext=p.get("ext"),
            artwork_url=p.get("artwork_url"),
        )

    async def process(self, track: SpotifyTrack, track_id: int, workdir: Path,
                      outdir: Path, force: bool = False,
                      specific: dict | None = None) -> dict:
        """Runs the full pipeline for one track. Returns result dict.

        `specific` (candidate payload from a previous uncertain result) skips
        search/ranking and downloads exactly that candidate.
        """
        result: dict = {"confidence": 0.0, "source": None, "source_url": None,
                        "filename": None, "error": None, "candidates": None}

        if specific is not None:
            chosen = self.candidate_from_payload(specific)
            result["confidence"] = specific.get("confidence", 0.0)
            return await self._finish(track, track_id, chosen, [], workdir, outdir, result)

        # ---- 1. Search all sources concurrently ----
        await self.cb.on_stage(track_id, "searching", "Searching sources...")
        candidates, errors = await registry.search_for_track(
            track, limit=settings.candidates_per_source, timeout_s=settings.search_timeout_s)

        if not candidates:
            # one retry with a simpler query
            simple = f"{track.title} {track.artists.split(',')[0].strip()}"
            candidates, _ = await registry.search_for_track(
                track.model_copy(update={"title": simple, "artists": ""}),
                limit=settings.candidates_per_source, timeout_s=settings.search_timeout_s)

        if errors:
            log.info("search errors for '%s': %s", track.title, errors)
        if not candidates:
            msg = "no results from any source" + (f" ({errors})" if errors else "")
            result["error"] = msg
            await self.cb.on_stage(track_id, "failed", msg)
            return result

        # ---- 2. Rank ----
        await self.cb.on_stage(track_id, "ranking",
                               f"Ranking {len(candidates)} candidates...")
        ranked = matching.rank_candidates(candidates, track)
        best = ranked[0]
        conf = best.score
        result["confidence"] = round(conf, 3)
        result["candidates"] = self.candidate_payload(ranked)

        top_summary = "; ".join(
            f"{s.candidate.source}:{s.candidate.title[:40]}={s.score:.2f}" for s in ranked[:3])
        log.info("best for '%s - %s' -> %s [%s]", track.artists, track.title, top_summary, errors)

        # ---- 3. Confidence gate ----
        chosen: Candidate = best.candidate
        if not force and conf < settings.confidence_auto_accept:
            msg = f"needs review: best match is '{chosen.title}' by {chosen.artist} ({conf:.2f})"
            result["error"] = msg
            result["source"], result["source_url"] = chosen.source, chosen.url
            await self.cb.on_stage(track_id, "uncertain", msg)
            return result

        return await self._finish(track, track_id, chosen, ranked, workdir, outdir, result)

    async def _finish(self, track: SpotifyTrack, track_id: int, chosen: Candidate,
                      ranked: list, workdir: Path, outdir: Path, result: dict) -> dict:
        # ---- 4. Download ----
        adapter = next((s for s in registry.sources if s.name == chosen.source), None)
        if adapter is None or not adapter.supports_download:
            result["error"] = f"source {chosen.source} cannot download"
            await self.cb.on_stage(track_id, "failed", result["error"])
            return result

        tmp_dir = workdir / f"tmp_{track_id}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        async def dl_progress(done: int, total: int) -> None:
            pct = int(done * 100 / max(total, 1))
            await self.cb.on_progress(track_id, pct, f"Downloading ({pct}%)")

        await self.cb.on_stage(track_id, "downloading",
                               f"Downloading from {adapter.human_name}...")
        try:
            raw_file = await asyncio.wait_for(
                adapter.download(chosen, tmp_dir, dl_progress), timeout=420)
        except (SourceError, asyncio.TimeoutError) as exc:
            # try the next-best candidate before giving up
            fallback = None
            for alt in ranked[1:]:
                alt_adapter = next((s for s in registry.sources if s.name == alt.candidate.source), None)
                if alt_adapter and alt_adapter.supports_download:
                    fallback = (alt_adapter, alt.candidate)
                    break
            if fallback is None:
                result["error"] = f"download failed: {exc}"
                await self.cb.on_stage(track_id, "failed", result["error"])
                result["source"], result["source_url"] = chosen.source, chosen.url
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return result
            adapter, chosen = fallback
            try:
                raw_file = await asyncio.wait_for(
                    adapter.download(chosen, tmp_dir, dl_progress), timeout=420)
            except Exception as exc2:  # noqa: BLE001
                result["error"] = f"download failed: {exc}; fallback failed: {exc2}"
                await self.cb.on_stage(track_id, "failed", result["error"])
                result["source"], result["source_url"] = chosen.source, chosen.url
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return result

        result["source"] = chosen.source
        result["source_url"] = chosen.url

        # ---- 5. Convert ----
        await self.cb.on_stage(track_id, "converting", "Converting to MP3...")
        try:
            duration, bitrate = await probe_audio_info(raw_file)
            needs_convert = raw_file.suffix.lower() != ".mp3" or (bitrate or 0) < 190
            if needs_convert:
                final_tmp = tmp_dir / "out.mp3"
                await convert_to_mp3(raw_file, dst=str(final_tmp), quality="320k")
            else:
                final_tmp = tmp_dir / "keep.mp3"
                shutil.copyfile(raw_file, final_tmp)
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"conversion failed: {exc}"
            await self.cb.on_stage(track_id, "failed", result["error"])
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return result

        # ---- 6. Tag ----
        await self.cb.on_stage(track_id, "tagging", "Embedding metadata & artwork...")
        art_url = track.artwork_url or chosen.artwork_url
        artwork = await _download_artwork(art_url, self._http)
        _tag_mp3(final_tmp, track, chosen.url, artwork)

        # ---- 7. Finalize ----
        fname = sanitize_filename(f"{track.artists} - {strip_feat_title(track.title)}.mp3")
        dest = unique_path(outdir, fname)
        shutil.move(str(final_tmp), dest)
        shutil.rmtree(tmp_dir, ignore_errors=True)

        dur, brate = await probe_audio_info(dest)
        result.update({
            "filename": dest.name,
            "file_size": dest.stat().st_size,
            "bitrate_kbps": brate,
        })
        await self.cb.on_progress(track_id, 100, "Done")
        await self.cb.on_stage(track_id, "completed", "")
        return result

    async def preview_best(self, track: SpotifyTrack, track_id: int) -> dict:
        """Search+rank only (used for uncertain->force decisions)."""
        candidates, errors = await registry.search_for_track(
            track, limit=settings.candidates_per_source, timeout_s=settings.search_timeout_s)
        ranked = matching.rank_candidates(candidates, track) if candidates else []
        return {
            "candidates": [
                {"source": s.candidate.source, "title": s.candidate.title,
                 "artist": s.candidate.artist, "score": round(s.score, 3),
                 "url": s.candidate.url}
                for s in ranked[:5]
            ],
            "errors": errors,
        }


def strip_feat_title(title: str) -> str:
    from .matching import strip_feat_text
    return strip_feat_text(title)
