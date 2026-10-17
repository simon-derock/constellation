#!/usr/bin/env bash
# the one quality chain: identical locally and in CI (PLAN_SPEC §22.4)
set -euo pipefail
uv run ruff check
uv run ruff format --check
uv run mypy src tests tools
uv run pytest "$@"
uv run vulture
uv run bandit -q -r src -x src/constellation/_vendor
uv run deptry src
uv run python tools/traceability.py
