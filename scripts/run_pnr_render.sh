#!/bin/bash
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
#
# Render every GDS that scripts/run_pnr.py produced. Separate from run_pnr.py
# because the render has to run under KLayout's own Python, not the venv's.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUMMARY="$ROOT/docs/pnr/summary.json"

if [ ! -f "$SUMMARY" ]; then
  echo "no $SUMMARY; run 'make pnr' first" >&2
  exit 1
fi

python3 - "$SUMMARY" <<'PY' | while read -r name gds; do
import json, sys
s = json.load(open(sys.argv[1]))
for name, v in s.items():
    if v.get("gds"):
        print(name, v["gds"])
PY
  echo "rendering $name from $gds"
  klayout -b -rm "$ROOT/scripts/render_gds.py" \
    -rd gds="$ROOT/$gds" \
    -rd out="$ROOT/docs/img/layout_$name.png" \
    -rd w=1600 -rd h=1200
done
