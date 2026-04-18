"""Article enrichment — regex-based extraction of explicit identifiers
from event title + description prose.

Extracts:
  - CVE IDs (CVE-YYYY-NNNN+)     → tags `cve-YYYY-NNNN`
  - ATT&CK technique IDs (T\\d+)  → attack_technique_tags rows
  - IPv4 / IPv6 addresses         → tags + geo (if lat/lon still NULL)
  - Domain names                   → tags (lowercase)
  - SHA256 / SHA1 / MD5 hashes     → tags
  - BTC / ETH addresses            → tags
  - Email addresses                → tags
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


# Regex patterns — compiled once.
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
_CVSS_PATTERN = re.compile(r"\bCVSS(?:\s*v?3?(?:\.\d+)?)?[^\d]*(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_CRITICAL_PATTERN = re.compile(r"\bcritical\b", re.IGNORECASE)
_HIGH_SEVERITY_PATTERN = re.compile(r"\b(high[- ]severity|severely)\b", re.IGNORECASE)
_ZERO_DAY_PATTERN = re.compile(r"\b(zero[- ]day|0-?day)\b", re.IGNORECASE)
_RANSOMWARE_PATTERN = re.compile(r"\bransomware\b", re.IGNORECASE)
_PHISHING_PATTERN = re.compile(r"\bphishing\b", re.IGNORECASE)
_APT_PATTERN = re.compile(r"\b(APT\d{1,3}|Lazarus|FIN\d{1,2}|Turla|Conti|LockBit|BlackCat|Scattered Spider)\b")

# Minimal country mentions (operator-visible set; expand as needed)
_COUNTRY_HINTS: dict[str, str] = {
    r"\bUnited States\b|\bU\.S\.\b|\bUSA\b": "US",
    r"\bRussia\b|\bRussian\b": "RU",
    r"\bChina\b|\bChinese\b": "CN",
    r"\bNorth Korea\b|\bDPRK\b": "KP",
    r"\bIran\b|\bIranian\b": "IR",
    r"\bUkraine\b|\bUkrainian\b": "UA",
    r"\bGermany\b|\bGerman\b": "DE",
    r"\bUnited Kingdom\b|\bBritish\b|\bU\.K\.\b": "GB",
    r"\bFrance\b|\bFrench\b": "FR",
    r"\bJapan\b|\bJapanese\b": "JP",
    r"\bIsrael\b|\bIsraeli\b": "IL",
    r"\bIndia\b|\bIndian\b": "IN",
    r"\bSouth Korea\b|\bROK\b": "KR",
    r"\bBrazil\b|\bBrazilian\b": "BR",
    r"\bAustralia\b|\bAustralian\b": "AU",
    r"\bCanada\b|\bCanadian\b": "CA",
}
_COUNTRY_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), cc) for p, cc in _COUNTRY_HINTS.items()
]


@dataclass
class Enrichment:
    tags: set[str] = field(default_factory=set)
    attack_techniques: set[str] = field(default_factory=set)
    cve_ids: set[str] = field(default_factory=set)
    iocs: dict[str, set[str]] = field(default_factory=dict)
    country_code: str | None = None
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

    # ATT&CK techniques — explicit IDs in body
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

    # BTC / ETH — often ransomware / crypto-theft context
    btc = set(_BTC_PATTERN.findall(text))
    eth = set(_ETH_PATTERN.findall(text))
    e.iocs["btc"].update(btc)
    e.iocs["eth"].update(eth)
    if btc or eth:
        e.tags.add("ioc")

    # Emails — often phishing / contact pivot
    emails = set(_EMAIL_PATTERN.findall(text))
    e.iocs["email"].update(e.lower() for e in emails)

    # Thematic tags from keywords
    if _ZERO_DAY_PATTERN.search(text):
        e.tags.add("exploit")
        e.tags.add("zero-day")
    if _RANSOMWARE_PATTERN.search(text):
        e.tags.add("ransomware")
        e.tags.add("malware")
    if _PHISHING_PATTERN.search(text):
        e.tags.add("phishing")
    if _APT_PATTERN.search(text):
        e.tags.add("apt")
        e.tags.add("actor")

    # Severity auto-tag
    sev = _auto_severity(text)
    if sev:
        e.auto_severity = sev
        e.tags.add(sev)

    # Country code from prose mentions (first match wins)
    for pattern, cc in _COUNTRY_COMPILED:
        if pattern.search(text):
            e.country_code = cc
            break

    return e


def merge_enrichment_into_event_row(
    event_row: dict, enrichment: Enrichment
) -> None:
    """Merge enrichment into a dict representing an events row before INSERT.

    Mutates `event_row` in place. Caller handles attack_technique_tags separately
    (those are a different table — see `attack_technique_tag_rows`).
    """
    # Tags union
    existing_tags = set(event_row.get("tags") or [])
    existing_tags.update(enrichment.tags)
    event_row["tags"] = sorted(existing_tags)

    # Country code fallback (don't override if already populated by STIX/MaxMind)
    if enrichment.country_code and not event_row.get("country_code"):
        event_row["country_code"] = enrichment.country_code


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
