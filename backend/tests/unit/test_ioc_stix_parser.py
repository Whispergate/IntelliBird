"""IOC-02 STIX 2.1 parser unit tests. Implemented by Plan 22-05 Task 1."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


def test_stix_indicator_pattern_extracts_ipv4():
    from app.services.ioc_import.stix_parser import parse_stix_bundle
    bundle = {
      "type":"bundle","id":"bundle--1",
      "objects":[{"type":"indicator","id":"indicator--1","spec_version":"2.1",
        "created":"2025-01-01T00:00:00Z","modified":"2025-01-01T00:00:00Z",
        "pattern_type":"stix","pattern":"[ipv4-addr:value = '1.2.3.4']",
        "valid_from":"2025-01-01T00:00:00Z"}]}
    rows = list(parse_stix_bundle(bundle))
    assert ("ip","1.2.3.4") in rows

def test_stix_observed_data_walks_scos():
    from app.services.ioc_import.stix_parser import parse_stix_bundle
    bundle = {"type":"bundle","id":"bundle--2","objects":[
      {"type":"observed-data","id":"observed-data--1","spec_version":"2.1",
       "created":"2025-01-01T00:00:00Z","modified":"2025-01-01T00:00:00Z",
       "first_observed":"2025-01-01T00:00:00Z","last_observed":"2025-01-01T00:00:00Z",
       "number_observed":1,"objects":{"0":{"type":"domain-name","value":"evil.com"}}}]}
    rows = list(parse_stix_bundle(bundle))
    assert ("domain","evil.com") in rows

def test_stix_unmapped_sdos_skipped_with_count():
    from app.services.ioc_import.stix_parser import parse_stix_bundle
    # relationship/intrusion-set should not raise, just be skipped
    bundle = {"type":"bundle","id":"bundle--3","objects":[
      {"type":"intrusion-set","id":"intrusion-set--apt29","spec_version":"2.1",
       "created":"2025-01-01T00:00:00Z","modified":"2025-01-01T00:00:00Z","name":"APT29"}]}
    rows = list(parse_stix_bundle(bundle))
    assert rows == []
