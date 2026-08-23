"""End-to-end test through the live HTTP API: preview -> job -> SSE -> files -> zip."""
import io
import json
import sys
import time
import zipfile

import httpx
from mutagen.id3 import ID3

BASE = "http://127.0.0.1:8000"
PLAYLIST_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"


def main() -> None:
    client = httpx.Client(timeout=30)

    print("== health ==", client.get(f"{BASE}/api/health").json())
    print("== sources =", [s["name"] for s in client.get(f"{BASE}/api/sources").json()["sources"]])

    r = client.post(f"{BASE}/api/playlists/preview", json={"url": PLAYLIST_URL})
    r.raise_for_status()
    preview = r.json()
    print(f"== preview == {preview['name']!r} tracks={preview['total_tracks']} src={preview['metadata_source']}")
    assert preview["tracks"], "no tracks in preview"

    # process only the first 3 tracks for the test
    r = client.post(f"{BASE}/api/jobs", json={"url": PLAYLIST_URL, "track_positions": [1, 2, 3]})
    r.raise_for_status()
    job = r.json()
    job_id = job["id"]
    print(f"== job created == id={job_id} total={job['total_tracks']}")

    # stream SSE until done
    start = time.time()
    with client.stream("GET", f"{BASE}/api/jobs/{job_id}/events", timeout=600) as resp:
        seen_done = False
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = json.loads(line[5:].strip())
            tpe = payload.get("type")
            if tpe == "track":
                t = payload["track"]
                print(f"  [{t['position']}] {t['status']:<11} conf={t['confidence']:.2f} "
                      f"src={t.get('source')} msg={t['stage_message'][:50]} err={str(t.get('error'))[:60]}")
            elif tpe == "done":
                seen_done = True
                print(f"== done == status={payload['status']} completed={payload['completed']} "
                      f"failed={payload['failed']} uncertain={payload['uncertain']}")
                break
            if time.time() - start > 540:
                break
        if not seen_done:
            print("WARN: stream ended without done event")

    state = client.get(f"{BASE}/api/jobs/{job_id}").json()
    completed = [t for t in state["tracks"] if t["status"] == "completed"]
    print(f"\nfinal: completed={len(completed)}/{state['total_tracks']} "
          f"(failed={state['failed']}, uncertain={state['uncertain']})")

    ok_files = 0
    for t in completed:
        fr = client.get(f"{BASE}/api/jobs/{job_id}/tracks/{t['id']}/file")
        assert fr.status_code == 200, f"file download failed for track {t['id']}"
        data = fr.content
        tags = ID3(io.BytesIO(data))
        title = str(tags.getall("TIT2")[0])
        artist = str(tags.getall("TPE1")[0])
        apic = bool(tags.getall("APIC"))
        print(f"  file OK: {fr.headers.get('content-disposition', '')[-40:]} {len(data)/1024:.0f}KB "
              f"| tags: {artist} - {title} | artwork={apic}")
        ok_files += 1

    zr = client.get(f"{BASE}/api/jobs/{job_id}/zip")
    if completed:
        assert zr.status_code == 200, "zip failed"
        zf = zipfile.ZipFile(io.BytesIO(zr.content))
        names = zf.namelist()
        print(f"\nzip OK: {len(names)} entries, {len(zr.content)/1024:.0f}KB -> {names}")
    else:
        print("\nzip skipped (nothing completed)")

    verdict = "PASS" if ok_files >= 2 or (ok_files + state["uncertain"]) >= 2 else "FAIL"
    print(f"\nE2E VERDICT: {verdict}")
    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
