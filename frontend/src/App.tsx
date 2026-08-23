import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { PlaylistPreview, TrackState } from "./types";
import { useJobStream } from "./useJobStream";

type Phase = "idle" | "loading" | "preview" | "job";

export default function App() {
  const [url, setUrl] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [preview, setPreview] = useState<PlaylistPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<{ name: string; human_name: string }[]>([]);
  const [starting, setStarting] = useState(false);

  const [jobId, setJobId] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const { job, connected } = useJobStream(jobId, () => setDone(true));

  useEffect(() => {
    fetch(api.sourcesUrl())
      .then((r) => r.json())
      .then((d) => setSources(d.sources ?? []))
      .catch(() => undefined);
  }, []);

  // if the stream drops before done, poll as fallback
  useEffect(() => {
    if (phase !== "job" || !jobId || done || connected) return;
    const iv = setInterval(async () => {
      try {
        await api.getJob(jobId); // keep server warm; SSE snapshot refreshes on reconnect
      } catch {
        /* ignore */
      }
    }, 5000);
    return () => clearInterval(iv);
  }, [phase, jobId, done, connected]);

  const loadPreview = useCallback(async () => {
    setError(null);
    setPhase("loading");
    try {
      const p = await api.preview(url);
      setPreview(p);
      setPhase("preview");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("idle");
    }
  }, [url]);

  const startProcessing = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      const j = await api.createJob(url);
      setDone(false);
      setJobId(j.id);
      setPhase("job");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }, [url]);

  const reset = () => {
    setPhase("idle");
    setPreview(null);
    setJobId(null);
    setJob_reset();
  };
  const setJob_reset = () => undefined;

  const retry = async (
    trackId: number,
    opts?: { force?: boolean; candidateIndex?: number; reject?: boolean }
  ) => {
    if (!jobId) return;
    try {
      await api.retry(jobId, trackId, opts);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <>
      <header className="topbar">
        <div className="logo">♪</div>
        <div>
          <h1>Playlist Downloader</h1>
          <div className="sub">
            Paste a Spotify playlist — find &amp; download every track from free sources
          </div>
        </div>
      </header>

      <form
        className="url-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) loadPreview();
        }}
      >
        <input
          placeholder="https://open.spotify.com/playlist/..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          spellCheck={false}
        />
        <button className="btn-primary" disabled={!url.trim() || phase === "loading"}>
          {phase === "loading" ? <><span className="spinner" />Loading</> : "Load playlist"}
        </button>
      </form>

      {error && <div className="error-banner">{error}</div>}

      {phase === "idle" && (
        <div className="sources-row">
          Searching across:
          {sources.map((s) => (
            <span key={s.name} className="source-chip">{s.human_name}</span>
          ))}
          {!sources.length && <span className="source-chip">loading sources…</span>}
        </div>
      )}

      {(phase === "preview" || phase === "job") && preview && (
        <PlaylistCard preview={preview} />
      )}

      {phase === "preview" && (
        <>
          <TrackList tracks={preview!.tracks} />
          <div className="actions-row">
            <button className="btn-primary" onClick={startProcessing} disabled={starting}>
              {starting ? <><span className="spinner" />Starting</> : `▶ Start processing ${preview!.total_tracks} tracks`}
            </button>
            <button className="btn-secondary" onClick={reset}>Back</button>
          </div>
        </>
      )}

      {phase === "job" && jobId && job && (
        <JobView jobId={jobId} job={job} connected={connected} onRetry={retry} />
      )}

      <div className="footer-note">
        Metadata from Spotify · audio matched from public sources · for personal use only
      </div>
    </>
  );
}

function PlaylistCard({ preview }: { preview: PlaylistPreview }) {
  return (
    <div className="playlist-card">
      {preview.artwork_url && (
        <img className="playlist-art" src={preview.artwork_url} alt="" referrerPolicy="no-referrer" />
      )}
      <div className="playlist-meta" style={{ flex: 1 }}>
        <h2>
          {preview.name}
          {preview.metadata_source === "embed" && (
            <span className="badge-embed" title="Using public metadata (no API credentials configured). Embed shows up to ~100 tracks.">
              embed metadata
            </span>
          )}
        </h2>
        <div className="owner">{preview.owner || "Spotify playlist"}</div>
        <div className="playlist-stats">
          <span><b>{preview.total_tracks}</b> tracks</span>
          <span>{new Set(preview.tracks.map((t) => t.artists)).size} artists</span>
          <span>
            {formatDuration(preview.tracks.reduce((a, t) => a + t.duration_ms, 0))} total
          </span>
        </div>
      </div>
    </div>
  );
}

