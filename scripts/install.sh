#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"

command -v uv >/dev/null 2>&1 || {
  echo "uv is required. Install it from https://docs.astral.sh/uv/ and rerun this script." >&2
  exit 1
}

if [[ ! -x "$VENV/bin/python" ]]; then
  uv venv --python 3.12 "$VENV"
fi

uv pip install --python "$VENV/bin/python" --requirement "$ROOT/requirements-lock.txt" --editable "$ROOT"
uv pip check --python "$VENV/bin/python"
echo "Installed bilibili-mcp-agent into $VENV"
