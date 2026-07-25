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
      [-rd lyp=<pdk>/libs.tech/klayout/tech/sg13g2.lyp] \\
      [-rd um_per_px=0.82] [-rd box=x1,y1,x2,y2] [-rd only_layers=50,67,126,134]

`lyp` loads the PDK's own layer display properties, so Metal1 through TopMetal2 get
the colours IHP assigns them. Without it KLayout hands out arbitrary colours in load
order and the plot means nothing.

`um_per_px` fixes the scale, which is what makes a side-by-side comparison honest: the
larger design then simply occupies more of the frame. Zoom-to-fit, the default,
flatters the smaller design by blowing it up to fill the same frame.

`box` crops to an absolute region in micrometres. `crop_um` is usually easier: it
takes a window size and centres it on the die, optionally offset by `crop_at` as a
fraction of the half-die, and works out the coordinates from KLayout's own bounding
box. That matters because the die does not start at the origin and its size is not
exactly the square root of the area metric, so computing the crop outside this script
means guessing at both.

`only_layers` restricts the render to a set of GDS layer numbers. Both of these exist
because a full-die render of a routed 130nm design is genuinely unreadable: the die is
1.5 mm across, Metal1 pitch is under a micron, so at any sane image width one pixel
covers several wires and the result is a solid block of colour. Two things fix it, and
the flow uses both. For the whole die, drop to Metal4 and above, where the power grid
and the long-haul routing live and the shape count is in the tens of thousands rather
than the millions. For structure below that, crop.
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
lyp = G.get("lyp")
only_layers = G.get("only_layers")
crop_um = float(G.get("crop_um", 0)) or None
crop_at = str(G.get("crop_at", "0,0"))

if not gds or not out:
    sys.stderr.write("need -rd gds=<file> -rd out=<png>\n")
    raise SystemExit(1)

lv = pya.LayoutView()
lv.load_layout(gds, 0)
lv.max_hier()

if lyp:
    lv.load_layer_props(lyp)
    sys.stderr.write(f"loaded layer properties from {lyp}\n")

if only_layers:
    keep = {int(v) for v in str(only_layers).split(",") if v.strip()}
    shown = hidden = 0
    it = lv.begin_layers()
    while not it.at_end():
        lp = it.current()
        want = lp.source_layer in keep
        if lp.visible != want:
            lp2 = lp.dup()
            lp2.visible = want
            lv.set_layer_properties(it, lp2)
        shown, hidden = shown + int(want), hidden + int(not want)
        it.next()
    sys.stderr.write(f"showing {shown} layer entries, hiding {hidden}\n")

lv.zoom_fit()
die = lv.box()

if crop_um:
    fx, fy = (float(v) for v in crop_at.split(","))
    c = die.center()
    cx = c.x + fx * die.width() / 2.0
    cy = c.y + fy * die.height() / 2.0
    r = crop_um / 2.0
    lv.zoom_box(pya.DBox(cx - r, cy - r, cx + r, cy + r))
    sys.stderr.write(f"cropped {crop_um} um square at ({cx:.1f}, {cy:.1f}) um, "
                     f"offset ({fx}, {fy}) of the half-die\n")
elif box:
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
