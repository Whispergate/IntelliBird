"""
SANDBOX-02 - SHA256 IOC creation triggers submit_sandbox_report.send(); sample fetch miss -> sample_unavailable.
SANDBOX-05 - _write_attack_tag called with tag_source='auto' for each MITRE technique in report.
Implemented in: backend/app/workers/sandbox.py
"""
import pytest


@pytest.mark.xfail(reason="not yet implemented -")
def test_sha256_ioc_creation_triggers_submit_actor():
    """After SHA256 IOC insert, submit_sandbox_report.send(ioc_id, project_id) is called."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented -")
def test_malwarebazaar_miss_sets_sample_unavailable():
    """MalwareBazaar 200-JSON miss path sets sandbox_reports.status='sample_unavailable'."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented -")
def test_auto_tags_techniques():
    """_write_attack_tag is called once per technique in SandboxReport.techniques with tag_source='auto'."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented -")
def test_network_iocs_upserted_from_report():
    """Network IOCs in SandboxReport are upserted via pg_insert(IOC) with confidence=0.8."""
    raise NotImplementedError
