"""Article enrichment - regex-based extraction of explicit identifiers
from event title + description prose.

Extracts:
 - CVE IDs (CVE-YYYY-NNNN+) → tags `cve-YYYY-NNNN`
 - ATT&CK technique IDs (T\\d+) → attack_technique_tags rows
 - IPv4 / IPv6 addresses → tags + geo (if lat/lon still NULL)
 - Domain names → tags (lowercase)
 - SHA256 / SHA1 / MD5 hashes → tags
 - BTC / ETH addresses → tags
 - Email addresses → tags
 - ISO 3166-1 alpha-2 country mentions (explicit two-letter codes) → country_code
 - Severity markers (CVSS, critical) → tags `high-severity` / `critical`

Explicitly NOT scope for M1 (banned per REQUIREMENTS.md):
 - NLP inference of ATT&CK techniques from TTP prose
 - LLM summarisation
 - Speculative actor / campaign attribution

Extraction is deterministic: if the string literally contains `T1190`, we
tag it. If it contains "spearphishing" without T1566, we DO NOT guess.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Iterable


# Regex patterns - compiled once.
_CVE_PATTERN = re.compile(r"\bCVE-(\d{4})-(\d{4,7})\b", re.IGNORECASE)
_ATTACK_TECHNIQUE_PATTERN = re.compile(r"\b(T\d{4}(?:\.\d{3})?)\b")
_IPV4_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
_IPV6_PATTERN = re.compile(
    r"(?<![:\w])(?:[A-Fa-f0-9]{1,4}:){2,7}[A-Fa-f0-9]{1,4}(?![:\w])"
)
# Domain: strict TLD match, excludes trailing punctuation
_DOMAIN_PATTERN = re.compile(
    r"\b((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[A-Za-z]{2,24})\b"
)
_SHA256_PATTERN = re.compile(r"\b[A-Fa-f0-9]{64}\b")
_SHA1_PATTERN = re.compile(r"\b[A-Fa-f0-9]{40}\b")
_MD5_PATTERN = re.compile(r"\b[A-Fa-f0-9]{32}\b")
_BTC_PATTERN = re.compile(r"\b(?:bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}\b")
_ETH_PATTERN = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b"
)
# DARK-05: Credential pair pattern for dark-web breach dumps.
# Matches "email:hash" or "email:plaintext" patterns. Only the email portion
# (group 1) is stored as an IOC value - the password/hash after ':' is
# intentionally discarded to avoid storing cleartext credentials in the
# primary IOC table. Minimum secret length: 4 non-whitespace chars to reduce
# false positives from URL port numbers (e.g. user@host:80 won't match).
_CRED_PAIR_PATTERN = re.compile(
    r"([\w.+-]+@[\w.-]+\.[a-z]{2,}):([\S]{4,})",
    re.IGNORECASE,
)
_CVSS_PATTERN = re.compile(r"\bCVSS(?:\s*v?3?(?:\.\d+)?)?[^\d]*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_CRITICAL_PATTERN = re.compile(r"\bcritical\b", re.IGNORECASE)
_HIGH_SEVERITY_PATTERN = re.compile(r"\b(high[- ]severity|severely)\b", re.IGNORECASE)
_ZERO_DAY_PATTERN = re.compile(r"\b(zero[- ]day|0-?day)\b", re.IGNORECASE)
_RANSOMWARE_PATTERN = re.compile(r"\bransomware\b", re.IGNORECASE)
_PHISHING_PATTERN = re.compile(r"\bphishing\b", re.IGNORECASE)
_APT_PATTERN = re.compile(r"\b((?:APT|UNC|DEV|FIN|TA|G|CL-STA-)\d{1,4}|Equation|Turla|Lazarus|Conti|LockBit|BlackCat(?:\sSpider)?|Scattered\sSpider|Cobalt\s(?:Group|Gang|Spider)|Charming\sKitten|Phosphorus|Ajax\sSecurity\sTeam|Cutting\sKitten|Ghambar|NewsBeef|Newscaster|Parastoo|Group\s42|Cobalt\sKitty|SilverTerrier|MoustachedBouncer|Cleaver|TG-?2889|Threat\sGroup[-\s]?2889)\b", re.IGNORECASE)
# Offensive-tooling chatter (bare `tooling` + `offensive-tooling` tags drive Red dashboard widget)
_TOOLING_PATTERN = re.compile(
    r"\b("
    # C2 Frameworks (explicit names)
    r"Cobalt\sStrike|Sliver|Havoc|Brute\sRatel|Covenant|Nighthawk|Mythic|Empire|PoshC2|Metasploit|Armitage|Silent\sTrinity|DeimosC2|TrevorC2|Pupy|AdaptixC2|"
    # Post-Exploitation & Credential Tools
    r"Mimikatz|BloodHound|SharpHound|Rubeus|Seatbelt|SharpUp|SharpView|Certify|ForgeCert|Whisker|KrbRelay(?:Up)?|PetitPotam|LaZagne|Responder|Impacket|CrackMapExec|"
    # RATs & Malware Frameworks
    r"AsyncRAT|EtherRAT|QuasarRAT|DarkComet|njRAT|Remcos|AgentTesla|Formbook|LokiBot|NanoCore|NetWire|Orcus|RevengeRAT|XtremeRAT|PlugX|PoisonIvy|Gh0st|"
    # Initial Access & Phishing
    r"Gophish|King\sPhisher|Evilginx2|Modlishka|CredSniper|ReelPhish|PwnAuth|o365-attack-toolkit|"
    # Reconnaissance & Scanning
    r"Nmap|Masscan|Nessus|Burp\sSuite|OWASP\sZAP|Nikto|Gobuster|Feroxbuster|Wfuzz|ffuf|dirsearch|theHarvester|Maltego|Shodan|Censys|Recon-ng|"
    # Password Cracking & Brute Force
    r"Hashcat|John\sThe\sRipper|Hydra|Medusa|Ncrack|Patator|Crowbar|Spray|DomainPasswordSpray|"
    # Tunneling & Pivoting
    r"Chisel|ligolo|sshuttle|ssf|frp|ngrok|pagekite|localtunnel|tunnelmole|zrok|expose|inlets|"
    # Evasion & Injection
    r"ScareCrow|Egejar|SigThief|Veil|Shellter|PEzor|Donut|sRDI|Invoke-Obfuscation|Invoke-CradleCrafter|"
    # Memory Dumping & Analysis
    r"ProcDump|Procdump|comsvc|Minidump|SharpDump|SafetyKatz|PPLDump|PPLKiller|"
    # Living Off The Land (LOTL) binaries commonly abused
    r"PsExec|WMIexec|SMBexec|Atexec|DCOMexec|WMIC|CertUtil|BitsAdmin|MSHTA|Regsvr32|Rundll32|CScript|WScript|PowerShell|Cmd\.exe|"
    # Data Exfiltration
    r"Rclone|Rsync|Steghide|Stegsolve|zsteg|stegseek|exiftool|"
    # Potatoes (privilege escalation)
    r"(?:Juicy|Rogue|Sweet|Lonely|Rotten|Hot|Generic|Fax|God|Bad|Multi|RasMan|EFS|Coerced|Pwn|NoFilter|MockingJay|Sigma)?Potato|"
    # UAC Bypass tools
    r"UACME|Akagi|Fodhelper|Slui|ComputerDefaults|ShellFolder|DiskCleanup|Dccw|WSReset|TikTok|"
    # Token manipulation
    r"Tokenvator|SharpToken|MakeToken|RunAsPPL|"
    # .NET/Assembly tools
    r"donut|sharpsploit|sharpsploit|sharphound|sharprdp|sharpwmi|sharpexec|sharpchrome|sharpdpapi|sharpcloud|sharpchromium|sharpapplocker|sharpbypassuac|sharpblock|sharphide|sharplocker|sharpnopsExec|sharpweb|sharpzerologon|"
    # Network sniffing & MITM
    r"BetterCAP|Ettercap|Bettercap|MITMf|Responder|Inveigh|InveighZero|"
    # AV/EDR Evasion
    r"UnDefender|Backstab|FireWalker|SharpEDRChecker|EDRSandBlast|EDRSandblast|"
    # Payload generators
    r"msfvenom|Veil-Evasion|Venom|TheFatRat|ezuri|avet|AVET|"
    # Exploit frameworks
    r"BeEF|Browser\sExploitation\sFramework|RouterSploit|AutoSploit|"
    # Wireless tools
    r"Aircrack-ng|Wifite|Fern|Reaver|Bully|WPS|Pixie\sDust|"
    # Social engineering
    r"SET|Social\sEngineer\sToolkit|BeEF|"
    # OSINT tools
    r"OSINT\sFramework|Spiderfoot|FOCA|theHarvester|Maltego|Shodan|Censys|"
    # Reverse shells & bind shells
    r"nc|netcat|ncat|socat|pwncat|pwncat-cs|rs|reverse\s?shell|bind\s?shell|"
    # Stagers & loaders
    r"Meterpreter|Stager|Stageless|Reflective\s?DLL|Shellcode|"
    # Additional common tools
    r"proxychains|proxychains-ng|tsocks|redsocks|dnscat2|iodine|dnscrypt|dns2tcp|ozymandns|"
    r")\b",
    re.IGNORECASE,
)
# Vendor advisories - drives Blue dashboard widget
_VENDOR_ADVISORY_PATTERN = re.compile(
    r"\b("
    # Microsoft
    r"Patch\sTuesday|MSRC\s(?:advisory|security\s(?:update|bulletin))|Microsoft\sSecurity\s(?:Response\sCenter|Bulletin|Update)|"
    # CISA & US Government
    r"CISA\s(?:alert|advisory|notice|BOD|ED|KEV)|(?:binding\soperational\sdirective|emergency\sdirective|known\sexploited\svulnerability)|"
    # Standards & identifiers
    r"CVE-\d{4}-\d{4,}|NVD|NIST|CVSS|CPE|CSAF|CVRF|"
    # GitHub & Open Source
    r"GitHub\sSecurity\sAdvisory|GHSA|(?:npm|PyPA|Python|RubyGems|RustSec|Go)\sSecurity|"
    # Major vendors with systematic IDs (regex patterns)
    r"(?:RHSA|FSAS|USN|DSA|MFSA|INTEL-SA|AMD-SB|NVSA|LSA|HPSB|BSA|VMSA|CTX|PAN-SA|FG-IR|PSIRT|SK|JSA|SNWLID|SB|ICSA)-\d{4}(?:-\d+)?|"
    # Explicit vendor advisory names
    r"Cisco\sPSIRT|Adobe\sSecurity\s(?:Bulletin|Update)|Google\sChrome\s(?:update|advisory|security)|VMware\sSecurity\sAdvisory|Oracle\s(?:CPU|Critical\sPatch\sUpdate)|"
    r"Red\sHat\sSecurity\sAdvisory|Fedora\sSecurity\sAdvisory|SUSE\sSecurity|Canonical\sSecurity\sNotice|Debian\sSecurity\sAdvisory|"
    r"Apple\sSecurity\s(?:Update|Content)|macOS\sSecurity|iOS\sSecurity|Apache\sSecurity|OpenSSL\sSecurity\sAdvisory|Mozilla\sFoundation\sSecurity\sAdvisory|"
    r"Kubernetes\sSecurity\sAdvisory|KSA|CNCF\sSecurity|Docker\sSecurity|AWS\sSecurity\sBulletin|Azure\sSecurity\sCenter|Google\sCloud\sSecurity\sBulletin|"
    r"IBM\sSecurity\sBulletin|X-Force\sAdvisory|Intel\sSecurity\sAdvisory|AMD\sSecurity\sBulletin|NVIDIA\sSecurity\sBulletin|SAP\sSecurity\sNote|"
    r"Siemens\sProductCERT|Schneider\sElectric\sSecurity\sAdvisory|Rockwell\sAutomation\sSecurity|GE\sCybersecurity|Johnson\sControls\sSecurity|"
    r"Honeywell\sSecurity\sNotice|ABB\sCyber\sSecurity|Mitsubishi\sElectric\sSecurity|Juniper\sSecurity\sAdvisory|"
    r"Palo\sAlto\sNetworks\sSecurity\sAdvisory|Fortinet\sSecurity\sAdvisory|Check\sPoint\sSecurity|F5\sSecurity\sAdvisory|"
    r"SonicWall\sSecurity|Trend\sMicro\sSecurity|McAfee\sSecurity\sBulletin|Symantec\sSecurity|Kaspersky\sSecurity|"
    r"Rapid7\sSecurity|Tenable\sSecurity|Qualys\sSecurity|Bugcrowd\sVulnerability|HackerOne\sDisclosure|"
    r"CERT\sCC|CERT\/CC|US-CERT|CERT-EU|JPCERT\/CC|ICS-CERT|ICSCERT|"
    # Generic fallback
    r"security\s(?:advisory|bulletin|update|notice|alert)"
    r")\b",
    re.IGNORECASE,
)

# C2 / command-and-control mentions - bare `c2` tag for ActorInfra widget
_C2_PATTERN = re.compile(r"\b(C2|C&C|command[- ]and[- ]control)\b", re.IGNORECASE)

# Country + keyword extraction: expanded to ISO 3166 (~210 countries) and a
# curated security-domain wordlist. See country_data.py + keyword_data.py.
from app.services.country_data import COUNTRY_PATTERNS, COUNTRY_PRIORITY  # noqa: E402
from app.services.keyword_data import KEYWORD_PATTERNS  # noqa: E402

_COUNTRY_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE), cc)
    for cc, pattern in COUNTRY_PATTERNS.items()
]
_KEYWORD_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE), term)
    for term, pattern in KEYWORD_PATTERNS.items()
]
_COUNTRY_PRIORITY_INDEX: dict[str, int] = {
    cc: i for i, cc in enumerate(COUNTRY_PRIORITY)
}


@dataclass
class Enrichment:
    tags: set[str] = field(default_factory=set)
    attack_techniques: set[str] = field(default_factory=set)
    cve_ids: set[str] = field(default_factory=set)
    iocs: dict[str, set[str]] = field(default_factory=dict)
    country_code: str | None = None
    country_codes: set[str] = field(default_factory=set)  # ALL country mentions
    keywords: set[str] = field(default_factory=set)        # curated wordlist hits
    auto_severity: str | None = None  # 'critical' | 'high-severity' | None

    def __post_init__(self) -> None:
        # init IOC buckets
        for kind in ("ip", "domain", "hash", "email", "btc", "eth"):
            self.iocs.setdefault(kind, set())


def _extract_ips(text: str) -> set[str]:
    """Return IPv4 + IPv6 addresses that pass `ipaddress` validation."""
    found: set[str] = set()
    for match in _IPV4_PATTERN.findall(text):
        try:
            ipaddress.ip_address(match)
            # Skip RFC1918 / loopback / reserved as low-value
            ip = ipaddress.ip_address(match)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                continue
            found.add(match)
        except ValueError:
            continue
    for match in _IPV6_PATTERN.findall(text):
        try:
            ipaddress.ip_address(match)
            found.add(match.lower())
        except ValueError:
            continue
    return found


def _extract_hashes(text: str) -> set[str]:
    """Extract SHA256/SHA1/MD5 with overlap-avoidance (sha256 > sha1 > md5)."""
    out: set[str] = set()
    sha256 = set(_SHA256_PATTERN.findall(text))
    out.update(h.lower() for h in sha256)
    # Remove sha256-length strings from remaining text before sha1 scan to avoid overlap
    remaining = text
    for h in sha256:
        remaining = remaining.replace(h, "")
    sha1 = set(_SHA1_PATTERN.findall(remaining))
    out.update(h.lower() for h in sha1)
    for h in sha1:
        remaining = remaining.replace(h, "")
    md5 = set(_MD5_PATTERN.findall(remaining))
    out.update(h.lower() for h in md5)
    return out


def _extract_domains(text: str, ignore_ips: Iterable[str]) -> set[str]:
    """Extract domain names, filter out IP-shaped and common false positives."""
    ip_set = set(ignore_ips)
    out: set[str] = set()
    for match in _DOMAIN_PATTERN.findall(text):
        dom = match.lower()
        if dom in ip_set:
            continue
        # Exclude single-label and numeric-only
        parts = dom.split(".")
        if len(parts) < 2:
            continue
        # Exclude common filename noise (".md", ".tar")
        # DARK-05 note: "onion" is intentionally absent from this set.
        # .onion TLD passes the 2-24 char length check and is extracted as a domain IOC.
        if parts[-1] in {"md", "py", "ts", "tsx", "js", "html", "txt", "log", "tar", "gz", "zip"}:
            continue
        # Exclude leading version-like digits ("1.2.3.foo")
        if all(p.isdigit() for p in parts[:-1]):
            continue
        out.add(dom)
    return out


def _auto_severity(text: str) -> str | None:
    """Return 'critical' / 'high-severity' / None based on explicit text markers."""
    if _CRITICAL_PATTERN.search(text):
        return "critical"
    cvss_match = _CVSS_PATTERN.search(text)
    if cvss_match:
        try:
            score = float(cvss_match.group(1))
            if score >= 9.0:
                return "critical"
            if score >= 7.0:
                return "high-severity"
        except ValueError:
            pass
    if _HIGH_SEVERITY_PATTERN.search(text):
        return "high-severity"
    return None


def enrich_event(title: str | None, description: str | None) -> Enrichment:
    """Parse title + description, return structured enrichment.

 Callers merge the result into event row + attack_technique_tags. Safe to
 call with None / empty strings.
