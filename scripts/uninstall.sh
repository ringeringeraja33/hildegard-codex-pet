#!/usr/bin/env bash
set -euo pipefail

CODEX_ROOT="${CODEX_HOME:-$HOME/.codex}"
DEST="$CODEX_ROOT/pets/hildegard"

if [[ -d "$DEST" ]]; then
  rm -rf "$DEST"
  printf 'Removed Hildegard from %s\n' "$DEST"
else
  printf 'Hildegard is not installed at %s\n' "$DEST"
fi

