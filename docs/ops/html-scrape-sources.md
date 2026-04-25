# HTML scrape sources

Quick task 260425-ovt — turn any server-rendered webpage into an IntelliBird
source by specifying CSS selectors.

## When to use this

Many high-value threat-intel sites (vendor research blogs, advisories) do not
publish RSS or TAXII. The `custom` feed type lets an admin create a source from
a regular HTML page — the worker fetches it on the normal poll schedule, runs
the CSS selectors you defined, and emits one event per matched item through
the same ingest pipeline as RSS/TAXII/NVD.

## How it works

- The worker (`app.workers.html_scrape.poll_html_scrape`) does an HTTP GET via
  `httpx` with the configured user agent and a 20s timeout.
- The response body is parsed by `lxml.html` and the `item_selector` is applied
  with `cssselect`. For each matched node the title / link / date / summary
  selectors run in turn.
- Relative `href` values are resolved against the source URL via
  `urllib.parse.urljoin`.
- Items are written via `_persist_event` with `stix_type="x-intellibird-html-scrape"`
  and a `content_hash = sha256(source_id || link || title)` — identical to the
  RSS hasher, so re-polling the same page dedups via the existing UNIQUE
  `(source_id, content_hash, observed_at)` index.

**No JavaScript execution.** Pages whose items are rendered client-side (React,
Vue, infinite-scroll feeds) yield zero entries. There is no headless-browser
sidecar in v1.

## Selector syntax

| Form              | Behaviour                                              |
| ----------------- | ------------------------------------------------------ |
| `h2 a`            | element text — `.text_content().strip()`               |
| `h2 a@href`       | attribute extraction — `element.get("href")`           |
| `time@datetime`   | `<time datetime="2026-04-25T10:00:00Z">` → ISO string  |

A trailing `@attr` is the only extension over plain CSS. Everything before the
`@` is fed straight to `cssselect`, so descendant combinators, classes, IDs,
and `nth-child` selectors are all supported.

## Example: research.checkpoint.com

```json
{
  "item_selector": "article.post",
  "title_selector": "h2 a",
  "link_selector": "h2 a@href",
  "date_selector": "time@datetime",
  "summary_selector": ".excerpt",
  "max_items": 50
}
```

If the live site has restructured its DOM, open it in a browser dev tools
inspector and copy the closest `article` selector that wraps each post card,
then walk the title / link / date selectors relative to that.

## Schema

| Key                | Required | Type     | Default                            | Notes                                    |
| ------------------ | -------- | -------- | ---------------------------------- | ---------------------------------------- |
| `item_selector`    | yes      | string   | —                                  | One node per emitted event.              |
| `title_selector`   | yes      | string   | —                                  | Text or `selector@attr`.                 |
| `link_selector`    | yes      | string   | —                                  | Resolved with `urljoin(base_url, …)`.    |
| `date_selector`    | no       | string   | —                                  | Falls back to `datetime.now(UTC)` if absent or unparseable. |
| `date_format`      | no       | strptime | (auto ISO-8601)                    | Tried before `fromisoformat`.            |
| `summary_selector` | no       | string   | —                                  | Optional description.                    |
| `user_agent`       | no       | string   | `IntelliBird/1.0 (+self-hosted)`   | Override per source.                     |
| `max_items`        | no       | integer  | 50 (hard-cap 200)                  | Server clamps `>200` to 200.             |

## Troubleshooting

- **Test Connection returns 0 items** — the page is JS-rendered, the
  `item_selector` matches nothing, or the site blocks non-browser User-Agents.
  Try `view-source:` in the browser to confirm the markup is in the initial
  HTML response.
- **Test Connection 4xx/5xx** — the upstream rejected the fetch. Some CDNs gate
  by User-Agent; set a custom `user_agent` (e.g. mimic a recent Chrome UA) and
  retry.
- **Events stop landing after a deploy** — the upstream restructured its DOM.
  Update selectors via Edit Source. The next poll picks up the change.
- **Source ingest stats** — `source_ingest_stats` rows record `parse_ok`,
  `parse_error`, `fetch_ok`, `fetch_error` per poll. Drift indicates a broken
  selector vs a network problem.

## Limitations & threat model (v1)

- **No JavaScript rendering.** SPA-only pages won't work; consider running an
  RSS bridge service externally and pointing IntelliBird at that.
- **No `robots.txt` enforcement.** The worker does not consult `robots.txt`.
  Operator responsibility — only point this at sites whose terms allow
  programmatic access.
- **No SSRF guard.** This is an admin-only feature; specifying internal URLs
  causes the worker container to fetch them. If your worker container can reach
  the cloud metadata service or other internal endpoints, treat operator-supplied
  URLs accordingly. Future hardening: an explicit allowlist (host or CIDR).
- **No infinite-scroll / pagination.** Single-page extraction only. Multi-page
  crawling is out of scope.
- **No sitemap.xml ingestion.** A separate plan if requested.

## Future hardening (out of scope for 260425-ovt)

- SSRF allowlist (admin-configured host/CIDR).
- `robots.txt` honour.
- JS rendering via a Playwright sidecar service.
- Sitemap.xml ingestion mode.
