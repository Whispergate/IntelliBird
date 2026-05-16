/**
 * EnrichmentProvidersCard test stubs — Phase 23 Wave 0
 * Component does not exist yet; tests are todos until plan 23-06.
 */
import { describe, test } from "vitest";

describe("EnrichmentProvidersCard", () => {
  test.todo("renders 6 provider rows (vt, abuseipdb, greynoise, otx, shodan, urlhaus)");
  test.todo("Switch toggles enabled state and calls upsertEnrichmentProvider");
  test.todo("API key input is masked (type=password by default)");
  test.todo("circuit breaker badge renders 'open until HH:MM UTC' when breaker is open");
  test.todo("Lead+ role gate — Analyst cannot edit (inputs disabled)");
  test.todo("OPSEC warning text visible: 'data leaves perimeter when this provider is enabled'");
});
