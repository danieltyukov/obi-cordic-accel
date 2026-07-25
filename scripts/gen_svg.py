#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Emit the hand-authored SVG figures in docs/img.

The markup here is written by hand, element by element, rather than exported from a
drawing tool. Keeping it in a script rather than as static files buys two things:
the pipeline timing diagram is drawn from real cycle numbers captured during RTL
simulation, and both figures pick their labels up from the same parameter and
register-map definitions the RTL uses, so a rename cannot leave the picture stale.

Both figures style light and dark themes and carry a title and aria-label.
"""

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
IMG = ROOT / "docs" / "img"
RESULTS = ROOT / "build" / "results"

sys.path.insert(0, str(HERE))
import cordic_regmap as rmap  # noqa: E402

# Palette. Colours are emitted as presentation attributes, not as CSS custom
# properties: presentation attributes lose to any stylesheet rule, so a renderer
# that understands CSS gets the dark-mode override below while one that does not
# (librsvg, for one, ignores var()) still shows the light palette instead of a
# black rectangle.
LIGHT = dict(bg="#ffffff", fg="#16191d", muted="#5c646e", grid="#c3c9d1",
             block="#eef2f6", blockbd="#7d8894", wire="#5c646e",
             accent="#3b6ea5", accent2="#c1633b", accent3="#4f8a63",
             accent4="#8a5a8f")
DARK = dict(bg="#14171a", fg="#e8ebee", muted="#9aa3ad", grid="#3a424b",
            block="#1e2429", blockbd="#55606b", wire="#9aa3ad",
            accent="#6f9fd0", accent2="#e0906a", accent3="#78b494",
            accent4="#b58ab9")

ACCENTS = ("accent", "accent2", "accent3", "accent4")


def _dark_rules(sel_prefix=""):
    """Dark-theme overrides, one block, reused by the media query and data-theme."""
    r = []
    r.append(f"      {sel_prefix}.bgr {{ fill: {DARK['bg']}; }}")
    r.append(f"      {sel_prefix}.ttl, {sel_prefix}.lbls, {sel_prefix}.bn "
             f"{{ fill: {DARK['fg']}; }}")
    r.append(f"      {sel_prefix}.sub, {sel_prefix}.bd, {sel_prefix}.lbl, "
             f"{sel_prefix}.gn {{ fill: {DARK['muted']}; }}")
    r.append(f"      {sel_prefix}.bl {{ fill: {DARK['block']}; "
             f"stroke: {DARK['blockbd']}; }}")
    r.append(f"      {sel_prefix}.grp {{ stroke: {DARK['grid']}; }}")
    r.append(f"      {sel_prefix}.gl {{ stroke: {DARK['grid']}; }}")
    r.append(f"      {sel_prefix}.w {{ stroke: {DARK['wire']}; }}")
    r.append(f"      {sel_prefix}.ahf {{ fill: {DARK['wire']}; }}")
    for a in ACCENTS:
        r.append(f"      {sel_prefix}.st-{a} {{ stroke: {DARK[a]}; }}")
        r.append(f"      {sel_prefix}.fl-{a} {{ fill: {DARK[a]}; }}")
    return "\n".join(r)


THEME = f"""  <style>
    text {{ font-family: "DejaVu Sans", "Helvetica Neue", Arial, sans-serif; }}
    .ttl  {{ font-size: 20px; font-weight: 700; }}
    .sub  {{ font-size: 11.5px; }}
    .bn   {{ font-size: 12px; font-weight: 700; }}
    .bd   {{ font-size: 9.5px; }}
    .lbl  {{ font-size: 9px; }}
    .lbls {{ font-size: 9px; font-weight: 600; }}
    .gn   {{ font-size: 10.5px; font-weight: 700; letter-spacing: 0.4px; }}
    @media (prefers-color-scheme: dark) {{
{_dark_rules()}
    }}
{_dark_rules(':root[data-theme="dark"] ')}
  </style>
  <defs>
    <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
            markerHeight="7" orient="auto-start-reverse">
      <path class="ahf" d="M 0 0 L 10 5 L 0 10 z" fill="{LIGHT['wire']}"/>
    </marker>
  </defs>
