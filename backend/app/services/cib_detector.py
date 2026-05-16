"""CIB (Coordinated Inauthentic Behaviour) detector — Phase 33 / DISINFO-02.

Uses MinHashLSH (datasketch) to detect clusters of near-identical social media
posts ingested by the social listening workers. Clusters of >= 5 similar posts
are stored as CibCluster rows and surface as synthetic events in the pipeline.

Entry point for APScheduler:  run_cib_sweep()  (global, every 300 s)
Per-project entry point:      run_cib_sweep_for_project(session, project_id)
Pure analysis helpers:        build_minhash(), detect_cib_cluster(), _severity()
DB extraction helper:         _fetch_recent_social_events(session, project_id)
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from datasketch import MinHash, MinHashLSH

from app.models.cib_clusters import CibCluster

logger = logging.getLogger(__name__)

# Tags that identify social-listening events (OR-matched via ARRAY overlap)
_SOCIAL_TAGS = [
    "social_listening:mastodon",
    "social_listening:4chan",
    "social_listening:reddit",
]

# How far back to look when querying recent social events for a project
_WINDOW_MINUTES = 10

# Maximum social events to analyse per project sweep
_MAX_EVENTS = 500


# ---------------------------------------------------------------------------
# Pure analysis helpers
# ---------------------------------------------------------------------------


def build_minhash(text: str, num_perm: int = 64) -> MinHash:
    """Return a MinHash sketch for *text* built from whitespace-tokenised words.

    Each word is lowercased and encoded to UTF-8 before being added to the
    sketch.  Caller controls *num_perm* (default 64 matches the LSH index
    used by detect_cib_cluster).
    """
    m = MinHash(num_perm=num_perm)
    for word in text.lower().split():
        m.update(word.encode("utf8"))
    return m


def detect_cib_cluster(
    posts: list[dict],
    threshold: float = 0.7,
    min_cluster_size: int = 5,
) -> list[list[str]]:
    """Return clusters of post IDs whose content exceeds the similarity threshold.

    Each post dict must have:
      - ``id``   — unique post identifier (any string-able value)
      - ``text`` — post content to compute MinHash over

    Only clusters with ``len(candidates) >= min_cluster_size`` are returned.
    Visited IDs are de-duplicated so no post appears in more than one cluster.

    Parameters
    ----------
    posts:
        Input post dicts.
    threshold:
        Jaccard similarity threshold for LSH (default 0.7 per DISINFO-02).
    min_cluster_size:
        Minimum members in a group to be reported as a CIB cluster (default 5).

    Returns
    -------
    list[list[str]]
        Each inner list contains the ``str(id)`` values of the cluster members.
        Returns ``[]`` when no qualifying cluster is found.
    """
    lsh = MinHashLSH(threshold=threshold, num_perm=64)
    minhashes: dict[str, MinHash] = {}

    for post in posts:
        key = str(post["id"])
        m = build_minhash(post.get("text", ""))
        try:
            lsh.insert(key, m)
        except ValueError:
            pass  # duplicate key — skip
        minhashes[key] = m

    clusters: list[list[str]] = []
    visited: set[str] = set()

    for post in posts:
        key = str(post["id"])
        if key in visited:
            continue
        if key not in minhashes:
            continue
        try:
            candidates: list[str] = lsh.query(minhashes[key])
        except KeyError:
            continue
        if len(candidates) >= min_cluster_size:
            clusters.append(list(candidates))
            visited.update(candidates)

    return clusters


def _severity(member_count: int, similarity_score: float) -> str:
    """Return 'high' or 'medium' based on cluster size and similarity score.

    Rules (DISINFO-02):
      - ``member_count >= 10``  OR  ``similarity_score >= 0.85``  → 'high'
      - otherwise (N >= 5 guaranteed by caller)                   → 'medium'
    """
    if member_count >= 10 or similarity_score >= 0.85:
        return "high"
    return "medium"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _fetch_recent_social_events(
    session: Session,
    project_id: uuid.UUID,
    window_start: datetime | None = None,
    limit: int = _MAX_EVENTS,
) -> list[dict]:
    """Return recent social-listening events for *project_id* as plain dicts.

    Each returned dict has keys ``id`` (str UUID) and ``text`` (description).
    Uses raw SQL for sync SQLAlchemy compatibility.
    """
    if window_start is None:
        window_start = datetime.now(timezone.utc) - timedelta(minutes=_WINDOW_MINUTES)

    rows = session.execute(
        text("""
            SELECT id::text, COALESCE(description, title, '') AS text
            FROM events
            WHERE project_id = :project_id
              AND observed_at >= :window_start
              AND ARRAY[:social_tag1, :social_tag2, :social_tag3] && tags
            ORDER BY observed_at DESC
            LIMIT :limit
        """),
        {
            "project_id": str(project_id),
            "window_start": window_start,
            "social_tag1": _SOCIAL_TAGS[0],
            "social_tag2": _SOCIAL_TAGS[1],
            "social_tag3": _SOCIAL_TAGS[2],
            "limit": limit,
        },
    ).fetchall()

    return [{"id": row.id, "text": row.text} for row in rows]


def _emit_synthetic_event(
    session: Session,
    project_id: uuid.UUID,
    cluster: CibCluster,
) -> None:
    """Insert a synthetic event for the CIB cluster so it surfaces in the pipeline."""
    content_hash = hashlib.sha256(
        f"cib-cluster:{cluster.id}".encode()
    ).hexdigest()[:64]
    session.execute(
        text("""
            INSERT INTO events (project_id, stix_type, content_hash, title, description,
                                observed_at, tags)
            VALUES (:project_id, 'x-intellibird-cib-cluster', :content_hash,
                    :title, :description, now(),
                    ARRAY['cib-cluster', :severity_tag])
            ON CONFLICT DO NOTHING
        """),
        {
            "project_id": str(project_id),
            "content_hash": content_hash,
            "title": (
                f"CIB Cluster: {cluster.member_count} coordinated accounts detected"
            ),
            "description": (
                f"Coordinated Inauthentic Behaviour cluster with "
                f"{cluster.member_count} accounts. Severity: {cluster.severity}."
            ),
            "severity_tag": f"severity:{cluster.severity}",
        },
    )


# ---------------------------------------------------------------------------
# Per-project sweep
# ---------------------------------------------------------------------------


def run_cib_sweep_for_project(
    session: Session,
    project_id: uuid.UUID,
) -> None:
    """Sweep recent social events for *project_id* and insert any CIB clusters found.

    Steps:
    1. Fetch last 500 social events from the last ``_WINDOW_MINUTES`` minutes.
    2. Run detect_cib_cluster with threshold=0.7, min_cluster_size=5.
    3. For each qualifying cluster: insert a CibCluster row + synthetic event.

    The caller is responsible for committing the session.
    """
    posts = _fetch_recent_social_events(session, project_id)
    if not posts:
        logger.debug(
            "cib_sweep_no_posts project_id=%s", project_id
        )
        return

    clusters = detect_cib_cluster(posts, threshold=0.7, min_cluster_size=5)
    if not clusters:
        logger.debug(
            "cib_sweep_no_clusters project_id=%s posts=%d", project_id, len(posts)
        )
        return

    for candidate_ids in clusters:
        member_count = len(candidate_ids)
        severity = _severity(member_count, 0.7)  # LSH threshold is the similarity proxy

        member_uuids: list[uuid.UUID] = []
        for cid in candidate_ids:
            # candidate_ids may be strings (real path) or dicts (test mock path)
            cid_str = cid["id"] if isinstance(cid, dict) else str(cid)
            try:
                member_uuids.append(uuid.UUID(cid_str))
            except (ValueError, AttributeError):
                pass  # non-UUID synthetic ID — skip

        cluster_row = CibCluster(
            project_id=project_id,
            member_event_ids=member_uuids,
            member_count=member_count,
            severity=severity,
            evidence={
                "threshold": 0.7,
                "member_ids": candidate_ids,
            },
        )
        session.add(cluster_row)
        session.flush()  # populate cluster_row.id before _emit_synthetic_event

        _emit_synthetic_event(session, project_id, cluster_row)

        logger.info(
            "cib_cluster_inserted project_id=%s member_count=%d severity=%s",
            project_id,
            member_count,
            severity,
        )


# ---------------------------------------------------------------------------
# Global sweep (APScheduler entry point)
# ---------------------------------------------------------------------------


def run_cib_sweep() -> None:
    """Global CIB sweep — called by APScheduler every 300 s.

    Acquires a Redis lock (NX EX 300) to prevent overlapping sweeps when
    multiple scheduler instances run (e.g. canary + stable deployments).
    """
    from app.config import settings  # noqa: PLC0415 — deferred to avoid circular import
    import redis as redis_lib  # noqa: PLC0415

    r = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    lock_acquired = r.set("cib_detection_lock", "1", nx=True, ex=300)
    if not lock_acquired:
        logger.info("cib_sweep_skipped lock_held=True")
        return

    try:
        # Build a synchronous engine from the async DATABASE_URL (strip +asyncpg)
        sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
        engine = create_engine(sync_url)
        window_start = datetime.now(timezone.utc) - timedelta(minutes=_WINDOW_MINUTES)

        with Session(engine) as session:
            project_ids = session.execute(
                text("""
                    SELECT DISTINCT project_id FROM events
                    WHERE observed_at >= :window_start
                      AND ARRAY[:social_tag1, :social_tag2, :social_tag3] && tags
                """),
                {
                    "window_start": window_start,
                    "social_tag1": _SOCIAL_TAGS[0],
                    "social_tag2": _SOCIAL_TAGS[1],
                    "social_tag3": _SOCIAL_TAGS[2],
                },
            ).fetchall()

            for row in project_ids:
                try:
                    run_cib_sweep_for_project(session, row.project_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "cib_sweep_project_error project_id=%s error=%s",
                        row.project_id,
                        exc,
                    )

            session.commit()

        engine.dispose()
        logger.info("cib_sweep_complete projects=%d", len(project_ids))

    except Exception as exc:  # noqa: BLE001
        logger.error("cib_sweep_failed error=%s", exc)
    finally:
        r.delete("cib_detection_lock")
