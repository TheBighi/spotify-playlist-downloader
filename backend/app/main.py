import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .ffmpeg_utils import has_ffmpeg
from .jobs import manager
from .schemas import JobCreateRequest, PlaylistPreviewRequest, RetryRequest
from .spotify import SpotifyError, spotify_client
from .sources.registry import registry

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.startup()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok", "ffmpeg": has_ffmpeg()}


@app.get("/api/sources")
async def sources():
    return {"sources": registry.names()}


@app.post("/api/playlists/preview")
async def preview_playlist(req: PlaylistPreviewRequest):
    try:
        playlist = await spotify_client.get_playlist(req.url)
    except SpotifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return playlist.model_dump()


@app.post("/api/jobs")
async def create_job(req: JobCreateRequest):
    try:
        playlist = await spotify_client.get_playlist(req.url)
    except SpotifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state = await manager.create_job(playlist, req.track_positions)
    await manager.start_job(state.id)
    return state.model_dump()


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    state = manager.get_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="job not found")
    return state.model_dump()


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    ok = await manager.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"cancelled": True}


@app.post("/api/jobs/{job_id}/retry")
async def retry_track(job_id: str, req: RetryRequest):
    ok = await manager.retry_track(job_id, req.track_id, force=req.force,
                                   candidate_index=req.candidate_index,
                                   reject=req.reject)
    if not ok:
        raise HTTPException(status_code=404, detail="track or job not found")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    rt, queue = manager.subscribe(job_id)
    if rt is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def stream():
        # initial snapshot so late subscribers catch up
        snap = json.dumps({"type": "snapshot",
                           "job": rt.state.model_dump()}, default=str)
        yield f"event: snapshot\ndata: {snap}\n\n"
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    data = json.dumps(payload, default=str)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            manager.unsubscribe(job_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/jobs/{job_id}/tracks/{track_id}/file")
async def track_file(job_id: str, track_id: int):
    path = manager.find_file(job_id, track_id)
    if not path:
        raise HTTPException(status_code=404, detail="file not available")
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)


@app.get("/api/jobs/{job_id}/zip")
async def job_zip(job_id: str):
    path = manager.build_zip(job_id)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="no completed files to zip yet")
    return FileResponse(path, media_type="application/zip", filename=path.name)


# ---- static frontend (built React app) ----
FRONTEND_DIST = settings.data_dir.parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


def run() -> None:
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
