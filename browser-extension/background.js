// background.js - IntelliBird Lookup MV3 service worker
// Cross-browser via webextension-polyfill (importScripts - NOT ES module syntax;
// Firefox MV3 does not support "type":"module" for service workers as of 2026).

// importScripts is only available in service worker contexts (not Node.js test env).
// Guard so that `node --test background.test.js` can require this file without error.
if (typeof importScripts === "function") {
  importScripts("browser-polyfill.min.js");
}

const MENU_ID = "intellibird-lookup";

/**
 * Build the full IntelliBird IOC search URL for the given selection and base URL.
 * Exported for unit testing via background.test.js.
 *
 * @param {string} text     - selected text (will be trimmed to 200 chars)
 * @param {string} baseUrl  - operator's IntelliBird origin (trailing slash stripped)
 * @returns {string}        - full URL: {origin}/iocs?q={encodedText}
 */
function buildLookupUrl(text, baseUrl) {
  const trimmed = text.slice(0, 200);
  const origin = baseUrl.replace(/\/$/, "");
  return `${origin}/iocs?q=${encodeURIComponent(trimmed)}`;
}

// Expose for unit testing when loaded as a CommonJS module (background.test.js uses require).
// In the browser service worker context, `module` is not defined, so this branch is skipped.
if (typeof module !== "undefined") {
  module.exports = { buildLookupUrl };
}

// Browser API listeners are only registered in the extension service worker context.
// Guard with typeof browser to allow require() in Node.js test environment.
if (typeof browser !== "undefined") {
  // Register context menu on install/update.
  // Chrome persists context menu registrations across service worker restarts;
  // remove first to prevent "Duplicate key" error on extension update.
  browser.runtime.onInstalled.addListener(() => {
    browser.contextMenus.remove(MENU_ID).catch(() => {});
    browser.contextMenus.create({
      id: MENU_ID,
      // %s is replaced by the browser with the selected text (built-in; cross-browser)
      title: 'Search IntelliBird: "%s"',
      contexts: ["selection"],
    });
  });

  browser.contextMenus.onClicked.addListener(async (info) => {
    if (info.menuItemId !== MENU_ID) return;

    const raw = (info.selectionText ?? "").trim();
    if (!raw) return;

    const { intellibird_base_url: baseUrl } = await browser.storage.sync.get(
      "intellibird_base_url"
    );

    if (!baseUrl) {
      // Operator hasn't configured the URL yet - open options page
      browser.runtime.openOptionsPage();
      return;
    }

    const url = buildLookupUrl(raw, baseUrl);
    browser.tabs.create({ url });
  });
}
