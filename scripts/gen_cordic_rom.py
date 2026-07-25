#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Emit rtl/cordic_rom.svh from scripts/cordic_tables.py.

Every constant the RTL needs is a plain integer literal here. Nothing in the
synthesisable path calls $atan, $ln or any other real-valued system function,
because Yosys does not implement them and Icarus Verilog silently folds them to
the wrong value. Integer literals plus a rounding shift work identically in
Verilator, Icarus, Yosys and commercial tools.

Run `make rom` (or this script directly) after changing cordic_tables.py. CI
regenerates and diffs the file, so a stale ROM fails the build.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import cordic_tables as ct  # noqa: E402

HEADER = """// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// GENERATED FILE - DO NOT EDIT.
// Produced by scripts/gen_cordic_rom.py from scripts/cordic_tables.py.
// Regenerate with `make rom`.
//
// Constant tables for the generalised CORDIC datapath. Every entry is a signed
// 64-bit integer in Q3.61 fixed point (value_int = round(value_real * 2**61)).
// 61 fractional bits is the most that still fits pi in a signed 64-bit word.
// `cordic_rom_to_fx` in cordic_fx.svh re-rounds an entry to the working format.
//
// Indexing conventions:
// Tables are flat vectors: entry i of a table with W-bit entries occupies bits
// [i*W + W-1 : i*W]. Read them through the accessors in cordic_rom_fx.svh rather
// than indexing directly. They are flat because Yosys 0.33 cannot parse a packed
// 2D localparam declaration at all.
//
//   CordicAtanRom      atan(2**-s)   for s = 0 .. CordicRomMaxIdx-1
//   CordicAtanhRom     atanh(2**-s)  for s = 1 .. CordicRomMaxIdx-1
//                      (entry 0 is zero: atanh(1) is infinite and shift 0 is
//                       never part of the hyperbolic sequence)
//   Cordic*Rom         quantity for an n-stage datapath, n = 0 .. CordicRomMaxStg
//   CordicHypShiftRom  shift amount of hyperbolic stage k
//
// Include this inside a module body, not at file scope, so the localparams stay
// module-local. There is deliberately no include guard: each module that needs
// the tables gets its own copy, and no tool has to support $unit-scope
// declarations shared across separately compiled files.
//
// No module uses every table, so unused-parameter linting is switched off for the
// span of the file rather than case by case.

/* verilator lint_off UNUSEDPARAM */
"""

FOOTER = "/* verilator lint_on UNUSEDPARAM */\n"


def emit_word_table(name, values, width, comment):
    """Emit a flat 1-D packed localparam plus its depth.

    Flat rather than a packed 2D array on purpose: Yosys 0.33 rejects
    `localparam logic [N-1:0][W-1:0]` outright ("syntax error, unexpected '['").
    A single wide vector parses everywhere, and cordic_rom_fx.svh reads entries
    back with an indexed part-select, which constant-folds at elaboration.

    Concatenations are MSB-first, so the table is written from the highest index
    down; entry i then lands at bit offset i*width.
    """
    n = len(values)
    digits = (width + 3) // 4
    lines = [f"  // {comment}"]
    lines.append(f"  localparam int unsigned {name}Depth = {n};")
    lines.append(f"  localparam int unsigned {name}Bits  = {width};")
    lines.append(f"  localparam logic [{n * width - 1}:0] {name} = {{")
    for pos, i in enumerate(reversed(range(n))):
        masked = values[i] & ((1 << width) - 1)
        sep = "" if pos == n - 1 else ","
        lines.append(f"    {width}'h{masked:0{digits}x}{sep} // [{i}]")
    lines.append("  };")
    return "\n".join(lines)


def build(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output", default=None, help="output path")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the output file is out of date")
    args = ap.parse_args(argv)

    t = ct.rom_tables()

    parts = [HEADER]
    parts.append(f"""
  localparam int unsigned CordicRomFrac   = {ct.ROM_FRAC};
  localparam int unsigned CordicRomWidth  = 64;
  localparam int unsigned CordicRomMaxIdx = {ct.ROM_MAX_IDX};
  localparam int unsigned CordicRomMaxStg = {ct.ROM_MAX_STG};

  // pi and pi/2 drive the circular pre-rotation.
  localparam logic [63:0] CordicPiRom     = 64'h{t['PiRom'] & (2**64 - 1):016x};
  localparam logic [63:0] CordicHalfPiRom = 64'h{t['HalfPiRom'] & (2**64 - 1):016x};
""")

    tables = [
        ("CordicAtanRom", t["AtanRom"], 64,
         "atan(2**-s): circular micro-rotation angles"),
        ("CordicAtanhRom", t["AtanhRom"], 64,
         "atanh(2**-s): hyperbolic micro-rotation angles"),
        ("CordicKCircRom", t["KCircRom"], 64,
         "circular gain K = prod sqrt(1 + 2**-2s)"),
        ("CordicInvKCircRom", t["InvKCircRom"], 64,
         "reciprocal circular gain 1/K, loaded as x0 for gain-free sin/cos"),
        ("CordicKHypRom", t["KHypRom"], 64,
         "hyperbolic gain Kh = prod sqrt(1 - 2**-2s)"),
        ("CordicInvKHypRom", t["InvKHypRom"], 64,
         "reciprocal hyperbolic gain 1/Kh, loaded as x0 for sinh/cosh/exp"),
        ("CordicLimCircRom", t["LimCircRom"], 64,
         "circular convergence radius sum atan(2**-s)"),
        ("CordicLimHypRom", t["LimHypRom"], 64,
         "hyperbolic convergence radius sum atanh(2**-s)"),
        ("CordicLimLinRom", t["LimLinRom"], 64,
         "linear convergence radius sum 2**-s"),
        ("CordicTanhLimHypRom", t["TanhLimHypRom"], 64,
         "tanh of the hyperbolic radius: the largest |y/x| atanh can resolve"),
        ("CordicHypShiftRom", t["HypShiftRom"], 8,
         "hyperbolic stage shift amounts, with 4 and 13 repeated"),
    ]
    for name, values, width, comment in tables:
        parts.append("")
        parts.append(emit_word_table(name, values, width, comment))

    parts.append(FOOTER)
    text = "\n".join(parts)

    out = args.output
    if out is None:
        out = pathlib.Path(__file__).resolve().parent.parent / "rtl" / "cordic_rom.svh"
    out = pathlib.Path(out)

    if args.check:
        if not out.exists():
            print(f"{out} does not exist", file=sys.stderr)
            return 1
        if out.read_text() != text:
            print(f"{out} is out of date, run `make rom`", file=sys.stderr)
            return 1
        print(f"{out} is up to date")
        return 0

    out.write_text(text)
    print(f"wrote {out} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(build())
