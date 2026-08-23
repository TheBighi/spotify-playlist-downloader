import type { JobState, PlaylistPreview } from "./types";

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  async preview(url: string): Promise<PlaylistPreview> {
    return handle(
      await fetch("/api/playlists/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      })
    );
  },

  async createJob(url: string): Promise<JobState> {
    return handle(
      await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      })
    );
  },

  async getJob(jobId: string): Promise<JobState> {
    return handle(await fetch(`/api/jobs/${jobId}`));
  },

  async retry(
    jobId: string,
    trackId: number,
    opts?: { force?: boolean; candidateIndex?: number; reject?: boolean }
  ): Promise<void> {
    await fetch(`/api/jobs/${jobId}/retry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        track_id: trackId,
        force: opts?.force ?? false,
        candidate_index: opts?.candidateIndex ?? null,
        reject: opts?.reject ?? false,
      }),
    });
  },

  async cancel(jobId: string): Promise<void> {
    await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
  },

  sourcesUrl(): string {
    return "/api/sources";
  },
};
