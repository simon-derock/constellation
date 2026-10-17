#!/usr/bin/env bash
# the web checks, identical locally and in CI: types, tests, and a production build that must succeed
set -euo pipefail
cd "$(dirname "$0")/../web"
npm ci --no-audit --no-fund
npm run typecheck
npm test
npm run build
