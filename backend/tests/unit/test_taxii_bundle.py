"""Unit tests for TAXII bundle builder — Phase 26 / TAXII-02.

Wave 0 stubs. All tests skip until taxii_bundle.py is implemented in plan 26-03.
"""
from __future__ import annotations
import pytest


@pytest.mark.skip(reason="stub — implement in plan 26-03")
def test_event_with_raw_stix_passthrough():
    """TAXII-02: event with raw_stix returns the stored SDO dict unchanged."""
    raise NotImplementedError


@pytest.mark.skip(reason="stub — implement in plan 26-03")
def test_event_without_stix_wraps_observed_data():
    """TAXII-02: event without raw_stix is wrapped as ObservedData with x_intellibird_* custom props."""
    raise NotImplementedError


@pytest.mark.skip(reason="stub — implement in plan 26-03")
def test_tlp_predicate_filters_amber_from_green_client():
    """TAXII-04: build_tlp_predicate('green') excludes amber, amber+strict, red levels."""
    raise NotImplementedError
