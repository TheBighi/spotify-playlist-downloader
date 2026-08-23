"""Common interface every external audio source must implement."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from ..schemas import SpotifyTrack


@dataclass
class Candidate:
    source: str
    source_id: str
    title: str
    artist: str
    url: str = ""
    artists_all: str = ""
    album: str | None = None
    duration_s: float | None = None
    download_url: str | None = None  # direct file URL when available
    needs_stream_download: bool = False  # must go through yt-dlp style extractor
    bitrate_kbps: int | None = None
    ext: str | None = None
    artwork_url: str | None = None
    play_count: int = 0
    extra: dict = field(default_factory=dict)


ProgressCallback = Callable[[int, int], Awaitable[None]]


class SourceError(Exception):
    pass


class SourceAdapter(ABC):
    name: str = "base"
    human_name: str = "Base"
    supports_download: bool = True

    @abstractmethod
    def query_for_track(self, track: SpotifyTrack) -> str:
        """Build a search query for a spotify track."""

    @abstractmethod
    async def search(self, query: str, limit: int = 8) -> list[Candidate]:
        """Return candidate matches for a free-text query."""

    @abstractmethod
    async def download(self, candidate: Candidate, dest_dir: Path,
                       progress: ProgressCallback | None = None) -> Path:
        """Download the candidate's audio into dest_dir and return the file path."""
