#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Assert that the design infers no multiplier, divider, modulo or MAC.

That is the whole reason to use CORDIC, so it deserves to be a checked property
rather than a claim in a README. Yosys is stopped just after `proc` and `flatten`,
before any cell mapping, where the inferred arithmetic is still visible as `$mul`,
`$div`, `$add` and so on, and asked to assert the forbidden types are absent.

Deliberately a separate pass, not folded into `make synth` or `make pdk`: adding
`proc; opt; flatten; opt` ahead of `synth` perturbs the optimisation sequence and
moves the reported cell counts, so the audit runs on its own and leaves the numbers
alone.

Also prints what arithmetic the design does infer, per variant, which is how you can
see that the folded core has a real barrel shifter ($shift/$shiftx) while the
pipelined core's shifts are constant and vanish.
"""

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
BUILD = ROOT / "build" / "arith"

SOURCES = [
    "cordic_stage.sv", "cordic_core_pipe.sv", "cordic_core_iter.sv",
    "cordic_pre.sv", "cordic_post.sv", "cordic_unit.sv", "cordic_fifo.sv",
    "cordic_obi_regs.sv", "cordic_accel.sv",
]

# Anything in here means the design is not doing what it says it does.
FORBIDDEN = ["$mul", "$div", "$mod", "$divfloor", "$modfloor", "$pow", "$macc"]

CONFIGS = [
    dict(name="pipelined Q3.29 N=28", variant=0, data_width=32, frac_bits=29,
         num_stages=28),
    dict(name="iterative Q3.29 N=28", variant=1, data_width=32, frac_bits=29,
         num_stages=28),
    dict(name="pipelined Q3.13 N=15", variant=0, data_width=16, frac_bits=13,
         num_stages=15),
    dict(name="iterative Q3.13 N=15", variant=1, data_width=16, frac_bits=13,
         num_stages=15),
]

CELL_LINE = re.compile(r"^\s+(\$[\w.]+)\s+(\d+)\s*$")
INTERESTING = ("$add", "$sub", "$neg", "$mux", "$pmux", "$shift", "$shiftx",
               "$sshl", "$sshr", "$shl", "$shr", "$alu")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    BUILD.mkdir(parents=True, exist_ok=True)
    srcs = " ".join(str(RTL / s) for s in SOURCES)
    forbidden = " ".join(f"t:{c}" for c in FORBIDDEN)
    rc = 0

    for cfg in CONFIGS:
        stat = BUILD / (cfg["name"].replace(" ", "_") + ".stat")
        script = f"""
read_verilog -sv -DSYNTHESIS -I {RTL} {srcs}
chparam -set DataWidth {cfg['data_width']} -set FracBits {cfg['frac_bits']} \
        -set NumStages {cfg['num_stages']} -set Variant {cfg['variant']} \
        cordic_accel
hierarchy -check -top cordic_accel
proc
opt
memory_dff
opt
flatten
opt
select -assert-none {forbidden}
tee -q -o {stat} stat
"""
        ys = BUILD / (cfg["name"].replace(" ", "_") + ".ys")
        ys.write_text(script)
        log = BUILD / (cfg["name"].replace(" ", "_") + ".log")
        with log.open("w") as fh:
            proc = subprocess.run(["yosys", "-q", "-s", str(ys)],
                                  stdout=fh, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            print(f"{cfg['name']}: FAILED, a forbidden arithmetic cell was inferred",
                  file=sys.stderr)
            print(log.read_text()[-2000:], file=sys.stderr)
            rc = 1
            continue

        counts = {}
        for line in stat.read_text().splitlines():
            m = CELL_LINE.match(line)
            if m:
                counts[m.group(1)] = int(m.group(2))
        arith = {k: v for k, v in counts.items() if k in INTERESTING}
        summary = ", ".join(f"{k[1:]} {v}" for k, v in
                            sorted(arith.items(), key=lambda kv: -kv[1]))
        print(f"{cfg['name']:<22} no multiplier, divider, modulo or MAC. "
              f"Arithmetic inferred: {summary}")

    if rc == 0:
        print(f"\nall {len(CONFIGS)} configurations infer only adds, subtracts, "
              f"negations, shifts and muxes")
    return rc


if __name__ == "__main__":
    sys.exit(main())
