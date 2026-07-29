#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
DEST="$CODEX_ROOT/pets/hildegard"

mkdir -p "$DEST"
cp "$REPO_DIR/package/pet.json" "$DEST/pet.json"
cp "$REPO_DIR/package/spritesheet.webp" "$DEST/spritesheet.webp"

printf 'Installed Hildegard to %s\n' "$DEST"
printf 'Refresh or restart Codex if the pet does not appear immediately.\n'

