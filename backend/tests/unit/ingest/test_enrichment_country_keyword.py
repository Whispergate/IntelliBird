"""Regression tests for the country + keyword enrichment expansion.

Locks:
- All country mentions captured (set, not first-only)
- country_code prefers cyber-attribution priority list (US > RU > CN > KP > IR ...)
- Unranked countries fall back to alpha-2 lex order
- `country:<CC>` tag emitted per match
- Curated security keywords emit `keyword:<term>` tag + populate keywords set
- Common English words do NOT false-positive (us / it / no / in)
"""


from app.services.enrichment import enrich_event


def test_multiple_countries_emit_tags_and_set():
    # Note: bare "US" deliberately NOT in US demonym pattern (false-positive
    # risk on lowercase "us" pronoun under re.IGNORECASE). Use full name / USA.
    e = enrich_event(
        "Russian APT29 hits the United States and German energy firms",
        "Ukrainian CERT confirms Iranian C2 infrastructure overlap.",
    )
    assert e.country_codes == {"US", "RU", "DE", "UA", "IR"}
    assert "country:US" in e.tags
    assert "country:RU" in e.tags
    assert "country:DE" in e.tags
    assert "country:UA" in e.tags
    assert "country:IR" in e.tags


def test_country_code_priority_picks_highest_priority_match():
    # RU > DE per COUNTRY_PRIORITY
    e = enrich_event(None, "German researchers attribute attacks to Russia.")
    assert e.country_code == "RU"


def test_country_code_priority_us_beats_brazil():
    e = enrich_event(
        None, "Brazilian victims of United States-attributed cyber operation."
    )
    assert e.country_code == "US"


def test_country_code_alpha2_fallback_when_no_priority():
    # Belgium + Netherlands - neither in priority list. Lex order picks BE.
    e = enrich_event(None, "Dutch and Belgian banks targeted in coordinated raid.")
    assert e.country_codes == {"BE", "NL"}
    assert e.country_code == "BE"


def test_keyword_extraction():
    e = enrich_event(
        "Massive DDoS attack triggers wiper malware",
        "Spear-phishing emails dropped a RAT establishing C2. SQL injection chained with privilege escalation.",
    )
    assert "ddos" in e.keywords
    assert "wiper" in e.keywords
    assert "spear-phishing" in e.keywords
    assert "rat" in e.keywords
    assert "c2" in e.keywords
    assert "sqli" in e.keywords
    assert "privilege-escalation" in e.keywords
    for term in e.keywords:
        assert f"keyword:{term}" in e.tags


def test_no_false_positive_on_common_english_words():
    # Risk: "us", "it", "no", "in" are 2-letter ISO codes (US, IT, NO, IN) but
    # also common pronouns/prepositions. Demonym patterns should not trigger.
    e = enrich_event(None, "Let us begin. It is not a real threat in this case.")
    assert e.country_codes == set()
    assert e.country_code is None
    # Also no spurious keyword hits on stopwords
    assert e.keywords == set()


def test_full_country_name_long_tail():
    # Country in the long-tail list (no demonym) - match by name only
    e = enrich_event(None, "Botnet C2 nodes located in Mongolia and Senegal.")
    assert "MN" in e.country_codes
    assert "SN" in e.country_codes


def test_country_code_priority_index_known():
    # Sanity: priority list head is US
    from app.services.country_data import COUNTRY_PRIORITY
    assert COUNTRY_PRIORITY[0] == "US"


def test_existing_enrichment_still_works():
    # Ensure prior CVE / ATT&CK / IOC extraction survives the refactor
    e = enrich_event(
        "CVE-2024-1234 exploited by APT29",
        "Technique T1059.001 used. C2 IP 8.8.4.4 observed.",
    )
    assert "CVE-2024-1234" in e.cve_ids
    assert "T1059.001" in e.attack_techniques
    assert "8.8.4.4" in e.iocs["ip"]
    assert "apt" in e.tags
