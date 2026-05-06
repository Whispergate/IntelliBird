// browser-extension/background.test.js
// Node built-in test runner (Node 18+) — Phase 34 Plan 02 (Wave 1 GREEN)
//
// Tests for the buildLookupUrl utility exported from background.js.
// Uses require() / CJS style to match the module.exports guard in background.js.
// background.js runs as a classic (non-module) service worker in the browser;
// module.exports is only defined in Node.js where `module` is a global.
//
// Run: node --test browser-extension/background.test.js

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { buildLookupUrl } = require("./background.js");

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
