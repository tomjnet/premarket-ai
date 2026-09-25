#!/usr/bin/env bash
# Copies the project from the Windows drive into the Linux filesystem and runs `git init`.
# Usage: scripts/wsl/01_move-repo.sh [SRC] [DST]
#   SRC defaults to /mnt/d/github_tomjnet/trader-news-ai
#   DST defaults to ~/src/premarket-ai
# The Windows copy is left untouched; delete it yourself once you've checked the new one.
set -euo pipefail

SRC="${1:-/mnt/d/github_tomjnet/trader-news-ai}"
DST="${2:-$HOME/src/premarket-ai}"

[[ -d "$SRC" ]] || { echo "Source not found: $SRC" >&2; exit 1; }
if [[ -e "$DST" ]]; then
  echo "Destination already exists: $DST (not overwriting)" >&2
  exit 1
fi

mkdir -p "$(dirname "$DST")"
cp -a "$SRC"/. "$DST"/
echo "Copied $SRC -> $DST"

# Files from Windows may carry CRLF or lose the executable bit.
find "$DST" -type f -name '*.sh' -exec sed -i 's/\r$//' {} + -exec chmod +x {} +

cd "$DST"
if [[ ! -d .git ]]; then
  git init -b main
fi

cat <<EOF

Done. Next:
  cd $DST
  git status                     # review what will be committed
  git add -A && git commit -m "Initial plan and setup scripts"
  gh repo create premarket-ai --public --source . --push   # needs the GitHub CLI

Open it in VS Code with:  code $DST   (Remote - WSL)
EOF
