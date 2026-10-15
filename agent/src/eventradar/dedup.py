"""Near-duplicate fingerprints and event clustering keys.

Two-layer dedup, per the industry practice (entity × event-type × time
window, not naive text equality):

1. ``simhash64`` on normalized title text collapses reworded reposts inside
   one scan batch (Hamming distance <= ``SIMHASH_THRESHOLD``).
2. ``cluster_key`` groups reports of the same underlying event across
   sources and batches: primary entity + event type + a time bucket of
   ``window_hours``.

Pure stdlib on purpose: no tokenization/jieba dependency. Chinese text is
handled by character 2-gram shingles, which works without a dictionary.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

#: 64-bit SimHash Hamming distance under which two titles are "near-duplicate".
SIMHASH_BITS = 64
SIMHASH_THRESHOLD = 3
#: Char-bigram Jaccard overlap above which Chinese reworded reposts collapse
#: even when their SimHash distance is large (word-order changes perturb
#: SimHash more than set overlap).
SHINGLE_JACCARD_THRESHOLD = 0.45

_PUNCT_RE = re.compile(r"[\s\u3000，。！？、；：「」『』【】（）()\[\]{}\"'“”‘’\-—_./\\:;!?]+")
_URL_RE = re.compile(r"https?://\S+")


def normalize_text(text: str) -> str:
    """Lowercase, strip URLs/punctuation/spacing; CJK and latin survive."""
    text = _URL_RE.sub(" ", text or "")
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return text.strip()


def _shingles(text: str) -> list[str]:
    chars = [c for c in normalize_text(text) if c != " "]
    if len(chars) < 2:
        return chars
    # Character bigrams give stable overlap for Chinese headlines; latin
    # words (already de-spaced incorrectly) are kept as single tokens too.
    grams = ["".join(chars[i:i + 2]) for i in range(len(chars) - 1)]
    grams.extend(chars)
    return grams


def _hash64(token: str) -> int:
    # FNV-1a 64 — deterministic, stdlib only.
    h = 0xCBF29CE484222325
    for b in token.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def simhash64(text: str) -> int:
    """Return a 64-bit SimHash fingerprint of the text."""
    vector = [0] * SIMHASH_BITS
    tokens = _shingles(text)
    if not tokens:
        return 0
    for token in tokens:
        h = _hash64(token)
        for bit in range(SIMHASH_BITS):
            vector[bit] += 1 if (h >> bit) & 1 else -1
    fingerprint = 0
    for bit, weight in enumerate(vector):
        if weight > 0:
            fingerprint |= 1 << bit
    return fingerprint


def to_hex(fingerprint: int) -> str:
    return f"{fingerprint:016x}"


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def shingle_set(text: str) -> set[str]:
    """Exposed char-bigram shingle set for Jaccard overlap."""
    return set(_shingles(text))


def jaccard(left: str, right: str) -> float:
    left_set = shingle_set(left)
    right_set = shingle_set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def is_near_duplicate(
    left: int,
    right: int,
    threshold: int = SIMHASH_THRESHOLD,
    *,
    left_text: str = "",
    right_text: str = "",
    jaccard_threshold: float = SHINGLE_JACCARD_THRESHOLD,
) -> bool:
    """Near-duplicate via SimHash distance OR char-shingle Jaccard overlap."""
    if left != 0 and right != 0 and hamming(left, right) <= threshold:
        return True
    if left_text and right_text:
        return jaccard(left_text, right_text) >= jaccard_threshold
    return False


def _bucket(seen_at: datetime, window_hours: int) -> str:
    """Time bucket anchor so events within ``window_hours`` share a key."""
    window = max(1, int(window_hours))
    epoch_minute = int(seen_at.timestamp()) // 60
    bucket_minutes = (epoch_minute // (window * 60)) * (window * 60)
    return datetime.fromtimestamp(bucket_minutes * 60).strftime("%Y%m%d%H%M")


def primary_entity(entities: list[str] | None) -> str:
    if not entities:
        return "unknown"
    return normalize_text(str(entities[0])) or "unknown"


def cluster_key(
    entities: list[str] | None,
    event_type: str,
    seen_at: datetime,
    window_hours: int,
) -> str:
    """Build the server-side clustering key for one event."""
    return "|".join(
        [primary_entity(entities), (event_type or "unknown").strip().lower(),
         _bucket(seen_at, window_hours)]
    )


def parse_published(value: str | None) -> datetime | None:
    """Best-effort parse of upstream published-time strings."""
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def within_window(seen_at: datetime, reference: datetime, window_hours: int) -> bool:
    return abs(seen_at - reference) <= timedelta(hours=max(1, int(window_hours)))
