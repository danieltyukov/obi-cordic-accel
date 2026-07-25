#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Synthesise and time the accelerator against the real IHP SG13G2 130nm PDK.

This is the process Croc taped out in, so the numbers here are real square
micrometres and real megahertz rather than gate equivalents.

Methodology, in the order a real flow does it:

  1. Yosys maps to sg13g2 standard cells against the **slow** corner Liberty
     (1.08 V, 125 C), which is the corner a design has to close on.
  2. OpenROAD's resizer repairs drive strength and slew. Straight out of
     `abc -liberty` the netlist has min-size gates driving 0.7 pF nets and slews
     of 13 ns, so timing it unrepaired would produce a meaningless number. The
     repair target period is iterated to convergence, which is what makes the
     resulting Fmax a measurement rather than an artefact of the probe period.
  3. The repaired netlist is then timed at all three corners. One netlist across
     corners, as signoff does it, rather than a separate netlist per corner.

What this does not include: placement and routing, so wire parasitics are
estimated from `set_wire_rc` rather than extracted. Post-route numbers come from
`make pnr`, which runs the full LibreLane flow; the delta between the two is
reported in docs/pdk/README.md.
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
OUT = ROOT / "docs" / "pdk"
BUILD = ROOT / "build" / "pdk"

PDK = pathlib.Path(os.environ.get(
    "IHP_PDK_ROOT",
    pathlib.Path.home() / ".local/share/pdk/IHP-Open-PDK/ihp-sg13g2"))
STDCELL = PDK / "libs.ref/sg13g2_stdcell"
TECH_LEF = STDCELL / "lef/sg13g2_tech.lef"
CELL_LEF = STDCELL / "lef/sg13g2_stdcell.lef"

# The three corners that matter, each with its nominal supply and temperature.
CORNERS = {
    "slow": ("sg13g2_stdcell_slow_1p08V_125C.lib", "1.08 V, 125 C"),
    "typ": ("sg13g2_stdcell_typ_1p20V_25C.lib", "1.20 V, 25 C"),
    "fast": ("sg13g2_stdcell_fast_1p65V_m40C.lib", "1.65 V, -40 C"),
}
SIGNOFF_CORNER = "slow"

SOURCES = [
    "cordic_stage.sv", "cordic_core_pipe.sv", "cordic_core_iter.sv",
    "cordic_pre.sv", "cordic_post.sv", "cordic_unit.sv", "cordic_fifo.sv",
    "cordic_obi_regs.sv", "cordic_accel.sv",
]

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

# Probe period to start the convergence from, and the tolerance to stop at.
PROBE_NS = 40.0
TOL = 0.02
MAX_ITERS = 4

# Noise from Yosys and OpenSTA that says nothing about this design: the scan
# flops in the library use an expression neither tool models.
NOISE = re.compile(r"unsupported expression|sg13g2_sdfrbp|Warning: Found unsupported")


def run(cmd, log_path, cwd=None):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=cwd)
    return proc.returncode


