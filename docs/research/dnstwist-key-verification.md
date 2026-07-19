# dnstwist JSON Key Verification

**Date verified:** 2026-04-22
**dnstwist version:** dnstwist 20250130
**Python:** Python 3.13.12
**Invocation:** `dnstwist --threads 10 --format json google.com`
**Total permutations emitted:** 2965

## Verified key shape

Sample permutation row from `dnstwist --format json google.com` (full-DNS case):

```json
{
    "dns_a": [
        "104.21.16.168"
    ],
    "dns_aaaa": [
        "2606:4700:3033::6815:10a8"
    ],
    "dns_mx": [
        "route1.mx.cloudflare.net"
    ],
    "dns_ns": [
        "damon.ns.cloudflare.com"
    ],
    "domain": "googleb.com",
    "fuzzer": "addition"
}
```

Exhaustive key enumeration across all 2965 rows:

```
['dns_a', 'dns_aaaa', 'dns_mx', 'dns_ns', 'domain', 'fuzzer']
```

No other keys appear in this version. No `whois_created`, no `whois_registrar`, no `geoip`, no `ssdeep_score` - those require `--whois` / `--geoip` / `--ssdeep` flags which does not pass.

## Resolution

- **Domain key:** `domain` (single canonical form - NOT `domain-name`, NOT `domain_name`; no hyphen variants observed in this version).
- **DNS records keys:** `dns_a`, `dns_aaaa`, `dns_mx`, `dns_ns` - all snake_case; no hyphen variants (`dns-a`, etc.) observed.
- **Fuzzer key:** `fuzzer` (values include `*original`, `addition`, `homoglyph`, `bitsquatting`, etc.; the `*original` row must be filtered by the parser).
- **`lookup_success` derivation:** `lookup_success` is NOT emitted by dnstwist. Parser derives it: `has_a = perm.get('dns_a') and perm['dns_a'][0] != '!ServFail'` AND/OR `has_ns = perm.get('dns_ns') and perm['dns_ns'][0] != '!ServFail'`. `lookup_success = has_a or has_ns`.
- **ServFail sentinel:** Unresolved records appear as `["!ServFail"]` (single-element list with a literal `!ServFail` string). Empty records appear as `[""]` for MX sometimes. Parser must treat both `!ServFail` and empty-string as "no data".
- **`whois_*` keys:** NOT present in this invocation (flag not passed). Parser must not assume they exist.

## Final parser strategy (locked for plan 12-02)

1. Parser reads JSON array from `dnstwist` subprocess stdout.
2. Skip rows where `fuzzer == "*original"`.
3. Access domain as `perm["domain"]` - the canonical key is `domain` per this verification. Defensive `.get("domain") or .get("domain-name") or .get("domain_name")` may still be added as a belt-and-braces guard per 12-RESEARCH.md implementation note, but the `golden_dnstwist_json` fixture asserts `domain`.
4. DNS records accessed by `.get("dns_a", [])` etc. - all four (`dns_a`, `dns_aaaa`, `dns_mx`, `dns_ns`) use snake_case.
5. Treat any dns record whose first element is `"!ServFail"` or `""` as "no data" when computing `lookup_success`.
6. Emit `lookup_success` as a derived bool in the parser's output dict - NOT read from dnstwist.

## Raw output archive

Full 2965-permutation JSON archived at `/tmp/dnstwist-google.json` (287 KB, captured 2026-04-22 16:14:00 local). Not checked in (too large; reproducible by re-running the invocation above). Three representative rows selected for the golden fixture (`backend/tests/fixtures/dnstwist_json/sample_permutations.json`): one full-DNS (cloudflare-parked `googleb.com`), one partial-DNS A+NS only (`googlec.com`), one all-ServFail (`google4.com`).
