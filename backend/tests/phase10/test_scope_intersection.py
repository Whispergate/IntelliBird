"""test_scope_intersection — PRJ-03 (plan 10-05).

Query-time scope intersection semantics: domain suffix match, CIDR << containment,
keyword FTS reuse, empty-scope-empty-result invariant, exclude rows subtract from
include matches.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

import pytest

from app.models.events import Event
from app.models.projects import Project, ProjectScopeRow
from app.services.events_query import EventsQueryParams, build_events_query
from app.services.project_scope import (
    build_scope_predicate,
    fetch_scope_rows_intel,
)

pytestmark = pytest.mark.integration


async def _make_project(db_session, name: str = "P") -> Project:
    p = Project(
        id=_uuid.uuid4(), name=name, engagement_type="internal",
        created_by="system",
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _make_event(
    db_session,
    project: Project,
    *,
    raw_stix: dict,
    title: str = "t",
    visibility: str = "shared",
) -> Event:
    e = Event(
        id=_uuid.uuid4(),
        stix_type="indicator",
        observed_at=datetime.now(timezone.utc),
        content_hash=str(_uuid.uuid4()),
        visibility=visibility,
        raw_stix=raw_stix,
        project_id=project.id,
        title=title,
    )
    db_session.add(e)
    await db_session.commit()
    await db_session.refresh(e)
    return e


@pytest.mark.asyncio
async def test_empty_scope_empty_result(db_session):
    """No intel_scope=true rows -> zero events, not all events."""
    p = await _make_project(db_session, "empty")
    # Add an event so there's something for the filter to exclude
    await _make_event(
        db_session, p,
        raw_stix={"objects": [{"type": "indicator",
                               "pattern": "[domain-name:value = 'any.example.com']"}]},
    )

    rows = await fetch_scope_rows_intel(db_session, p.id)
    assert rows == []
    pred = build_scope_predicate(rows)

    stmt = build_events_query(
        EventsQueryParams(), None,
        project_id=p.id, scope_predicate=pred,
    )
    results = (await db_session.execute(stmt)).scalars().all()
    assert results == []


@pytest.mark.asyncio
async def test_domain_suffix(db_session):
    """domain scope row matches exact domain AND any subdomain."""
    p = await _make_project(db_session, "dom")
    db_session.add(ProjectScopeRow(
        project_id=p.id, scope_type="domain",
        value="example.com", intel_scope=True,
    ))
    await db_session.commit()

    match_raw = {"objects": [{
        "type": "indicator",
        "pattern": "[domain-name:value = 'sub.example.com']",
    }]}
    nomatch_raw = {"objects": [{
        "type": "indicator",
        "pattern": "[domain-name:value = 'evil.com']",
    }]}
    e1 = await _make_event(db_session, p, raw_stix=match_raw)
    e2 = await _make_event(db_session, p, raw_stix=nomatch_raw)

    rows = await fetch_scope_rows_intel(db_session, p.id)
    pred = build_scope_predicate(rows)
    stmt = build_events_query(
        EventsQueryParams(), None,
        project_id=p.id, scope_predicate=pred,
    )
    ids = {r.id for r in (await db_session.execute(stmt)).scalars().all()}
    assert e1.id in ids
    assert e2.id not in ids


@pytest.mark.asyncio
async def test_cidr_contains(db_session):
    """ip_range scope row matches IPs inside the CIDR (inet <<)."""
    p = await _make_project(db_session, "ip")
    db_session.add(ProjectScopeRow(
        project_id=p.id, scope_type="ip_range",
        value="10.0.0.0/8", intel_scope=True,
    ))
    await db_session.commit()

    match_raw = {"objects": [{
        "type": "indicator",
        "pattern": "[ipv4-addr:value = '10.5.5.5']",
    }]}
    nomatch_raw = {"objects": [{
        "type": "indicator",
        "pattern": "[ipv4-addr:value = '8.8.8.8']",
    }]}
    e1 = await _make_event(db_session, p, raw_stix=match_raw)
    e2 = await _make_event(db_session, p, raw_stix=nomatch_raw)

    rows = await fetch_scope_rows_intel(db_session, p.id)
    pred = build_scope_predicate(rows)
    stmt = build_events_query(
        EventsQueryParams(), None,
        project_id=p.id, scope_predicate=pred,
    )
    ids = {r.id for r in (await db_session.execute(stmt)).scalars().all()}
    assert e1.id in ids
    assert e2.id not in ids


@pytest.mark.asyncio
async def test_keyword_fts(db_session):
    """keyword scope row uses FTS via events.search_tsv."""
    p = await _make_project(db_session, "kw")
    db_session.add(ProjectScopeRow(
        project_id=p.id, scope_type="keyword",
        value="ransomware", intel_scope=True,
    ))
    await db_session.commit()

    e1 = await _make_event(
        db_session, p,
        raw_stix={"objects": []},
        title="New ransomware campaign discovered",
    )
    e2 = await _make_event(
        db_session, p,
        raw_stix={"objects": []},
        title="Phishing email analysis",
    )

    rows = await fetch_scope_rows_intel(db_session, p.id)
    pred = build_scope_predicate(rows)
    stmt = build_events_query(
        EventsQueryParams(), None,
        project_id=p.id, scope_predicate=pred,
    )
    ids = {r.id for r in (await db_session.execute(stmt)).scalars().all()}
    assert e1.id in ids
    assert e2.id not in ids


@pytest.mark.asyncio
async def test_exclude_subtracts(db_session):
    """exclude=true rows subtract from the include match (include AND NOT exclude)."""
    p = await _make_project(db_session, "xclude")
    db_session.add_all([
        ProjectScopeRow(
            project_id=p.id, scope_type="domain",
            value="example.com", intel_scope=True, exclude=False,
        ),
        ProjectScopeRow(
            project_id=p.id, scope_type="domain",
            value="internal.example.com", intel_scope=True, exclude=True,
        ),
    ])
    await db_session.commit()

    r_in = {"objects": [{
        "type": "indicator",
        "pattern": "[domain-name:value = 'www.example.com']",
    }]}
    r_out = {"objects": [{
        "type": "indicator",
        "pattern": "[domain-name:value = 'internal.example.com']",
    }]}
    e1 = await _make_event(db_session, p, raw_stix=r_in)
    e2 = await _make_event(db_session, p, raw_stix=r_out)

    rows = await fetch_scope_rows_intel(db_session, p.id)
    pred = build_scope_predicate(rows)
    stmt = build_events_query(
        EventsQueryParams(), None,
        project_id=p.id, scope_predicate=pred,
    )
    ids = {r.id for r in (await db_session.execute(stmt)).scalars().all()}
    assert e1.id in ids
    assert e2.id not in ids
