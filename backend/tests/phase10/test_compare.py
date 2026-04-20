"""Wave 0 stub - Plan 10-07 owns implementation. Test bodies land with that plan.

PRJ-06 cross-project compare: two-project comparison returns shared actors,
shared ATT&CK techniques, shared IOCs (IPs/domains/hashes); rejects users who
lack membership on either side.
See VALIDATION.md Per-Task Verification Map for row-level automated commands.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration
pytest.skip("Wave 0 stub - plan 10-07-PLAN activates", allow_module_level=True)


# --- Placeholder signatures (all will be filled in by plan 10-07) ---


def test_shared_actors() -> None:
    """See VALIDATION.md row PRJ-06 test_shared_actors."""
    # Will be filled in by plan 10-07
    pass


def test_shared_techniques() -> None:
    """See VALIDATION.md row PRJ-06 test_shared_techniques."""
    # Will be filled in by plan 10-07
    pass


def test_shared_iocs() -> None:
    """See VALIDATION.md row PRJ-06 test_shared_iocs."""
    # Will be filled in by plan 10-07
    pass


def test_auth_both_sides() -> None:
    """See VALIDATION.md row PRJ-06 test_auth_both_sides."""
    # Will be filled in by plan 10-07
    pass
