#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Emit sw/host/cordic_vectors.h: test vectors for the C driver.

Each vector carries the operands, the exact result words the hardware produces
(taken from the bit-accurate model, which the RTL is asserted against operation by
operation), and the double-precision reference for the output of interest expressed
in the working fixed-point format.

That lets the C test check two different things:
  - the raw result words match exactly, which verifies the driver's register
    sequencing and flag decoding;
  - the wrapper output lands within its documented LSB bound of the true value,
    which verifies the driver's gain compensation.

The peripheral model in sw/host/ answers register reads out of this same table, so
the C test is driven by data that came from the verified model rather than from a
second CORDIC implementation written in C.
"""

import argparse
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tb"))

import cordic_bounds as cb  # noqa: E402
from cordic_model import CordicModel, FUNC, reference  # noqa: E402

# The configuration the C test assumes. Must match sw/Makefile's documentation.
CFG = dict(data_width=32, frac_bits=29, num_stages=28, guard_int=2, guard_frac=4)

# Above this the reference comparison carries no information, so it is dropped.
# One part in 2**16 of full scale.
TOL_CAP_LSB = 1 << 13

# Which output each wrapper hands back, and whether the driver undoes a gain.
WRAPPER = {
    "SIN_COS": [("cos", "x", None), ("sin", "y", None)],
    "ATAN2": [("atan2", "z", None), ("hypot", "x", "k_circ")],
    "SINH_COSH": [("cosh", "x", None), ("sinh", "y", None)],
    "EXP": [("exp", "x", None)],
    "LN": [("ln", "z", None)],
    "ATANH": [("atanh", "z", None)],
    "MUL": [("mul", "y", None)],
    "DIV": [("div", "z", None)],
    "ROTATE": [("rot_x", "x", "k_circ"), ("rot_y", "y", "k_circ")],
    "HROTATE": [("hrot_x", "x", "k_hyp"), ("hrot_y", "y", "k_hyp")],
}


def cases(m):
    """Directed cases covering every function, both signs, and the error paths."""
    lim_hyp = m.int_to_real(m.lim_hyp)
    lim_lin = m.int_to_real(m.lim_lin)
    t = m.int_to_real(m.tanh_lim_hyp)
    ln_lo = (1 - t) / (1 + t)
    out = []

    def add(name, x=0.0, y=0.0, z=0.0, note=""):
        out.append((name, m.to_fx(x), m.to_fx(y), m.to_fx(z), note))

    # These come first on purpose. The RV32 build truncates the table to fit Croc's
    # default 8 KB SRAM, and sw/test_cordic.c's named-wrapper checks use exactly
    # these operands, so they have to survive the truncation.
    one = m.to_fx(1.0)
    lim_fx = m.lim_hyp >> m.guard_frac
    for entry in (
        ("SIN_COS", 0, 0, 0, "wrapper: sin/cos(0)"),
        ("ATAN2", one, 0, 0, "wrapper: atan2(0, 1) and hypot(1, 0)"),
        ("EXP", 0, 0, 0, "wrapper: exp(0)"),
        ("LN", one, 0, 0, "wrapper: ln(1)"),
        ("MUL", one, 0, one, "wrapper: 1 * 1"),
        ("DIV", one + one, one, 0, "wrapper: 1 / 2"),
        ("ROTATE", one, 0, 0, "wrapper: rotate identity"),
        ("EXP", 0, 0, lim_fx + lim_fx // 2, "wrapper: exp out of domain"),
        ("LN", 0, 0, 0, "wrapper: ln(0), out of domain"),
        ("DIV", 0, one, 0, "wrapper: divide by zero"),
    ):
        out.append(entry)

    for z in (0.0, 0.5, -0.5, 1.0, -1.0, math.pi / 4, math.pi / 2, -math.pi / 2,
              math.pi, -math.pi, 2.5, -2.5, 3.9, -3.9):
        add("SIN_COS", z=z, note=f"sin/cos({z:+.4f})")
    for x, y in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (1.0, 1.0),
                 (-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0), (0.6, 0.8), (-0.6, -0.8)):
        add("ATAN2", x=x, y=y, note=f"atan2({y:+.2f}, {x:+.2f})")
    add("ATAN2", note="atan2(0, 0), defined as zero")
    for z in (0.0, 0.25, -0.25, 0.9, -0.9, lim_hyp, -lim_hyp):
        add("SINH_COSH", z=z, note=f"sinh/cosh({z:+.6f})")
        add("EXP", z=z, note=f"exp({z:+.6f})")
    add("SINH_COSH", z=lim_hyp * 1.5, note="sinh out of domain")
    add("EXP", z=-lim_hyp * 1.5, note="exp out of domain")
    for w in (ln_lo, 0.5, 1.0, math.e, 2.0, 3.5):
        add("LN", x=w, note=f"ln({w:.6f})")
    add("LN", x=0.0, note="ln(0), out of domain")
    add("LN", x=-1.0, note="ln(-1), out of domain")
    for xv, r in ((1.0, 0.0), (1.0, 0.5), (1.0, -0.5), (2.0, 0.75), (-1.0, 0.5),
                  (1.0, t)):
        add("ATANH", x=xv, y=r * abs(xv), note=f"atanh({r:+.4f})")
    add("ATANH", x=1.0, y=0.95, note="atanh out of domain")
    add("ATANH", x=0.0, y=0.5, note="atanh with a zero denominator")
    for a, b in ((1.0, 1.0), (1.5, 0.5), (-2.0, 0.25), (2.5, -0.75), (0.0, 1.0),
                 (1.0, lim_lin)):
        add("MUL", x=a, z=b, note=f"{a:+.3f} * {b:+.3f}")
    add("MUL", x=1.0, z=lim_lin * 1.5, note="multiply out of domain")
    for num, den in ((0.5, 1.0), (-0.5, 1.0), (1.0, 2.0), (1.0, -2.0), (3.0, 2.0),
                     (0.0, 1.0)):
        add("DIV", x=den, y=num, note=f"{num:+.3f} / {den:+.3f}")
    add("DIV", x=0.0, y=1.0, note="divide by zero")
    add("DIV", x=1.0, y=3.0, note="divide out of domain")
    for x, y, z in ((1.0, 0.0, 0.5), (0.0, 1.0, -0.5), (0.5, 0.5, math.pi / 3)):
        add("ROTATE", x=x, y=y, z=z, note=f"rotate by {z:+.4f}")
    for x, y, z in ((0.5, 0.0, 0.3), (0.0, 0.5, -0.3)):
        add("HROTATE", x=x, y=y, z=z, note=f"hyperbolic rotate by {z:+.4f}")

    # Drop duplicates, keeping first appearance so the wrapper cases stay at the
    # front.
    seen = set()
    unique = []
    for entry in out:
        key = entry[:4]
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def build():
    m = CordicModel(**CFG)
    ctx = cb.BoundCtx(m)
    lsb = 1.0 / (1 << m.frac_bits)
    rows = []
    for name, xf, yf, zf, note in cases(m):
        r = m.run(FUNC[name], x_fx=xf, y_fx=yf, z_fx=zf)
        checks = []
        if not r.domain_error:
            xr, yr, zr = m.to_real(xf), m.to_real(yf), m.to_real(zf)
            try:
                ref = reference(name, x=xr, y=yr, z=zr,
                                k_circ=ctx.k_circ, k_hyp=ctx.k_hyp)
            except (ValueError, ZeroDivisionError):
                ref = {}
            for label, key, ungain in WRAPPER[name]:
                if key not in ref:
                    continue
                value = ref[key]
                if ungain == "k_circ":
                    value /= ctx.k_circ
                elif ungain == "k_hyp":
                    value /= ctx.k_hyp
                # Convert the bound on the raw output into a bound on the value
                # the wrapper hands back, which is the raw one divided by the gain.
                lim = cb.bound(ctx, name, key, xr, yr, zr)
                if lim is None:
                    continue
                if ungain == "k_circ":
                    lim /= ctx.k_circ
                elif ungain == "k_hyp":
                    lim /= ctx.k_hyp
                # Undoing the gain in the driver costs another rounding step.
                if ungain is not None:
                    lim += 2.0 * lsb
                if abs(value) >= 2.0 ** (m.data_width - m.frac_bits - 1):
                    continue  # not representable, the hardware saturates
                tol = int(math.ceil(lim / lsb))
                # An ill-conditioned argument (atan2 of the zero vector, division
                # by a near-zero denominator) has a bound so wide the comparison
                # says nothing. Drop it: the exact result-word check still applies
                # to every vector, conditioning or not.
                if tol > TOL_CAP_LSB:
                    continue
                checks.append((label, key, m.to_fx(value), max(1, tol)))
        rows.append(dict(name=name, func=FUNC[name], x=xf, y=yf, z=zf, note=note,
                         rx=r.x, ry=r.y, rz=r.z, flags=r.flags, checks=checks))
    return m, rows


HEADER = """/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * GENERATED FILE - DO NOT EDIT.
 * Produced by scripts/gen_sw_vectors.py from tb/cordic_model.py.
 * Regenerate with `make sw-vectors`.
 *
 * Test vectors for the C driver. Every expected result word came out of the
 * bit-accurate model that the RTL is asserted against operation by operation, so
 * these are hardware results, not a second implementation's opinion.
 */

