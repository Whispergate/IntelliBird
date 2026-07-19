# AI Providers - Operator Guide

IntelliBird supports three AI provider backends for on-demand event summarisation,
daily project digests, and AI-assisted score re-ranking: **Ollama** (self-hosted
local inference), **OpenAI**, and **Anthropic**. This guide covers setup,
recommended models, key procurement, and the security model.

---

## Overview

AI summarisation is **on-demand and opt-in per project**. Summaries are never
generated automatically on ingest - an analyst triggers summarisation from the
Event Detail Drawer, or the nightly digest job runs for projects with digest
enabled. This keeps token expenditure predictable and prevents queue saturation
during high-volume feed ingest.

Each project stores its own AI provider configuration (provider type, model,
encrypted API key). Project A's credentials are never used in Project B's
requests - credential isolation is enforced at the per-call level.

---

## Activating the AI profile (Ollama)

Ollama runs under the `--profile ai` Compose profile so it does not consume
resources on stacks using only OpenAI or Anthropic.

Start Ollama alongside the rest of the stack:

```bash
docker compose --profile ai up -d
```

Confirm the service is running:

```bash
docker compose ps ollama
```

Expected output: `ollama` service with status `Up (healthy)` after the 60-second
start period (model load time on first pull).

The `ollama_models` named volume persists downloaded models across container
restarts and upgrades - model files survive `docker compose down` and
`docker compose --profile ai up -d` cycles.

---

## GPU passthrough (NVIDIA)

By default the `ollama` service runs in CPU-only mode. To enable GPU inference:

**1. Install nvidia-container-toolkit on the host:**

```bash
# Ubuntu / Debian
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor \
    -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Full instructions: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

**2. Uncomment the GPU deploy block in `ops/docker-compose.yml`:**

Find the `ollama` service block and uncomment the `deploy` section:

```yaml
  ollama:
    image: ollama/ollama:latest
    profiles: ["ai"]
    # ...
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

**3. Restart the Ollama service:**

```bash
docker compose --profile ai up -d ollama
```

**4. Verify GPU access:**

```bash
docker compose exec ollama nvidia-smi
```

Confirm the model is using the GPU:

```bash
docker compose exec ollama ollama list
docker compose exec ollama ollama ps
```

---

## CPU-only deployment

Leave the `deploy.resources` block commented (the default). Ollama automatically
falls back to CPU inference - no configuration change required.

**Recommended CPU-only models:**

| Model | Pull command | RAM required | CPU speed (8-core) | Context window |
|-------|-------------|--------------|-------------------|----------------|
| `phi3:mini` | `ollama pull phi3:mini` | ~2.2 GB | 3–8 tok/s | 4k tokens |
| `gemma2:2b` | `ollama pull gemma2:2b` | ~1.6 GB | 3–8 tok/s | 8k tokens |

Both models are viable on an 8 GB host alongside the rest of the IntelliBird
stack (PostgreSQL + Redis + FastAPI + Next.js). A 1024-token event summary takes
approximately 2 minutes worst case on CPU - the 1-hour Redis chunk buffer allows
the browser tab to refresh and still replay the full summary.

Pull a model:

```bash
docker compose exec ollama ollama pull phi3:mini
```

Verify the model is available:

```bash
docker compose exec ollama ollama list
```

For faster GPU-accelerated inference, `phi3:mini` and `gemma2:2b` also benefit
significantly from even a mid-range NVIDIA GPU (RTX 3060 or better drops
inference to <1s/token).

---

## Configuring a project

Once Ollama is running (or you have an OpenAI/Anthropic key), configure each
project through the web UI:

1. Open **Admin → Projects → {Project} → Settings**
2. Scroll to the **AI Provider** card
3. Select **Provider**: Ollama, OpenAI, or Anthropic
4. Enter **Model**: e.g. `phi3:mini` for Ollama, `gpt-4o` for OpenAI,
   `claude-3-5-sonnet-20241022` for Anthropic
5. For OpenAI/Anthropic: paste the **API Key**
6. Click **Save**
7. Click **Test connection** to verify the provider responds

The project setting takes effect immediately for all subsequent summarisation
requests. Changing the provider mid-project does not affect existing summaries.

---

## OpenAI

**Sign up and create an API key:**

1. Go to https://platform.openai.com
2. Create an account or sign in
3. Navigate to **Settings → API keys**
4. Click **Create new secret key** - copy the key immediately (shown once)
5. Paste into the project AI Provider card → **API Key**

**Recommended model:** `gpt-4o`

OpenAI bills per token. The default 100,000 token/project/day cap protects
against unexpected charges. Adjust the **Daily token cap** in project settings
for incident response scenarios requiring higher throughput.

---

## Anthropic

**Sign up and create an API key:**

1. Go to https://console.anthropic.com
2. Create an account or sign in
3. Navigate to **API Keys** in the left sidebar
4. Click **Create Key** - copy the key immediately (shown once)
5. Paste into the project AI Provider card → **API Key**

