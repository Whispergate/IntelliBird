# Owned by: 12.1-03-PLAN
"""Unit tests for compute_asset_scope + helpers (Task 2)."""
from __future__ import annotations

from app.models.projects import ProjectScopeRow
from app.schemas.assets import AssetScope
from app.services.assets_query import compute_asset_scope


def _domain_row(value: str, *, exclude: bool = False) -> ProjectScopeRow:
    return ProjectScopeRow(
        scope_type="domain",
        value=value,
        exclude=exclude,
        active_test_scope=True,
        intel_scope=True,
    )


def _ip_range_row(value: str, *, exclude: bool = False) -> ProjectScopeRow:
    return ProjectScopeRow(
        scope_type="ip_range",
        value=value,
        exclude=exclude,
        active_test_scope=True,
        intel_scope=True,
    )


# --- UNSCOPED_BY_DESIGN ---

def test_technology_always_unscoped_regardless_of_rows():
    rows = [_domain_row("evilcorp.com"), _ip_range_row("10.0.0.0/24")]
    assert compute_asset_scope("TECHNOLOGY", "nginx", rows) == AssetScope.UNSCOPED


def test_email_address_always_unscoped_regardless_of_rows():
    rows = [_domain_row("evilcorp.com")]
    assert (
        compute_asset_scope("EMAIL_ADDRESS", "ops@evilcorp.com", rows)
        == AssetScope.UNSCOPED
    )


# --- Domain dispatch ---

def test_dns_name_in_scope_via_suffix():
    rows = [_domain_row("evilcorp.com")]
    assert (
        compute_asset_scope("DNS_NAME", "sub.evilcorp.com", rows)
        == AssetScope.IN_SCOPE
    )


def test_dns_name_out_of_scope_when_applicable_row_no_match():
    rows = [_domain_row("evilcorp.com")]
    assert (
        compute_asset_scope("DNS_NAME", "sub.safeacme.com", rows)
        == AssetScope.OUT_OF_SCOPE
    )


def test_dns_name_unscoped_when_no_applicable_rows():
    assert compute_asset_scope("DNS_NAME", "anything.com", []) == AssetScope.UNSCOPED


def test_dns_name_exact_match_counts_as_in_scope():
    rows = [_domain_row("evilcorp.com")]
    assert (
        compute_asset_scope("DNS_NAME", "evilcorp.com", rows) == AssetScope.IN_SCOPE
    )


# --- IP dispatch ---

def test_ip_address_in_scope_via_cidr():
    rows = [_ip_range_row("10.0.0.0/24")]
    assert (
        compute_asset_scope("IP_ADDRESS", "10.0.0.5", rows) == AssetScope.IN_SCOPE
    )


def test_ip_address_out_of_scope_when_no_cidr_match():
    rows = [_ip_range_row("10.0.0.0/24")]
    assert (
        compute_asset_scope("IP_ADDRESS", "192.168.1.1", rows)
        == AssetScope.OUT_OF_SCOPE
    )


def test_ip_address_exclude_wins_over_include():
    rows = [
        _ip_range_row("10.0.0.0/24", exclude=False),
        _ip_range_row("10.0.0.5/32", exclude=True),
    ]
    assert (
        compute_asset_scope("IP_ADDRESS", "10.0.0.5", rows)
        == AssetScope.OUT_OF_SCOPE
    )


# --- Hybrid dispatch (host:port) ---

def test_open_tcp_port_ip_host_routes_to_ip_range():
    rows = [_ip_range_row("10.0.0.0/24")]
    assert (
        compute_asset_scope("OPEN_TCP_PORT", "10.0.0.5:443", rows)
        == AssetScope.IN_SCOPE
    )


def test_open_tcp_port_domain_host_routes_to_domain():
    rows = [_domain_row("evilcorp.com")]
    assert (
        compute_asset_scope("OPEN_TCP_PORT", "sub.evilcorp.com:8080", rows)
        == AssetScope.IN_SCOPE
    )


# --- Caller pre-filters rows ---

def test_caller_filtered_rows_pass_through():
    # Caller passed only intel_scope=True rows (emulating fetch_scope_rows_intel)
    rows = [_domain_row("evilcorp.com")]
    result = compute_asset_scope("DNS_NAME", "api.evilcorp.com", rows)
    assert result == AssetScope.IN_SCOPE


# --- Hostname-bearing finding types (CONTEXT §Scope reconciliation) ---

def test_subdomain_takeover_candidate_routes_through_domain_dispatch():
    rows = [_domain_row("evilcorp.com")]
    assert (
        compute_asset_scope(
            "SUBDOMAIN_TAKEOVER_CANDIDATE", "takeover.evilcorp.com", rows
        )
        == AssetScope.IN_SCOPE
    )


def test_vulnerability_routes_through_domain_dispatch():
    rows = [_domain_row("evilcorp.com")]
    assert (
        compute_asset_scope("VULNERABILITY", "vuln.evilcorp.com", rows)
        == AssetScope.IN_SCOPE
    )


def test_finding_routes_through_domain_dispatch_out_of_scope():
    rows = [_domain_row("evilcorp.com")]
    assert (
        compute_asset_scope("FINDING", "finding.safeacme.com", rows)
        == AssetScope.OUT_OF_SCOPE
    )
