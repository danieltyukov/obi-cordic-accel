#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Render a place-and-routed GDS to PNG with KLayout.

Run under KLayout's own interpreter, which is where `pya` lives. KLayout batch mode
passes values through `-rd name=value` and ignores positional argv, so every option
below is read out of the global namespace:

    klayout -b -rm scripts/render_gds.py \\
      -rd gds=path/to.gds -rd out=docs/img/x.png \\
      -rd w=2000 -rd h=1500 \\
      [-rd um_per_px=0.35] [-rd box=x1,y1,x2,y2] [-rd top_metal_off=1]

`um_per_px` is what makes a side-by-side comparison honest: at a fixed scale the
larger design simply occupies more of the frame, so two renders are directly
comparable. Zoom-to-fit, the default, flatters the smaller design by blowing it up to
the same frame.

`box` crops to a region in micrometres. A full-die render of a routed 130nm design is
dense enough to read as noise, because every metal layer overlaps at that scale, so
the detail crop is not decoration: it is the only view in which individual cells and
routing are legible.

`top_metal_off` hides the upper metal and via layers, which is what turns the full-die
view from a solid blur into something where the power grid and cell rows show through.

scripts/run_pnr_render.sh drives this for each variant.
"""

import sys

try:
    import pya
except ImportError:  # pragma: no cover
    sys.stderr.write("run this under 'klayout -b -rm', not a plain python\n")
    raise SystemExit(1)

G = globals()
gds = G.get("gds")
out = G.get("out")
w = int(G.get("w", 1600))
h = int(G.get("h", 1200))
um_per_px = float(G.get("um_per_px", 0)) or None
box = G.get("box")
top_metal_off = str(G.get("top_metal_off", "0")) not in ("0", "", "false", "False")

if not gds or not out:
    sys.stderr.write("need -rd gds=<file> -rd out=<png>\n")
    raise SystemExit(1)

lv = pya.LayoutView()
lv.load_layout(gds, 0)
lv.max_hier()

# Layer names in the sg13g2 GDS are numeric, so layers are picked by number. Metal5
# and above, plus their vias, sit at layer 8 and up in this stack; hiding them
# uncovers the cell rows and the power grid underneath.
if top_metal_off:
    hidden = 0
    it = lv.begin_layers()
    while not it.at_end():
        lp = it.current()
        if lp.source_layer >= 8:
            lp2 = lp.dup()
            lp2.visible = False
            lv.set_layer_properties(it, lp2)
            hidden += 1
        it.next()
    sys.stderr.write(f"hid {hidden} upper metal layer entries\n")

lv.zoom_fit()
die = lv.box()

if box:
    x1, y1, x2, y2 = (float(v) for v in str(box).split(","))
    lv.zoom_box(pya.DBox(x1, y1, x2, y2))
    sys.stderr.write(f"cropped to ({x1}, {y1}) - ({x2}, {y2}) um\n")
elif um_per_px:
    # Centre the die and fix the scale, so two renders share one scale.
    c = die.center()
    half_w = w * um_per_px / 2.0
    half_h = h * um_per_px / 2.0
    lv.zoom_box(pya.DBox(c.x - half_w, c.y - half_h, c.x + half_w, c.y + half_h))
    sys.stderr.write(f"fixed scale {um_per_px} um/px, "
                     f"frame {2 * half_w:.1f} x {2 * half_h:.1f} um\n")

lv.save_image(out, w, h)
sys.stderr.write(f"wrote {out} ({w}x{h}) from {gds}; "
                 f"die {die.width():.1f} x {die.height():.1f} um\n")