"""
    e = Enrichment()
    parts: list[str] = []
    if title:
        parts.append(title)
    if description:
        parts.append(description)
    if not parts:
        return e
    text = "\n".join(parts)

    # CVEs → cve-YYYY-NNNN tag + cve_ids set
    for year, num in _CVE_PATTERN.findall(text):
        cve_id = f"CVE-{year}-{num}"
        e.cve_ids.add(cve_id)
        e.tags.add(cve_id.lower())
        e.tags.add("vulnerability")

    # ATT&CK techniques - explicit IDs in body
    for tech in _ATTACK_TECHNIQUE_PATTERN.findall(text):
        e.attack_techniques.add(tech)

    # IPs
    ips = _extract_ips(text)
    e.iocs["ip"].update(ips)
    if ips:
        e.tags.add("ioc")

    # Domains
    domains = _extract_domains(text, ips)
    e.iocs["domain"].update(domains)

    # Hashes
    hashes = _extract_hashes(text)
    e.iocs["hash"].update(hashes)
    if hashes:
        e.tags.add("ioc")
        e.tags.add("malware")

    # BTC / ETH - often ransomware / crypto-theft context
    btc = set(_BTC_PATTERN.findall(text))
    eth = set(_ETH_PATTERN.findall(text))
    e.iocs["btc"].update(btc)
    e.iocs["eth"].update(eth)
    if btc or eth:
        e.tags.add("ioc")

    # Emails - often phishing / contact pivot
    emails = set(_EMAIL_PATTERN.findall(text))
    e.iocs["email"].update(e.lower() for e in emails)

    # DARK-05: Credential pair extraction.
    # Email portion only → iocs["email"]. Password/hash → discarded (never stored as IOC).
    cred_pairs = _CRED_PAIR_PATTERN.findall(text)
    if cred_pairs:
        for email_part, _secret in cred_pairs:
            e.iocs["email"].add(email_part.lower())
        e.tags.add("credential-exposure")
        e.tags.add("ioc")

    # Thematic tags from keywords
    if _ZERO_DAY_PATTERN.search(text):
        e.tags.add("exploit")
        e.tags.add("zero-day")
        e.tags.add("0day")
        e.tags.add("0-day")
    if _RANSOMWARE_PATTERN.search(text):
        e.tags.add("ransomware")
        e.tags.add("malware")
    if _PHISHING_PATTERN.search(text):
        e.tags.add("phishing")
    if _APT_PATTERN.search(text):
        e.tags.add("apt")
        e.tags.add("actor")
    if _TOOLING_PATTERN.search(text):
        e.tags.add("tooling")
        e.tags.add("offensive-tooling")
    if _VENDOR_ADVISORY_PATTERN.search(text):
        e.tags.add("vendor-advisory")
        e.tags.add("advisory")
    if _C2_PATTERN.search(text):
        e.tags.add("c2")

    # Severity auto-tag
    sev = _auto_severity(text)
    if sev:
        e.auto_severity = sev
        e.tags.add(sev)

    # Country mentions: collect ALL matches as `country:<CC>` tags + set.
    # `country_code` field keeps a single value for the geo map pin -
    # priority list selects (US > RU > CN > KP > IR > UA ...); unranked
    # countries fall back to alpha-2 lex order so output is deterministic.
    for pattern, cc in _COUNTRY_COMPILED:
        if pattern.search(text):
            e.country_codes.add(cc)
            e.tags.add(f"country:{cc}")
    if e.country_codes:
        e.country_code = min(
            e.country_codes,
            key=lambda c: (_COUNTRY_PRIORITY_INDEX.get(c, 10_000), c),
        )

    # Curated security keywords → `keyword:<term>` tags + set
    for pattern, term in _KEYWORD_COMPILED:
        if pattern.search(text):
            e.keywords.add(term)
            e.tags.add(f"keyword:{term}")

    return e


def merge_enrichment_into_event_row(
    event_row: dict, enrichment: Enrichment
) -> None:
    """Merge enrichment into a dict representing an events row before INSERT.

 Mutates `event_row` in place. Caller handles attack_technique_tags separately
 (those are a different table - see `attack_technique_tag_rows`).
