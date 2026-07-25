#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Measure the routed netlist's register-to-register Fmax, comparably to `make pdk`.

The problem this solves. `make pdk` reports Fmax by iterating the clock period until
the reg-to-reg slack reaches zero, with wire parasitics estimated by
`set_wire_rc -layer Metal2`. LibreLane reports slack left over at the one period the
design was routed for, under an SDC that also charges a quarter of the period to
input arrival and output setup. Dividing into that slack gives a number that is not
the same measurement: it carries the IO budget, the setup uncertainty and the routed
target all at once, so comparing it against docs/pdk says nothing about what changed.

So the routed netlist is re-timed here under the same constraint style docs/pdk uses,
against the extracted parasitics from the routed design instead of an estimate. Every
difference between the two numbers is then the parasitics and the cells PnR added,
which is the thing worth measuring.

What this is not: a claim that the design would close at the frequency reported. The
netlist was optimised against the period in the LibreLane config and the tool stopped
when it met it, so a tighter target would have produced a different netlist. This is
the routed netlist's own path delay, not the best the flow could do.

Usage:
    scripts/pnr_fmax.py                      # every variant in docs/pnr/summary.json
    scripts/pnr_fmax.py --only iter_q3_29_n28
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "pnr"
BUILD = ROOT / "build" / "pnr-fmax"

PDK = pathlib.Path(os.environ.get(
    "IHP_PDK_ROOT",
    pathlib.Path.home() / ".local/share/pdk/IHP-Open-PDK/ihp-sg13g2"))
STDCELL = PDK / "libs.ref" / "sg13g2_stdcell"
TECH_LEF = STDCELL / "lef" / "sg13g2_tech.lef"
CELL_LEF = STDCELL / "lef" / "sg13g2_stdcell.lef"

# Same three corners and the same Liberty files docs/pdk times at, under the names
# LibreLane gives its own corners so the two can be lined up.
CORNERS = {
    "slow": ("sg13g2_stdcell_slow_1p08V_125C.lib", "nom_slow_1p08V_125C"),
    "typ":  ("sg13g2_stdcell_typ_1p20V_25C.lib",   "nom_typ_1p20V_25C"),
    "fast": ("sg13g2_stdcell_fast_1p65V_m40C.lib", "nom_fast_1p32V_m40C"),
}

# Generous enough that nothing violates, so every path delay is reported rather than
# clipped. Path delays do not depend on the period here: this SDC has no
# period-proportional term in it, which is the whole reason it is used.
PROBE_NS = 60.0

NOISE = re.compile(r"unsupported expression|Warning: .*sdfrbpq")


def sta_script(corner, netlist, spef, top):
    """The docs/pdk constraint style, with extracted parasitics instead of set_wire_rc.

    read_lef twice before read_verilog, tech LEF first: OpenROAD reports
    [ERROR ORD-2010] no technology has been read otherwise.

    `spef` of None substitutes the `set_wire_rc -layer Metal2` estimate docs/pdk uses,
    on the same routed netlist. That is the control: it separates "the estimate's wire
    model is wrong" from "the netlist PnR produced is different", and on this design it
    is the second, since the estimate comes out optimistic rather than pessimistic once
    the netlist is held fixed.
    """
    lib = STDCELL / "lib" / CORNERS[corner][0]
    parasitics = f"read_spef {spef}" if spef else "set_wire_rc -layer Metal2"
    return f"""read_lef {TECH_LEF}
read_lef {CELL_LEF}
read_liberty {lib}
read_verilog {netlist}
link_design {top}
{parasitics}
create_clock -name clk -period {PROBE_NS:.4f} [get_ports clk_i]
set_output_delay 0.0 -clock clk [all_outputs]
set_driving_cell -lib_cell sg13g2_inv_4 [all_inputs]
set_load 0.01 [all_outputs]
puts "@@@WORST [sta::worst_slack_cmd max]"
puts "@@@REGSTART"
report_checks -path_delay max -digits 4 -group_count 1 \
  -from [all_registers -clock_pins] -to [all_registers -data_pins]
puts "@@@REGEND"
puts "@@@HOLD [sta::worst_slack_cmd min]"
"""


def resolve_flop(netlist_text, inst):
    """Name the RTL register a flattened flop instance implements.

    ABC renames every cell to _NNNNN_, but Yosys keeps the original signal name on
    the flop's Q net, so reading that back turns "_15000_" into a register name.
    Same trick scripts/run_pdk.py and scripts/run_pnr.py use.
    """
    if not inst:
        return None
    m = re.search(r"\b\w+\s+" + re.escape(inst) + r"\s*\((.*?)\);", netlist_text, re.S)
    if not m:
        return None
    conns = dict(re.findall(r"\.(\w+)\(([^)]*)\)", m.group(1)))
    q = (conns.get("Q") or conns.get("Q_N") or "").strip().lstrip("\\").strip()
    return q or None


