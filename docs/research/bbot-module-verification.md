# BBOT 2.8.x Module Verification

**Date verified:** 2026-04-20
**BBOT version:** 2.8.4 (from image banner: `BIGHUGE BLS OSINT TOOL v2.8.4`)
**BBOT image digest:** sha256:ae34a24ee3f30eb334466450303dc2df739b5505aa0c248fa0f603b167f0fc69
**Verification command:** `docker run --rm blacklanternsecurity/bbot:stable -l`

---

## Verified passive module names (for BBOT_STABLE_PASSIVE_MODULES)

The following modules are confirmed present in BBOT 2.8.4 with `passive` flag and `safe` flag.
All were verified against live `docker run --rm blacklanternsecurity/bbot:stable -l` output.

| Module | Type | Needs API Key | Notes |
|--------|------|---------------|-------|
| `crt` | scan | No | Certificate transparency via crt.sh - confirmed present as `crt` (NOT `crt.sh`) |
| `dnsdumpster` | scan | No | Confirmed present |
| `otx` | scan | Yes | AlienVault OTX - confirmed present; **requires OTX API key** (research doc omitted this) |
| `shodan_dns` | scan | Yes | Shodan passive DNS - confirmed present; requires SHODAN_API_KEY |
| `wayback` | scan | No | archive.org - confirmed present |
| `github_codesearch` | scan | Yes | GitHub code search - confirmed present; requires GITHUB_TOKEN |
| `certspotter` | scan | No | Certspotter CT logs - confirmed present |
| `hackertarget` | scan | No | hackertarget.com - confirmed present |
| `anubisdb` | scan | No | jldc.me subdomain DB - confirmed present |
| `bevigil` | scan | Yes | OSINT from mobile apps - confirmed present; requires BEVIGIL_API_KEY |
| `chaos` | scan | Yes | ProjectDiscovery Chaos - confirmed present; requires CHAOS_API_KEY |
| `urlscan` | scan | No | urlscan.io - confirmed present |
| `securitytrails` | scan | Yes | SecurityTrails - confirmed present; requires SECURITYTRAILS_API_KEY |
| `subdomaincenter` | scan | No | Passive subdomain enumeration - confirmed present (replaces `sublist3r` + `subdomains`) |

---

## Name corrections confirmed

- **`sublist3r`** - **ABSENT** from BBOT 2.8.4 module registry (not present in `-l` output). Must NOT be included in `BBOT_STABLE_PASSIVE_MODULES`. PITFALLS §Pitfall 3 confirmed.
- **`crt` vs `crt.sh`** - actual name in BBOT 2.8.4: **`crt`** (not `crt.sh`). `crt.sh` is the external service; the BBOT module is named `crt`.
- **`subdomaincenter` vs `subdomains`** - actual name in BBOT 2.8.4: **`subdomaincenter`**. There is no `subdomains` module. There is also `subdomainradar` (requires API key) as an alternative.

### Additional correction from research doc

- **`otx`** - Confirmed present but the research doc listed it as "confirmed" without noting it **requires an OTX API key** (`Yes` in Needs API Key column). BBOT will skip this module silently if no API key is configured.

---

## Additional passive modules available (not in original 14-module research list)

These were observed in the live output and may be worth adding to the safelist in v2.1:

| Module | API Key | Notes |
|--------|---------|-------|
| `bufferoverrun` | Yes | TLS API passive subdomain lookup |
| `builtwith` | Yes | Affiliate/subdomain passive lookup |
| `c99` | Yes | Passive subdomain lookup |
| `censys_dns` | Yes | Censys passive DNS |
| `crt_db` | No | crt.sh via PostgreSQL (alternative to `crt`) |
| `digitorus` | No | certificatedetails.com passive |
| `dnsbimi` / `dnscaa` / `dnstlsrpt` | No | Passive DNS record lookups |
| `fullhunt` | Yes | fullhunt.io passive |
| `hunterio` | Yes | hunter.io passive (email + subdomain) |
| `leakix` | No | leakix.net passive subdomain |
| `myssl` | No | myssl.com passive subdomain |
| `rapiddns` | No | rapiddns.io passive |
| `shodan_idb` | No | Shodan InternetDB - passive, no API key needed |
| `sitedossier` | No | sitedossier.com passive |
| `subdomainradar` | Yes | Subdomain API passive |
| `virustotal` | Yes | VirusTotal passive subdomain |

Decision on expanding the safelist is deferred to v2.1 per CONTEXT.md §Deferred Ideas.

---

## Final BBOT_STABLE_PASSIVE_MODULES set (frozen for plan 11-04)

