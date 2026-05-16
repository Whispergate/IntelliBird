# Social Listening Sources

Phase 33 / DISINFO-01.  IntelliBird ingests posts from Mastodon, 4chan, and Reddit via the `social_listening` feed type. Twitter/X is documented below as an opt-in path.

---

## Adding a Social Source via the UI

1. Open **Sources** > **Add Source**.
2. Set **Feed Type** to `social_listening`.
3. Fill in the platform-specific fields described below.
4. Save. APScheduler registers a poll job at the configured interval automatically.

---

## Platform: Mastodon

| `source_config` key       | Type            | Default            | Description                                                   |
|---------------------------|-----------------|--------------------|---------------------------------------------------------------|
| `platform`                | string (const)  | —                  | Must be `"mastodon"`.                                         |
| `instance_url`            | string (URL)    | `https://mastodon.social` | Base URL of the Mastodon instance.                   |
| `topic_keywords`          | list[string]    | `[]` (all posts)   | Case-insensitive keyword filter.  Empty = ingest all.         |
| `poll_interval_seconds`   | int             | `300`              | Minimum `60`. Enforced by `register_social_jobs`.             |

**Rate limits:** Mastodon's public timeline API is unauthenticated and has per-instance rate limits (typically 300 req/5 min).  The worker fetches a single page of 40 posts per poll, well within normal limits.

**Example `source_config`:**
```json
{
  "platform": "mastodon",
  "instance_url": "https://infosec.exchange",
  "topic_keywords": ["ransomware", "apt", "vulnerability"],
  "poll_interval_seconds": 300
}
```

---

## Platform: 4chan

| `source_config` key       | Type            | Default | Description                                                           |
|---------------------------|-----------------|---------|-----------------------------------------------------------------------|
| `platform`                | string (const)  | —       | Must be `"4chan"`.                                                    |
| `board`                   | string          | `"g"`   | Board identifier (e.g. `pol`, `g`, `biz`, `int`).                    |
| `topic_keywords`          | list[string]    | `[]`    | Case-insensitive filter applied to decoded OP text.  Empty = all OPs.|
| `poll_interval_seconds`   | int             | `300`   | Minimum `60`.                                                         |

**Rate limits:** 4chan's read API (`a.4cdn.org`) is unauthenticated.  Requests use default httpx timeouts (15 s).  Do not poll faster than 60 s to avoid temporary IP bans.

**HTML decoding:** 4chan posts use HTML entities (`&gt;`, `&amp;`, `&lt;`) throughout OP text.  The worker calls `html.unescape()` on the combined `com` + `sub` fields before persisting.

**Example `source_config`:**
```json
{
  "platform": "4chan",
  "board": "pol",
  "topic_keywords": ["ukraine", "cyberattack", "disinfo"],
  "poll_interval_seconds": 600
}
```

---

## Platform: Reddit

| `source_config` key       | Type            | Default     | Description                                                            |
|---------------------------|-----------------|-------------|------------------------------------------------------------------------|
| `platform`                | string (const)  | —           | Must be `"reddit"`.                                                    |
| `subreddit`               | string          | `"netsec"`  | Subreddit name without `/r/` prefix.                                   |
| `topic_keywords`          | list[string]    | `[]`        | Filtered across title + selftext.  Empty = ingest all.                 |
| `poll_interval_seconds`   | int             | `300`       | Minimum `60`.                                                          |

**User-Agent:** All Reddit requests use `IntelliBird/4.0 (self-hosted threat intelligence platform)`.  Reddit requires a descriptive User-Agent to avoid 429 / 403 responses.

**Rate limits:** Reddit's public JSON API allows roughly 60 requests per minute per IP for unauthenticated clients.  At the default 300 s interval, a single source generates 12 requests per hour — well within limits.

**Example `source_config`:**
```json
{
  "platform": "reddit",
  "subreddit": "netsec",
  "topic_keywords": ["breach", "malware", "zero-day"],
  "poll_interval_seconds": 300
}
```

---

## topic_keywords Filter

The `topic_keywords` list applies **before persistence** (no DB write occurs for non-matching posts). An empty or missing list disables filtering — all posts from the source are ingested.

Keywords are matched case-insensitively against the decoded, plain-text post body.

---

## AI Narrative Classification

Each persisted social event triggers `suggest_for_event.send(event_id, project_id)` automatically (Phase 33 / DISINFO-01).  AI classification runs asynchronously on the `ai` Dramatiq queue and does not block ingest.

---

## Twitter / X Opt-In Path

Twitter/X requires a **paid API Basic tier** ($100 USD/month as of 2025) for programmatic access to the `/2/tweets/search/recent` endpoint.

**To enable Twitter/X ingest:**

1. Sign up at [developer.twitter.com](https://developer.twitter.com) and create a project with a Basic tier app.
2. Copy the Bearer Token from the app settings.
3. Set the environment variable on the API/worker containers:
   ```
   TWITTER_BEARER_TOKEN=<your-token-here>
   ```
4. Implement `_fetch_twitter_posts(src: dict) -> list[dict]` in `backend/app/workers/social_worker.py`:
   ```python
   def _fetch_twitter_posts(src: dict) -> list[dict]:
       import os
       bearer = os.environ["TWITTER_BEARER_TOKEN"]
       src_config = src.get("source_config") or {}
       query = src_config.get("query", "cybersecurity")
       url = "https://api.twitter.com/2/tweets/search/recent"
       response = httpx.get(
           url,
           params={"query": query, "max_results": 25, "tweet.fields": "created_at"},
           headers={"Authorization": f"Bearer {bearer}"},
           timeout=15,
       )
       response.raise_for_status()
       return response.json().get("data", [])
   ```
5. Add `"twitter": _fetch_twitter_posts` to the `_fetch_posts` dispatch in `social_worker.py`.
6. Add `"twitter"` to the `source_config.platform` allowed values in the Add Source UI schema.

**Twitter is not implemented in this release.** No Twitter/X posts will be fetched until the above steps are completed.

---

## Health Statuses

| Status          | Cause                                      |
|-----------------|--------------------------------------------|
| `ok`            | Successful poll with at least 0 posts.     |
| `rate_limited`  | Platform returned HTTP 429.                |
| `network_error` | Connection failure, DNS error, timeout.    |
| `parse_error`   | Unexpected response shape (per-post).      |
