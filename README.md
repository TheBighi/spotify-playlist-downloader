# Playlist Downloader

Open-source, self-hosted Spotify playlist downloader web app. Paste a Spotify
playlist URL, preview every track, and automatically find and download the best
matching MP3 from multiple free music sources, one-click ZIP export.

> For personal use only.

## Features

- **Paste a Spotify playlist URL** — loads name, artwork, artists, albums, durations
- **Multi-source search** — YouTube, Audius, Internet Archive (Jamendo optional) searched concurrently through a pluggable adapter system
- **Smart matching** — confidence scoring against Spotify metadata; filters out covers, remixes, live, karaoke, nightcore, sped-up/slowed versions
- **Human review** — uncertain matches show exactly what was found so you can allow or disallow each candidate
- **Automatic pipeline** — download → FFmpeg convert to 320 kbps MP3 → embed title/artist/album/track/date → embed album artwork
- **Live progress** — real-time updates via Server-Sent Events, per-track status bars
- **Downloads** — individual files or the whole playlist as ZIP
- **No required API keys** — works out of the box using public metadata; Spotify API credentials optional for full playlists

## Quick start

Requirements: Python 3.11+, Node 18+, [FFmpeg](https://ffmpeg.org) on PATH.

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Linux/Mac: .venv/bin/pip install -r requirements.txt

# 2. Frontend (one-time build)
cd ../frontend
npm install
npm run build

# 3. Run
cd ../backend
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Open **http://127.0.0.1:8000**, paste a playlist URL, press start.

## Optional (NOT NECCESARRY FOR THIS APP TO WORK): Spotify API credentials

Create `backend/.env`:

```
SPOTIFY_CLIENT_ID=your_id
SPOTIFY_CLIENT_SECRET=your_secret
```

Get free credentials at [developer.spotify.com](https://developer.spotify.com/dashboard).
Without them the app uses public embed metadata (limited to ~100 tracks per playlist).

## How it works

1. Spotify provides metadata only (title, artist, album, duration, artwork)
2. Every enabled source is searched in parallel for each track
3. Candidates are ranked by title/artist similarity, duration difference, album match, and version-keyword penalties
4. High-confidence matches are downloaded automatically; uncertain ones wait for your approval
5. Audio is converted to MP3 with FFmpeg, tagged, and packaged

## Tech stack

FastAPI · React · TypeScript · Vite · SQLite · SSE real-time updates · yt-dlp · FFmpeg · mutagen

## Project layout

```
backend/app/
  main.py            FastAPI routes + static hosting
  spotify.py         Spotify metadata client (API + public fallback)
  matching.py        confidence scoring engine
  pipeline.py        search -> rank -> download -> convert -> tag
  jobs.py            job manager, SSE events, cleanup
  sources/           source adapters (youtube, audius, internetarchive, jamendo)
frontend/src/        React UI
```