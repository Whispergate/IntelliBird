"""
MISP-02 — System pulls MISP attributes by tag/galaxy; attributes persist as
          rows in the iocs table with source='misp'.

Implemented in: backend/app/workers/misp_pull.py
"""
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


@pytest.mark.xfail(reason="misp_pull worker not yet implemented", strict=False)
def test_attribute_type_mapping_ip_src():
    """MISP attribute type 'ip-src' maps to IOC type 'ip'."""
    from app.workers.misp_pull import _misp_type_to_ioc_type
    assert _misp_type_to_ioc_type("ip-src") == "ip"
    assert _misp_type_to_ioc_type("ip-dst") == "ip"


@pytest.mark.xfail(reason="misp_pull worker not yet implemented", strict=False)
def test_attribute_type_mapping_domain():
    """MISP attribute types 'domain' and 'hostname' map to IOC type 'domain'."""
    from app.workers.misp_pull import _misp_type_to_ioc_type
    assert _misp_type_to_ioc_type("domain") == "domain"
    assert _misp_type_to_ioc_type("hostname") == "domain"


@pytest.mark.xfail(reason="misp_pull worker not yet implemented", strict=False)
def test_attribute_type_mapping_hash():
    """MISP 'md5' and 'sha256' map to IOC type 'hash'; others return None."""
    from app.workers.misp_pull import _misp_type_to_ioc_type
    assert _misp_type_to_ioc_type("md5") == "hash"
    assert _misp_type_to_ioc_type("sha256") == "hash"
    assert _misp_type_to_ioc_type("unknown-type") is None


@pytest.mark.xfail(reason="misp_pull worker not yet implemented", strict=False)
def test_attribute_type_mapping_email():
    """MISP 'email-src' and 'email-dst' map to IOC type 'email'."""
    from app.workers.misp_pull import _misp_type_to_ioc_type
    assert _misp_type_to_ioc_type("email-src") == "email"
    assert _misp_type_to_ioc_type("email-dst") == "email"


@pytest.mark.xfail(reason="misp_pull worker not yet implemented", strict=False)
def test_ioc_source_is_misp():
    """IOC rows created from MISP attributes have source='misp'."""
    from app.workers.misp_pull import _build_ioc_dict
    ioc = _build_ioc_dict(misp_type="ip-src", value="1.2.3.4", project_id="p1")
    assert ioc["source"] == "misp"
