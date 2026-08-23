"""Live integration tests for every source + spotify metadata."""
import asyncio
import sys

sys.path.insert(0, ".")

from app.spotify import spotify_client  # noqa: E402
from app.sources.registry import registry  # noqa: E402
from app.schemas import SpotifyTrack  # noqa: E402


async def main() -> None:
    print("=== Spotify metadata (embed fallback) ===")
    try:
        pl = await spotify_client.get_playlist(
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=test")
        print(f"OK name={pl.name!r} tracks={pl.total_tracks} src={pl.metadata_source} "
              f"art={bool(pl.artwork_url)}")
        t = pl.tracks[0]
        print(f"first track: {t.artists} - {t.title} ({t.duration_ms}ms)")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}")

    print("\n=== Per-source searches ===")
    track = SpotifyTrack(position=1, title="Never Gonna Give You Up",
                         artists="Rick Astley", album="Whenever You Need Somebody",
                         duration_ms=213000)
    for src in registry.sources:
        q = src.query_for_track(track)
        try:
            cands = await asyncio.wait_for(src.search(q, limit=5), timeout=35)
            top = cands[0] if cands else None
            print(f"[{src.name}] OK {len(cands)} candidates | q={q[:60]}")
            if top:
                print(f"    top: {top.artist} - {top.title} dur={top.duration_s} url={top.url[:70]}")
                # verify download works for one candidate per source
                from pathlib import Path
                dest = Path("../tmp_test") / src.name
                file = await asyncio.wait_for(src.download(top, dest), timeout=180)
                size = file.stat().st_size
                print(f"    download OK: {file.name} {size/1024:.0f} KB")
        except Exception as exc:  # noqa: BLE001
            print(f"[{src.name}] FAIL: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
