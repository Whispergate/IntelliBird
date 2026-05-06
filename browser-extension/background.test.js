// browser-extension/background.test.js
// Node built-in test runner (Node 18+) — Phase 34 Plan 01 (Wave 0 RED)
//
// Tests for the buildLookupUrl utility exported from background.js.
// These tests are intentionally RED — background.js does not yet export
// buildLookupUrl. They will go Green when Wave 1 (plan 34-02) delivers
// the implementation.
//
// Run: node --test browser-extension/background.test.js

import { describe, it } from "node:test";
import assert from "node:assert/strict";

// RED: background.js does not export buildLookupUrl yet — this import will throw
import { buildLookupUrl } from "./background.js";

describe("buildLookupUrl", () => {
  it("builds correct URL for plain text", () => {
    const url = buildLookupUrl("malware.exe", "https://intellibird.internal");
    assert.equal(url, "https://intellibird.internal/iocs?q=malware.exe");
  });

  it("trims text to 200 chars max", () => {
    const long = "a".repeat(300);
    const url = buildLookupUrl(long, "https://intellibird.internal");
    const q = new URL(url).searchParams.get("q");
    assert.equal(q?.length, 200);
  });

  it("strips trailing slash from base URL", () => {
    const url = buildLookupUrl("test", "https://intellibird.internal/");
    assert.ok(url.startsWith("https://intellibird.internal/iocs"));
    assert.ok(!url.startsWith("https://intellibird.internal//iocs"));
  });

  it("percent-encodes special chars in selection", () => {
    const url = buildLookupUrl("foo bar&baz", "https://intellibird.internal");
    const q = new URL(url).searchParams.get("q");
    // URL.searchParams.get() decodes — verify the decoded value is correct
    assert.equal(q, "foo bar&baz");
    // Also verify raw encoding: space → %20, & → %26 (or + for space)
    assert.ok(url.includes("foo%20bar%26baz") || url.includes("foo+bar"));
  });
});
