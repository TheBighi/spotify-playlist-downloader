"""Track matching engine: scores external-source candidates against Spotify metadata."""

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .schemas import SpotifyTrack
from .utils import normalize_text

# Version keywords that usually indicate NOT the original studio recording.
VERSION_KEYWORDS = {
    "remix": 0.30,
    "bootleg": 0.25,
    "vip mix": 0.28,
    "extended mix": 0.20,
    "club mix": 0.20,
    "dub mix": 0.22,
    "radio edit": 0.12,
    "live": 0.35,
    "cover": 0.40,
    "karaoke": 0.60,
    "instrumental": 0.45,
    "acoustic": 0.30,
    "unplugged": 0.32,
    "sped up": 0.55,
    "slowed": 0.50,
    "reverb": 0.45,
    "nightcore": 0.60,
    "daycore": 0.60,
    "8d audio": 0.55,
    "mashup": 0.35,
    "reaction": 0.70,
    "tutorial": 0.65,
    "lesson": 0.60,
    "how to play": 0.60,
    "demo": 0.25,
    "rehearsal": 0.35,
    "session": 0.18,
    "concert": 0.35,
    "tour": 0.20,
    "snippet": 0.45,
    "preview": 0.35,
    "1 hour": 0.55,
    "hour version": 0.55,
    "extended version": 0.15,
    "clean": 0.10,
}

# Signals that the candidate is the official/auto-generated audio.
POSITIVE_SIGNALS = ("official audio", "official video", "official music", "topic", "lyric video", "audio")


@dataclass
class ScoredCandidate:
    candidate: object
    score: float
    title_ratio: float = 0.0
    artist_ratio: float = 0.0
    duration_score: float = 0.0
    album_ratio: float = 0.0
    penalties: list[str] = field(default_factory=list)


def _keywords_in_text(text_norm: str) -> list[str]:
    found = []
    for kw in VERSION_KEYWORDS:
        if kw in text_norm:
            found.append(kw)
    return found


def score_candidate(candidate, track: SpotifyTrack) -> ScoredCandidate:
    cand_title = normalize_text(candidate.title)
    cand_artist = normalize_text(candidate.artist) + " " + normalize_text(getattr(candidate, "artists_all", "") or "")
    cand_album = normalize_text(candidate.album or "")

    sp_title_full = normalize_text(track.title)
    # For comparison we use the title stripped of featuring tags.
    sp_title_core = normalize_text(_remove_parens(strip_feat_text(track.title)))

    title_a = max(
        fuzz.token_sort_ratio(sp_title_core, cand_title),
        fuzz.partial_ratio(sp_title_core, cand_title) * 0.98,
        fuzz.token_set_ratio(sp_title_core, cand_title),
    ) / 100.0

    sp_artists = [a.strip() for a in track.artists.split(",") if a.strip()]
    artist_best = 0.0
    for a in sp_artists:
        a_norm = normalize_text(a)
        if not a_norm:
            continue
        r = max(fuzz.token_sort_ratio(a_norm, cand_artist.strip()), fuzz.partial_ratio(a_norm, cand_artist))
        artist_best = max(artist_best, r)
    artist_ratio = artist_best / 100.0

    # Duration
    dur_s = (track.duration_ms or 0) / 1000.0
    cdur = candidate.duration_s
    if cdur and dur_s:
        diff = abs(cdur - dur_s)
        if diff <= 2.0:
            duration_score = 1.0
        elif diff >= 20.0:
            duration_score = 0.0
        else:
            duration_score = 1.0 - (diff - 2.0) / 18.0
    else:
        duration_score = 0.55  # neutral when unknown

    album_ratio = 0.0
    if cand_album and track.album:
        album_ratio = fuzz.token_sort_ratio(normalize_text(track.album), cand_album) / 100.0

    score = 0.44 * title_a + 0.32 * artist_ratio + 0.16 * duration_score + 0.08 * album_ratio

    penalties: list[str] = []
    haystack = " ".join([cand_title, cand_artist, cand_album])
    sp_haystack = " ".join([sp_title_full, normalize_text(track.album)])
    for kw, weight in VERSION_KEYWORDS.items():
        kw_norm = normalize_text(kw)
        if kw_norm in haystack and kw_norm not in sp_haystack:
            score -= weight
            penalties.append(kw)

    joined_cand = " ".join(haystack.split())
    if POSITIVE_SIGNALS:
        for sig in POSITIVE_SIGNALS:
            if normalize_text(sig) in joined_cand:
                score += 0.03
                break

    if title_a > 0.97 and artist_ratio > 0.9:
        score += 0.05

    score = max(0.0, min(1.0, score))
    return ScoredCandidate(
        candidate=candidate,
        score=score,
        title_ratio=title_a,
        artist_ratio=artist_ratio,
        duration_score=duration_score,
        album_ratio=album_ratio,
        penalties=penalties,
    )


def rank_candidates(candidates: list, track: SpotifyTrack) -> list[ScoredCandidate]:
    scored = [score_candidate(c, track) for c in candidates]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def strip_feat_text(value: str) -> str:
    import re

    from .utils import FEAT_PATTERN

    return re.sub(r"\s+", " ", FEAT_PATTERN.sub(" ", value)).strip()


def _remove_parens(value: str) -> str:
    import re

    return re.sub(r"[\(\[\{][^)\]}]*[\)\]\}]", " ", value)
