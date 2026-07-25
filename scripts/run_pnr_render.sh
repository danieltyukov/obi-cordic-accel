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

python3 - "$SUMMARY" "$ROOT" <<'PY' | while read -r name gds; do
import json, pathlib, sys
s = json.load(open(sys.argv[1]))
root = pathlib.Path(sys.argv[2])
for name, v in s.items():
    if v.get("gds"):
        print(name, v["gds"])
        continue
    # final/ only gets a GDS once all 79 stages finish, but the streamout step's
    # copy appears much earlier and is the same layout.
    run = v.get("run_dir")
    if not run:
        continue
    found = sorted((root / run).glob("*streamout/*.klayout.gds")) or \
            sorted((root / run).glob("*streamout/*.gds"))
    if found:
        print(name, found[0].relative_to(root))
PY
  echo "rendering $name from $gds"
  klayout -b -rm "$ROOT/scripts/render_gds.py" \
    -rd gds="$ROOT/$gds" \
    -rd out="$ROOT/docs/img/layout_$name.png" \
    -rd w=1600 -rd h=1200
done
