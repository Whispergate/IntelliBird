"""Brand-term stoplist + specificity predicates.

DEFAULT_STOPLIST is a code constant - frozen in v2.0. Operators extend it via the
BRAND_STOPLIST_EXTRA environment variable (comma-separated, case-insensitive),
which is unioned into the runtime set by load_runtime_stoplist().

BRAND-01: per-project additive union via load_runtime_stoplist_for_project.
Existing zero-arg load_runtime_stoplist() (sync) is UNCHANGED - back-compat preserved.

Pattern mirrors app.services.bbot_safelist - frozenset + env-extra union
+ lazy settings read so tests can monkeypatch the settings singleton.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# DEFAULT_STOPLIST - ~150 generic English / brand / tech / action words that
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


def is_stoplisted(value: str, runtime_stoplist: frozenset[str] | None = None) -> bool:
    """True if `value` (case-insensitive, stripped) is in the runtime stoplist.

    Pass a pre-loaded frozenset (e.g. from load_runtime_stoplist_for_project) to
    avoid redundant DB + env reads inside hot loops. Defaults to zero-arg
    load_runtime_stoplist() for back-compat with all existing callers.
    """
    sl = runtime_stoplist if runtime_stoplist is not None else load_runtime_stoplist()
    return value.strip().lower() in sl


def is_short(value: str) -> bool:
    """True if `value` is shorter than 6 characters - too generic for safe matching."""
    return len(value) < 6


def load_runtime_stoplist() -> frozenset[str]:
    """Return DEFAULT_STOPLIST unioned with BRAND_STOPLIST_EXTRA (comma-separated env).

    Settings singleton is read at call time so tests can monkeypatch.
    Zero-arg sync API - UNCHANGED for back-compat with all existing callers.
    """
    extra_raw = getattr(settings, "BRAND_STOPLIST_EXTRA", None) or ""
    extras = frozenset(
        w.strip().lower() for w in extra_raw.split(",") if w.strip()
    )
    if not extras:
        return DEFAULT_STOPLIST
    return DEFAULT_STOPLIST | extras


async def load_runtime_stoplist_for_project(
    session: "AsyncSession",
    project_id: UUID,
) -> frozenset[str]:
    """Return DEFAULT_STOPLIST ∪ env extras ∪ project-specific stoplist terms.

    BRAND-01. Additive union: per-project terms ADD to the global set;
    operators can never weaken DEFAULT_STOPLIST or env-set BRAND_STOPLIST_EXTRA.

    All project terms are lowercased to match the lookup convention used by
    is_stoplisted() and DEFAULT_STOPLIST entries.

    Async - requires an active AsyncSession (from brand_monitor.scan_project or
    brand router handlers). Use zero-arg load_runtime_stoplist() from sync paths.
    """
    from sqlalchemy import select  # local import avoids circular at module level

    from app.models.brand import BrandStoplistTerm  # local import avoids circular

    base = load_runtime_stoplist()  # reuse zero-arg sync (includes DEFAULT + env)
    result = await session.execute(
        select(BrandStoplistTerm.term).where(
            BrandStoplistTerm.project_id == project_id
        )
    )
    project_terms = frozenset(t.lower() for t in result.scalars().all())
    return base | project_terms