"""
    # Tags union
    existing_tags = set(event_row.get("tags") or [])
    existing_tags.update(enrichment.tags)
    event_row["tags"] = sorted(existing_tags)

    # Country code fallback (don't override if already populated by STIX/MaxMind)
    if enrichment.country_code and not event_row.get("country_code"):
        event_row["country_code"] = enrichment.country_code

    # Geo centroid fallback: when no IP-based geo and no STIX location SDO
    # populated lat/lon, project the country code to its centroid so the
    # event lands on the geo map. Coarse (~10km) but enough for clustering.
    cc = event_row.get("country_code")
    if cc and event_row.get("geo_lat") is None and event_row.get("geo_lon") is None:
        from app.services.country_centroids import country_centroid
        lat, lon = country_centroid(cc)
        if lat is not None:
            event_row["geo_lat"] = lat
            event_row["geo_lon"] = lon


def attack_technique_tag_rows(
    event_id, enrichment: Enrichment, evidence_prefix: str = "description"
) -> list[dict]:
    """Build rows for `attack_technique_tags` insert. Provenance=feed_asserted
 since the technique ID was explicitly present in the feed content.
"""
    return [
        {
            "event_id": event_id,
            "technique_id": tech,
            "tag_source": "feed_asserted",
            "confidence": 0.8,
            "evidence_text": f"{evidence_prefix}: literal match for {tech}",
        }
        for tech in enrichment.attack_techniques
    ]
