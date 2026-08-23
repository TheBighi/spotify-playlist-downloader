import re
import unicodedata


def normalize_text(value: str | None) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.casefold()
    # replace common separators
    value = value.replace("&", "and")
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


FEAT_PATTERN = re.compile(r"\s*[\(\[\{]?\s*(?:feat\.?|featuring|ft\.?|with)\s+[^)\]}]*[\)\]\}]?", re.IGNORECASE)


def strip_feat(value: str | None) -> str:
    if not value:
        return ""
    out = FEAT_PATTERN.sub(" ", value)
    # also handle "Artist A x Artist B" style secondary artists kept intact elsewhere
    return re.sub(r"\s+", " ", out).strip()


def sanitize_filename(name: str, max_len: int = 150) -> str:
    if not name:
        name = "untitled"
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


def parse_duration_seconds(raw) -> float | None:
    """Parse durations like 213.0, '213', '3:33', '1:02:03'."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    raw = str(raw).strip()
    if not raw:
        return None
    parts = raw.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + float(p)
        return seconds
    except ValueError:
        return None
