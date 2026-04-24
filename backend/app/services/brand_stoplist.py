"""Brand-term stoplist + specificity predicates.

DEFAULT_STOPLIST is a code constant — frozen in v2.0. Operators extend it via the
BRAND_STOPLIST_EXTRA environment variable (comma-separated, case-insensitive),
which is unioned into the runtime set by load_runtime_stoplist().

Pattern mirrors app.services.bbot_safelist (Phase 11) — frozenset + env-extra union
+ lazy settings read so tests can monkeypatch the settings singleton.
"""
from __future__ import annotations

from app.config import settings

# ---------------------------------------------------------------------------
# DEFAULT_STOPLIST — ~150 generic English / brand / tech / action words that
# would otherwise produce runaway FTS + ct_log noise for short generic terms.
# Every entry must be lowercase; is_stoplisted() lowercases inputs before check.
# ---------------------------------------------------------------------------
DEFAULT_STOPLIST: frozenset[str] = frozenset({
    # Common English short words
    "the", "and", "for", "you", "not", "but", "are", "was", "one", "two",
    "get", "new", "now", "use", "all", "any", "can", "day", "end", "far",
    "few", "got", "has", "had", "her", "him", "his", "how", "its", "let",
    "may", "old", "our", "out", "own", "put", "run", "saw", "say", "see",
    "she", "sit", "ten", "top", "try", "via", "way", "who", "why", "yes",
    # Generic product / brand words
    "apex", "arc", "atlas", "core", "link", "peak", "echo", "sky", "rush",
    "nexus", "prime", "zen", "alpha", "beta", "gamma", "delta", "omega",
    "sigma", "theta", "iota", "kappa", "lambda",
    "ace", "aim", "app", "art", "ask", "big", "bit", "box", "bug", "car",
    "cat", "con", "dev", "dot", "fix", "fly", "fog", "fox", "fun", "gem",
    "go", "hub", "ice", "ink", "key", "kid", "kit", "lab", "log", "map",
    "max", "mid", "min", "mix", "net", "ops", "org", "pad", "pen", "pet",
    "pin", "pop", "pro", "red", "row", "set", "sip", "spy", "sun", "tag",
    "tap", "tea", "tip", "ton", "uni", "up", "us", "van", "vox", "web",
    "win", "zip", "zoo",
    # Action / state words
    "open", "wide", "fast", "slow", "high", "best", "good", "real", "easy",
    "made", "make", "mind", "more", "less", "plus", "none", "next", "last",
    "near", "help", "work", "play", "love", "life", "time", "line", "mark",
    "page", "name", "note", "plan", "port", "post", "ride", "ring", "rock",
    "rose", "safe", "said", "sale", "seat", "ship", "shop", "shot", "show",
    "side", "site", "soft", "sole", "some", "song", "sort", "star", "step",
    "tale", "talk", "team", "tell", "term", "test", "text", "that", "this",
    "tour", "town", "tree", "true", "type", "unit", "user", "view", "wave",
    "what", "when", "wood", "word", "year", "zone",
    # Common tech words
    "data", "node", "root", "loop", "sync", "async", "wait", "read", "write",
    "hash", "mesh",
})


def is_stoplisted(value: str) -> bool:
    """True if `value` (case-insensitive, stripped) is in the runtime stoplist."""
    return value.strip().lower() in load_runtime_stoplist()


def is_short(value: str) -> bool:
    """True if `value` is shorter than 6 characters — too generic for safe matching."""
    return len(value) < 6


def load_runtime_stoplist() -> frozenset[str]:
    """Return DEFAULT_STOPLIST unioned with BRAND_STOPLIST_EXTRA (comma-separated env).

    Settings singleton is read at call time so tests can monkeypatch.
    """
    extra_raw = getattr(settings, "BRAND_STOPLIST_EXTRA", None) or ""
    extras = frozenset(
        w.strip().lower() for w in extra_raw.split(",") if w.strip()
    )
    if not extras:
        return DEFAULT_STOPLIST
    return DEFAULT_STOPLIST | extras