#ifndef CORDIC_VECTORS_H
#define CORDIC_VECTORS_H

#include <stdint.h>

"""


def emit(m, rows):
    o = [HEADER]
    o.append(f"#define CORDIC_VEC_DATA_WIDTH {m.data_width}")
    o.append(f"#define CORDIC_VEC_FRAC_BITS  {m.frac_bits}")
    o.append(f"#define CORDIC_VEC_NUM_STAGES {m.num_stages}")
    o.append(f"#define CORDIC_VEC_GUARD_INT  {m.guard_int}")
    o.append(f"#define CORDIC_VEC_GUARD_FRAC {m.guard_frac}")
    o.append("")
    o.append("/* Constants the peripheral model reports, in the working format. */")
    for name, value in (("K_CIRC", m.k_circ), ("IK_CIRC", m.inv_k_circ),
                        ("K_HYP", m.k_hyp), ("IK_HYP", m.inv_k_hyp)):
        o.append(f"#define CORDIC_VEC_{name} {(value + (1 << (m.guard_frac - 1))) >> m.guard_frac}")
    for name, value in (("LIM_CIRC", m.lim_circ), ("LIM_HYP", m.lim_hyp),
                        ("LIM_LIN", m.lim_lin), ("TANH_LIM_HYP", m.tanh_lim_hyp)):
        o.append(f"#define CORDIC_VEC_{name} {value >> m.guard_frac}")
    o.append("")
    o.append("#define CORDIC_VEC_MAX_CHECKS 2")
    o.append("")
    o.append("typedef struct {")
    o.append("  const char *label;   /* which wrapper output this is */")
    o.append("  char        out;     /* 'x', 'y' or 'z' */")
    o.append("  int32_t     expected; /* double-precision reference, in the format */")
    o.append("  int32_t     tol_lsb;  /* documented bound, in LSBs */")
    o.append("} cordic_vec_check_t;")
    o.append("")
    o.append("/* The note strings are only used by the host build's log. Define")
    o.append(" * CORDIC_VEC_NO_NOTES to drop them, which the RV32 build does: Croc's")
    o.append(" * default SRAM is 8 KB and the strings alone are around 2 KB. */")
    o.append("#if defined(CORDIC_VEC_NO_NOTES)")
    o.append("#define CORDIC_VEC_NOTE(s) 0")
    o.append("#else")
    o.append("#define CORDIC_VEC_NOTE(s) (s)")
    o.append("#endif")
    o.append("")
    o.append("typedef struct {")
    o.append("  const char *note;")
    o.append("  uint8_t     func;")
    o.append("  int32_t     x, y, z;          /* operands */")
    o.append("  int32_t     rx, ry, rz;       /* exact result words */")
    o.append("  uint32_t    flags;            /* exact RES_FLAGS bits 3:0 */")
    o.append("  int         n_checks;")
    o.append("  cordic_vec_check_t checks[CORDIC_VEC_MAX_CHECKS];")
    o.append("} cordic_vec_t;")
    o.append("")
    o.append(f"/* {len(rows)} vectors are defined. A build may keep only the first")
    o.append(" * CORDIC_VEC_LIMIT of them, which is how the RV32 image fits Croc's")
    o.append(" * default 8 KB SRAM. The wrapper-check operands come first so they")
    o.append(" * always survive truncation. */")
    o.append(f"#define CORDIC_VEC_TOTAL {len(rows)}")
    o.append("#if !defined(CORDIC_VEC_LIMIT)")
    o.append("#define CORDIC_VEC_LIMIT CORDIC_VEC_TOTAL")
    o.append("#endif")
    o.append("")
    o.append("static const cordic_vec_t cordic_vectors[] = {")
    for idx, r in enumerate(rows):
        chk = ", ".join(
            f'{{CORDIC_VEC_NOTE("{lab}"), \'{key}\', {exp}, {tol}}}'
            for lab, key, exp, tol in r["checks"])
        if not chk:
            chk = "{0, 0, 0, 0}"
        o.append(f"#if {idx} < CORDIC_VEC_LIMIT")
        o.append(f'  {{ /* [{idx}] {r["name"]}: {r["note"]} */')
        o.append(f'    CORDIC_VEC_NOTE("{r["note"]}"), {r["func"]},')
        o.append(f'    {r["x"]}, {r["y"]}, {r["z"]},')
        o.append(f'    {r["rx"]}, {r["ry"]}, {r["rz"]}, 0x{r["flags"]:x}u,')
        o.append(f'    {len(r["checks"])}, {{{chk}}} }},')
        o.append("#endif")
    o.append("};")
    o.append("")
    o.append("#define CORDIC_VEC_COUNT "
             "((int)(sizeof(cordic_vectors) / sizeof(cordic_vectors[0])))")
    o.append("")
    o.append("#endif /* CORDIC_VECTORS_H */")
    return "\n".join(o) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    m, rows = build()
    text = emit(m, rows)
    out = ROOT / "sw" / "host" / "cordic_vectors.h"
    if args.check:
        if not out.exists() or out.read_text() != text:
            print(f"stale: {out.relative_to(ROOT)}, run `make sw-vectors`",
                  file=sys.stderr)
            return 1
        print(f"{out.relative_to(ROOT)} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    n_checks = sum(len(r["checks"]) for r in rows)
    print(f"wrote {out.relative_to(ROOT)}: {len(rows)} vectors, {n_checks} "
          f"reference checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
