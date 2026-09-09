#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

uvx --from cairosvg cairosvg \
  "$repo_root/docs/images/cover-image.svg" \
  -o "$repo_root/docs/images/cover-image.png" \
  -s 1
