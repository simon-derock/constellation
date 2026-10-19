# Deploying Constellation

Everything runs on free tiers. Nothing here needs a credit card except the optional paid upgrades named at the end.

| Part | Where | Why |
|---|---|---|
| Web app | Vercel (free) | Static build of `web/`, served from the edge |
| FalkorDB and the API | Render (free web service, one container) | `deploy/Dockerfile` runs FalkorDB 4.22.1 on loopback beside the API; 127 MB resident, the free tier gives 512 MB |
| Graph snapshot | GitHub Releases | `brain.rdb.gz`, verified by SHA-256 before it is loaded |
| Model | Any one free key: Groq, Cerebras, Gemini, OpenRouter, Cohere or Workers AI | The first configured key answers Ask; see [Choosing the model](#choosing-the-model) |
| Keep-warm | GitHub Actions | `.github/workflows/keepwarm.yml` pings `/health` every 10 minutes |

## 1. The API on Render

1. Render dashboard → **New** → **Blueprint** → pick this repository. `render.yaml` defines the service.
2. Fill the secrets Render asks for (the blueprint marks them `sync: false`):

| Variable | Value |
|---|---|
| `GROQ_KEY` (or `GROQ_API_KEY`) | A Groq key for Ask; first in the priority order, pins `openai/gpt-oss-120b` |
| `CEREBRAS_API_KEY` | A Cerebras key for Ask; pins `gpt-oss-120b` |
| `GEMINI_API_KEY` | A Google AI Studio key for Ask; pins `gemini-3.5-flash-lite` |
| `OPENROUTER_API_KEY` | An OpenRouter key for Ask; pins `nvidia/nemotron-3-super-120b-a12b:free` |
| `COHERE_CHAT_KEY` | A Cohere trial key for Ask; pins `command-a-03-2025` |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | A Workers AI token (Workers AI → Read and Run); pins `@cf/openai/gpt-oss-20b` |
| `MODEL_PROVIDER` | Optional: `groq`, `cerebras`, `gemini`, `openrouter`, `cohere` or `workers` to use only that provider instead of the first configured key |
| `COHERE_KEY` | A Cohere key for query embeddings in live search; without it search uses the full-text index alone |
| `GITHUB_TOKEN` | Fine-grained token, **public repositories, read-only**. Without it the live tenant serves the snapshot unchanged |
| `PSEUDONYM_KEY` | The same value that built the snapshot. A different key changes every alias on the next sync |
| `APPROVER_KEY` | Any long random string. Real action execution is off unless it is set |
| `GITHUB_ACTIONS_TOKEN` | Fine-grained token with **Issues: write on this repository only**. Needed only for real execution |

Ask needs only one of the six model keys; everything else runs without any.

3. Deploy. `/ready` returns 200 once both graphs are loaded, in about ten seconds.

### Choosing the model

Every provider is called through its OpenAI-compatible chat-completions endpoint with the same messages and tools, and the process opens no other host. Which one answers:

- **Default:** the first configured key in this order, the largest free allowance first and the two trial tiers last: Groq, Cerebras, Gemini, OpenRouter, Cohere, Workers AI.
- **`MODEL_PROVIDER`** (`groq`, `cerebras`, `gemini`, `openrouter`, `cohere` or `workers`) names one provider and uses only it. An unknown name stops the API at startup.
- **`MODEL`** replaces the pinned model id. A model id belongs to one host, so it applies to the provider that would answer first (or the one `MODEL_PROVIDER` names) and no other is tried.
- **Between questions, not within one.** A question runs on one provider and one model from its first call to its last. When it finds that provider unavailable (HTTP 401, 402, 403, 413, 429 or a 5xx that outlasts the retries), it fails as before, the provider rests for ten minutes, and later questions start on the next configured key. With one key, or with `MODEL_PROVIDER` or `MODEL` set, nothing rests.

| Provider | Pinned model | Free allowance, from the providers' documentation on 2026-10-19 (Groq's also from its response headers) |
|---|---|---|
| Groq | `openai/gpt-oss-120b`, reasoning effort `low` | 1,000 requests a day, 8,000 tokens a minute and 200,000 tokens a day |
| Cerebras | `gpt-oss-120b` | 1 million tokens a day, 30,000 input tokens and 5 requests a minute; the page also lists 30 requests a minute, so check your console |
| Gemini | `gemini-3.5-flash-lite` | Set per project in AI Studio and not printed in the docs; users report about 500 requests a day for Flash-Lite and 20 for `gemini-3.8-flash` |
| OpenRouter | `nvidia/nemotron-3-super-120b-a12b:free` | 20 requests a minute and 50 a day on `:free` models until credits are bought |
| Cohere | `command-a-03-2025` | A trial key: 1,000 calls a month |
| Workers AI | `@cf/openai/gpt-oss-20b` | 10,000 neurons a day |

`gemini-2.5-flash` is not the Gemini default because Google now limits it to projects that already used it. One Ask is about four model calls and 3,800 tokens, so when Groq answers first the Ask limits default to 2 a minute and 45 a day, which fits its 8,000 tokens a minute and 200,000 a day. Set `ASKS_PER_MINUTE` and `ASKS_PER_DAY` to change them; any other provider keeps the API defaults of 6 and 150.

## 2. The web app on Vercel

1. **Add New → Project** → this repository. Set **Root Directory** to `web`; the framework preset is Vite. Add no environment variables.
2. `web/vercel.json` does the rest. It rewrites `/api/*` and `/mcp/*` to the Render service, and sends every other path (so `/blog`) to the app. The browser therefore sees one origin, which is also the MCP address shown in the hero.
3. The rewrites name the service `https://constellation-api.onrender.com`. If Render gives yours another address (the name was taken), edit the three `destination` lines in `web/vercel.json`, and the matching host in its `connect-src`.

## 3. The domain: constellation.philipsimonderock.com

The domain's DNS is on Netlify. In Vercel, open the project → **Settings → Domains** → add `constellation.philipsimonderock.com`. Then in Netlify, **Domains → philipsimonderock.com → DNS records → Add new record**:

| Type | Name | Value |
|---|---|---|
| `CNAME` | `constellation` | `cname.vercel-dns.com` (use the exact value Vercel shows if it differs) |

Vercel issues the certificate once the record resolves, usually within minutes. `https://constellation.philipsimonderock.com/blog` then serves the blog, and `https://constellation.philipsimonderock.com/mcp/` is the MCP endpoint.

## 4. Keeping the free service awake

Repository → Settings → Secrets and variables → Actions → **Variables** → `API_URL` = the Render URL. The workflow runs every ten minutes. One always-on service uses about 744 of the 750 free hours in a month.

## 5. Refreshing the snapshot

```bash
scripts/make-snapshot.sh snapshot-YYYYMMDD --upload   # prints SNAPSHOT_URL and SNAPSHOT_SHA256
```

Update the two values in `render.yaml`, push, and Render redeploys. The live tenant also keeps itself current while the service is up.

## What the model costs

Each answer is a few thousand tokens; a free allowance covers a few dozen answers a day, and several keys together cover more. The demo's preset questions are cached, and the API caps asks per caller and per day, so the allowance cannot be drained by a crowd. Workers Paid ($5 a month) removes that provider's cap if you want it.
