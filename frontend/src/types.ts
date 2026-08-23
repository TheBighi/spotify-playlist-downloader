export interface SpotifyTrack {
  spotify_id: string;
  position: number;
  title: string;
  artists: string;
  album: string;
  duration_ms: number;
  artwork_url: string | null;
}

export interface PlaylistPreview {
  playlist_id: string;
  name: string;
  url: string;
  owner: string;
  description: string;
  artwork_url: string | null;
  tracks: SpotifyTrack[];
  total_tracks: number;
  metadata_source: string;
}

export type TrackStatus =
  | "queued"
  | "searching"
  | "ranking"
  | "downloading"
  | "converting"
  | "tagging"
  | "completed"
  | "failed"
  | "uncertain"
  | "rejected";

export interface CandidateInfo {
  index: number;
  source: string;
  title: string;
  artist: string;
  album: string | null;
  duration_s: number | null;
  url: string;
  confidence: number;
}

export interface TrackState {
  id: number;
  position: number;
  title: string;
  artists: string;
  album: string;
  duration_ms: number;
  artwork_url: string | null;
  release_date: string | null;
  status: TrackStatus;
  stage_message: string;
  confidence: number;
  source: string | null;
  source_url: string | null;
  filename: string | null;
  file_size: number;
  bitrate_kbps: number | null;
  error: string | null;
  has_file: boolean;
  candidates: CandidateInfo[];
}

export interface JobSummary {
  completed: number;
  failed: number;
  uncertain: number;
  processed: number;
  overall_progress: number;
}

export interface JobState {
  id: string;
  playlist_id: string;
  playlist_name: string;
  playlist_url: string;
  artwork_url: string | null;
  status: string;
  created_at: number;
  total_tracks: number;
  completed: number;
  failed: number;
  uncertain: number;
  rejected: number;
  processed: number;
  overall_progress: number;
  tracks: TrackState[];
}
