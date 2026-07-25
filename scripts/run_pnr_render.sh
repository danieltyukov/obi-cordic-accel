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
#
#   layout_<name>.png         whole die, Metal4 and above only. Below that the shape
#                             count runs into the millions and one pixel covers
#                             several wires, so the die renders as a solid block. At
#                             Metal4 and above the power grid and the long-haul
#                             routing are visible and the congestion pattern is real
#                             information.
#   layout_<name>_scaled.png  whole die again, but at a scale shared across variants,
#                             so the larger design occupies more of the frame. This is
#                             the honest side-by-side: zoom-to-fit would blow the
#                             smaller design up to the same size and hide the whole
#                             point of the comparison.
#   layout_<name>_detail.png  a 12 um square with every layer on, which is the only
#                             view where standard cell rows, transistors, contacts and
#                             local routing are individually legible.
#
# The shared scale is derived from whichever die is biggest rather than hard-coded, so
# adding a variant cannot silently crop an existing figure.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUMMARY="$ROOT/docs/pnr/summary.json"
IMG="$ROOT/docs/img"

if [ ! -f "$SUMMARY" ]; then
  echo "no $SUMMARY; run 'make pnr' first" >&2
  exit 1
fi

# The PDK's own layer display properties. Without these KLayout hands out colours in
# load order and Metal1 comes out the same red as everything else.
PDK_ROOT="${IHP_PDK_ROOT:-$HOME/.local/share/pdk/IHP-Open-PDK/ihp-sg13g2}"
LYP="$PDK_ROOT/libs.tech/klayout/tech/sg13g2.lyp"
[ -f "$LYP" ] || { echo "no layer properties at $LYP" >&2; exit 1; }

# Metal4, Via4, Metal5, TopVia1, TopMetal1, TopVia2, TopMetal2.
UPPER="${UPPER:-50,66,67,125,126,133,134}"
W="${W:-1600}"
H="${H:-1600}"
DETAIL_UM="${DETAIL_UM:-12}"
# Offset the detail crop from the die centre so it lands in ordinary logic rather than
# on the central power strap.
DETAIL_AT="${DETAIL_AT:--0.35,-0.35}"

mkdir -p "$IMG" "$ROOT/build/pnr"
LIST="$ROOT/build/pnr/render_list.txt"

# name<TAB>gds, one line per variant.
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
    print(f"{name}\t{gds}")
PY

render() {
  klayout -b -rm "$ROOT/scripts/render_gds.py" -rd lyp="$LYP" "$@"
}

# Pass one: whole die per variant, and record the die size KLayout reports so the
# shared scale can be set from the largest.
: > "$ROOT/build/pnr/die_sizes.txt"
while IFS=$'\t' read -r name gds; do
  [ -n "${name:-}" ] || continue
  echo "== $name: whole die, upper metal, from $gds"
  size=$(render -rd gds="$ROOT/$gds" -rd out="$IMG/layout_$name.png" \
           -rd w="$W" -rd h="$H" -rd only_layers="$UPPER" 2>&1 \
         | sed -n 's/.*extent \([0-9.]*\) x .*/\1/p')
  echo -e "$name\t$size" >> "$ROOT/build/pnr/die_sizes.txt"
  echo "   ${size} um across at its widest"
done < "$LIST"

# 1.04 leaves a thin margin so the largest die is not flush against the frame edge.
UM_PER_PX=$(awk -F'\t' -v w="$W" \
  'BEGIN{m=0} {if ($2+0 > m) m=$2+0} END{printf "%.4f", m * 1.04 / w}' \
  "$ROOT/build/pnr/die_sizes.txt")
echo "shared scale: $UM_PER_PX um/px over a ${W}x${H} frame"

# Pass two: the shared-scale view and the detail crop.
while IFS=$'\t' read -r name gds; do
  [ -n "${name:-}" ] || continue
  echo "== $name: shared scale and detail crop"
  render -rd gds="$ROOT/$gds" -rd out="$IMG/layout_${name}_scaled.png" \
    -rd w="$W" -rd h="$H" -rd only_layers="$UPPER" -rd um_per_px="$UM_PER_PX"
  render -rd gds="$ROOT/$gds" -rd out="$IMG/layout_${name}_detail.png" \
    -rd w=1300 -rd h=1300 -rd crop_um="$DETAIL_UM" -rd crop_at="$DETAIL_AT"
done < "$LIST"

echo "rendered $(wc -l < "$LIST") variant(s) into docs/img at $UM_PER_PX um/px"
