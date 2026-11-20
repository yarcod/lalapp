#!/usr/bin/env bash
# Print the footprint of this fork on upstream-path files, modified, added or deleted
# (home-owned paths excluded).
# With --since <rev>, print the upstream commits in <rev>..upstream/main that touch a path
# listed in backend/app/home/SEAMS.md (the upstream files the fork modifies), grouped by path.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! git remote get-url upstream >/dev/null 2>&1; then
  echo "error: git remote 'upstream' is missing; add it with 'git remote add upstream <url>' and fetch it." >&2
  exit 1
fi

if ! git rev-parse --verify --quiet upstream/main >/dev/null; then
  echo "error: 'upstream/main' does not resolve; run 'git fetch upstream' first." >&2
  exit 1
fi

if [ "${1:-}" = "--since" ]; then
  rev="${2:-}"
  if [ -z "$rev" ]; then
    echo "error: --since needs a revision, e.g. '--since <last synced upstream commit>'." >&2
    exit 1
  fi
  if ! git rev-parse --verify --quiet "$rev^{commit}" >/dev/null; then
    echo "error: '$rev' is not a known commit." >&2
    exit 1
  fi
  total=0
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    log=$(git log --oneline "$rev"..upstream/main -- "$path")
    [ -n "$log" ] || continue
    echo "$path"
    echo "$log" | sed 's/^/  /'
    total=$((total + $(echo "$log" | wc -l)))
  done < <(grep -E '^(backend|frontend)/' backend/app/home/SEAMS.md)
  echo "$total upstream commits touch hooked files (a commit touching several paths is counted once per path)"
  exit 0
fi

base=$(git merge-base HEAD upstream/main)

stats=$(git diff --numstat --no-renames --diff-filter=AMD "$base"..HEAD -- . \
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