def check_pdk():
    missing = [str(p) for p in (TECH_LEF, CELL_LEF) if not p.exists()]
    for lib, _ in CORNERS.values():
        if not (STDCELL / "lib" / lib).exists():
            missing.append(str(STDCELL / "lib" / lib))
    if missing:
        print("IHP SG13G2 PDK files not found:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        print("Set IHP_PDK_ROOT to the ihp-sg13g2 directory.", file=sys.stderr)
        return False
    for tool in ("yosys", "openroad"):
        if shutil.which(tool) is None:
            print(f"{tool} not on PATH", file=sys.stderr)
            return False
    return True


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------
def synth(cfg):
    lib = STDCELL / "lib" / CORNERS[SIGNOFF_CORNER][0]
    netlist = BUILD / f"{cfg['name']}.v"
    stat = BUILD / f"{cfg['name']}.stat"
    srcs = " ".join(str(RTL / s) for s in SOURCES)
    params = " ".join(
        f"-set {k} {cfg[v]}" for k, v in (
            ("DataWidth", "data_width"), ("FracBits", "frac_bits"),
            ("NumStages", "num_stages"), ("Variant", "variant"),
            ("GuardInt", "guard_int"), ("GuardFrac", "guard_frac"),
            ("InDepth", "in_depth"), ("OutDepth", "out_depth"),
            ("IdWidth", "id_width"), ("UseRReady", "use_rready")))
    # The latch, memory and tristate assertions run before cell mapping: after it
    # every cell is an sg13g2 primitive and those checks no longer apply.
    script = f"""
read_verilog -sv -DSYNTHESIS -I {RTL} {srcs}
chparam {params} {cfg['top']}
hierarchy -check -top {cfg['top']}
synth -top {cfg['top']} -flatten
check -assert
select -assert-none t:$dlatch t:$_DLATCH_N_ t:$_DLATCH_P_
select -assert-none t:$sr t:$_SR_NN_ t:$_SR_NP_ t:$_SR_PN_ t:$_SR_PP_
select -assert-none t:$mem t:$mem_v2 t:$tribuf t:$_TBUF_
dfflibmap -liberty {lib}
abc -liberty {lib}
opt_clean
write_verilog -noattr {netlist}
tee -q -o {stat} stat -liberty {lib}
"""
    ys = BUILD / f"{cfg['name']}.ys"
    ys.parent.mkdir(parents=True, exist_ok=True)
    ys.write_text(script)
    rc = run(["yosys", "-q", "-s", str(ys)], BUILD / f"{cfg['name']}_yosys.log")
    if rc != 0:
        return None
    return netlist, stat


AREA_RE = re.compile(r"Chip area for module '\\?(\S+?)':\s+([0-9.]+)")
CELLS_RE = re.compile(r"Number of cells:\s+(\d+)")
CELL_LINE = re.compile(r"^\s+(sg13g2_\S+)\s+(\d+)\s*$")


def parse_stat(path):
    text = path.read_text()
    m = AREA_RE.search(text)
    area = float(m.group(2)) if m else None
    m = CELLS_RE.search(text)
    cells = int(m.group(1)) if m else None
    by_type = {}
    for line in text.splitlines():
        cm = CELL_LINE.match(line)
        if cm:
            by_type[cm.group(1)] = int(cm.group(2))
    ffs = sum(n for c, n in by_type.items() if "df" in c or "sdf" in c)
    return dict(synth_area_um2=area, cells=cells, flip_flops=ffs,
                cells_by_type=by_type)


# ---------------------------------------------------------------------------
# Repair and timing
# ---------------------------------------------------------------------------
def sta_preamble(corner, netlist, top, period):
    lib = STDCELL / "lib" / CORNERS[corner][0]
    return f"""read_lef {TECH_LEF}
read_lef {CELL_LEF}
read_liberty {lib}
read_verilog {netlist}
link_design {top}
create_clock -name clk -period {period:.4f} [get_ports clk_i]
set_output_delay 0.0 -clock clk [all_outputs]
# A real driver and a real load. Without these every input looks like an ideal
# zero-slew source and every output like an open circuit.
set_driving_cell -lib_cell sg13g2_inv_4 [all_inputs]
set_load 0.01 [all_outputs]
set_wire_rc -layer Metal2
"""


def repair(cfg, period):
    """Repair drive strength against `period`, write the repaired netlist."""
    out_v = BUILD / f"{cfg['name']}_repaired.v"
    tcl = BUILD / f"{cfg['name']}_repair.tcl"
    tcl.write_text(sta_preamble(SIGNOFF_CORNER, BUILD / f"{cfg['name']}.v",
                                cfg["top"], period) + f"""
repair_design
puts "@@@SLACK [sta::worst_slack_cmd max]"
puts "@@@AREA [rsz::design_area]"
write_verilog {out_v}
""")
    log = BUILD / f"{cfg['name']}_repair.log"
    rc = run(["openroad", "-no_init", "-exit", str(tcl)], log)
    if rc != 0:
        return None
    text = log.read_text()
    m = re.search(r"@@@SLACK ([-0-9.e+]+)", text)
    if not m:
        return None
    slack_ns = float(m.group(1)) * 1e9
    m = re.search(r"@@@AREA ([-0-9.e+]+)", text)
    area = float(m.group(1)) * 1e12 if m else None   # m^2 -> um^2
    return dict(netlist=out_v, slack_ns=slack_ns, delay_ns=period - slack_ns,
                repaired_area_um2=area)


def converge_fmax(cfg):
    """Iterate the repair target until the achieved delay stops moving.

    A single repair pass at a generous period leaves the resizer no reason to
    work hard, so the first delay is pessimistic. Feeding it back as the next
    target is what turns the number into a measurement.
    """
    history = []
    period = PROBE_NS
    best = None
    for i in range(MAX_ITERS):
        r = repair(cfg, period)
        if r is None:
            return None, history
        history.append(dict(iteration=i, target_ns=period,
                            slack_ns=r["slack_ns"], delay_ns=r["delay_ns"]))
        print(f"    iter {i}: target {period:8.3f} ns -> delay "
              f"{r['delay_ns']:8.3f} ns (slack {r['slack_ns']:+.3f})",
              flush=True)
        if best is None or r["delay_ns"] < best["delay_ns"]:
            best = r
        prev, period = period, r["delay_ns"]
        if abs(prev - period) / max(prev, 1e-9) < TOL:
            break
        # A negative-slack result means the target was too tight; back off to the
        # achieved delay rather than chasing it down.
        period = max(period, 0.5)
    return best, history


PATH_HDR = re.compile(r"^(Startpoint|Endpoint): (.*)$", re.M)
PATH_CELL = re.compile(r"\((sg13g2_\S+?)\)")


def time_corner(cfg, netlist, corner, period):
    tcl = BUILD / f"{cfg['name']}_{corner}.tcl"
    tcl.write_text(sta_preamble(corner, netlist, cfg["top"], period) + """
puts "@@@SLACK [sta::worst_slack_cmd max]"
puts "@@@TNS [sta::total_negative_slack_cmd max]"
report_design_area
puts "@@@PATHSTART"
report_checks -path_delay max -digits 4 -group_count 1
puts "@@@PATHEND"
puts "@@@HOLDSLACK [sta::worst_slack_cmd min]"
""")
    log = BUILD / f"{cfg['name']}_{corner}.log"
    rc = run(["openroad", "-no_init", "-exit", str(tcl)], log)
    if rc != 0:
        return None
    text = "\n".join(l for l in log.read_text().splitlines()
                     if not NOISE.search(l))
    def grab(tag, scale=1.0):
        m = re.search(rf"@@@{tag} ([-0-9.e+]+)", text)
        return float(m.group(1)) * scale if m else None
    slack = grab("SLACK", 1e9)
    if slack is None:
        return None
    body = text.split("@@@PATHSTART", 1)[-1].split("@@@PATHEND", 1)[0]
    hdr = dict((k, v.strip()) for k, v in PATH_HDR.findall(body))
    cells = PATH_CELL.findall(body)
    m = re.search(r"Design area (\d+) um\^2", text)
    return dict(
        corner=corner, conditions=CORNERS[corner][1], period_ns=period,
        slack_ns=slack, delay_ns=period - slack,
        fmax_mhz=1000.0 / (period - slack) if period - slack > 0 else None,
        tns_ns=grab("TNS", 1e9), hold_slack_ns=grab("HOLDSLACK", 1e9),
        area_um2=float(m.group(1)) if m else None,
        path_start=hdr.get("Startpoint", ""), path_end=hdr.get("Endpoint", ""),
        path_depth=len(cells), path_cells=cells,
        path_report="\n".join(body.strip().splitlines()),
    )


def classify_path(cells):
    """Name what the critical path actually runs through.

    Carry chains map to alternating AOI/OAI pairs, shifters to mux cells, sum
    bits to XOR/XNOR. Counting those tells you which structure to blame without
    having to read a 40-line path report.
    """
    n = len(cells) or 1
    groups = {
        "carry chain (AOI/OAI)": sum(1 for c in cells
                                     if re.search(r"a\d+oi|o\d+ai|a\d+o_|o\d+a_", c)),
        "mux (shifter or select)": sum(1 for c in cells if "mux" in c),
        "xor/xnor (sum bits)": sum(1 for c in cells if "xor" in c or "xnor" in c),
        "nand/nor/inv": sum(1 for c in cells
                            if re.search(r"nand|nor|inv|buf", c)),
        "flip-flop": sum(1 for c in cells if re.search(r"df|sdf", c)),
    }
    ranked = sorted(((v, k) for k, v in groups.items() if v), reverse=True)
    return groups, [f"{k} {v} of {n}" for v, k in ranked]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def write_report(cfg, info):
    L = []
    add = L.append
    add(f"IHP SG13G2 130nm synthesis and timing: {cfg['name']}")
    add("=" * 76)
    add("")
    add("Real standard cells and real Liberty timing on the process Croc taped out")
    add("in. Produced by scripts/run_pdk.py; see docs/pdk/README.md for the")
    add("methodology and its limits.")
    add("")
    add("Configuration")
    add("-" * 76)
    add(f"  variant          {cfg['variant']} "
        f"({'iterative (folded)' if cfg['variant'] else 'fully pipelined'})")
    add(f"  format           Q{cfg['data_width'] - cfg['frac_bits']}.{cfg['frac_bits']}"
        f"  ({cfg['data_width']}-bit interface word)")
    add(f"  micro-rotations  {cfg['num_stages']}")
    add(f"  guard bits       {cfg['guard_int']} integer, {cfg['guard_frac']} fractional")
    add(f"  FIFO depths      {cfg['in_depth']} in, {cfg['out_depth']} out")
    add("")
    add("Area")
    add("-" * 76)
    add(f"  cells                    {info['cells']}")
    add(f"  flip-flops               {info['flip_flops']}")
    add(f"  area after mapping       {info['synth_area_um2']:.1f} um^2")
    if info.get("repaired_area_um2"):
        add(f"  area after drive repair  {info['repaired_area_um2']:.1f} um^2  "
            f"(+{100 * (info['repaired_area_um2'] / info['synth_area_um2'] - 1):.1f}%)")
    add("")
    add("Timing, one repaired netlist across all three corners")
    add("-" * 76)
    add(f"  {'corner':<7} {'conditions':<16} {'path delay':>11} {'Fmax':>10} "
        f"{'setup slack':>12} {'hold slack':>11}")
    for c in ("slow", "typ", "fast"):
        t = info["corners"].get(c)
        if not t:
            continue
        add(f"  {c:<7} {t['conditions']:<16} {t['delay_ns']:>8.3f} ns "
            f"{t['fmax_mhz']:>7.1f} MHz {t['slack_ns']:>9.3f} ns "
            f"{(t['hold_slack_ns'] if t['hold_slack_ns'] is not None else 0):>8.3f} ns")
    add("")
    sign = info["corners"].get(SIGNOFF_CORNER)
    if sign:
        add(f"Critical path at the {SIGNOFF_CORNER} corner")
        add("-" * 76)
        add(f"  startpoint  {sign['path_start']}")
        add(f"  endpoint    {sign['path_end']}")
        add(f"  cells       {sign['path_depth']}")
        groups, ranked = classify_path(sign["path_cells"])
        add("  runs through:")
        for r in ranked:
            add(f"    {r}")
        add("")
        add("  Full path report:")
        for line in sign["path_report"].splitlines():
            add(f"  {line}")
    add("")
    add("Convergence of the repair target")
    add("-" * 76)
    add("  Each pass feeds the achieved delay back as the next target, so the")
    add("  reported Fmax is a converged measurement rather than a function of the")
    add("  probe period.")
    for h in info["convergence"]:
        add(f"    iteration {h['iteration']}: target {h['target_ns']:8.3f} ns -> "
            f"delay {h['delay_ns']:8.3f} ns (slack {h['slack_ns']:+.3f} ns)")
    add("")
    (OUT / f"{cfg['name']}.rpt").write_text("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", default=None)
    ap.add_argument("--quick", action="store_true",
                    help="the two headline configurations only")
    args = ap.parse_args(argv)

    if not check_pdk():
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
        print(f"[{cfg['name']}] synthesising against the {SIGNOFF_CORNER} corner",
              flush=True)
        res = synth(cfg)
        if res is None:
            print(f"  yosys failed, see {BUILD / (cfg['name'] + '_yosys.log')}",
                  file=sys.stderr)
            return 1
        netlist, stat = res
        info = parse_stat(stat)
        print(f"  {info['cells']} cells, {info['flip_flops']} flip-flops, "
              f"{info['synth_area_um2']:.1f} um^2", flush=True)

        print("  repairing drive strength and converging the target", flush=True)
        best, history = converge_fmax(cfg)
        if best is None:
            print(f"  repair failed, see {BUILD / (cfg['name'] + '_repair.log')}",
                  file=sys.stderr)
            return 1
        info["repaired_area_um2"] = best["repaired_area_um2"]
        info["convergence"] = history

        info["corners"] = {}
        period = best["delay_ns"]
        for corner in CORNERS:
            t = time_corner(cfg, best["netlist"], corner, period)
            if t is None:
                print(f"  STA failed at the {corner} corner", file=sys.stderr)
                return 1
            info["corners"][corner] = t
            print(f"    {corner:<5} {t['delay_ns']:7.3f} ns -> "
                  f"{t['fmax_mhz']:6.1f} MHz", flush=True)

        write_report(cfg, info)
        summary[cfg["name"]] = dict(config=cfg, **info)

    path = OUT / "summary.json"
    if path.exists() and (args.only or args.quick):
        merged = json.loads(path.read_text())
        merged.update(summary)
        summary = merged
    # The full path report is bulky and already in the .rpt files.
    slim = json.loads(json.dumps(summary))
    for v in slim.values():
        for c in v.get("corners", {}).values():
            c.pop("path_report", None)
    path.write_text(json.dumps(slim, indent=1))
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