```python
BBOT_STABLE_PASSIVE_MODULES: frozenset[str] = frozenset({
    "crt",               # crt.sh certificate transparency - name is "crt" NOT "crt.sh"
    "dnsdumpster",       # dnsdumpster.com passive DNS
    "otx",               # AlienVault OTX - requires OTX_API_KEY credential
    "shodan_dns",        # Shodan passive DNS - requires SHODAN_API_KEY credential
    "wayback",           # archive.org Wayback Machine
    "github_codesearch", # GitHub code search - requires GITHUB_TOKEN credential
    "certspotter",       # Certspotter CT logs
    "hackertarget",      # hackertarget.com API
    "anubisdb",          # jldc.me subdomain database
    "bevigil",           # OSINT from mobile apps - requires BEVIGIL_API_KEY credential
    "chaos",             # ProjectDiscovery Chaos - requires CHAOS_API_KEY credential
    "urlscan",           # urlscan.io
    "securitytrails",    # SecurityTrails - requires SECURITYTRAILS_API_KEY credential
    "subdomaincenter",   # subdomain.center API - replaces CONTEXT.md's "sublist3r"/"subdomains"
    # "sublist3r"        # NOT in BBOT 2.8.4 - EXCLUDED (PITFALLS §Pitfall 3)
    # "crt.sh"           # NOT a valid module name - actual name is "crt"
})
# NOTE: Modules requiring API keys degrade gracefully (BBOT skips them silently if key not set)
# NOTE: BBOT_EXPERIMENTAL_OVERRIDE env var (comma-separated) unions additional modules at startup
# BBOT version pinned: blacklanternsecurity/bbot:stable @ sha256:ae34a24ee3f30eb334466450303dc2df739b5505aa0c248fa0f603b167f0fc69
```

---

## Verification checklist

- [x] `sublist3r` is NOT in the BBOT_STABLE_PASSIVE_MODULES set
- [x] `crt` (not `crt.sh`) is present
- [x] `subdomaincenter` (not `subdomains`) is present
- [x] File contains BBOT image sha256 digest
- [x] All 14 modules from 11-RESEARCH.md §Verified BBOT Module Safelist confirmed or corrected

---

## Raw output archive

Full output of `docker run --rm blacklanternsecurity/bbot:stable -l` (ANSI codes stripped):

```
### MODULES ###
+----------------------+----------+-----------------+--------------------------------+--------------------------------+----------------------+----------------------+
| Module               | Type     | Needs API Key   | Description                    | Flags                          | Consumed Events      | Produced Events      |
+======================+==========+=================+================================+================================+======================+======================+
| ajaxpro              | scan     | No              | Check for potentially          | active, safe, web-thorough     | HTTP_RESPONSE, URL   | FINDING,             |
|                      |          |                 | vulnerable Ajaxpro instances   |                                |                      | VULNERABILITY        |
| aspnet_bin_exposure  | scan     | No              | Check for ASP.NET Security     | active, safe, web-thorough     | URL                  | VULNERABILITY        |
| baddns               | scan     | No              | Check hosts for                | active, baddns, cloud-enum,    | DNS_NAME,            | FINDING,             |
|                      |          |                 | domain/subdomain takeovers     | safe, subdomain-hijack, web-   | DNS_NAME_UNRESOLVED  | VULNERABILITY        |
| badsecrets           | scan     | No              | Library for detecting known or | active, safe, web-basic        | HTTP_RESPONSE        | FINDING, TECHNOLOGY, |
|                      |          |                 | weak secrets                   |                                |                      | VULNERABILITY        |
| anubisdb             | scan     | No              | Query jldc.me's database for   | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
|                      |          |                 | subdomains                     |                                |                      |                      |
| bevigil              | scan     | Yes             | Retrieve OSINT data from       | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME,            |
|                      |          |                 | mobile applications using      |                                |                      | URL_UNVERIFIED       |
|                      |          |                 | BeVigil                        |                                |                      |                      |
| bufferoverrun        | scan     | Yes             | Query BufferOverrun's TLS API  | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| certspotter          | scan     | No              | Query Certspotter's API for    | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| chaos                | scan     | Yes             | Query ProjectDiscovery's Chaos | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| crt                  | scan     | No              | Query crt.sh (certificate      | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
|                      |          |                 | transparency) for subdomains   |                                |                      |                      |
| crt_db               | scan     | No              | Query crt.sh via PostgreSQL    | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| dnsdumpster          | scan     | No              | Query dnsdumpster for          | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| github_codesearch    | scan     | Yes             | Query Github's API for code    | code-enum, passive, safe,      | DNS_NAME             | CODE_REPOSITORY,     |
|                      |          |                 | containing the target domain   | subdomain-enum                 |                      | URL_UNVERIFIED       |
| hackertarget         | scan     | No              | Query the hackertarget.com API | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| leakix               | scan     | No              | Query leakix.net               | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| myssl                | scan     | No              | Query myssl.com's API          | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| otx                  | scan     | Yes             | Query otx.alienvault.com       | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| rapiddns             | scan     | No              | Query rapiddns.io              | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| securitytrails       | scan     | Yes             | Query the SecurityTrails API   | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| shodan_dns           | scan     | Yes             | Query Shodan for subdomains    | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| shodan_idb           | scan     | No              | Query Shodan's InternetDB      | passive, portscan, safe,       | DNS_NAME, IP_ADDRESS | DNS_NAME, FINDING... |
| sitedossier          | scan     | No              | Query sitedossier.com          | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| subdomaincenter      | scan     | No              | Query subdomain.center's API   | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| subdomainradar       | scan     | Yes             | Query the Subdomain API        | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| urlscan              | scan     | No              | Query urlscan.io               | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME, URL_UNVERIFIED |
| virustotal           | scan     | Yes             | Query VirusTotal's API         | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME             |
| wayback              | scan     | No              | Query archive.org's API        | passive, safe, subdomain-enum  | DNS_NAME             | DNS_NAME, URL_UNVERIFIED |
[... internal modules: cloudcheck, dnsresolve, aggregate, excavate, speculate, unarchive ...]
```

(Full tabular output omitted for brevity - contains all scan/internal module rows. Key passive-safe modules shown above.)
