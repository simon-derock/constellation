# Deploying Constellation

Everything runs on free tiers. Nothing here needs a credit card except the optional paid upgrades named at the end.

| Part | Where | Why |
|---|---|---|
| Web app | Vercel (free) | Static build of `web/`, served from the edge |
| FalkorDB and the API | Render (free web service, one container) | `deploy/Dockerfile` runs FalkorDB 4.22.1 on loopback beside the API; 127 MB resident, the free tier gives 512 MB |
| Graph snapshot | GitHub Releases | `brain.rdb.gz`, verified by SHA-256 before it is loaded |
| Model | Cloudflare Workers AI (free) | `@cf/openai/gpt-oss-20b`; 10,000 neurons a day |
| Keep-warm | GitHub Actions | `.github/workflows/keepwarm.yml` pings `/health` every 10 minutes |

## 1. The API on Render

1. Render dashboard → **New** → **Blueprint** → pick this repository. `render.yaml` defines the service.
2. Fill the secrets Render asks for (the blueprint marks them `sync: false`):

| Variable | Value |
|---|---|
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | A Workers AI token (Workers AI → Read and Run) |
| `GITHUB_TOKEN` | Fine-grained token, **public repositories, read-only**. Without it the live tenant serves the snapshot unchanged |
| `PSEUDONYM_KEY` | The same value that built the snapshot. A different key changes every alias on the next sync |
| `APPROVER_KEY` | Any long random string. Real action execution is off unless it is set |
| `GITHUB_ACTIONS_TOKEN` | Fine-grained token with **Issues: write on this repository only**. Needed only for real execution |

3. Deploy. `/ready` returns 200 once both graphs are loaded, in about ten seconds.

## 2. The web app on Vercel

1. **Add New → Project** → this repository. Set **Root Directory** to `web`; the framework preset is Vite.
2. Environment variable `VITE_API_URL` = the Render service URL, for example `https://constellation-api.onrender.com`.
3. Domain: add `constellation.philipsimonderock.com` in the project, then create the CNAME record Vercel shows.
4. In the Render service, `ALLOWED_ORIGINS` already names that domain; add the `*.vercel.app` preview origin if you want previews to call the API.

## 3. Keeping the free service awake

Repository → Settings → Secrets and variables → Actions → **Variables** → `API_URL` = the Render URL. The workflow runs every ten minutes. One always-on service uses about 744 of the 750 free hours in a month.

## 4. Refreshing the snapshot

```bash
scripts/make-snapshot.sh snapshot-YYYYMMDD --upload   # prints SNAPSHOT_URL and SNAPSHOT_SHA256
```

Update the two values in `render.yaml`, push, and Render redeploys. The live tenant also keeps itself current while the service is up.

## What the model costs

Each answer is a few thousand tokens; the free allowance covers a few dozen answers a day. The demo's preset questions are cached, and the API caps asks per caller and per day, so the allowance cannot be drained by a crowd. Workers Paid ($5 a month) removes the cap if you want it.
