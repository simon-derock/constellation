#!/bin/bash
# FalkorDB listens on loopback only; the API is the sole public surface. If either process exits, the container
# exits and the platform restarts it from a verified snapshot.
set -eu
DATA=/data
PY=/opt/venv/bin/python

su-exec redis "$PY" -m constellation.deploy.restore --dest "$DATA/dump.rdb"

# no periodic saves and no AOF: a background save forks the process, which a 512 MB host cannot always afford
su-exec redis redis-server \
  --loadmodule /var/lib/falkordb/bin/falkordb.so MAX_QUEUED_QUERIES 25 TIMEOUT_DEFAULT 5000 TIMEOUT_MAX 45000 RESULTSET_SIZE 10000 \
  --bind 127.0.0.1 --protected-mode yes --port 6379 \
  --dir "$DATA" --dbfilename dump.rdb --save "" --appendonly no --maxmemory 256mb &
REDIS_PID=$!

i=0
until redis-cli -h 127.0.0.1 ping >/dev/null 2>&1; do
  i=$((i + 1))
  [ "$i" -gt 60 ] && { echo "FalkorDB did not start" >&2; exit 1; }
  sleep 1
done

su-exec redis "$PY" -m constellation.api.main &
API_PID=$!

trap 'kill "$REDIS_PID" "$API_PID" 2>/dev/null' TERM INT
wait -n "$REDIS_PID" "$API_PID"
EXIT=$?
kill "$REDIS_PID" "$API_PID" 2>/dev/null || true
exit "$EXIT"
