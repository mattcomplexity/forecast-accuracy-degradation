#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

uv export \
  --frozen \
  --no-dev \
  --no-hashes \
  --format requirements-txt \
  --output-file requirements.txt
