#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Run Yosys over a set of configurations and collect the reports.

Produces one text report per configuration under docs/synth/, plus a machine
readable summary at docs/synth/summary.json that the area comparison chart is
drawn from.

The mapping is technology-independent, so the absolute numbers are gate-equivalent
counts rather than IHP 130nm square micrometres. What they are good for is the
comparison between the two microarchitectures and across stage counts, which is
apples to apples because both go through exactly the same script.
"""

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
OUT = ROOT / "docs" / "synth"
BUILD = ROOT / "build" / "synth"
TEMPLATE = ROOT / "scripts" / "synth.ys.in"

# Configurations to synthesise. The first two are the headline comparison; the
# rest show how area moves with the stage count and the word width.
CONFIGS = [
    dict(name="pipe_q3_29_n28", variant=0, data_width=32, frac_bits=29, num_stages=28),
    dict(name="iter_q3_29_n28", variant=1, data_width=32, frac_bits=29, num_stages=28),
    dict(name="pipe_q3_29_n16", variant=0, data_width=32, frac_bits=29, num_stages=16),
    dict(name="iter_q3_29_n16", variant=1, data_width=32, frac_bits=29, num_stages=16),
    dict(name="pipe_q3_13_n15", variant=0, data_width=16, frac_bits=13, num_stages=15),
    dict(name="iter_q3_13_n15", variant=1, data_width=16, frac_bits=13, num_stages=15),
]

DEFAULTS = dict(guard_int=2, guard_frac=4, in_depth=4, out_depth=4,
                id_width=3, use_rready=0, top="cordic_accel")


def render(cfg):
    text = TEMPLATE.read_text()
    subs = {
        "RTLDIR": str(RTL),
        "TOP": cfg["top"],
        "DATA_WIDTH": cfg["data_width"],
        "FRAC_BITS": cfg["frac_bits"],
        "NUM_STAGES": cfg["num_stages"],
        "VARIANT": cfg["variant"],
        "GUARD_INT": cfg["guard_int"],
        "GUARD_FRAC": cfg["guard_frac"],
        "IN_DEPTH": cfg["in_depth"],
        "OUT_DEPTH": cfg["out_depth"],
        "ID_WIDTH": cfg["id_width"],
        "USE_RREADY": cfg["use_rready"],
        "STATFILE": str(BUILD / f"{cfg['name']}.stat"),
        "LTPFILE": str(BUILD / f"{cfg['name']}.ltp"),
        "JSON": str(BUILD / f"{cfg['name']}.json"),
    }
    for k, v in subs.items():
        text = text.replace(f"@{k}@", str(v))
    return text


CELL_RE = re.compile(r"^\s+(\$?[\w.\\]+)\s+(\d+)\s*$")
FF_PREFIXES = ("$_DFF", "$_SDFF", "$_ADFF", "$_DFFE", "$_ALDFF", "$dff", "$adff")


def parse_stat(path, top):
    """Top-level wire and cell counts, per-type cell tally, and the FF total."""
    text = path.read_text()
    result = {"cells": {}, "num_cells": None, "num_wires": None,
              "num_wire_bits": None, "num_ffs": 0, "unmapped": []}

    blocks = re.split(r"\n=== (\S+) ===\n", text)
    for i in range(1, len(blocks) - 1, 2):
        name, body = blocks[i], blocks[i + 1]
        if name.strip("\\") != top:
            continue
        for key, field in (("Number of wires", "num_wires"),
                           ("Number of wire bits", "num_wire_bits"),
                           ("Number of cells", "num_cells")):
            m = re.search(rf"{key}:\s+(\d+)", body)
            if m:
                result[field] = int(m.group(1))
        in_cells = False
        for line in body.splitlines():
            if line.strip().startswith("Number of cells:"):
                in_cells = True
                continue
            if not in_cells:
                continue
            cm = CELL_RE.match(line)
            if cm:
                result["cells"][cm.group(1)] = int(cm.group(2))
            elif line.strip():
                in_cells = False

    for cell, n in result["cells"].items():
        if cell.startswith(FF_PREFIXES):
            result["num_ffs"] += n
        # Anything that is not a Yosys internal cell after a flattened, mapped
        # run is an unmapped submodule, which is what a blackbox looks like.
        if not cell.startswith("$"):
            result["unmapped"].append(cell)
    return result


def parse_ltp(path):
    """Longest topological path length, ignoring paths through flip-flops."""
    text = path.read_text()
    m = re.search(r"Longest topological path in \S+ \(length\s*=\s*(\d+)\)", text)
    return int(m.group(1)) if m else None


def write_report(cfg, info):
    """Compose the committed report. Yosys's own ltp output lists every node on the
    critical path, tens of thousands of lines, so only the summary is kept."""
    lines = []
    lines.append(f"CORDIC accelerator synthesis report: {cfg['name']}")
    lines.append("=" * 72)
    lines.append("")
    lines.append("Produced by scripts/run_synth.py, which runs scripts/synth.ys.in")
    lines.append("through Yosys. Technology-independent mapping (abc -g cmos4), so the")
    lines.append("counts are gate equivalents, comparable between configurations but")
    lines.append("not IHP 130nm areas.")
    lines.append("")
    lines.append("Configuration")
    lines.append("-" * 72)
    for k in ("top", "variant", "data_width", "frac_bits", "num_stages",
              "guard_int", "guard_frac", "in_depth", "out_depth", "id_width",
              "use_rready"):
        lines.append(f"  {k:<12s} {cfg[k]}")
    lines.append(f"  {'format':<12s} Q{cfg['data_width'] - cfg['frac_bits']}."
                 f"{cfg['frac_bits']}")
    lines.append(f"  {'variant':<12s} "
                 f"{'iterative (folded)' if cfg['variant'] else 'fully pipelined'}")
    lines.append("")
    lines.append("Totals")
    lines.append("-" * 72)
    lines.append(f"  wires                  {info['num_wires']}")
    lines.append(f"  wire bits              {info['num_wire_bits']}")
    lines.append(f"  cells                  {info['num_cells']}")
    lines.append(f"  flip-flops             {info['num_ffs']}")
    lines.append(f"  combinational cells    {info['num_cells'] - info['num_ffs']}")
    lines.append(f"  longest logic depth    {info['longest_path']} "
                 f"(register to register, gates)")
    lines.append("")
    lines.append("Checks")
    lines.append("-" * 72)
    lines.append("  hierarchy -check       passed, no undefined module instantiated")
    lines.append("  check -assert          passed, no combinational loop, no")
    lines.append("                         multiply-driven or undriven wire")
    lines.append("  inferred latches       none ($dlatch, $_DLATCH_*, $sr, $_SR_*")
    lines.append("                         all asserted empty, before and after")
    lines.append("                         technology mapping)")
    lines.append("  unmapped submodules    none, every cell is a Yosys primitive")
    lines.append("  tristate               none")
    lines.append("")
    lines.append("Cells by type")
    lines.append("-" * 72)
    for cell, n in sorted(info["cells"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {cell:<24s} {n:>8d}")
    lines.append("")
    (OUT / f"{cfg['name']}.rpt").write_text("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", default=None,
                    help="run only these configuration names")
    ap.add_argument("--quick", action="store_true",
                    help="run only the two headline configurations")
    args = ap.parse_args(argv)

    if shutil.which("yosys") is None:
        print("yosys not found on PATH", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    configs = [dict(DEFAULTS, **c) for c in CONFIGS]
    if args.quick:
        configs = configs[:2]
    if args.only:
        wanted = set(args.only)
        configs = [c for c in configs if c["name"] in wanted]
        if not configs:
            print(f"no configuration matched {sorted(wanted)}", file=sys.stderr)
            return 1

    summary = {}
    for cfg in configs:
        script = BUILD / f"{cfg['name']}.ys"
        script.write_text(render(cfg))
        log = BUILD / f"{cfg['name']}.log"
        print(f"synthesising {cfg['name']} ...", flush=True)
        with log.open("w") as fh:
            proc = subprocess.run(["yosys", "-q", "-s", str(script)],
                                  stdout=fh, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            print(f"yosys failed for {cfg['name']}, see {log}", file=sys.stderr)
            print(log.read_text()[-4000:], file=sys.stderr)
            return 1
        info = parse_stat(BUILD / f"{cfg['name']}.stat", cfg["top"])
        info["longest_path"] = parse_ltp(BUILD / f"{cfg['name']}.ltp")
        if info["unmapped"]:
            print(f"{cfg['name']}: cells left unmapped (blackboxes?): "
                  f"{info['unmapped']}", file=sys.stderr)
            return 1
        if info["num_cells"] is None:
            print(f"{cfg['name']}: could not parse the cell count from the stat "
                  f"output", file=sys.stderr)
            return 1
        write_report(cfg, info)
        summary[cfg["name"]] = {"config": cfg, **info}
        print(f"  cells {info['num_cells']}  flip-flops {info['num_ffs']}  "
              f"combinational {info['num_cells'] - info['num_ffs']}  "
              f"logic depth {info['longest_path']}")

    path = OUT / "summary.json"
    if path.exists() and (args.only or args.quick):
        # A partial run must not throw away the configurations it did not touch.
        merged = json.loads(path.read_text())
        merged.update(summary)
        summary = merged
    path.write_text(json.dumps(summary, indent=1))
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
