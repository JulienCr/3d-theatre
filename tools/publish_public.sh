#!/usr/bin/env bash
# Publish master and feat/lighting-rig without *.pdf and references/*.jpg.
# Filtering is deterministic: the same input gives the same hashes, so later
# publishes fast-forward. Use --force only for the very first publish.
# Usage: tools/publish_public.sh [--force] [--dry-run] [remote-url]
set -euo pipefail

FORCE=""
DRY_RUN=0
REMOTE="https://github.com/JulienCr/3d-theatre.git"
for arg in "$@"; do
  case "$arg" in
    --force) FORCE="--force" ;;
    --dry-run) DRY_RUN=1 ;;
    *) REMOTE="$arg" ;;
  esac
done

SRC="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --no-local --quiet --branch master "$SRC" "$WORK/repo"
cd "$WORK/repo"
git branch --track feat/lighting-rig origin/feat/lighting-rig 2>/dev/null \
  || git fetch --quiet origin feat/lighting-rig:feat/lighting-rig

git filter-repo --invert-paths --path-glob '*.pdf' --path-glob 'references/*.jpg' \
  --refs refs/heads/master refs/heads/feat/lighting-rig --force

git remote remove origin
git for-each-ref --format='%(refname)' refs/original | xargs -r -n1 git update-ref -d

if git log --all --name-only --format= | grep -Ei '\.pdf$|^references/[^/]*\.jpg$'; then
  echo "error: filtered history still contains PDF or reference JPG files" >&2
  exit 1
fi
git gc --prune=now --quiet
echo "filtered repo: $(du -sh .git | cut -f1)"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "dry run: nothing pushed"
  exit 0
fi

git remote add origin "$REMOTE"
git push $FORCE origin master feat/lighting-rig
