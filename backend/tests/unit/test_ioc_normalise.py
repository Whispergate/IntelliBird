"""IOC-01 normalisation unit tests. Implemented by Plan 22-02 Task 3."""

def test_normalise_ipv4_strips_leading_zeros():
    from app.services.iocs import normalise
    assert normalise("ip", "01.02.03.04") == "1.2.3.4"

def test_normalise_ipv6_compresses():
    from app.services.iocs import normalise
    assert normalise("ipv6", "2001:0db8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"

def test_normalise_idn_domain_punycode_lower():
    from app.services.iocs import normalise
    assert normalise("domain", "BÜCHER.de") == "xn--bcher-kva.de"

def test_normalise_url_lowercase_scheme_host_preserves_path():
    from app.services.iocs import normalise
    assert normalise("url", "HTTPS://Evil.COM/Path?Q=A") == "https://evil.com/Path?Q=A"

def test_normalise_hashes_lowercase():
    from app.services.iocs import normalise
    assert normalise("sha256", "ABCDEF1234") == "abcdef1234"

def test_normalise_email_lowercase():
    from app.services.iocs import normalise
    assert normalise("email", "Foo@Bar.COM") == "foo@bar.com"

def test_normalise_btc_preserves_case():
    from app.services.iocs import normalise
    assert normalise("btc", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa") == "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
