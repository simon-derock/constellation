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
# only the checks a change needs: web-only and docs-only commits do not wait for the Python suite
needs_python=false
needs_web=false
for path in "$@"; do
  case "$path" in
    web|web/*) needs_web=true ;;
    docs|docs/*|results/published|results/published/*|*.md) ;;
    *) needs_python=true ;;
  esac
done

run_gate() {
  local log
  log=$(mktemp)
  if ! "$@" > "$log" 2>&1; then
    # a failed gate says why, in full: a silent refusal costs more than the failure
    tail -60 "$log" >&2
    rm -f "$log"
    exit 1
  fi
  rm -f "$log"
}

if $needs_python; then run_gate scripts/gate.sh; fi
if $needs_web; then run_gate scripts/gate-web.sh; fi
git add -- "$@"
git commit -q -m "$subject" "${body[@]}"
git push -q origin main
git log --oneline -1
