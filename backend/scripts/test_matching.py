"""Sanity checks for the matching engine."""
import sys
sys.path.insert(0, ".")

from app.matching import rank_candidates
from app.schemas import SpotifyTrack
from app.sources.base import Candidate

track = SpotifyTrack(position=1, title="Never Gonna Give You Up",
                     artists="Rick Astley", album="Whenever You Need Somebody",
                     duration_ms=213000)

candidates = [
    Candidate(source="youtube", source_id="a", title="Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)",
              artist="Rick Astley", duration_s=214),
    Candidate(source="youtube", source_id="b", title="Never Gonna Give You Up (Rick Astley Cover)",
              artist="Kamileon", duration_s=125),
    Candidate(source="youtube", source_id="c", title="Never Gonna Give You Up (Nightcore Version)",
              artist="nightcore lab", duration_s=180),
    Candidate(source="youtube", source_id="d", title="Never Gonna Give You Up - Live at Wembley",
              artist="Rick Astley", duration_s=230),
    Candidate(source="audius", source_id="e", title="Never Gonna Give You Up",
              artist="Rick Astley Tribute Band", duration_s=212),
    Candidate(source="youtube", source_id="f", title="Rick Astley - Never Gonna Give You Up (Official Music Video)",
              artist="Rick Astley", duration_s=213),
]

ranked = rank_candidates(candidates, track)
for s in ranked:
    print(f"{s.score:.3f}  [{s.candidate.source}] {s.candidate.artist} - {s.candidate.title}"
          f"  penalties={s.penalties}")

assert ranked[0].candidate.source_id in ("f", "a"), f"unexpected best: {ranked[0].candidate.title}"

# remix that IS part of the original title must not be penalized
track2 = SpotifyTrack(position=2, title="Sun Is Shining (Radio Edit)", artists="Bob Marley vs. Funkstar De Luxe", album="", duration_ms=234000)
c2 = [Candidate(source="youtube", source_id="g", title="Bob Marley vs Funkstar De Luxe - Sun Is Shining (Radio Edit)", artist="Funkstar De Luxe", duration_s=233)]
r2 = rank_candidates(c2, track2)
print(f"\noriginal-remix case score: {r2[0].score:.3f} penalties={r2[0].penalties}")
assert r2[0].score > 0.8 and not r2[0].penalties
print("\nmatching sanity: PASS")
