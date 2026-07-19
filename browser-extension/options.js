// options.js - reads/writes chrome.storage.sync via webextension-polyfill
document.addEventListener("DOMContentLoaded", async () => {
  const input = document.getElementById("url");
  const statusEl = document.getElementById("status");

  // Load saved value
  const { intellibird_base_url: saved } = await browser.storage.sync.get(
    "intellibird_base_url"
  );
  if (saved) input.value = saved;

  document.getElementById("save").addEventListener("click", async () => {
    const raw = input.value.trim();

    // Validate: must be http(s) or empty (clearing the value)
    if (raw && !raw.startsWith("http://") && !raw.startsWith("https://")) {
      statusEl.textContent = "URL must start with http:// or https://";
      statusEl.style.color = "#dc2626";
      return;
    }

    // Normalise: strip trailing slash
    const url = raw.replace(/\/$/, "");

    await browser.storage.sync.set({ intellibird_base_url: url });
    statusEl.textContent = "Saved.";
    statusEl.style.color = "#1D9E75";
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
  });
});
