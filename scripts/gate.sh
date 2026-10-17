#!/usr/bin/env bash
# the one quality chain: identical locally and in CI (PLAN_SPEC §22.4)
set -euo pipefail
uv run ruff check
uv run ruff format --check
uv run mypy src tests
uv run pytest "$@"
uv run vulture
uv run bandit -q -r src
uv run deptry src
