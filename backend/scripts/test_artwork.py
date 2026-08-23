import httpx

c = httpx.Client(timeout=60)
r = c.post("http://127.0.0.1:8000/api/playlists/preview",
           json={"url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"})
p = r.json()
have = sum(1 for t in p["tracks"] if t["artwork_url"])
print(f"artwork: {have}/{len(p['tracks'])} tracks have covers")
print("example:", p["tracks"][0]["title"], "->", (p["tracks"][0]["artwork_url"] or "NONE")[:80])