**Recommended model:** `claude-3-5-sonnet-20241022`

Anthropic bills per token. The same daily token cap applies - adjust in project
settings as needed.

---

## Security model

**Credential storage:** API keys are encrypted with AES-256-GCM before storage
in the `ai_providers.credentials_enc` column. The encryption key is derived from
the `CREDENTIALS_KEY` environment variable (same mechanism as `sources.credentials_enc`
). Credentials are never stored in plaintext.

**Credential isolation:** Each project has its own `ai_providers` row. Per-call
LLM requests pass `api_key` and `api_base` as parameters - there is no global
`litellm.api_key` state. Project A's key cannot leak into Project B's requests.

**Rekeying:** To rotate the `CREDENTIALS_KEY`, set `REKEY_FROM_SECRET` to the
old key and the new value in `CREDENTIALS_KEY`, then call:

```bash
POST /api/admin/rekey-credentials
```

This sweeps both `sources.credentials_enc` and `ai_providers.credentials_enc`
in a single transaction. The `ai_providers.credentials_key_version` column
tracks which key version encrypted each row.

**Prompt injection mitigation:** Prompt templates are code constants in
`backend/app/services/llm/prompts.py` - there is no admin UI for editing
prompts. Event content is passed as JSON-serialised structured data (never
f-string interpolated into prompts). This limits the prompt injection surface
to the event data pipeline.

**Proxy server isolation:** The LiteLLM proxy server (`litellm.proxy_server`)
is never imported. IntelliBird uses the LiteLLM SDK in call-only mode.

---

## Health probe

FastAPI probes Ollama at startup via HTTP GET to `${OLLAMA_BASE_URL}/api/tags`
with a 10-second timeout.

| Probe result | `app.state.ollama_health` | Frontend banner |
|---|---|---|
| Response ≤5s, HTTP 200 | `healthy` | (none) |
| Response >5s, HTTP 200 | `slow` | "Ollama responding slowly - recommend `phi3:mini` or `gemma2:2b` on CPU-only hosts" |
| Connection refused / timeout | `down` | "Ollama unreachable - start `docker compose --profile ai up` or switch provider" |

The current health state is available via:

```bash
GET /api/admin/ai-health
```

---

## Token budget

Each project has a **daily token cap** (default: 100,000 tokens/project/day,
resets at 00:00 UTC). The cap covers all LLM calls for the project that day -
event summaries, digest generation, and AI re-ranking.

**Pre-flight check:** Before dispatching a request to the LLM, IntelliBird
estimates the input token count. If `current_used + estimated > cap`, the
request is rejected with HTTP 429 before any tokens are consumed.

**At-cap response:**
```json
HTTP 429 Too Many Requests
Retry-After: <seconds until 00:00 UTC>
X-Budget-Reset-At: <ISO-8601 timestamp>

{"detail": "Daily AI budget exhausted - resets at 00:00 UTC"}
```

**Adjusting the cap:** Admin → Projects → {Project} → Settings → AI Provider
→ Daily token cap. Increase for incident response; decrease for cost discipline.

---

## Troubleshooting

**"Ollama unreachable" banner in project settings:**

```bash
docker compose --profile ai ps
# Confirm ollama is Up (healthy)

docker compose --profile ai logs ollama --tail 50
# Look for startup errors or model load failures
```

**"Ollama responding slowly" banner:**

- Switch to `phi3:mini` or `gemma2:2b` in project settings - these are optimised for CPU inference
- Move to a GPU host - even a mid-range GPU dramatically improves throughput
- Check host memory: `free -h` - ensure at least 4 GB RAM free for the model + stack

**429 Too Many Requests (budget exhausted):**

- Wait until 00:00 UTC for the daily counter to reset
- Raise the daily token cap in project settings for the current incident

**Summary never appears (spinner stuck):**

```bash
# Check if the ai queue has stuck jobs
docker compose exec redis redis-cli LLEN "dramatiq:ai.Messages"

# Check ai-worker logs
docker compose logs ai-worker --tail 50
```

If the `dramatiq:ai.Messages` queue is growing but not draining, the `ai-worker`
service may be unhealthy or misconfigured.

---

## Anti-features (not supported by design)

These capabilities are explicitly excluded from M2:

- **Auto-summarise on ingest:** Would saturate the AI queue during high-volume
  feed ingestion and exhaust token budgets silently
- **Admin UI prompt editing:** DB-stored, user-editable prompts widen the prompt
  injection surface (C-3 mitigation - prompts remain code constants)
- **Auto-promote AI suggestions:** Every entity suggestion (CVE, ATT&CK technique,
  threat actor) requires explicit analyst confirmation (C-2 - no auto-promote)
- **Multi-provider failover:** If Ollama is unreachable, the request fails with a
  clear error; operators switch providers manually in project settings
