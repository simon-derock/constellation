#!/usr/bin/env bash
# Build brain:apex in a clean, digest-pinned FalkorDB, add the live graph from a running development server
# (LIVE_PORT, default 16379), and save both as one release asset; prints the two values the deployment needs
# (SNAPSHOT_URL and SNAPSHOT_SHA256). Usage: scripts/make-snapshot.sh <tag> [--upload]
set -euo pipefail
tag="${1:?usage: scripts/make-snapshot.sh <tag> [--upload]}"
image="falkordb/falkordb:v4.22.1@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a"
name="constellation-snapshot-$$"
port=16390
work="$(mktemp -d)"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT

docker run -d --name "$name" -p "127.0.0.1:$port:6379" "$image" >/dev/null
until docker exec "$name" redis-cli ping >/dev/null 2>&1; do sleep 1; done

uv run python -m constellation.ingest.build_apex --port "$port"
uv run python -m constellation.deploy.copy_graph brain:falkordb --from-port "${LIVE_PORT:-16379}" --to-port "$port"
docker exec "$name" redis-cli SAVE >/dev/null
docker cp "$name:/var/lib/falkordb/data/dump.rdb" "$work/brain.rdb"
gzip -9 -n "$work/brain.rdb"

sha="$(sha256sum "$work/brain.rdb.gz" | cut -d' ' -f1)"
size="$(du -h "$work/brain.rdb.gz" | cut -f1)"
url="https://github.com/simon-derock/constellation/releases/download/$tag/brain.rdb.gz"
echo "snapshot: $size"
echo "SNAPSHOT_URL=$url"
echo "SNAPSHOT_SHA256=$sha"

if [ "${2:-}" = "--upload" ]; then
  gh release create "$tag" "$work/brain.rdb.gz" \
    --title "Graph snapshot ($tag)" \
    --notes "FalkorDB 4.22.1 RDB of brain:apex (pinned OrgForge data) and brain:falkordb (public GitHub metadata, aliases only), built by scripts/make-snapshot.sh. sha256 $sha"
fi
