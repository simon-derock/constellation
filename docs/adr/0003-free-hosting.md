# ADR-0003 — Free, no-card hosting with self-hosted FalkorDB

- **Status:** accepted · 2026-10-17 (limits checked that day)
- **Decision:** Vercel Hobby serves the static web app and rewrites `/api` and `/mcp` to one Render free web service running FalkorDB beside the API. Graph snapshots live in GitHub Releases; memory writes are journalled to Cloudflare D1 before acknowledgement. A Cloudflare Worker cron (5 min) and GitHub Actions (10 min) keep the API warm.
- **Constraints accepted:** 512 MB RAM and 0.1 CPU; sleep after 15 idle minutes; restart at any time; no persistent disk; bandwidth cap. Hence: snapshot + journal recovery, JSON-only API, media from CDNs, and Redwood (512k documents) published as recorded runs with local replay rather than hosted live.
- **Rejected:** FalkorDB Cloud free (100 MB, deleted after 7 idle days, no backups); Hugging Face Gradio/Docker Spaces (paid to create); ZeroGPU (5 GPU-minutes a day); Koyeb, Fly.io, Railway, hyperscaler trials (card or expiring credit); Coolify (manages a server, does not supply one).
- **Revisit when:** a free tier with ≥ 4 GB RAM and no card appears, or the demo outgrows 512 MB.
