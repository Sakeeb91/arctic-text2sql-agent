#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

if [[ ! -f "constraints.txt" ]]; then
  echo "constraints.txt not found; aborting." >&2
  exit 1
fi

pip install -r requirements.txt -c constraints.txt

