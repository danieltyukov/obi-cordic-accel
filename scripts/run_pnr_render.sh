#!/bin/bash
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
#
# Render every routed variant that scripts/run_pnr.py produced.
#
# Separate from run_pnr.py because the render has to run under KLayout's own Python,
# not the venv's. `make layout` invokes this, and `make images` calls it when a PnR
# result is present.
#
# Three views per variant:
#   layout_<name>.png         full die, zoom to fit, upper metal hidden
#   layout_<name>_scaled.png  full die at a scale shared across variants, which is
#                             what makes the side-by-side comparison honest
#   layout_<name>_detail.png  a small square crop, the only view in which individual
#                             cells and routing are legible at 130nm
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUMMARY="$ROOT/docs/pnr/summary.json"
IMG="$ROOT/docs/img"

if [ ! -f "$SUMMARY" ]; then
  echo "no $SUMMARY; run 'make pnr' first" >&2
  exit 1
fi

# One scale for every variant, so a reader comparing two images is comparing area
# rather than comparing two different zoom levels.
UM_PER_PX="${UM_PER_PX:-0.55}"
W="${W:-1800}"
H="${H:-1350}"
DETAIL_UM="${DETAIL_UM:-60}"

mkdir -p "$IMG" "$ROOT/build/pnr"
LIST="$ROOT/build/pnr/render_list.txt"

# name<TAB>gds<TAB>die_area_um2, one line per variant.
python3 - "$SUMMARY" "$ROOT" > "$LIST" <<'PY'
import json, pathlib, sys
s = json.load(open(sys.argv[1]))
root = pathlib.Path(sys.argv[2])
for name, v in s.items():
    gds = v.get("gds")
    if not gds:
        # final/ only gets a GDS once all 79 stages finish; the streamout step's copy
        # appears much earlier and is the same layout.
        run = v.get("run_dir")
        if not run:
            continue
        found = (sorted((root / run).glob("*streamout/*.klayout.gds")) or
                 sorted((root / run).glob("*streamout/*.gds")))
        if not found:
            continue
        gds = str(found[0].relative_to(root))
    print(f"{name}\t{gds}\t{v.get('design__die__area') or 0}")
PY

echo "shared scale: $UM_PER_PX um/px, frame ${W}x${H} px"

while IFS=$'\t' read -r name gds die; do
  [ -n "${name:-}" ] || continue
  echo "== $name  (die ${die} um^2)  from $gds"

  # Full die, zoom to fit, upper metal hidden for legibility.
  klayout -b -rm "$ROOT/scripts/render_gds.py" \
    -rd gds="$ROOT/$gds" -rd out="$IMG/layout_$name.png" \
    -rd w="$W" -rd h="$H" -rd top_metal_off=1

  # Full die at the shared scale, so the larger design visibly fills more frame.
  klayout -b -rm "$ROOT/scripts/render_gds.py" \
    -rd gds="$ROOT/$gds" -rd out="$IMG/layout_${name}_scaled.png" \
    -rd w="$W" -rd h="$H" -rd um_per_px="$UM_PER_PX" -rd top_metal_off=1

  # Detail crop from inside the die, offset from the centre so it does not land on
  # the central power strap.
  box=$(python3 - "$die" "$DETAIL_UM" <<'PY'
import math, sys
die = float(sys.argv[1]) or 1.0
side = math.sqrt(die)
d = float(sys.argv[2])
c = side * 0.42
print(f"{c - d / 2:.2f},{c - d / 2:.2f},{c + d / 2:.2f},{c + d / 2:.2f}")
PY
)
  klayout -b -rm "$ROOT/scripts/render_gds.py" \
    -rd gds="$ROOT/$gds" -rd out="$IMG/layout_${name}_detail.png" \
    -rd w=1400 -rd h=1400 -rd box="$box"
done < "$LIST"

echo "rendered $(wc -l < "$LIST") variant(s) into docs/img"
