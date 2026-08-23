"""Job manager: orchestrates background processing, live events, artifacts."""

import asyncio
import logging
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .db import JobRow, SessionLocal, TrackRow, init_db, new_job_id
from .pipeline import PipelineCallbacks, TrackProcessor
from .schemas import CandidateInfo, JobState, PlaylistMeta, TrackState

log = logging.getLogger("jobs")


@dataclass
class JobRuntime:
    id: str
    dir: Path
    state: JobState
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None
    cancelled: bool = False


class ManagerCallbacks(PipelineCallbacks):
    def __init__(self, manager: "JobManager", job_id: str):
        self.m = manager
        self.job_id = job_id

    async def on_stage(self, track_id: int, status: str, message: str = "") -> None:
        await self.m.update_track_status(self.job_id, track_id, status=status,
                                         stage_message=message)

    async def on_progress(self, track_id: int, pct: int, message: str = "") -> None:
        await self.m.publish_progress(self.job_id, track_id, pct, message)


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, JobRuntime] = {}
        self._lock = asyncio.Lock()

    # ---------------- lifecycle ----------------

    def startup(self) -> None:
        init_db()
        asyncio.get_event_loop().create_task(self._cleanup_loop())

    def job_dir(self, job_id: str) -> Path:
        return settings.data_dir / "jobs" / job_id

    async def create_job(self, playlist: PlaylistMeta,
                         track_positions: list[int] | None = None) -> JobState:
        job_id = new_job_id()
        jdir = self.job_dir(job_id)
        (jdir / "tmp").mkdir(parents=True, exist_ok=True)

        selected = playlist.tracks
        if track_positions:
            wanted = set(track_positions)
            selected = [t for t in playlist.tracks if t.position in wanted]
        if not selected:
            selected = playlist.tracks

        def persist() -> None:
            with SessionLocal() as s:
                s.add(JobRow(
                    id=job_id, playlist_id=playlist.playlist_id,
                    playlist_name=playlist.name, playlist_url=playlist.url,
                    artwork_url=playlist.artwork_url, status="created"))
                for t in selected:
                    s.add(TrackRow(
                        job_id=job_id, position=t.position, spotify_id=t.spotify_id,
                        title=t.title, artists=t.artists, album=t.album,
                        duration_ms=t.duration_ms, artwork_url=t.artwork_url,
                        release_date=t.release_date, track_number=t.track_number))
                s.commit()

        await asyncio.to_thread(persist)

        state = JobState(
            id=job_id, playlist_id=playlist.playlist_id, playlist_name=playlist.name,
            playlist_url=playlist.url, artwork_url=playlist.artwork_url,
            status="created", created_at=time.time(), total_tracks=len(selected),
            tracks=[TrackState(
                id=t.position, position=t.position, title=t.title, artists=t.artists,
                album=t.album, duration_ms=t.duration_ms, artwork_url=t.artwork_url,
                release_date=t.release_date, status="queued") for t in selected],
        )
        rt = JobRuntime(id=job_id, dir=jdir, state=state)
        self.jobs[job_id] = rt
        return state

    async def start_job(self, job_id: str) -> None:
        rt = self.jobs.get(job_id)
        if not rt or rt.task and not rt.task.done():
            return
        rt.cancelled = False
        rt.state.status = "running"
        await self._publish(rt, {"type": "job", "status": "running"})
        rt.task = asyncio.create_task(self._run_job(rt))

    async def _run_job(self, rt: JobRuntime) -> None:
        cb = ManagerCallbacks(self, rt.id)
        proc = TrackProcessor(cb)
        sem = asyncio.Semaphore(settings.max_concurrent_tracks)
        try:
            async def worker(ts: TrackState):
                async with sem:
                    if rt.cancelled:
                        return
                    await self._process_one(rt, proc, ts, force=False)

            await asyncio.gather(*(worker(ts) for ts in list(rt.state.tracks)))
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s crashed: %s", rt.id, exc)
            rt.state.status = "failed"
        finally:
            await proc.close()
            if not rt.cancelled:
                any_ok = any(t.status == "completed" for t in rt.state.tracks)
                rt.state.status = "completed" if any_ok else "completed_with_errors"
            else:
                rt.state.status = "cancelled"
            await self._persist_job_status(rt)
            await self._publish(rt, {
                "type": "done", "status": rt.state.status,
                **self._counters(rt),
            })
            shutil.rmtree(rt.dir / "tmp", ignore_errors=True)
            for p in rt.dir.glob("tmp_*"):
                shutil.rmtree(p, ignore_errors=True)

    async def _process_one(self, rt: JobRuntime, proc: TrackProcessor, ts: TrackState,
                           force: bool = False, specific: dict | None = None) -> None:
        sp_track = track_model_to_spotify(ts)
        result = await proc.process(sp_track, ts.id, workdir=rt.dir, outdir=rt.dir,
                                    force=force, specific=specific)
        # statuses were already updated via callbacks; fill final fields
        if result.get("candidates"):
            ts.candidates = [CandidateInfo(**c) for c in result["candidates"]]
            ts.error = result.get("error")
            ts.confidence = result.get("confidence") or ts.confidence
        if result["filename"]:
            ts.filename = result["filename"]
            ts.file_size = result["file_size"]
            ts.bitrate_kbps = result["bitrate_kbps"]
            ts.has_file = True
        if result["confidence"]:
            ts.confidence = result["confidence"]
        if result["source"]:
            ts.source = result["source"]
        if result["source_url"]:
            ts.source_url = result["source_url"]
        await self._publish_track(rt, ts)

    # ---------------- updates ----------------

    async def update_track_status(self, job_id: str, track_id: int, *,
                                  status: str | None = None,
                                  stage_message: str | None = None) -> None:
        rt = self.jobs.get(job_id)
        if not rt:
            return
        ts = next((t for t in rt.state.tracks if t.id == track_id), None)
        if not ts:
            return
        if status:
            ts.status = status
        if stage_message is not None:
            ts.stage_message = stage_message
        await self._publish_track(rt, ts)

    async def publish_progress(self, job_id: str, track_id: int, pct: int,
                               message: str) -> None:
        rt = self.jobs.get(job_id)
        if not rt:
            return
        await self._publish(rt, {"type": "progress", "track_id": track_id,
                                 "pct": pct, "message": message})

    async def retry_track(self, job_id: str, track_id: int, force: bool = False,
                          candidate_index: int | None = None,
                          reject: bool = False) -> bool:
        rt = self.jobs.get(job_id)
        if not rt:
            return False
        ts = next((t for t in rt.state.tracks if t.id == track_id), None)
        if not ts:
            return False

        if reject:
            ts.status = "rejected"
            ts.stage_message = "Rejected — will not download"
            await self._publish_track(rt, ts)
            return True

        specific: dict | None = None
        if candidate_index is not None and ts.candidates:
            for c in ts.candidates:
                if c.index == candidate_index:
                    specific = c.model_dump()
                    break
            if specific is None and 0 <= candidate_index < len(ts.candidates):
                specific = ts.candidates[candidate_index].model_dump()
            if specific is None:
                return False

        async def runner():
            cb = ManagerCallbacks(self, job_id)
            proc = TrackProcessor(cb)
            try:
                ts.status = "searching" if specific is None else "downloading"
                ts.stage_message = "Re-searching..." if specific is None else \
                    f"Downloading accepted match from {specific['source']}..."
                await self._publish_track(rt, ts)
                await self._process_one(rt, proc, ts, force=force, specific=specific)
                if ts.status == "completed":
                    ts.candidates = []
                    ts.stage_message = ""
                    await self._publish_track(rt, ts)
            finally:
                await proc.close()

        asyncio.create_task(runner())
        return True

    async def cancel_job(self, job_id: str) -> bool:
        rt = self.jobs.get(job_id)
        if not rt:
            return False
        rt.cancelled = True
        return True

    # ---------------- queries & artifacts ----------------

    def get_state(self, job_id: str) -> JobState | None:
        rt = self.jobs.get(job_id)
        return rt.state if rt else None

    def subscribe(self, job_id: str) -> tuple[JobRuntime | None, asyncio.Queue]:
        rt = self.jobs.get(job_id)
        if not rt:
            return None, asyncio.Queue()
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        rt.subscribers.add(q)
        return rt, q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        rt = self.jobs.get(job_id)
        if rt:
            rt.subscribers.discard(q)

    def find_file(self, job_id: str, track_id: int) -> Path | None:
        rt = self.jobs.get(job_id)
        if not rt:
            return None
        ts = next((t for t in rt.state.tracks if t.id == track_id), None)
        if not ts or not ts.has_file or not ts.filename:
            return None
        p = rt.dir / ts.filename
        return p if p.exists() else None

    def build_zip(self, job_id: str) -> Path | None:
        rt = self.jobs.get(job_id)
        if not rt:
            return None
        files = [(rt.dir / t.filename) for t in rt.state.tracks
                 if t.has_file and t.filename and (rt.dir / t.filename).exists()]
        if not files:
            return None
        safe_name = "".join(c for c in rt.state.playlist_name if c.isalnum() or c in " -_").strip() or "playlist"
        zip_path = settings.data_dir / f"{job_id}_{safe_name[:60]}.zip"
        if zip_path.exists():
            newest_src = max(f.stat().st_mtime for f in files)
            if zip_path.stat().st_mtime >= newest_src:
                return zip_path
        tmp = zip_path.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
            for f in files:
                zf.write(f, arcname=f.name)
        tmp.replace(zip_path)
        return zip_path

    # ---------------- internals ----------------

    def _counters(self, rt: JobRuntime) -> dict:
        done = sum(1 for t in rt.state.tracks if t.status == "completed")
        failed = sum(1 for t in rt.state.tracks if t.status == "failed")
        uncertain = sum(1 for t in rt.state.tracks if t.status == "uncertain")
        rejected = sum(1 for t in rt.state.tracks if t.status == "rejected")
        processed = done + failed + uncertain + rejected
        progress = round(processed * 100.0 / max(len(rt.state.tracks), 1), 1)
        rt.state.completed, rt.state.failed = done, failed
        rt.state.uncertain, rt.state.processed = uncertain, processed
        rt.state.overall_progress = progress
        return {"completed": done, "failed": failed, "uncertain": uncertain,
                "rejected": rejected, "processed": processed, "overall_progress": progress}

    def _publish_nowait(self, rt: JobRuntime, payload: dict) -> None:
        dead = []
        for q in rt.subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            rt.subscribers.discard(q)

    async def _publish(self, rt: JobRuntime, payload: dict) -> None:
        self._publish_nowait(rt, payload)
        await self._persist_job_counters(rt)

    async def _publish_track(self, rt: JobRuntime, ts: TrackState) -> None:
        self._counters(rt)
        self._publish_nowait(rt, {"type": "track", "track": ts.model_dump(),
                                  "summary": {k: v for k, v in _state_summary(rt.state).items()}})
        await asyncio.to_thread(self._sync_job_row, rt)

    def _sync_job_row(self, rt: JobRuntime) -> None:
        with SessionLocal() as s:
            row = s.get(JobRow, rt.id)
            if not row:
                return
            row.status = rt.state.status
            row.updated_at = time.time()
            rows = {r.position: r for r in s.query(TrackRow).filter_by(job_id=rt.id)}
            for t in rt.state.tracks:
                tr = rows.get(t.id)
                if tr is None:
                    continue
                tr.status = t.status
                tr.stage_message = t.stage_message
                tr.confidence = t.confidence
                tr.source = t.source
                tr.source_url = t.source_url
                tr.filename = t.filename
                tr.file_size = t.file_size
                tr.bitrate_kbps = t.bitrate_kbps
                tr.error = t.error
                tr.has_file = t.has_file
            s.commit()

    async def _persist_job_counters(self, rt: JobRuntime) -> None:
        await asyncio.to_thread(self._sync_job_row, rt)

    async def _persist_job_status(self, rt: JobRuntime) -> None:
        await asyncio.to_thread(self._sync_job_row, rt)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(1800)
            cutoff = time.time() - settings.cleanup_after_hours * 3600
            base = settings.data_dir / "jobs"
            if not base.exists():
                continue
            for d in base.iterdir():
                try:
                    if d.is_dir() and d.stat().st_mtime < cutoff:
                        rt = self.jobs.pop(d.name, None)
                        if rt and rt.task and not rt.task.done():
                            continue
                        shutil.rmtree(d, ignore_errors=True)
                        log.info("cleaned up job dir %s", d.name)
                except Exception:  # noqa: BLE001
                    continue
            zips = settings.data_dir.glob("*.zip")
            for z in zips:
                try:
                    if z.stat().st_mtime < cutoff:
                        z.unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    continue


def _state_summary(state: JobState) -> dict:
    done = sum(1 for t in state.tracks if t.status == "completed")
    failed = sum(1 for t in state.tracks if t.status == "failed")
    uncertain = sum(1 for t in state.tracks if t.status == "uncertain")
    rejected = sum(1 for t in state.tracks if t.status == "rejected")
    processed = done + failed + uncertain + rejected
    return {"completed": done, "failed": failed, "uncertain": uncertain,
            "rejected": rejected, "processed": processed,
            "overall_progress": round(processed * 100.0 / max(len(state.tracks), 1), 1)}


def track_model_to_spotify(ts: TrackState):
    from .schemas import SpotifyTrack
    return SpotifyTrack(
        position=ts.position,
        title=ts.title,
        artists=ts.artists,
        album=ts.album,
        duration_ms=ts.duration_ms,
        artwork_url=ts.artwork_url,
        release_date=ts.release_date,
    )


manager = JobManager()