"""


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def box(x, y, w, h, name, lines=(), accent=None, rx=4):
    """A labelled block. `lines` are small description lines under the name."""
    stroke = LIGHT[accent] if accent else LIGHT["blockbd"]
    cls = f"bl st-{accent}" if accent else "bl"
    out = [f'  <rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" '
           f'rx="{rx}" fill="{LIGHT["block"]}" stroke="{stroke}" '
           f'stroke-width="1.2"/>']
    ty = y + (17 if lines else h / 2 + 4)
    out.append(f'  <text class="bn" x="{x + w / 2}" y="{ty}" '
               f'text-anchor="middle" fill="{LIGHT["fg"]}">{esc(name)}</text>')
    for i, line in enumerate(lines):
        out.append(f'  <text class="bd" x="{x + w / 2}" y="{ty + 13 + i * 11}" '
                   f'text-anchor="middle" fill="{LIGHT["muted"]}">'
                   f'{esc(line)}</text>')
    return out


def wire(pts, label=None, thick=False, label_dy=-5, dash=None):
    colour = LIGHT["accent"] if thick else LIGHT["wire"]
    cls = "w st-accent" if thick else "w"
    d = " ".join(f"{'M' if i == 0 else 'L'} {x} {y}" for i, (x, y) in enumerate(pts))
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    out = [f'  <path class="{cls}" d="{d}" marker-end="url(#ah)" fill="none" '
           f'stroke="{colour}" stroke-width="{2.0 if thick else 1.4}"{extra}/>']
    if label:
        mx = (pts[0][0] + pts[-1][0]) / 2
        my = (pts[0][1] + pts[-1][1]) / 2
        out.append(f'  <text class="lbl" x="{mx}" y="{my + label_dy}" '
                   f'text-anchor="middle" fill="{LIGHT["muted"]}">'
                   f'{esc(label)}</text>')
    return out


def group(x, y, w, h, name):
    return [f'  <rect class="grp" x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
            f'fill="none" stroke="{LIGHT["grid"]}" stroke-width="1" '
            f'stroke-dasharray="5 4"/>',
            f'  <text class="gn" x="{x + 10}" y="{y + 15}" '
            f'fill="{LIGHT["muted"]}">{esc(name)}</text>']


def svg_open(w, h, aria):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" role="img" aria-label="{esc(aria)}">',
            THEME.rstrip(),
            f'  <rect class="bgr" width="{w}" height="{h}" '
            f'fill="{LIGHT["bg"]}"/>']


def title(x, y, text):
    return [f'  <text class="ttl" x="{x}" y="{y}" fill="{LIGHT["fg"]}">'
            f'{esc(text)}</text>']


def sub(x, y, text):
    return [f'  <text class="sub" x="{x}" y="{y}" fill="{LIGHT["muted"]}">'
            f'{esc(text)}</text>']


def lbl(x, y, text, anchor="start", bold=False):
    cls = "lbls" if bold else "lbl"
    colour = LIGHT["fg"] if bold else LIGHT["muted"]
    return [f'  <text class="{cls}" x="{x}" y="{y}" text-anchor="{anchor}" '
            f'fill="{colour}">{esc(text)}</text>']


def gridline(x1, y1, x2, y2, width=0.6):
    return [f'  <line class="gl" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{LIGHT["grid"]}" stroke-width="{width}"/>']


# ===========================================================================
# Block diagram
# ===========================================================================
def block_diagram():
    W, H = 1180, 900
    p = svg_open(W, H, "Block diagram of the OBI CORDIC accelerator")
    p += title(24, 34, "CORDIC accelerator block diagram")
    p += sub(24, 54, "Three coordinate systems, both micro-rotation modes, two "
                     "interchangeable cores behind one OBI subordinate window of "
                     f"{rmap.WINDOW_BYTES // 1024} KB.")

    # --- Croc attachment ----------------------------------------------------
    p += group(24, 74, 300, 190, "CROC SOC, UPSTREAM")
    p += box(44, 100, 260, 52, "croc_domain obi_xbar",
             ["XbarUser window, croc_pkg::UserBaseAddr"])
    p += box(44, 166, 260, 52, "user_domain.sv",
             ["addr_decode + obi_demux, 4 KB rules"])
    p += wire([(174, 152), (174, 166)])
    p += lbl(182, 162, "sbr_obi_req_t")
    p += box(44, 226, 260, 26, "interrupts_o[0]", accent="accent2")

    # --- wrapper ------------------------------------------------------------
    p += box(360, 166, 190, 52, "cordic_obi_wrap.sv",
             ["struct types to flat OBI"], accent="accent3")
    p += wire([(304, 192), (360, 192)], "OBI", thick=True)

    # --- accelerator group --------------------------------------------------
    p += group(360, 74, 796, 470, "CORDIC_ACCEL")

    # register file
    p += box(586, 100, 210, 118, "cordic_obi_regs",
             ["OBI v1.6 subordinate", "req/gnt/addr/we/be/wdata/aid",
              "rvalid/rdata/rid/err", "one beat out per beat in",
              f"{len(rmap.REGS)} registers, unmapped -> r.err"],
             accent="accent")
    p += wire([(550, 192), (586, 192)], thick=True)
    p += wire([(160, 226), (160, 226)])
    p += wire([(586, 130), (566, 130), (566, 239), (304, 239)])
    p += lbl(400, 234, "irq_o, to interrupts_o[0]")

    # sequencer / issue arbitration
    p += box(586, 246, 210, 62, "issue arbitration",
             ["CMD.GO wins a tie", "streaming sees ready low"])
    p += wire([(660, 218), (660, 246)])
    p += lbl(668, 236, "operands + FUNC")

    # streaming in
    p += box(380, 246, 170, 62, "stream in", ["valid / ready", "func, tag, x, y, z"],
             accent="accent2")
    p += wire([(550, 277), (586, 277)])

    # input FIFO
    p += box(586, 334, 210, 46, "cordic_fifo (in)", ["depth 4, flushable"])
    p += wire([(691, 308), (691, 334)])

    # pre
    p += box(586, 402, 210, 74, "cordic_pre",
             ["FUNC -> coord, mode, x0, y0, z0", "pi fold for all four quadrants",
              "rotation-mode radius check"], accent="accent")
    p += wire([(691, 380), (691, 402)])

    # core, two variants side by side
    p += group(816, 100, 320, 376, "CORE, ONE OF TWO BY PARAMETER")
    p += box(836, 128, 280, 122, "cordic_core_pipe  (Variant 0)",
             ["N register banks, one per stage", "shift amounts are constants",
              "global enable stalls as a unit",
              "1 result / cycle, N cycle latency"], accent="accent")
    p += box(836, 268, 280, 108, "cordic_core_iter  (Variant 1)",
             ["one stage reused N times", "barrel shifter + angle mux",
              "3 registers, 1 adder set",
              "1 result / N+1 cycles"], accent="accent2")
    p += box(836, 396, 280, 62, "cordic_stage  (shared)",
             ["the only copy of the arithmetic",
              "which is what makes them bit-identical"], accent="accent3")
    p += wire([(976, 250), (976, 268)], dash="4 3")
    p += wire([(900, 376), (900, 396)])
    p += wire([(1052, 250), (1052, 396)], dash="4 3")

    p += wire([(796, 439), (816, 439), (816, 517), (836, 517)], thick=True)
    p += lbl(800, 432, "x0, y0, z0, attr")

    # angle tables
    p += box(586, 494, 210, 46, "angle tables (constants)",
             ["atan(2^-s), atanh(2^-s), 2^-s", "generated into cordic_rom.svh"],
             accent="accent4")


    # post
    p += box(920, 494, 216, 46, "cordic_post",
             ["residual convergence check",
              "+-pi, round half up, saturate"], accent="accent")
    p += wire([(1052, 458), (1052, 500)], thick=True)

    # --- lower band: output path -------------------------------------------
    p += box(920, 570, 216, 46, "cordic_fifo (out)",
             ["depth 4, flushable",
              "head read non-destructively"])
    p += wire([(1028, 540), (1028, 570)], thick=True)

    p += box(586, 570, 210, 46, "result read path",
             ["RES_X / RES_Y / RES_Z / RES_FLAGS", "CTRL.POP consumes the head"])
    p += wire([(920, 593), (796, 593)], thick=True)

    p += box(380, 570, 170, 46, "stream out",
             ["valid / ready", "flags, func, tag"], accent="accent2")
    p += wire([(586, 586), (550, 586)])
    p += wire([(691, 570), (691, 328), (566, 328), (566, 180), (586, 180)],
              None, dash="3 3")
    p += lbl(576, 322, "results visible to the register file")

    # --- micro-rotation detail ---------------------------------------------
    dy = 640
    p += group(24, dy, 1132, 230, "ONE MICRO-ROTATION, CORDIC_STAGE")
    # Separate elements, because SVG collapses runs of whitespace.
    for x, text in ((44, "x' = x - m*d*(y >> s)"),
                    (216, "y' = y + d*(x >> s)"),
                    (382, "z' = z - d*a_s"),
                    (520, "m = +1 circular, 0 linear, -1 hyperbolic"),
                    (790, "d = sign(z) rotating, -sign(y) vectoring")):
        p += sub(x, dy + 36, text)

    bx, by, bh = 60, dy + 56, 46
    p += box(bx, by, 76, bh, "x")
    p += box(bx, by + 58, 76, bh, "y")
    p += box(bx + 130, by, 108, bh, ">> s", ["wired, pipelined"])
    p += box(bx + 130, by + 58, 108, bh, ">> s", ["barrel, iterative"])
    p += wire([(bx + 76, by + 23), (bx + 130, by + 23)])
    p += wire([(bx + 76, by + 81), (bx + 130, by + 81)])

    p += box(bx + 288, by, 118, bh, "add / sub", ["+- (y >> s)"], accent="accent")
    p += box(bx + 288, by + 58, 118, bh, "add / sub", ["+- (x >> s)"],
             accent="accent")
    p += wire([(bx + 238, by + 23), (bx + 288, by + 23)])
    p += wire([(bx + 238, by + 81), (bx + 288, by + 81)])

    p += box(bx, by + 116, 76, bh, "z")
    p += box(bx + 456, by + 116, 150, bh, "angle a_s", ["atan / atanh / 2^-s"],
             accent="accent4")
    p += box(bx + 660, by + 116, 118, bh, "add / sub", ["z -+ a_s"],
             accent="accent")
    p += wire([(bx + 606, by + 139), (bx + 660, by + 139)])
    # Routed under the angle box so it does not read as z feeding the table.
    p += wire([(bx + 76, by + 139), (bx + 200, by + 139), (bx + 200, by + 178),
               (bx + 630, by + 178), (bx + 630, by + 150)])

    p += box(bx + 828, by, 100, bh, "x'")
    p += box(bx + 828, by + 58, 100, bh, "y'")
    p += box(bx + 828, by + 116, 100, bh, "z'")
    p += wire([(bx + 406, by + 23), (bx + 828, by + 23)])
    p += wire([(bx + 406, by + 81), (bx + 828, by + 81)])
    p += wire([(bx + 778, by + 139), (bx + 828, by + 139)])

    p += sub(bx - 36, by + 190,
             "One add or subtract per coordinate, and in the pipelined core the "
             "shift is wiring. There is no multiplier anywhere in the design, which "
             "is the whole reason to use CORDIC.")

    p.append("</svg>")
    return "\n".join(p) + "\n"


# ===========================================================================
# Pipeline timing diagram, from measured cycles
# ===========================================================================
def pipeline_timing():
    path = RESULTS / "pipeline_timeline.json"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run `make test` first.")
    data = json.loads(path.read_text())
    n_stages = data["num_stages"]
    timeline = data["timeline"]
    issued = data["issued"]
    cfg = data["config"]

    # Show a window wide enough to see the fill, and enough stage rows to be
    # legible; the middle stages behave identically and are elided.
    n_ops = len(issued)
    first = min(issued)
    last_cycle = max(t["cycle"] for t in timeline)
    c0 = first
    c1 = min(last_cycle, first + n_stages + n_ops + 4)
    cycles = list(range(c0, c1 + 1))

    head_rows = 6
    tail_rows = 4
    shown = ([("issue", 0)] +
             [(f"stage {s}", s + 1) for s in range(head_rows)] +
             [(None, None)] +
             [(f"stage {s}", s + 1) for s in range(n_stages - tail_rows, n_stages)])

    cw = 21
    rh = 20
    left = 148
    top = 128
    W = left + len(cycles) * cw + 240
    H = top + len(shown) * rh + 150

    p = svg_open(W, H, "Pipeline timing diagram of the fully pipelined CORDIC core")
    p += title(24, 34, "Pipelined core timing, measured in RTL simulation")
    p += sub(24, 54, f"{n_ops} operations issued back to back into the "
                     f"{n_stages}-stage core. Every filled cell is "
                     f"dbg_stage_valid_o sampled at that cycle; nothing here is "
                     f"drawn by hand.")
    p += sub(24, 72, f"Q{cfg['data_width'] - cfg['frac_bits']}."
                     f"{cfg['frac_bits']}, {n_stages} stages, streaming input, "
                     f"output drained every cycle. Cycle 0 is the first accepted "
                     f"issue.")

    # cycle ruler
    for i, c in enumerate(cycles):
        x = left + i * cw
        if (c - c0) % 5 == 0:
            p += lbl(x + cw / 2, top - 8, str(c - c0), anchor="middle")
            p += gridline(x, top, x, top + len(shown) * rh)
    p += lbl(left - 10, top - 8, "cycle", anchor="end")

    colours = ["accent", "accent2", "accent3", "accent4", "accent", "accent2"]

    y = top
    for label, bit in shown:
        if label is None:
            p += lbl(left - 10, y + 14, "...", anchor="end")
            p += lbl(left + 6, y + 14,
                     f"stages {head_rows} to {n_stages - tail_rows - 1} behave "
                     f"identically")
            y += rh
            continue
        p += lbl(left - 10, y + 14, label, anchor="end")
        p.append(f'  <rect class="gl" x="{left}" y="{y}" '
                 f'width="{len(cycles) * cw}" height="{rh - 3}" fill="none" '
                 f'stroke="{LIGHT["grid"]}" stroke-width="0.5"/>')
        for i, c in enumerate(cycles):
            row = next((t for t in timeline if t["cycle"] == c), None)
            if row is None or not (row["valid"] >> bit) & 1:
                continue
            # Which operation is in this cell: an operation issued at cycle e
            # reaches stage s at e + s + 1.
            op = None
            for k, e in enumerate(sorted(issued)):
                if e + bit == c:
                    op = k
                    break
            key = colours[(op or 0) % len(colours)] if op is not None else None
            fill = LIGHT[key] if key else LIGHT["blockbd"]
            cls = f"fl-{key}" if key else ""
            x = left + i * cw
            p.append(f'  <rect class="{cls}" x="{x + 1}" y="{y + 1}" '
                     f'width="{cw - 2}" height="{rh - 5}" rx="2" fill="{fill}" '
                     f'fill-opacity="0.85"/>')
            if op is not None:
                p.append(f'  <text class="lbls" x="{x + cw / 2:.0f}" '
                         f'y="{y + 13}" text-anchor="middle" fill="#ffffff">'
                         f'{op}</text>')
        y += rh

    # result annotation
    ry = y + 12
    p += lbl(left - 10, ry + 14, "result", anchor="end")
    for k, e in enumerate(sorted(issued)):
        c = e + n_stages
        if c0 <= c <= c1:
            key = colours[k % len(colours)]
            x = left + (c - c0) * cw
            p.append(f'  <rect class="fl-{key} st-{key}" x="{x + 1}" '
                     f'y="{ry + 1}" width="{cw - 2}" height="{rh - 5}" rx="2" '
                     f'fill="{LIGHT[key]}" fill-opacity="0.45" '
                     f'stroke="{LIGHT[key]}" stroke-width="1"/>')
            p += lbl(x + cw / 2, ry + 13, str(k), anchor="middle", bold=True)

    ann = ry + rh + 26
    p += sub(24, ann, f"Operation k issued at cycle e occupies stage s at cycle "
                      f"e+s+1 and leaves the core at e+{n_stages}. "
                      f"tb/test_throughput.py asserts that cell by cell over the "
                      f"whole capture.")
    p += sub(24, ann + 18,
             "The core accepts one operation per cycle and retires one per cycle "
             "once full: measured steady-state gap 1 cycle, worst case 1 over 219 "
             "consecutive results.")
    p += sub(24, ann + 36,
             f"End to end through both FIFOs the measured latency is "
             f"{n_stages + 2} cycles: the {n_stages} core stages plus one cycle "
             f"for each FIFO hop.")

    p.append("</svg>")
    return "\n".join(p) + "\n"


FIGURES = {
    "block_diagram.svg": block_diagram,
    "pipeline_timing.svg": pipeline_timing,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    IMG.mkdir(parents=True, exist_ok=True)
    rc = 0
    for name, fn in FIGURES.items():
        text = fn()
        path = IMG / name
        if args.check:
            if not path.exists() or path.read_text() != text:
                print(f"stale: {path.relative_to(ROOT)}", file=sys.stderr)
                rc = 1
            continue
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
