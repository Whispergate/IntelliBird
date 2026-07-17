"""External provider modules — ENRICH-02.

Each sub-module exports:
  enrich(client, redis, api_key, ioc_type, normalized_value,
         project_scope, daily_cap, force_refresh) -> dict | None

Provider modules: virustotal, abuseipdb, greynoise, otx, shodan, urlhaus
"""
