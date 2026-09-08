from types import SimpleNamespace

from app.matching import rank_candidates, score_candidate


def make_track(
    title="Blinding Lights",
    artists="The Weeknd",
    album="After Hours",
    duration_ms=200_000,
):
    return SimpleNamespace(
        title=title,
        artists=artists,
        album=album,
        duration_ms=duration_ms,
    )


def make_candidate(
    title="Blinding Lights",
    artist="The Weeknd",
    album="After Hours",
    duration_s=200,
    artists_all="",
):
    return SimpleNamespace(
        title=title,
        artist=artist,
        album=album,
        duration_s=duration_s,
        artists_all=artists_all,
    )


def test_exact_match_gets_high_score():
    track = make_track()
    candidate = make_candidate()

    result = score_candidate(candidate, track)

    assert result.score >= 0.95


def test_wrong_song_gets_lower_score():
    track = make_track()

    correct_candidate = make_candidate()

    wrong_candidate = make_candidate(
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        album="Whenever You Need Somebody",
        duration_s=213,
    )

    correct_result = score_candidate(correct_candidate, track)
    wrong_result = score_candidate(wrong_candidate, track)

    assert correct_result.score > wrong_result.score


def test_karaoke_version_gets_penalty():
    track = make_track()

    normal_candidate = make_candidate()

    karaoke_candidate = make_candidate(
        title="Blinding Lights Karaoke",
    )

    normal_result = score_candidate(normal_candidate, track)
    karaoke_result = score_candidate(karaoke_candidate, track)

    assert "karaoke" in karaoke_result.penalties
    assert karaoke_result.score < normal_result.score


def test_matching_duration_gets_full_duration_score():
    track = make_track(duration_ms=200_000)
    candidate = make_candidate(duration_s=200)

    result = score_candidate(candidate, track)

    assert result.duration_score == 1.0


def test_large_duration_difference_gets_zero_duration_score():
    track = make_track(duration_ms=200_000)
    candidate = make_candidate(duration_s=230)

    result = score_candidate(candidate, track)

    assert result.duration_score == 0.0


def test_rank_candidates_puts_best_match_first():
    track = make_track()

    best_candidate = make_candidate()

    bad_candidate = make_candidate(
        title="Random Song",
        artist="Random Artist",
        album="Random Album",
        duration_s=260,
    )

    karaoke_candidate = make_candidate(
        title="Blinding Lights Karaoke",
        artist="The Weeknd",
        album="After Hours",
        duration_s=200,
    )

    candidates = [
        bad_candidate,
        karaoke_candidate,
        best_candidate,
    ]

    results = rank_candidates(candidates, track)

    assert results[0].candidate is best_candidate
    assert results[0].score >= results[1].score
    assert results[1].score >= results[2].score