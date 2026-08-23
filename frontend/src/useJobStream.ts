import { useEffect, useRef, useState } from "react";
import type { JobState, TrackState } from "./types";

type Handler = (job: JobState) => void;

/**
 * Subscribes to the job's SSE stream and maintains a live-updated JobState.
 */
export function useJobStream(jobId: string | null, onDone?: () => void): {
  job: JobState | null;
  connected: boolean;
} {
  const [job, setJob] = useState<JobState | null>(null);
  const [connected, setConnected] = useState(false);
  const doneCb = useRef(onDone);
  doneCb.current = onDone;

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    let current: JobState | null = null;

    es.addEventListener("open", () => setConnected(true));

    es.addEventListener("snapshot", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setJob(data.job);
      current = data.job;
    });

    es.onmessage = (ev) => {
      const payload = JSON.parse(ev.data);
      setJob((prev) => {
        if (!prev) return prev;
        const next: JobState = structuredClone(prev);
        if (payload.type === "track") {
          applyTrack(next, payload.track as TrackState);
        } else if (payload.type === "progress") {
          const t = next.tracks.find((t) => t.id === payload.track_id);
          if (t) t.stage_message = payload.message ?? t.stage_message;
        } else if (payload.type === "job") {
          next.status = payload.status ?? next.status;
        } else if (payload.type === "done") {
          next.status = payload.status;
          Object.assign(next, pickCounters(payload));
          doneCb.current?.();
        }
        recomputeSummary(next);
        current = next;
        return next;
      });
    };

    es.onerror = () => {
      setConnected(false);
      // EventSource auto-reconnects; snapshot will refresh state
    };
    es.addEventListener("snapshot", () => setConnected(true));

    return () => es.close();
  }, [jobId]);

  return { job, connected };
}

function applyTrack(job: JobState, track: TrackState) {
  const idx = job.tracks.findIndex((t) => t.id === track.id);
  if (idx >= 0) job.tracks[idx] = track;
}

function recomputeSummary(job: JobState) {
  const completed = job.tracks.filter((t) => t.status === "completed").length;
  const failed = job.tracks.filter((t) => t.status === "failed").length;
  const uncertain = job.tracks.filter((t) => t.status === "uncertain").length;
  const rejected = job.tracks.filter((t) => t.status === "rejected").length;
  const processed = completed + failed + uncertain + rejected;
  job.completed = completed;
  job.failed = failed;
  job.uncertain = uncertain;
  job.rejected = rejected;
  job.processed = processed;
  job.overall_progress = Math.round(
    (processed * 100) / Math.max(job.tracks.length, 1)
  );
}

function pickCounters(p: Record<string, unknown>) {
  const out: Record<string, unknown> = {};
  for (const k of ["completed", "failed", "uncertain", "processed", "overall_progress"]) {
    if (k in p) out[k] = p[k];
  }
  return out;
}
