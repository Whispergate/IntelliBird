"""Unit tests for dark-web IOC extraction patterns - DARK-05.

Tests the credential pair regex, .onion domain pass-through, and BTC/ETH
patterns applied to dark-web event content via Enrichment.iocs().
"""
from app.services.enrichment import enrich_event
from app.services.enrichment._text_extraction import _DOMAIN_PATTERN


def test_credential_pair_extracts_email_as_ioc():
    """credential pair 'user@example.com:s3cr3t' → iocs['email'] contains 'user@example.com'"""
    result = enrich_event("breach dump", "user@example.com:s3cr3t")
    assert "user@example.com" in result.iocs["email"]


def test_credential_pair_does_not_store_password_in_email_value():
    """IOC value must be email portion only; password must NOT appear as iocs['email'] value"""
    result = enrich_event("breach dump", "user@example.com:s3cr3t")
    for val in result.iocs["email"]:
        assert ":" not in val, f"password/hash leaked into email IOC value: {val!r}"
        assert "s3cr3t" not in val, f"password leaked into email IOC value: {val!r}"


def test_onion_domain_extracted_as_domain_ioc():
    """.onion hostname in text → iocs['domain'] contains the full .onion value"""
    result = enrich_event("dark web market", "Visit abc12345xyzwww.onion for details")
    assert "abc12345xyzwww.onion" in result.iocs["domain"]


def test_btc_wallet_extracted_from_dark_web_content():
    """BTC bc1… address in text → iocs['btc'] contains wallet address"""
    btc_addr = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
    result = enrich_event("ransomware payment", f"Send payment to {btc_addr}")
    assert btc_addr in result.iocs["btc"]


def test_eth_wallet_extracted_from_dark_web_content():
    """ETH 0x… address in text → iocs['eth'] contains wallet address"""
    eth_addr = "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"
    result = enrich_event("crypto theft", f"ETH wallet: {eth_addr}")
    assert eth_addr.lower() in {v.lower() for v in result.iocs["eth"]}


def test_multiple_credential_pairs_all_extracted():
    """3 email:pass pairs in one text block → all 3 emails in iocs['email']"""
    text = "alice@evil.com:p4ss123\nbob@bad.com:hunter2\ncarol@dark.net:secret99"
    result = enrich_event("credential dump", text)
    assert "alice@evil.com" in result.iocs["email"]
    assert "bob@bad.com" in result.iocs["email"]
    assert "carol@dark.net" in result.iocs["email"]


def test_onion_url_not_filtered_by_extension_exclusion_list():
    """'onion' TLD is NOT in the extension exclusion list - must not be silently dropped"""
    m = _DOMAIN_PATTERN.search("abc12345.onion")
    assert m is not None, ".onion domain was not matched by _DOMAIN_PATTERN"
    assert m.group(1).endswith(".onion"), f"unexpected match: {m.group(1)}"
