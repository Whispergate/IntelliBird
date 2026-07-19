# IntelliBird Browser Extension - Operator Deployment Guide

The IntelliBird Lookup extension adds a right-click context menu item that opens the IntelliBird IOC search page pre-filtered with any selected text.

## Prerequisites

- IntelliBird instance running and accessible (any origin: `https://intellibird.internal`, `http://localhost:3000`, etc.)
- Operator is logged into IntelliBird in the same browser profile where the extension will be loaded

## Distribution

The extension is distributed as `intellibird-extension.zip` (this directory). It is **not** published to the Chrome Web Store, Firefox AMO, or Microsoft Edge Add-ons store - it is operator-loaded only.

## Installation

### Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode** (toggle in the top-right corner)
3. Either:
   - Click **Load unpacked** and select the extracted `browser-extension/` directory from the repository, OR
   - Drag and drop `intellibird-extension.zip` directly onto the `chrome://extensions` page
4. The "IntelliBird Lookup" extension appears in the list with no errors

### Microsoft Edge

1. Open `edge://extensions`
2. Enable **Developer mode** (left sidebar toggle)
3. Click **Load unpacked** and select the extracted `browser-extension/` directory, OR drag the zip onto the extensions page
4. The "IntelliBird Lookup" extension appears in the list

### Firefox

Firefox requires add-ons to be signed for permanent installation. For operator use, load as a temporary add-on:

1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on...**
3. Navigate to the `browser-extension/` directory and select `manifest.json`

> **Note:** Temporary add-ons are removed when Firefox restarts. For persistent installs:
> - Use **Firefox Developer Edition** or **Firefox Nightly** with `xpinstall.signatures.required = false` set in `about:config`
> - Or deploy via an [Enterprise Policy](https://mozilla.github.io/policy-templates/) (`ExtensionSettings` key)

## Post-Install Configuration

After installing, configure the IntelliBird base URL:

1. Right-click the IntelliBird extension icon in the browser toolbar
2. Select **Options** (Chrome/Edge) or **Manage Extension → Preferences** (Firefox)
3. Enter your IntelliBird base URL - for example:
   - `https://intellibird.internal` (production with Caddy TLS)
   - `http://localhost:3000` (local development)
4. Click **Save**

The URL is stored in `chrome.storage.sync` and persists across browser restarts. If Chrome Sync is enabled, the setting syncs across devices on the same Chrome profile.

## Usage

1. Select any text on any webpage (IP address, domain, hash, URL, actor name, etc.)
2. Right-click the selection
3. Click **Search IntelliBird: "..."**
4. A new tab opens the IntelliBird Global IOC Search page (`/iocs?q=<selection>`)
5. If you are logged in, the page shows matching IOCs immediately. If you see a login prompt, sign in to IntelliBird first.

### Behaviour Notes

- Selected text is trimmed to **200 characters** before searching (prevents oversized URLs)
- If no base URL has been configured, clicking the menu item opens the Options page instead of searching
- The extension does **not** inject authentication tokens - it relies on the existing browser session cookie (`next-auth.session-token`) from your active IntelliBird login

## HTTPS / HTTP Notes

- Chrome and Edge require `https://` origins for all non-localhost URLs in production. If your IntelliBird instance is on HTTP (non-localhost), use Firefox or resolve the HTTPS configuration with Caddy.
- `http://localhost:*` origins work in all three browsers without HTTPS.

## Uninstall

### Chrome / Edge

1. Open `chrome://extensions` (or `edge://extensions`)
2. Find "IntelliBird Lookup"
3. Click **Remove**

### Firefox

1. Open `about:addons`
2. Find "IntelliBird Lookup"
3. Click the three-dot menu and select **Remove**

## Updating the Extension

When a new `intellibird-extension.zip` is distributed:

1. Uninstall the existing extension (see above)
2. Install the new zip using the same steps as initial installation

Chrome preserves `chrome.storage.sync` data across uninstall/reinstall on the same Chrome profile, so your configured base URL is retained.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Context menu doesn't appear | Extension not loaded or service worker error | Check `chrome://extensions` for error badges; reload extension |
| Click opens Options page instead of search | Base URL not configured | Enter URL in Options |
| New tab opens login page | Not logged into IntelliBird | Sign in at `{base_url}/login` |
| "Invalid URL" in Options | URL missing `http://` or `https://` prefix | Ensure URL starts with `http://` or `https://` |
| Firefox context menu disappears after browser restart | Temporary add-on removed on restart | Reload via `about:debugging` or use Developer Edition |
| `<all_urls>` permission warning on Firefox | Expected - broad host permission required for arbitrary IntelliBird origins | Accept the permission; the extension only opens tabs, it does not read page content |
