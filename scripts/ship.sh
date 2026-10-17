#!/usr/bin/env bash
# commit only on a green gate: the gate runs first and any failure aborts before git is touched
set -euo pipefail
if [ "$#" -lt 2 ]; then
  echo "usage: scripts/ship.sh '<subject>' '<body line>' [more body lines...] -- <paths...>" >&2
  exit 2
fi
subject="$1"; shift
body=()
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do body+=(-m "$1"); shift; done
[ "${1:-}" = "--" ] && shift
scripts/gate.sh > /dev/null
git add -- "$@"
git commit -q -m "$subject" "${body[@]}"
git push -q origin main
git log --oneline -1
