"""Unit test stubs — enrichment verdict derivation per provider.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-02 ships the verdict module.

Verdict ENUM: clean | suspicious | malicious | unknown

Requirement coverage: ENRICH-02 (per-provider verdict normalisation).
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# VirusTotal verdict thresholds
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="not yet implemented —")
def test_vt_malicious_threshold():
    """5+ malicious detections → verdict 'malicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_vt_suspicious_threshold():
    """5+ suspicious, <5 malicious → verdict 'suspicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_vt_clean():
    """0 malicious, 0 suspicious → verdict 'clean'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


# ---------------------------------------------------------------------------
# AbuseIPDB verdict thresholds
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="not yet implemented —")
def test_abuseipdb_score_75_malicious():
    """AbuseIPDB confidence score >= 75 → verdict 'malicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_abuseipdb_score_50_suspicious():
    """AbuseIPDB confidence score >= 50 (and < 75) → verdict 'suspicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_abuseipdb_score_10_clean():
    """AbuseIPDB confidence score < 50 → verdict 'clean'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


# ---------------------------------------------------------------------------
# GreyNoise verdict
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="not yet implemented —")
def test_greynoise_riot_clean():
    """GreyNoise riot=True → verdict 'clean' (benign internet scanner)."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_greynoise_malicious_classification():
    """GreyNoise noise=True, classification='malicious' → verdict 'malicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_greynoise_no_noise_unknown():
    """GreyNoise noise=False, riot=False → verdict 'unknown'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


# ---------------------------------------------------------------------------
# OTX (AlienVault) verdict
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="not yet implemented —")
def test_otx_10_pulses_malicious():
    """OTX pulse_count >= 10 → verdict 'malicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_otx_3_pulses_suspicious():
    """OTX pulse_count in range [1, 9] → verdict 'suspicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_otx_0_pulses_clean():
    """OTX pulse_count == 0 → verdict 'clean'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


# ---------------------------------------------------------------------------
# URLhaus verdict
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="not yet implemented —")
def test_urlhaus_listed_malicious():
    """URLhaus query_status='listed' → verdict 'malicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_urlhaus_not_listed_clean():
    """URLhaus query_status='not_listed' → verdict 'clean'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


# ---------------------------------------------------------------------------
# Shodan verdict
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="not yet implemented —")
def test_shodan_vulns_suspicious():
    """Shodan 1-3 vulns in the vulns dict → verdict 'suspicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_shodan_many_vulns_malicious():
    """Shodan > 3 vulns → verdict 'malicious'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_shodan_no_data_unknown():
    """Shodan empty vulns dict (or no host data) → verdict 'unknown'."""
    mod = pytest.importorskip("app.services.ioc_enrichment.verdict")
    assert False, "stub"