function JobView({
  jobId,
  job,
  connected,
  onRetry,
}: {
  jobId: string;
  job: import("./types").JobState;
  connected: boolean;
  onRetry: (
    trackId: number,
    opts?: { force?: boolean; candidateIndex?: number; reject?: boolean }
  ) => void;
}) {
  const finished = ["completed", "completed_with_errors", "cancelled", "failed"].includes(job.status);

  return (
    <>
      <div className="overall-progress">
        <div className="progress-line">
          <span>
            {!finished && <span className="spinner" />}
            {finished
              ? job.status === "completed" ? "Finished" : `Finished (${job.status.replace("_", " ")})`
              : connected ? "Processing…" : "Reconnecting…"}
          </span>
          <span className="count-chips">
            <span className="chip-done">✔ <b>{job.completed}</b></span>
            <span className="chip-fail">✖ <b>{job.failed}</b></span>
            <span className="chip-uncertain">? <b>{job.uncertain}</b></span>
            {(job.rejected > 0) && <span className="chip-fail">🚫 <b>{job.rejected}</b></span>}
            <span>{job.overall_progress}%</span>
          </span>
        </div>
        <div className="bar-track">
          <div className="bar-fill" style={{ width: `${job.overall_progress}%` }} />
        </div>
        <div className="actions-row" style={{ marginTop: 12 }}>
          {job.completed > 0 && (
            <a href={`/api/jobs/${job.id}/zip`} download>
              <button className="btn-primary">⬇ Download ZIP ({job.completed})</button>
            </a>
          )}
          {!finished && (
            <button className="btn-danger" onClick={() => api.cancel(job.id)}>Cancel</button>
          )}
          <button className="btn-secondary" onClick={() => location.reload()}>New playlist</button>
        </div>
      </div>
      <TrackList tracks={job.tracks} onRetry={onRetry} live={!finished} jobId={jobId} />
    </>
  );
}

function TrackList({
  tracks,
  onRetry,
  live = false,
  jobId,
}: {
  tracks: (import("./types").SpotifyTrack | TrackState)[];
  onRetry?: (
    trackId: number,
    opts?: { force?: boolean; candidateIndex?: number; reject?: boolean }
  ) => void;
  live?: boolean;
  jobId?: string;
}) {
  return (
    <div className="track-list">
      {tracks.map((t) => (
        <TrackRow
          key={t.position}
          track={t as TrackState}
          onRetry={onRetry}
          live={live}
          jobId={jobId}
        />
      ))}
    </div>
  );
}

const ACTIVE_STATUSES = new Set(["searching", "ranking", "downloading", "converting", "tagging"]);

function TrackRow({
  track,
  onRetry,
  live,
  jobId,
}: {
  track: TrackState;
  onRetry?: (
    trackId: number,
    opts?: { force?: boolean; candidateIndex?: number; reject?: boolean }
  ) => void;
  live?: boolean;
  jobId?: string;
}) {
  const active = live && ACTIVE_STATUSES.has(track.status);
  const pct = parsePct(track.stage_message);
  const needsReview = track.status === "uncertain" && track.candidates.length > 0;

  return (
    <div className={`track-row${active ? " active" : ""}${needsReview ? " review" : ""}`}>
      <div className="t-num">{track.position}</div>
      {track.artwork_url ? (
        <img className="t-art" src={track.artwork_url} alt="" loading="lazy" referrerPolicy="no-referrer" />
      ) : (
        <div className="t-art" />
      )}
      <div style={{ minWidth: 0 }}>
        <div className="t-title" title={track.title}>{track.title}</div>
        <div className="t-sub">{track.artists}</div>
      </div>
      <div className="t-album" title={track.album}>
        {track.album || "—"}
        <div className="t-sub">{formatDuration(track.duration_ms)}</div>
      </div>
      <div>
        <span className={`status-badge s-${track.status}`}>{track.status}</span>
        {active && (
          <>
            <div className="stage-msg">{track.stage_message}</div>
            {track.status === "downloading" && pct !== null && (
              <div className="mini-bar"><div style={{ width: `${pct}%` }} /></div>
            )}
          </>
        )}
        {(track.status === "failed" || track.status === "rejected") && track.error && (
          <div className="stage-msg" title={track.error}>{track.error.slice(0, 60)}</div>
        )}
      </div>
      <div className="t-actions">
        {track.confidence > 0 && (
          <span className="conf-pill" title="Match confidence">{Math.round(track.confidence * 100)}%</span>
        )}
        {track.has_file && jobId && (
          <a href={`/api/jobs/${jobId}/tracks/${track.id}/file`} download={track.filename ?? true}>
            <button className="btn-small btn-primary">⬇</button>
          </a>
        )}
      </div>
      {needsReview && onRetry && (
        <div className="review-panel">
          <div className="review-head">
            Not sure this is the right song — pick one, or skip it:
          </div>
          {track.candidates.map((c) => (
            <div key={c.index} className="cand-row">
              <span className={`source-chip src-${c.source}`}>{c.source}</span>
              <div className="cand-info" title={`${c.title} — ${c.artist}`}>
                <b>{c.title}</b> · {c.artist}
                {c.duration_s ? ` · ${formatSeconds(c.duration_s)}` : ""}
              </div>
              <span className="conf-pill">{Math.round(c.confidence * 100)}%</span>
              {c.url && (
                <a href={c.url} target="_blank" rel="noreferrer" className="cand-link">listen</a>
              )}
              <button
                className="btn-small btn-primary"
                onClick={() => onRetry(track.id, { candidateIndex: c.index, force: true })}
                disabled={!live}
              >
                Allow
              </button>
            </div>
          ))}
          <div className="review-actions">
            <button
              className="btn-small btn-danger"
              onClick={() => onRetry(track.id, { reject: true })}
              disabled={!live}
            >
              Disallow — none of these
            </button>
            <button
              className="btn-small btn-secondary"
              onClick={() => onRetry(track.id)}
              disabled={!live}
            >
              Search again
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function formatSeconds(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function parsePct(message: string): number | null {
  const m = /(\d+)%/.exec(message);
  return m ? Number(m[1]) : null;
}

export function formatDuration(ms: number): string {
  if (!ms) return "—";
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}
