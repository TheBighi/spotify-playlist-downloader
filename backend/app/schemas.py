"""Pydantic schemas shared between API layers."""

from pydantic import BaseModel, Field


class SpotifyTrack(BaseModel):
    spotify_id: str = ""
    position: int
    title: str
    artists: str
    album: str = ""
    duration_ms: int = 0
    artwork_url: str | None = None
    release_date: str | None = None
    track_number: int | None = None
    disc_number: int | None = None


class PlaylistMeta(BaseModel):
    playlist_id: str
    name: str
    url: str
    owner: str = ""
    description: str = ""
    artwork_url: str | None = None
    tracks: list[SpotifyTrack] = []
    total_tracks: int = 0
    metadata_source: str = "api"  # "api" or "embed"


class PlaylistPreviewRequest(BaseModel):
    url: str


class JobCreateRequest(BaseModel):
    url: str
    track_positions: list[int] | None = Field(default=None, description="Optional subset of track positions to process")


class CandidateInfo(BaseModel):
    index: int
    source: str
    title: str
    artist: str = ""
    album: str | None = None
    duration_s: float | None = None
    url: str = ""
    confidence: float
    source_id: str = ""
    download_url: str | None = None
    needs_stream_download: bool = False
    bitrate_kbps: int | None = None
    ext: str | None = None
    artwork_url: str | None = None
    artists_all: str = ""


class TrackState(BaseModel):
    id: int
    position: int
    title: str
    artists: str
    album: str
    duration_ms: int
    artwork_url: str | None = None
    release_date: str | None = None
    status: str
    stage_message: str = ""
    confidence: float = 0.0
    source: str | None = None
    source_url: str | None = None
    filename: str | None = None
    file_size: int = 0
    bitrate_kbps: int | None = None
    error: str | None = None
    has_file: bool = False
    candidates: list[CandidateInfo] = []


class JobState(BaseModel):
    id: str
    playlist_id: str
    playlist_name: str
    playlist_url: str
    artwork_url: str | None = None
    status: str
    created_at: float
    total_tracks: int
    completed: int = 0
    failed: int = 0
    uncertain: int = 0
    rejected: int = 0
    processed: int = 0
    overall_progress: float = 0.0
    tracks: list[TrackState] = []


class RetryRequest(BaseModel):
    track_id: int
    force: bool = False
    candidate_index: int | None = Field(default=None,
                                        description="Accept a specific candidate from the review list")
    reject: bool = Field(default=False, description="Disallow the track entirely")