def time_corner(name, corner, netlist, spef, top, tag=""):
    BUILD.mkdir(parents=True, exist_ok=True)
    tcl = BUILD / f"{name}_{corner}{tag}.tcl"
    tcl.write_text(sta_script(corner, netlist, spef, top))
    log = BUILD / f"{name}_{corner}{tag}.log"
    with log.open("w") as fh:
        rc = subprocess.run(["openroad", "-no_init", "-exit", str(tcl)],
                            stdout=fh, stderr=subprocess.STDOUT).returncode
    text = "\n".join(l for l in log.read_text().splitlines() if not NOISE.search(l))
    if rc != 0:
        print(f"  openroad failed for {name} {corner}, see {log}", file=sys.stderr)
        print("\n".join(text.splitlines()[-25:]), file=sys.stderr)
        return None

    body = text.split("@@@REGSTART", 1)[-1].split("@@@REGEND", 1)[0]
    m = re.search(r"([-\d.]+)\s+slack \((MET|VIOLATED)\)", body)
    if not m:
        print(f"  no reg-to-reg path reported for {name} {corner}", file=sys.stderr)
        return None
    slack = float(m.group(1))
    delay = PROBE_NS - slack

    start = end = None
    ms = re.search(r"Startpoint:\s*(\S+)", body)
    me = re.search(r"Endpoint:\s*(\S+)", body)
    nl = pathlib.Path(netlist).read_text()
    if ms:
        start = resolve_flop(nl, ms.group(1)) or ms.group(1)
    if me:
        end = resolve_flop(nl, me.group(1)) or me.group(1)

    cells = re.findall(r"\((sg13g2_\S+?)\)", body)
    hold = re.search(r"@@@HOLD ([-0-9.e+]+)", text)
    return dict(
        corner=corner,
        reg_path_delay_ns=round(delay, 4),
        fmax_mhz=round(1000.0 / delay, 2),
        startpoint=start,
        endpoint=end,
        path_cells=len(cells),
        # Buffers and inverters on the path are what PnR had to add to drive real
        # wires. The synthesis estimate never charged for them.
        path_buffers=sum(1 for c in cells if "buf" in c or c.startswith("sg13g2_inv")),
        overall_hold_slack_ns=(round(float(hold.group(1)) * 1e9, 4) if hold else None),
    )


def routed_inputs(run, top):
    """The routed netlist and the extracted parasitics, wherever the run keeps them.

    A finished run collects both under final/. An unfinished one has them in the step
    that produced them, and everything this script needs is done by step 54, long
    before the signoff DRC stages that dominate the wall clock. So an interrupted run
    is still measurable.
    """
    netlist = run / "final" / "nl" / f"{top}.nl.v"
    if not netlist.exists():
        netlist = next(run.glob("*detailedrouting/*.nl.v"), None)
    spef = next((run / "final" / "spef").rglob("*.spef"), None) \
        if (run / "final" / "spef").is_dir() else None
    if spef is None:
        spef = next(run.glob("*rcx/*/*.spef"), None)
    return netlist, spef


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", default=None)
    args = ap.parse_args(argv)

    spath = OUT / "summary.json"
    if not spath.exists():
        print(f"missing {spath}; run `make pnr` first", file=sys.stderr)
        return 1
    summary = json.loads(spath.read_text())

    names = [n for n in summary if not args.only or n in set(args.only)]
    if not names:
        print(f"no configuration matched {args.only}", file=sys.stderr)
        return 1

    changed = False
    for name in names:
        entry = summary[name]
        run = ROOT / entry["run_dir"]
        top = entry["config"]["top"]
        netlist, spef = routed_inputs(run, top)
        if netlist is None or not netlist.exists() or spef is None:
            print(f"[{name}] no routed netlist or SPEF under {run}; skipping",
                  file=sys.stderr)
            continue

        print(f"[{name}] re-timing the routed netlist against extracted parasitics",
              flush=True)
        got = {}
        for corner in CORNERS:
            r = time_corner(name, corner, netlist, spef, top)
            if r is None:
                continue
            got[corner] = r
            print(f"    {corner:<5} {r['reg_path_delay_ns']:7.3f} ns reg-to-reg "
                  f"-> {r['fmax_mhz']:7.2f} MHz over {r['path_cells']} cells "
                  f"({r['path_buffers']} buffers)", flush=True)
        if not got:
            continue
        print(f"    {got[list(got)[0]]['startpoint']}\n"
              f"    -> {got[list(got)[0]]['endpoint']}", flush=True)
        entry["postroute_fmax"] = got

        # The control. Same routed netlist, same constraints, wire RC estimated the
        # way docs/pdk estimates it instead of extracted. If the estimate were the
        # reason the synthesis Fmax is low, this would come out slow; it comes out
        # fast, which puts the difference in the netlist rather than the wire model.
        ctl = time_corner(name, "slow", netlist, None, top, tag="_wirerc")
        if ctl:
            entry["wire_rc_control"] = {
                "corner": "slow",
                "note": "routed netlist, set_wire_rc -layer Metal2 instead of SPEF",
                "reg_path_delay_ns": ctl["reg_path_delay_ns"],
                "fmax_mhz": ctl["fmax_mhz"],
            }
            ext = got["slow"]["reg_path_delay_ns"]
            print(f"    control: same netlist on set_wire_rc gives "
                  f"{ctl['reg_path_delay_ns']:.3f} ns against {ext:.3f} ns extracted "
                  f"({ext / ctl['reg_path_delay_ns']:.2f}x optimistic)", flush=True)
        changed = True

    if changed:
        spath.write_text(json.dumps(summary, indent=1))
        print(f"wrote {spath.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
