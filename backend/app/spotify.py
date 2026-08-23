"""Spotify metadata client.

Primary path: official Web API using client-credentials from env vars.
Fallback path (no credentials): scrape the public playlist embed page which
ships a __NEXT_DATA__ JSON payload containing name/cover/track list
(limited to what Spotify exposes publicly, ~first 100 tracks).
"""

import asyncio
import json
import logging
import re
import time

import httpx

from .config import settings
from .schemas import PlaylistMeta, SpotifyTrack

log = logging.getLogger("spotify")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

PLAYLIST_ID_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[a-zA-Z-]+/)?playlist/|spotify:playlist:)([A-Za-z0-9]+)"
)


def parse_playlist_id(url: str) -> str | None:
    m = PLAYLIST_ID_RE.search(url or "")
    return m.group(1) if m else None


class SpotifyError(Exception):
    pass


class SpotifyClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=True,
                                         headers={"User-Agent": UA})
        self._token: str | None = None
        self._token_exp: float = 0
        self._art_cache: dict[str, str] = {}

    @property
    def has_credentials(self) -> bool:
        return bool(settings.spotify_client_id and settings.spotify_client_secret)

    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        r = await self._client.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(settings.spotify_client_id, settings.spotify_client_secret),
        )
        if r.status_code != 200:
            raise SpotifyError(f"token request failed ({r.status_code}): {r.text[:200]}")
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + float(data.get("expires_in", 3600))
        return self._token

    async def get_playlist(self, url_or_id: str) -> PlaylistMeta:
        pid = parse_playlist_id(url_or_id)
        if not pid:
            raise SpotifyError("Could not find a playlist id in that URL")
        if self.has_credentials:
            try:
                meta = await self._get_playlist_api(pid)
                if meta:
                    return meta
            except Exception as exc:  # noqa: BLE001
                log.warning("Web API failed (%s); falling back to embed scraping", exc)
        meta = await self._get_playlist_embed(pid)
        await self.fill_track_artwork(meta)
        return meta

    async def fill_track_artwork(self, playlist: PlaylistMeta) -> None:
        """Fetch per-track cover art via the public oEmbed endpoint for tracks
        that lack artwork (embed fallback has no per-track covers)."""
        missing = [t for t in playlist.tracks
                   if not t.artwork_url and t.spotify_id
                   and t.spotify_id not in self._art_cache]
        if not missing:
            for t in playlist.tracks:
                if not t.artwork_url and t.spotify_id in self._art_cache:
                    t.artwork_url = self._art_cache[t.spotify_id]
            return

        sem = asyncio.Semaphore(8)

        async def fetch_one(track: SpotifyTrack) -> None:
            cached = self._art_cache.get(track.spotify_id)
            if cached:
                track.artwork_url = cached
                return
            async with sem:
                try:
                    r = await self._client.get(
                        "https://open.spotify.com/oembed",
                        params={"url": f"https://open.spotify.com/track/{track.spotify_id}"},
                        headers={"User-Agent": UA},
                    )
                    if r.status_code == 200:
                        thumb = r.json().get("thumbnail_url")
                        if thumb:
                            track.artwork_url = thumb
                            self._art_cache[track.spotify_id] = thumb
                except Exception:  # noqa: BLE001
                    pass

        try:
            await asyncio.wait_for(
                asyncio.gather(*(fetch_one(t) for t in missing)), timeout=25)
        except asyncio.TimeoutError:
            log.warning("artwork enrichment timed out; continuing with partial covers")

    # ---------- official API ----------

    async def _get_playlist_api(self, pid: str) -> PlaylistMeta | None:
        token = await self._access_token()
        headers = {"Authorization": f"Bearer {token}"}
        r = await self._client.get(
            f"https://api.spotify.com/v1/playlists/{pid}",
            params={"fields": "id,name,description,owner(display_name),images,external_urls"},
            headers=headers,
        )
        if r.status_code != 200:
            raise SpotifyError(f"playlist fetch {r.status_code}: {r.text[:200]}")
        pl = r.json()
        tracks: list[SpotifyTrack] = []
        offset = 0
        while True:
            r = await self._client.get(
                f"https://api.spotify.com/v1/playlists/{pid}/tracks",
                params={
                    "offset": str(offset),
                    "limit": "100",
                    "fields": "next,items(is_local,track(id,name,duration_ms,track_number,"
                              "disc_number,album(name,release_date,images),"
                              "artists(name),type))",
                },
                headers=headers,
            )
            r.raise_for_status()
            page = r.json()
            for item in page.get("items") or []:
                t = item.get("track")
                if not t or item.get("is_local"):
                    continue
                album = t.get("album") or {}
                artists = ", ".join(a.get("name", "") for a in t.get("artists") or [])
                images = album.get("images") or []
                artwork = max(images, key=lambda i: i.get("width") or 0)["url"] if images else None
                tracks.append(SpotifyTrack(
                    spotify_id=t.get("id") or "",
                    position=len(tracks) + 1,
                    title=t.get("name") or "Unknown",
                    artists=artists or "Unknown artist",
                    album=album.get("name") or "",
                    duration_ms=int(t.get("duration_ms") or 0),
                    artwork_url=artwork,
                    release_date=album.get("release_date"),
                    track_number=t.get("track_number"),
                    disc_number=t.get("disc_number"),
                ))
            nxt = page.get("next")
            if not nxt:
                break
            offset += 100
        images = pl.get("images") or []
        artwork = max(images, key=lambda i: i.get("width") or 0)["url"] if images else None
        return PlaylistMeta(
            playlist_id=pid,
            name=pl.get("name") or f"Playlist {pid}",
            url=f"https://open.spotify.com/playlist/{pid}",
            owner=(pl.get("owner") or {}).get("display_name") or "",
            description=pl.get("description") or "",
            artwork_url=artwork,
            tracks=tracks,
            total_tracks=len(tracks),
            metadata_source="api",
        )

    # ---------- public embed fallback ----------

    async def _get_playlist_embed(self, pid: str) -> PlaylistMeta:
        url = f"https://open.spotify.com/embed/playlist/{pid}"
        r = await self._client.get(url, headers={"User-Agent": UA})
        if r.status_code != 200:
            raise SpotifyError(f"embed page returned HTTP {r.status_code}; "
                               f"if this is a private playlist configure API credentials")
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
                      r.text, re.DOTALL)
        if not m:
            raise SpotifyError("embed page did not contain expected metadata payload")
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            raise SpotifyError(f"embed metadata parse failed: {exc}") from exc

        entity = (((data.get("props") or {}).get("pageProps") or {})
                  .get("state") or {}).get("data", {}).get("entity") \
            or (((data.get("props") or {}).get("pageProps") or {}).get("state") or {}).get("data")

        if not isinstance(entity, dict):
            raise SpotifyError("embed metadata structure unrecognized")

        name = entity.get("name") or entity.get("title") or f"Playlist {pid}"
        cover_sources = ((entity.get("coverArt") or entity.get("cover")) or {}).get("sources") or []
        artwork = cover_sources[-1]["url"] if cover_sources else None
        owner = entity.get("subtitle") or entity.get("ownerName") or ""

        tracks: list[SpotifyTrack] = []
        seen_ids: set[str] = set()
        for i, t in enumerate(entity.get("trackList") or [], start=1):
            uri = t.get("uri") or ""
            sid = uri.split(":")[-1] if uri else ""
            if sid and sid in seen_ids:
                continue
            seen_ids.add(sid)
            dur = t.get("duration")
            tracks.append(SpotifyTrack(
                spotify_id=sid,
                position=len(tracks) + 1,
                title=t.get("title") or "Unknown",
                artists=(t.get("subtitle") or "").replace(", ", ", ") or "Unknown artist",
                album="",
                duration_ms=int(dur) if dur else 0,
                artwork_url=None,
                release_date=None,
                track_number=i,
            ))

        if not tracks:
            raise SpotifyError("embed contained no tracks")

        return PlaylistMeta(
            playlist_id=pid,
            name=name,
            url=f"https://open.spotify.com/playlist/{pid}",
            owner=str(owner),
            description="",
            artwork_url=artwork,
            tracks=tracks,
            total_tracks=len(tracks),
            metadata_source="embed",
        )


spotify_client = SpotifyClient()
