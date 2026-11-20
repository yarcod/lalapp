#!/usr/bin/env bash
# Print the footprint of this fork on upstream-owned files (home-owned paths excluded).
set -euo pipefail

cd "$(dirname "$0")/.."

if ! git remote get-url upstream >/dev/null 2>&1; then
  echo "error: git remote 'upstream' is missing; add it with 'git remote add upstream <url>' and fetch it." >&2
  exit 1
fi

base=$(git merge-base HEAD upstream/main)

stats=$(git diff --numstat --diff-filter=M "$base"..HEAD -- . \
  ':(exclude)backend/app/home/' \
  ':(exclude)backend/alembic_home/' \
  ':(exclude)backend/alembic_home.ini' \
  ':(exclude)backend/tests/home/' \
  ':(exclude)frontend/src/home/' \
  ':(exclude)frontend/tests/home/' \
  ':(exclude)messages/home/' \
  ':(exclude)services/speech-gateway/' \
  ':(exclude)docs/superpowers/' \
  ':(exclude)specs/home-deployment.instructions.md' \
  ':(exclude)CLAUDE.md' \
  ':(exclude)scripts/home-surface.sh')

[ -n "$stats" ] && echo "$stats"
echo "$stats" | awk -F'\t' 'NF {f++; a+=$1; d+=$2} END {printf "%d upstream files, +%d -%d lines\n", f, a, d}'
