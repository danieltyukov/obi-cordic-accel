#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Render each place-and-routed GDS to docs/img via KLayout.

Run under KLayout's own interpreter, which is where `pya` lives:

    klayout -b -rm scripts/render_gds.py -rd gds=... -rd out=... -rd w=... -rd h=...

Called that way for each GDS by scripts/run_pnr_render.sh, which `make layout`
invokes. KLayout's batch mode passes values through -rd rather than argv, so the
names below are read out of the global namespace.
"""

import sys

try:
    import pya
except ImportError:  # pragma: no cover
    sys.stderr.write("run this under klayout -b -rm, not a plain python\n")
    raise SystemExit(1)

gds = globals().get("gds")
out = globals().get("out")
w = int(globals().get("w", 1600))
h = int(globals().get("h", 1200))

if not gds or not out:
    sys.stderr.write("need -rd gds=<file> -rd out=<png>\n")
    raise SystemExit(1)

lv = pya.LayoutView()
lv.load_layout(gds, 0)
lv.max_hier()
lv.zoom_fit()
lv.save_image(out, w, h)
sys.stderr.write(f"wrote {out} ({w}x{h}) from {gds}\n")
