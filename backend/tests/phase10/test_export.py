"""Wave 0 stub - Plan 10-07 owns implementation. Test bodies land with that plan.

PRJ-07 per-project export: STIX 2.1 Bundle (events + project note with
x_intellibird_* custom properties) is parseable; CSV column set + order locked;
50k cap returns 413 with hint; Observer role cannot export (403).
See VALIDATION.md Per-Task Verification Map for row-level automated commands.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration
pytest.skip("Wave 0 stub - plan 10-07-PLAN activates", allow_module_level=True)


# --- Placeholder signatures (all will be filled in by plan 10-07) ---


def test_stix_bundle_parseable() -> None:
    """See VALIDATION.md row PRJ-07 test_stix_bundle_parseable."""
    # Will be filled in by plan 10-07
    pass


def test_csv_columns() -> None:
    """See VALIDATION.md row PRJ-07 test_csv_columns."""
    # Will be filled in by plan 10-07
    pass


def test_size_cap_413() -> None:
    """See VALIDATION.md row PRJ-07 test_size_cap_413."""
    # Will be filled in by plan 10-07
    pass


def test_observer_cannot_export() -> None:
    """See VALIDATION.md row PRJ-07 test_observer_cannot_export."""
    # Will be filled in by plan 10-07
    pass
