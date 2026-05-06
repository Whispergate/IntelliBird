# IntelliBird Lookup — Browser Extension

Right-click any selected text on any webpage to pivot instantly to IntelliBird IOC search.

## Quick Install

### Chrome / Edge
1. Open `chrome://extensions` (Chrome) or `edge://extensions` (Edge)
2. Enable **Developer mode** (toggle, top right)
3. Click **Load unpacked** -> select the `browser-extension/` directory

### Firefox
1. Open `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on...** -> select `browser-extension/background.js`
   - Note: Temporary add-ons are removed on Firefox restart. For persistent install,
     use Firefox Developer Edition with `xpinstall.signatures.required = false`
     in about:config, then install the `.zip` as a permanent unsigned add-on.

## Configuration
After loading, right-click the IntelliBird icon in the browser toolbar -> **Options**.
Enter your IntelliBird base URL (e.g. `https://intellibird.internal` or `http://localhost:3000`).

## Usage
Select any text on any page -> right-click -> **Search IntelliBird: "..."** -> a new tab opens the IOC search page pre-filtered with your selection.

You must be logged in to IntelliBird in the same browser profile for the search to work without a login redirect.

## Notes
- Selected text is trimmed to 200 characters before search.
- The extension stores only your base URL in `chrome.storage.sync` — no other data is collected or transmitted.
- The `<all_urls>` host permission is required so the extension can open tabs to any configured IntelliBird origin, including `http://localhost` for local development.
- The `browser-polyfill.min.js` file is webextension-polyfill 0.12.0 from https://cdn.jsdelivr.net/npm/webextension-polyfill@0.12.0/dist/browser-polyfill.min.js — replace it with the latest release if you see browser API compatibility errors.
