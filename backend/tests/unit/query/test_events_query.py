"""Tests for build_events_query - FIL-01, FIL-02.

Updated in plan 09-05: role: str | None -> dashboard_roles: list[str] | None.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.services.events_query import EventsQueryParams, build_events_query


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()


def test_source_filter_in_clause():
    sid = uuid.uuid4()
    stmt = build_events_query(EventsQueryParams(source=[sid]), dashboard_roles=None)
    sql = _sql(stmt)
    assert "events.source_id in" in sql


def test_source_type_subquery():
    stmt = build_events_query(EventsQueryParams(source_type=["rss", "taxii"]), dashboard_roles=None)
    sql = _sql(stmt)
    assert "sources.feed_type in" in sql
    assert "events.source_id in (select" in sql


def test_observed_from_to_bounds():
    t1 = datetime(2025, 9, 1, tzinfo=timezone.utc)
    t2 = datetime(2025, 10, 1, tzinfo=timezone.utc)
    stmt = build_events_query(EventsQueryParams(observed_from=t1, observed_to=t2), dashboard_roles=None)
    sql = _sql(stmt)
    assert "events.observed_at >=" in sql
    assert "events.observed_at <=" in sql


def test_tlp_name_to_uuid_subquery():
    stmt = build_events_query(EventsQueryParams(tlp=["clear", "green"]), dashboard_roles=None)
    sql = _sql(stmt)
    assert "tlp_markings.name in" in sql
    assert "events.tlp_marking_id in (select" in sql


def test_attack_technique_filter_subquery():
    stmt = build_events_query(EventsQueryParams(attack_technique=["T1190"]), dashboard_roles=None)
    sql = _sql(stmt)
    assert "attack_technique_tags.technique_id in" in sql
    assert "events.id in (select" in sql


def test_tag_and_semantics_coalesce_null():
    stmt = build_events_query(EventsQueryParams(tag=["apt28", "phishing"]), dashboard_roles=None)
    sql = _sql(stmt)
    assert "coalesce(events.tags" in sql  # - NULL-safe
    assert "@>" in sql


def test_include_archived_default_false():
    stmt = build_events_query(EventsQueryParams(), dashboard_roles=None)
    sql = _sql(stmt)
    assert "events.archived =" in sql


def test_include_archived_true_disables_filter():
    stmt = build_events_query(EventsQueryParams(include_archived=True), dashboard_roles=None)
    sql = _sql(stmt)
    # archived filter absent
    assert "events.archived = false" not in sql.replace("  ", " ")


def test_sort_observed_at_desc_id_desc():
    stmt = build_events_query(EventsQueryParams(), dashboard_roles=None)
    sql = _sql(stmt)
    assert "order by events.observed_at desc" in sql
    assert "events.id desc" in sql
