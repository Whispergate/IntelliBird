"""Curated security-domain keyword wordlist.

Used by `enrichment.py` to extract topic mentions from event text and emit
`keyword:<term>` tags. Deterministic regex match - matches M1 enrichment
philosophy (no NLP inference per PROJECT.md key decision).

Term canonical form is the dict key (kebab-case). Pattern accepts common
variants. Word-boundary `\b` is added by the consumer.
"""

from __future__ import annotations

# Canonical kebab-case term -> regex (alternates separated by `|`).
KEYWORD_PATTERNS: dict[str, str] = {
    "ddos": r"DDoS|distributed[- ]denial[- ]of[- ]service",
    "supply-chain": r"supply[- ]chain(?: attack| compromise)?",
    "wiper": r"wiper(?: malware| attack)?",
    "cryptominer": r"crypto[- ]?miner|cryptojack(?:er|ing)",
    "infostealer": r"info[- ]?stealer|stealer malware|credential[- ]stealer",
    "rat": r"\bRAT\b|remote[- ]access[- ]trojan",
    "backdoor": r"backdoor",
    "exploit-kit": r"exploit[- ]kit",
    "c2": r"\bC2\b|\bC&C\b|command[- ]and[- ]control",
    "watering-hole": r"watering[- ]hole(?: attack)?",
    "spear-phishing": r"spear[- ]phishing",
    "smishing": r"smishing|SMS phishing",
    "vishing": r"vishing|voice phishing",
    "business-email-compromise": r"business[- ]email[- ]compromise|\bBEC\b(?! certificate)",
    "credential-stuffing": r"credential[- ]stuffing",
    "password-spraying": r"password[- ]spray(?:ing)?",
    "malvertising": r"malvertising|malicious advertis(?:ing|ement)",
    "deepfake": r"deep[- ]?fake",
    "rootkit": r"rootkit",
    "bootkit": r"bootkit",
    "fileless": r"fileless(?: malware| attack)?",
    "lateral-movement": r"lateral movement",
    "privilege-escalation": r"privilege escalation|priv[- ]?esc",
    "data-exfiltration": r"data exfiltration|exfil(?:tration)?",
    "data-breach": r"data breach",
    "double-extortion": r"double[- ]extortion",
    "triple-extortion": r"triple[- ]extortion",
    "rce": r"\bRCE\b|remote code execution",
    "lpe": r"\bLPE\b|local privilege escalation",
    "sqli": r"\bSQLi\b|SQL injection",
    "xss": r"\bXSS\b|cross[- ]site scripting",
    "csrf": r"\bCSRF\b|cross[- ]site request forgery",
    "ssrf": r"\bSSRF\b|server[- ]side request forgery",
    "xxe": r"\bXXE\b|XML external entity",
    "deserialization": r"deserialization(?: vulnerability)?|insecure deserialization",
    "lfi": r"\bLFI\b|local file inclusion",
    "rfi": r"\bRFI\b|remote file inclusion",
    "directory-traversal": r"directory traversal|path traversal",
    "type-confusion": r"type confusion",
    "use-after-free": r"use[- ]after[- ]free|UAF\b",
    "buffer-overflow": r"buffer overflow",
    "heap-overflow": r"heap overflow",
    "race-condition": r"race condition",
    "ttp": r"\bTTPs?\b",
    "ioc": r"\bIoCs?\b|indicators? of compromise",
    "yara": r"\bYARA\b",
    "sigma": r"\bSigma\b(?! Rules)|Sigma rules?",
    "edr-evasion": r"EDR evasion|endpoint detection bypass",
    "av-evasion": r"AV evasion|antivirus evasion",
    "living-off-the-land": r"living[- ]off[- ]the[- ]land|LOLbins?",
    "dll-sideloading": r"DLL sideload(?:ing)?|DLL hijack(?:ing)?",
    "dns-tunneling": r"DNS tunneling",
    "kerberoasting": r"kerberoasting",
    "pass-the-hash": r"pass[- ]the[- ]hash|PtH\b",
    "pass-the-ticket": r"pass[- ]the[- ]ticket|PtT\b",
    "golden-ticket": r"golden ticket",
    "silver-ticket": r"silver ticket",
    "supply-chain-attack-solarwinds-style": r"SUNBURST|SolarWinds compromise",
    "ransomware-as-a-service": r"\bRaaS\b|ransomware[- ]as[- ]a[- ]service",
    "initial-access-broker": r"initial access broker|\bIAB\b(?! interface)",
    "ml-poisoning": r"model poisoning|prompt injection|jailbreak",
}
