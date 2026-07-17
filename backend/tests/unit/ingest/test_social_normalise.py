"""
DISINFO-01 — Social post normaliser produces canonical event dicts for
             Mastodon, 4chan, and Reddit posts.

Implemented in: backend/app/ingest/social_normalise.py
"""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

social_normalise = pytest.importorskip(
    "app.ingest.social_normalise",
    reason="social_normalise not yet implemented",
)


def test_normalise_mastodon_post():
    """_normalise_social_post returns required keys for a Mastodon post.

    Keys: source_id, title, description, observed_at, content_hash, tags.
    Tags must contain exactly 'social_listening:mastodon'.
    """
    import uuid

    source_uuid = uuid.uuid4()
    post = {
        "id": "109832547891234567",
        "content": "<p>Test status update about cyber threat</p>",
        "created_at": "2025-01-15T10:30:00.000Z",
        "url": "https://mastodon.social/@example/109832547891234567",
    }

    result = social_normalise._normalise_social_post(post, source_uuid, "mastodon")

    assert "source_id" in result
    assert "title" in result
    assert "description" in result
    assert "observed_at" in result
    assert "content_hash" in result
    assert "tags" in result
    assert "social_listening:mastodon" in result["tags"]


def test_normalise_4chan_post():
    """_normalise_social_post decodes HTML entities for 4chan posts.

    Tags must contain 'social_listening:4chan'.
    HTML entities such as &gt; and &amp; are decoded in description.
    """
    import uuid

    source_uuid = uuid.uuid4()
    post = {
        "no": 12345678,
        "com": "This is &gt;implying &amp; we care about &lt;actors&gt;",
        "time": 1705312200,
        "board": "pol",
    }

    result = social_normalise._normalise_social_post(post, source_uuid, "4chan")

    assert "social_listening:4chan" in result["tags"]
    # HTML entities must be decoded in description
    assert "&amp;" not in result["description"]
    assert "&gt;" not in result["description"]


def test_normalise_reddit_post():
    """_normalise_social_post returns 'social_listening:reddit' tag for Reddit posts."""
    import uuid

    source_uuid = uuid.uuid4()
    post = {
        "id": "t3_abc123",
        "title": "New ransomware campaign targeting healthcare",
        "selftext": "Details about the campaign...",
        "created_utc": 1705312200.0,
        "permalink": "/r/netsec/comments/abc123/",
    }

    result = social_normalise._normalise_social_post(post, source_uuid, "reddit")

    assert "social_listening:reddit" in result["tags"]
    assert result["title"] == post["title"]


def test_content_hash_dedup():
    """Two calls with the same platform + post id produce identical content_hash.

    The content_hash must be deterministic so the dedup logic prevents
    duplicate events when the worker polls the same post twice.
    """
    import uuid

    source_uuid = uuid.uuid4()
    post = {
        "id": "109832547891234567",
        "content": "<p>Duplicate detection test</p>",
        "created_at": "2025-01-15T12:00:00.000Z",
        "url": "https://mastodon.social/@example/109832547891234567",
    }

    result_a = social_normalise._normalise_social_post(post, source_uuid, "mastodon")
    result_b = social_normalise._normalise_social_post(post, source_uuid, "mastodon")

    assert result_a["content_hash"] == result_b["content_hash"]
