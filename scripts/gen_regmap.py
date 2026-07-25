#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Generate every artefact derived from the register map.

Outputs:
  rtl/cordic_regmap.svh        offsets, field positions and function codes for RTL
  sw/include/cordic_regmap.h   the same for the C driver
  docs/REGISTERS.md            register and function tables
  docs/img/regmap.svg          bit-field figure

`--check` regenerates in memory and diffs, so CI catches a stale checkout.
"""

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import cordic_regmap as rm  # noqa: E402

GEN_NOTE_SV = """// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// GENERATED FILE - DO NOT EDIT.
// Produced by scripts/gen_regmap.py from scripts/cordic_regmap.py.
// Regenerate with `make regmap`.
//
// Include this inside a module body, not at file scope. There is deliberately no
// include guard: each module that needs the offsets gets its own module-local
// copy, so no tool has to share $unit-scope declarations across files.
//
// No module uses every offset, so unused-parameter linting is switched off for the
// span of the file rather than case by case.

/* verilator lint_off UNUSEDPARAM */
"""

GEN_NOTE_C = """/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * GENERATED FILE - DO NOT EDIT.
 * Produced by scripts/gen_regmap.py from scripts/cordic_regmap.py.
 * Regenerate with `make regmap`.
 */
"""


def sv_ident(reg, field=None):
    base = f"Cordic{camel(reg.name)}"
    return base if field is None else f"{base}{camel(field.name)}"


def camel(snake):
    return "".join(p.capitalize() for p in snake.split("_"))


def gen_svh():
    out = [GEN_NOTE_SV, ""]
    out.append(f"  localparam int unsigned CordicWindowBytes = 'h{rm.WINDOW_BYTES:x};")
    out.append(f"  localparam int unsigned CordicMappedBytes = 'h{rm.MAPPED_BYTES:x};")
    out.append(f"  localparam logic [31:0] CordicIdMagic     = 32'h{rm.MAGIC:08x};")
    maj, minr, pat = rm.VERSION
    out.append(f"  localparam logic [31:0] CordicVersionValue = "
               f"32'h{(maj << 24) | (minr << 16) | (pat << 8):08x};")
    out.append(f"  localparam logic [31:0] CordicBadAccessData = "
               f"32'h{rm.BAD_ACCESS_DATA:08x};")
    out.append(f"  localparam int unsigned CordicNumFuncs    = {rm.NUM_FUNCS};")
    out.append("")
    out.append("  // Word offsets, i.e. byte offset >> 2, used by the address decoder.")
    for r in REGS_SORTED:
        out.append(f"  localparam int unsigned {sv_ident(r)}Word = 'h{r.offset >> 2:x};"
                   f" // byte 0x{r.offset:03x}  {r.access}")
    out.append("")
    out.append("  // Field positions.")
    for r in REGS_SORTED:
        for fl in r.fields:
            if fl.hi == fl.lo:
                out.append(f"  localparam int unsigned {sv_ident(r, fl)}Bit = {fl.lo};")
            else:
                out.append(f"  localparam int unsigned {sv_ident(r, fl)}Lsb = {fl.lo};")
                out.append(f"  localparam int unsigned {sv_ident(r, fl)}Msb = {fl.hi};")
    out.append("")
    out.append("  // Writable-bit masks. A write only affects these bits; the rest are")
    out.append("  // reserved, ignore writes and read back zero.")
    for r in REGS_SORTED:
        out.append(f"  localparam logic [31:0] {sv_ident(r)}WrMask = 32'h{wr_mask(r):08x};")
    out.append("")
    out.append("  // Bits that self-clear after one cycle (write-1-to-trigger).")
    for r in REGS_SORTED:
        if trig_mask(r):
            out.append(f"  localparam logic [31:0] {sv_ident(r)}TrigMask = "
                       f"32'h{trig_mask(r):08x};")
    out.append("")
    out.append("  // Function codes for CMD.FUNC.")
    for fn in rm.FUNCS:
        out.append(f"  localparam logic [4:0] CordicFunc{camel(fn.name)} = 5'd{fn.code};"
                   f" // {fn.coord} {fn.mode}")
    out.append("")
    out.append("/* verilator lint_on UNUSEDPARAM */")
    return "\n".join(out) + "\n"


def wr_mask(reg):
    m = 0
    for fl in reg.fields:
        if fl.access in ("RW", "W1S", "W1C"):
            m |= ((1 << (fl.hi - fl.lo + 1)) - 1) << fl.lo
    return m


def trig_mask(reg):
    m = 0
    for fl in reg.fields:
        if fl.access == "W1S":
            m |= ((1 << (fl.hi - fl.lo + 1)) - 1) << fl.lo
    return m


def readable_mask(reg):
    """Bits that read back a value. W1S bits always read zero."""
    m = 0
    for fl in reg.fields:
        if fl.access != "W1S":
            m |= ((1 << (fl.hi - fl.lo + 1)) - 1) << fl.lo
    return m


def gen_header():
    out = [GEN_NOTE_C, "", "#ifndef CORDIC_REGMAP_H", "#define CORDIC_REGMAP_H", ""]
    out.append(f"#define CORDIC_WINDOW_BYTES     0x{rm.WINDOW_BYTES:x}U")
    out.append(f"#define CORDIC_MAPPED_BYTES     0x{rm.MAPPED_BYTES:x}U")
    out.append(f"#define CORDIC_ID_MAGIC         0x{rm.MAGIC:08x}U")
    maj, minr, pat = rm.VERSION
    out.append(f"#define CORDIC_VERSION_MAJOR    {maj}U")
    out.append(f"#define CORDIC_VERSION_MINOR    {minr}U")
    out.append(f"#define CORDIC_VERSION_PATCH    {pat}U")
    out.append(f"#define CORDIC_BAD_ACCESS_DATA  0x{rm.BAD_ACCESS_DATA:08x}U")
    out.append("")
    out.append("/* Byte offsets from the peripheral base address. */")
    for r in REGS_SORTED:
        out.append(f"#define CORDIC_{r.name:<14s} 0x{r.offset:03x}U   /* {r.access:3s} "
                   f"{r.desc} */")
    out.append("")
    out.append("/* Field shifts and masks. CORDIC_<REG>_<FIELD>_{SHIFT,MASK}. */")
    for r in REGS_SORTED:
        for fl in r.fields:
            width = fl.hi - fl.lo + 1
            mask = ((1 << width) - 1) << fl.lo
            base = f"CORDIC_{r.name}_{fl.name}"
            out.append(f"#define {base + '_SHIFT':<34s} {fl.lo}U")
            out.append(f"#define {base + '_MASK':<34s} 0x{mask:08x}U")
    out.append("")
    out.append("/* Function codes for the CMD.FUNC field. */")
    for fn in rm.FUNCS:
        out.append(f"#define CORDIC_FUNC_{fn.name:<12s} {fn.code}U   "
                   f"/* {fn.coord} {fn.mode}: {fn.result} */")
    out.append(f"#define CORDIC_NUM_FUNCS         {rm.NUM_FUNCS}U")
    out.append("")
    out.append("#endif /* CORDIC_REGMAP_H */")
    return "\n".join(out) + "\n"


def gen_reg_tables():
    """Markdown register and function tables, shared by docs and the README."""
    out = []
    out.append("### Register summary")
    out.append("")
    out.append("| Offset | Name | Access | Description |")
    out.append("|--------|------|--------|-------------|")
    for r in REGS_SORTED:
        out.append(f"| `0x{r.offset:03X}` | `{r.name}` | {r.access} "
                   f"| {md(r.desc)} |")
    out.append(f"| `0x{rm.MAPPED_BYTES:03X}` .. `0x{rm.WINDOW_BYTES - 4:03X}` "
               f"| unmapped | - | Reads return "
               f"`0x{rm.BAD_ACCESS_DATA:08X}` with `r.err`, writes take `r.err` |")
    out.append("")
    out.append("### Bit fields")
    out.append("")
    for r in REGS_SORTED:
        if len(r.fields) == 1 and r.fields[0].hi == 31 and r.fields[0].lo == 0:
            continue
        out.append(f"#### `{r.name}` at `0x{r.offset:03X}` ({r.access})")
        out.append("")
        out.append("| Bits | Name | Access | Description |")
        out.append("|------|------|--------|-------------|")
        for fl in sorted(r.fields, key=lambda x: -x.hi):
            bits = f"{fl.hi}" if fl.hi == fl.lo else f"{fl.hi}:{fl.lo}"
            out.append(f"| `{bits}` | `{fl.name}` | {fl.access} | {md(fl.desc)} |")
        reserved = 0xFFFFFFFF & ~(wr_mask(r) | readable_mask(r))
        if reserved:
            out.append(f"| others | reserved | RO | Read 0, writes ignored |")
        out.append("")
    return "\n".join(out)


def md(text):
    """Escape a pipe so it survives inside a markdown table cell."""
    return text.replace("|", "\\|")


def gen_func_table():
    out = []
    out.append("| `FUNC` | Name | System | Mode | Operands | Result | Convergence domain | Gain |")
    out.append("|-------:|------|--------|------|----------|--------|--------------------|------|")
    for fn in rm.FUNCS:
        out.append(f"| {fn.code} | `{fn.name}` | {fn.coord} | {fn.mode} "
                   f"| {md(fn.operands)} | {md(fn.result)} | {md(fn.domain)} "
                   f"| {md(fn.gain)} |")
    return "\n".join(out)


def gen_registers_md():
    out = ["# Register map", "",
           "Generated from `scripts/cordic_regmap.py` by `scripts/gen_regmap.py`.",
           "Do not edit by hand.", "",
           f"The peripheral occupies a {rm.WINDOW_BYTES // 1024} KB window. "
           f"Offsets `0x000` to `0x{rm.MAPPED_BYTES - 4:03X}` are implemented; "
           f"everything above is unmapped.", "",
           gen_reg_tables(), "", "## Function codes", "", gen_func_table(), ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# SVG figure
# ---------------------------------------------------------------------------

# Colours go out as presentation attributes with class-based dark overrides, not as
# CSS custom properties: presentation attributes lose to any stylesheet rule, so a
# renderer that ignores var() (librsvg, for one) still shows the light palette
# rather than a black rectangle.
LIGHT = dict(bg="#ffffff", fg="#16191d", muted="#5c646e", grid="#c3c9d1")
DARK = dict(bg="#14171a", fg="#e8ebee", muted="#9aa3ad", grid="#3a424b")

# Muted, colour-blind-safe hues, one per access class.
ACCESS_FILL = {"RO": "#5b7fa6", "RW": "#4f9d76", "W1C": "#b8863b", "W1S": "#a3618f"}
ACCESS_FILL_DARK = {"RO": "#7fa3c9", "RW": "#74bd9a", "W1C": "#d5a75d",
                    "W1S": "#c188b3"}


def _dark_rules(prefix=""):
    r = [f"      {prefix}.bgr {{ fill: {DARK['bg']}; }}",
         f"      {prefix}.ttl, {prefix}.rn, {prefix}.lg {{ fill: {DARK['fg']}; }}",
         f"      {prefix}.sub, {prefix}.ro, {prefix}.bit "
         f"{{ fill: {DARK['muted']}; }}",
         f"      {prefix}.box, {prefix}.gl {{ stroke: {DARK['grid']}; }}"]
    for acc, colour in ACCESS_FILL_DARK.items():
        r.append(f"      {prefix}.acc-{acc} {{ fill: {colour}; }}")
    return "\n".join(r)


def svg_style():
    return "\n".join([
        "  <style>",
        '    text { font-family: "DejaVu Sans", "Helvetica Neue", Arial, '
        "sans-serif; }",
        "    .ttl  { font-size: 21px; font-weight: 700; }",
        "    .sub  { font-size: 12px; }",
        "    .rn   { font-size: 13px; font-weight: 700; }",
        "    .ro   { font-size: 11px; }",
        "    .bit  { font-size: 9px; }",
        "    .fl   { font-size: 10px; font-weight: 600; }",
        "    .lg   { font-size: 11px; }",
        "    @media (prefers-color-scheme: dark) {",
        _dark_rules(),
        "    }",
        _dark_rules(':root[data-theme="dark"] '),
        "  </style>",
    ])


REGS_SORTED = sorted(rm.REGS, key=lambda r: r.offset)


def gen_svg():
    left = 152            # x where the 32-bit strip starts, wide enough for TANH_LIM_HYP
    cellw = 20            # width of one bit cell
    roww = 32 * cellw
    rowh = 30
    gap = 8
    top = 108
    rows = list(REGS_SORTED)
    height = top + len(rows) * (rowh + gap) + 96
    width = left + roww + 30

    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} '
             f'{height}" width="{width}" height="{height}" role="img" '
             f'aria-label="CORDIC accelerator OBI register map">')
    p.append(svg_style())
    p.append(f'  <rect class="bgr" width="{width}" height="{height}" '
             f'fill="{LIGHT["bg"]}"/>')
    p.append(f'  <text class="ttl" x="16" y="34" fill="{LIGHT["fg"]}">'
             f'CORDIC accelerator register map</text>')
    p.append(f'  <text class="sub" x="16" y="54" fill="{LIGHT["muted"]}">'
             f'OBI subordinate window, {rm.WINDOW_BYTES // 1024} KB, 32-bit words. '
             f'Offsets 0x{rm.MAPPED_BYTES:03X} and above are unmapped and answer '
             f'with r.err.</text>')

    # Bit ruler: bit 31 on the left, bit 0 on the right.
    for b in range(32):
        x = left + (31 - b) * cellw
        if b % 4 == 0 or b == 31:
            p.append(f'  <text class="bit" x="{x + cellw / 2:.0f}" y="{top - 8}" '
                     f'text-anchor="middle" fill="{LIGHT["muted"]}">{b}</text>')
    p.append(f'  <text class="ro" x="{left - 10}" y="{top - 8}" '
             f'text-anchor="end" fill="{LIGHT["muted"]}">bit</text>')

    y = top
    for r in rows:
        p.append(f'  <text class="rn" x="16" y="{y + 15}" fill="{LIGHT["fg"]}">'
                 f'{r.name}</text>')
        p.append(f'  <text class="ro" x="16" y="{y + 27}" '
                 f'fill="{LIGHT["muted"]}">0x{r.offset:03X} {r.access}</text>')
        for b in range(1, 32):
            if b % 4 == 0:
                x = left + b * cellw
                p.append(f'  <line class="gl" x1="{x}" y1="{y}" x2="{x}" '
                         f'y2="{y + rowh}" stroke="{LIGHT["grid"]}" '
                         f'stroke-width="0.5" stroke-dasharray="2 3"/>')
        for fl in r.fields:
            w = (fl.hi - fl.lo + 1) * cellw
            x = left + (31 - fl.hi) * cellw
            fill = ACCESS_FILL.get(fl.access, "#7a7a7a")
            p.append(f'  <rect class="acc-{fl.access}" x="{x}" y="{y}" '
                     f'width="{w}" height="{rowh}" rx="2" fill="{fill}" '
                     f'fill-opacity="0.9"><title>{fl.name} ({fl.access}): '
                     f'{fl.desc}</title></rect>')
            label = fl.name
            # Roughly 6.3 px per character at 10 px DejaVu Sans.
            if len(label) * 6.3 > w - 4:
                label = "" if w < 22 else label[0]
            if label:
                p.append(f'  <text class="fl" x="{x + w / 2:.0f}" y="{y + 19}" '
                         f'text-anchor="middle" fill="#ffffff">{label}</text>')
        p.append(f'  <rect class="box" x="{left}" y="{y}" width="{roww}" '
                 f'height="{rowh}" rx="2" fill="none" stroke="{LIGHT["grid"]}" '
                 f'stroke-width="1"/>')
        y += rowh + gap

    # Legend
    ly = y + 18
    p.append(f'  <text class="lg" x="16" y="{ly + 11}" fill="{LIGHT["fg"]}">'
             f'Access</text>')
    lx = 78
    for acc in ("RO", "RW", "W1C", "W1S"):
        p.append(f'  <rect class="acc-{acc}" x="{lx}" y="{ly}" width="16" '
                 f'height="14" rx="2" fill="{ACCESS_FILL[acc]}" '
                 f'fill-opacity="0.9"/>')
        p.append(f'  <text class="lg" x="{lx + 22}" y="{ly + 11}" '
                 f'fill="{LIGHT["fg"]}">{acc}</text>')
        lx += 22 + len(acc) * 8 + 22
    p.append(f'  <text class="lg" x="16" y="{ly + 34}" fill="{LIGHT["fg"]}">'
             f'Unlabelled cells are reserved: writes are ignored and reads return '
             f'0. W1S bits self-clear and always read 0.</text>')
    p.append(f'  <text class="lg" x="16" y="{ly + 52}" fill="{LIGHT["fg"]}">'
             f'Operand and result words hold signed fixed-point values in the '
             f'elaborated format reported by CFG0.</text>')
    p.append("</svg>")
    return "\n".join(p) + "\n"


REGS_SORTED = sorted(rm.REGS, key=lambda r: r.offset)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    rm.check()
    artefacts = {
        ROOT / "rtl" / "cordic_regmap.svh": gen_svh(),
        ROOT / "sw" / "include" / "cordic_regmap.h": gen_header(),
        ROOT / "docs" / "REGISTERS.md": gen_registers_md(),
        ROOT / "docs" / "img" / "regmap.svg": gen_svg(),
    }

    rc = 0
    for path, text in artefacts.items():
        if args.check:
            if not path.exists() or path.read_text() != text:
                print(f"stale: {path.relative_to(ROOT)}, run `make regmap`", file=sys.stderr)
                rc = 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")
    if args.check and rc == 0:
        print("register map artefacts are up to date")
    return rc


if __name__ == "__main__":
    sys.exit(main())
