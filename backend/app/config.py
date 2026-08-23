from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Playlist Downloader"
    host: str = "127.0.0.1"
    port: int = 8000

    # Spotify API credentials (optional - falls back to public embed scraping)
    spotify_client_id: str = ""
    spotify_client_secret: str = ""

    # Storage
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"

    # Matching thresholds
    # >= auto_accept: download automatically (near-certain match)
    # below: hold for manual review - user sees the candidates and allows/disallows
    confidence_auto_accept: float = 0.88
    confidence_uncertain_min: float = 0.50

    # Pipeline tuning
    max_concurrent_tracks: int = 3
    search_timeout_s: float = 25.0
    candidates_per_source: int = 8

    # Cleanup of finished job artifacts (hours)
    cleanup_after_hours: float = 12.0

    # Sources
    audius_hosts: list[str] = [
        "https://discoveryprovider.audius.co",
        "https://discoveryprovider2.audius.co",
        "https://audius-discovery-1.altego.net",
    ]
    jamendo_client_id: str = ""

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "jobs").mkdir(parents=True, exist_ok=True)
