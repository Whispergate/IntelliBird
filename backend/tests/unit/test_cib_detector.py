"""
DISINFO-02 - Coordinated Inauthentic Behaviour (CIB) detector identifies
             clusters of near-identical posts using MinHash similarity.

Implemented in: backend/app/services/cib_detector.py
"""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

cib_detector = pytest.importorskip(
    "app.services.cib_detector",
    reason="cib_detector not yet implemented",
)


def test_build_minhash_returns_minhash():
    """build_minhash(text) returns a MinHash object (datasketch.MinHash).

    The return type must be MinHash so that jaccard similarity can be
    computed between pairs of posts.
    """
    datasketch = pytest.importorskip("datasketch", reason="datasketch not installed")

    text = "Breaking: new ransomware group targets energy sector with custom payload"
    result = cib_detector.build_minhash(text)

    assert isinstance(result, datasketch.MinHash)


def test_detect_cib_cluster_returns_cluster():
    """detect_cib_cluster finds a cluster when 6 near-identical posts exist.

    Six posts with near-identical text (small word substitution) must yield
    at least one cluster of >= 5 members.
    """
    base = "Urgent warning: critical vulnerability CVE-2025-1234 found in {product} - patch now"
    posts = [
        {"id": str(i), "text": base.format(product=f"product_{i}")}
        for i in range(6)
    ]

    clusters = cib_detector.detect_cib_cluster(posts, threshold=0.7, min_cluster_size=5)

    assert isinstance(clusters, list)
    assert len(clusters) >= 1
    # The largest cluster must have at least 5 members
    max_cluster = max(clusters, key=lambda c: len(c))
    assert len(max_cluster) >= 5


def test_detect_cib_cluster_no_cluster():
    """detect_cib_cluster returns [] when posts are completely distinct.

    Five completely different posts (no shared shingles) must not form a
    cluster, so the result is an empty list.
    """
    distinct_posts = [
        {"id": "1", "text": "Breaking: earthquake hits coastal city, rescue teams deployed"},
        {"id": "2", "text": "Stock markets rally after Federal Reserve rate announcement"},
        {"id": "3", "text": "Scientists discover new exoplanet with potential water"},
        {"id": "4", "text": "Championship football match ends in dramatic penalty shootout"},
        {"id": "5", "text": "New malware strain uses steganography to exfiltrate data"},
    ]

    clusters = cib_detector.detect_cib_cluster(distinct_posts, threshold=0.7, min_cluster_size=5)

    assert clusters == []


def test_sweep_inserts_cluster():
    """run_cib_sweep_for_project inserts a cib_clusters row when >= 5 similar events found.

    Stubs the DB session. Verifies the INSERT is attempted when the detector
    returns a cluster of size >= 5.
    """
    from unittest.mock import MagicMock, patch
    import uuid

    project_id = uuid.uuid4()
    fake_cluster = [{"id": str(i), "text": f"near-identical post {i}"} for i in range(6)]

    with patch.object(cib_detector, "detect_cib_cluster", return_value=[fake_cluster]):
        with patch.object(cib_detector, "_fetch_recent_social_events", return_value=fake_cluster):
            mock_session = MagicMock()
            cib_detector.run_cib_sweep_for_project(mock_session, project_id)
            # A cib_clusters row must be added when a cluster is detected
            assert mock_session.add.call_count >= 1 or mock_session.execute.call_count >= 1
