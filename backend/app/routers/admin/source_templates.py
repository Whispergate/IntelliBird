"""Pre-configured source templates — operator picks a template and fills
credentials only. Static list for M1; could move to DB later.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/admin/source-templates", tags=["admin"])


class CredentialField(BaseModel):
    key: str              # field name in the credentials JSON dict
    label: str            # operator-facing label in the form
    type: str             # "password" | "text"
    required: bool = True
    placeholder: str | None = None


class SourceTemplate(BaseModel):
    id: str               # stable identifier
    name: str             # operator-facing display name (pre-fills `name` field)
    feed_type: str        # rss | taxii | nvd
    url: str              # pre-fills `url` field
    description: str      # one-line explainer
    auth_scheme: str | None = None   # basic | bearer | otx-apikey | api-key | null
    credential_fields: list[CredentialField] = []
    poll_interval_sec: int = 3600
    docs_url: str | None = None


TEMPLATES: list[SourceTemplate] = [
    SourceTemplate(
        id="mitre-cti",
        name="MITRE ATT&CK CTI",
        feed_type="taxii",
        url="https://attack-taxii.mitre.org/taxii2/",
        description="Official MITRE ATT&CK STIX 2.1 via TAXII 2.1. No authentication.",
        auth_scheme=None,
        credential_fields=[],
        poll_interval_sec=86400,
        docs_url="https://attack-taxii.mitre.org/",
    ),
    SourceTemplate(
        id="otx-alienvault",
        name="AlienVault OTX (TAXII 1.1)",
        feed_type="taxii",
        url="https://otx.alienvault.com/taxii/discovery",
        description="Open Threat Exchange pulse indicators via TAXII 1.1 XML. Requires OTX API key.",
        auth_scheme="otx-apikey",
        credential_fields=[
            CredentialField(
                key="key",
                label="OTX API Key",
                type="password",
                required=True,
                placeholder="40-char hex token from https://otx.alienvault.com/api",
            ),
        ],
        poll_interval_sec=3600,
        docs_url="https://otx.alienvault.com/api",
    ),
    SourceTemplate(
        id="nvd-cve",
        name="NVD CVE Database",
        feed_type="nvd",
        url="https://services.nvd.nist.gov/rest/json/cves/2.0",
        description="NIST National Vulnerability Database CVE feed. API key optional (boosts rate limit 10x).",
        auth_scheme="api-key",
        credential_fields=[
            CredentialField(
                key="key",
                label="NVD API Key (optional)",
                type="password",
                required=False,
                placeholder="Request at https://nvd.nist.gov/developers/request-an-api-key",
            ),
        ],
        poll_interval_sec=3600,
        docs_url="https://nvd.nist.gov/developers/vulnerabilities",
    ),
    SourceTemplate(
        id="cisa-kev",
        name="CISA Known Exploited Vulnerabilities",
        feed_type="rss",
        url="https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.xml",
        description="CISA KEV catalog — vulnerabilities actively exploited in the wild.",
        auth_scheme=None,
        credential_fields=[],
        poll_interval_sec=21600,
        docs_url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
    ),
    SourceTemplate(
        id="krebs-on-security",
        name="Krebs on Security",
        feed_type="rss",
        url="https://krebsonsecurity.com/feed/",
        description="Investigative security journalism by Brian Krebs.",
        auth_scheme=None,
        credential_fields=[],
        poll_interval_sec=21600,
        docs_url="https://krebsonsecurity.com/",
    ),
    SourceTemplate(
        id="the-hacker-news",
        name="The Hacker News",
        feed_type="rss",
        url="https://feeds.feedburner.com/TheHackersNews",
        description="Daily cybersecurity news covering threats, vulnerabilities, and defense.",
        auth_scheme=None,
        credential_fields=[],
        poll_interval_sec=3600,
        docs_url="https://thehackernews.com/",
    ),
    SourceTemplate(
        id="bleeping-computer",
        name="BleepingComputer",
        feed_type="rss",
        url="https://www.bleepingcomputer.com/feed/",
        description="Ransomware, malware, and breach coverage.",
        auth_scheme=None,
        credential_fields=[],
        poll_interval_sec=3600,
        docs_url="https://www.bleepingcomputer.com/",
    ),
    SourceTemplate(
        id="sans-isc",
        name="SANS Internet Storm Center",
        feed_type="rss",
        url="https://isc.sans.edu/rssfeed_full.xml",
        description="Daily threat intelligence diaries from SANS handlers.",
        auth_scheme=None,
        credential_fields=[],
        poll_interval_sec=21600,
        docs_url="https://isc.sans.edu/",
    ),
    SourceTemplate(
        id="cert-eu",
        name="CERT-EU News",
        feed_type="rss",
        url="https://cert.europa.eu/static/SecurityAdvisories/CERT-EU-SA.xml",
        description="EU institutions CERT security advisories.",
        auth_scheme=None,
        credential_fields=[],
        poll_interval_sec=21600,
        docs_url="https://cert.europa.eu/",
    ),
    SourceTemplate(
        id="us-cert-cisa",
        name="CISA Advisories",
        feed_type="rss",
        url="https://www.cisa.gov/cybersecurity-advisories/all.xml",
        description="US Cybersecurity & Infrastructure Security Agency advisories.",
        auth_scheme=None,
        credential_fields=[],
        poll_interval_sec=21600,
        docs_url="https://www.cisa.gov/news-events/cybersecurity-advisories",
    ),
]


@router.get("", response_model=list[SourceTemplate])
async def list_source_templates() -> list[SourceTemplate]:
    """List pre-configured source templates operators can quick-add."""
    return TEMPLATES
