#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Place and route both variants through LibreLane on the IHP SG13G2 PDK.

What this adds over `make pdk`, which stops after synthesis:

  - post-route die area per variant, so the synthesis-to-route inflation can be
    measured. The pipelined variant has four times the registers of the folded
    one and far more wiring, so the two do not inflate by the same factor, and a
    synthesis-only comparison flatters the pipelined design.
  - signoff: the router's own DRC iterated to convergence, the Magic runset, the
    KLayout sg13g2 runset, an XOR of Magic's streamed-out GDS against KLayout's,
    and netgen LVS of the extracted layout against the post-route netlist. See
    docs/pnr/README.md.
  - a GDS, which scripts/render_gds.py turns into a layout figure.
  - post-route timing at all three corners, with extracted parasitics instead of
    the set_wire_rc estimate `make pdk` has to use, and the post-route critical
    path resolved back to RTL register names.

On post-route timing: it is real, but it is not the same measurement as the Fmax
in docs/pdk. This flow closes on one fixed target period and reports the slack
left over; `make pdk` iterates the period until the slack is zero. Slack at a
fixed period implies a frequency, but only under the assumption that a tighter
target would not have made the tool choose differently, which it would. The two
numbers are reported side by side and labelled, not merged.

The worst path overall is always an IO path here, because the SDC charges a
quarter of the period to input arrival and output setup. The reg-to-reg path is
the one that describes the logic, so that is what gets resolved and classified.
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
PNR = ROOT / "pnr"
OUT = ROOT / "docs" / "pnr"
BUILD = ROOT / "build" / "pnr"

SOURCES = [
    "cordic_stage.sv", "cordic_core_pipe.sv", "cordic_core_iter.sv",
    "cordic_pre.sv", "cordic_post.sv", "cordic_unit.sv", "cordic_fifo.sv",
    "cordic_obi_regs.sv", "cordic_accel.sv",
]

# Clock periods come from what `make pdk` actually measured at the slow corner,
# rounded up. Asking PnR to close on a period synthesis cannot reach wastes an
# hour and produces a violated run.
CONFIGS = [
    dict(name="pipe_q3_29_n28", variant=0, data_width=32, frac_bits=29,
         num_stages=28, period_ns=18.0, util=35, top="cordic_pnr_pipe"),
    dict(name="iter_q3_29_n28", variant=1, data_width=32, frac_bits=29,
         num_stages=28, period_ns=22.0, util=40, top="cordic_pnr_iter"),
]
DEFAULTS = dict(guard_int=2, guard_frac=4, in_depth=4, out_depth=4)

# Leave a couple of cores for everything else.
THREADS = max(1, (os.cpu_count() or 4) - 2)

# The metrics worth extracting from LibreLane's flat metrics dict.
METRICS = [
    "design__instance__count",
    "design__instance__area",
    "design__die__area",
    "design__core__area",
    "design__instance__utilization",
    "timing__setup__ws",
    "timing__hold__ws",
    "timing__setup__tns",
    # LibreLane's mid-PnR STA runs the default corner only; the post-route signoff
    # STA runs everything in STA_CORNERS, which for sg13g2 is all three. The slow
    # corner is the one a design has to close on, so it is the number worth quoting.
    "timing__setup__ws__corner:nom_slow_1p08V_125C",
    "timing__hold__ws__corner:nom_slow_1p08V_125C",
    "timing__setup__ws__corner:nom_typ_1p20V_25C",
    "timing__hold__ws__corner:nom_typ_1p20V_25C",
    "timing__setup__ws__corner:nom_fast_1p32V_m40C",
    "timing__hold__ws__corner:nom_fast_1p32V_m40C",
    # `stdcell` is everything but the fill, which is the number to compare against a
    # synthesis area. `class:standard_cell` says the same thing but only appears in
    # the per-step metrics, not in final/metrics.json, so both are collected and the
    # figures fall back from one to the other.
    "design__instance__area__stdcell",
    "design__instance__count__stdcell",
    "design__instance__area__class:standard_cell",
    "design__instance__area__class:fill_cell",
    "design__instance__count__class:standard_cell",
    # The breakdown is what explains post-route growth rather than just recording it:
    # a clock tree, the buffers the resizer added to meet timing, and the registers
    # themselves are separable, and they do not scale the same way with variant.
    "design__instance__area__class:sequential_cell",
    "design__instance__area__class:multi_input_combinational_cell",
    "design__instance__area__class:clock_buffer",
    "design__instance__area__class:clock_inverter",
    "design__instance__area__class:timing_repair_buffer",
    "design__instance__area__class:inverter",
    "route__drc_errors",
    "route__wirelength",
    "magic__drc_error__count",
    # Magic and KLayout each stream out a GDS independently and the flow XORs them.
    # A non-zero difference means the two tools disagree about what the layout is,
    # which would make every other number here suspect.
    "design__xor_difference__count",
    # The Classic flow for ihp-sg13g2 runs KLayout's DRC runset as well as Magic's,
    # and netgen LVS of the extracted layout against the post-route netlist. Both
    # land near the end, after the DRC stages that take the longest, so a run that is
    # interrupted holds valid routing numbers with these still null. Null is reported
    # rather than dropped, because "no LVS number" and "LVS passed" are different
    # claims and the README has to say which one it is quoting.
    "klayout__drc_error__count",
    "design__lvs_error__count",
    "design__lvs_device_difference__count",
    "design__lvs_net_difference__count",
    "design__lvs_unmatched_device__count",
    "design__lvs_unmatched_net__count",
    "design__lvs_unmatched_pin__count",
    "antenna__violating__nets",
    "power__total",
]


WRAPPER_TEMPLATE = """// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// GENERATED by scripts/run_pnr.py for the {name} configuration.
//
// LibreLane drives synthesis without exposing Yosys's chparam, so the parameters
// are fixed by wrapping cordic_accel rather than by overriding them. A wrapper
// keeps the RTL free of flow-specific defines, and since it only passes ports
// through it adds nothing to place and route.

module {top} (
  input  logic clk_i,
  input  logic rst_ni,

  input  logic                 obi_req_i,
  output logic                 obi_gnt_o,
  input  logic [31:0]          obi_addr_i,
  input  logic                 obi_we_i,
  input  logic [3:0]           obi_be_i,
  input  logic [31:0]          obi_wdata_i,
  input  logic [2:0]           obi_aid_i,
  output logic                 obi_rvalid_o,
  input  logic                 obi_rready_i,
  output logic [31:0]          obi_rdata_o,
  output logic [2:0]           obi_rid_o,
  output logic                 obi_err_o,

  output logic                 irq_o,

  input  logic                 str_in_valid_i,
  output logic                 str_in_ready_o,
  input  logic [4:0]           str_in_func_i,
  input  logic [7:0]           str_in_tag_i,
  input  logic signed [{dw_m1}:0] str_in_x_i,
  input  logic signed [{dw_m1}:0] str_in_y_i,
  input  logic signed [{dw_m1}:0] str_in_z_i,

  output logic                 str_out_valid_o,
  input  logic                 str_out_ready_i,
  output logic signed [{dw_m1}:0] str_out_x_o,
  output logic signed [{dw_m1}:0] str_out_y_o,
  output logic signed [{dw_m1}:0] str_out_z_o,
  output logic [3:0]           str_out_flags_o,
  output logic [4:0]           str_out_func_o,
  output logic [7:0]           str_out_tag_o
);

  // The observation ports exist for the testbench and the documentation figures.
  // A real integration leaves them unconnected, so they are terminated here and
  // marked as a false path in pnr/cordic.sdc.
  logic [{ns}:0]        unused_stage_valid;
  logic                 unused_iter_valid;
  logic [7:0]           unused_iter_idx;
  logic signed [{iw_m1}:0] unused_iter_x, unused_iter_y, unused_iter_z;

  cordic_accel #(
    .DataWidth ({dw}),
    .FracBits  ({fb}),
    .NumStages ({ns}),
    .Variant   ({variant}),
    .GuardInt  ({gi}),
    .GuardFrac ({gf}),
    .InDepth   ({ind}),
    .OutDepth  ({outd}),
    .AddrWidth (32),
    .IdWidth   (3),
    .UseRReady (0)
  ) i_accel (
    .clk_i, .rst_ni,
    .obi_req_i, .obi_gnt_o, .obi_addr_i, .obi_we_i, .obi_be_i, .obi_wdata_i,
    .obi_aid_i, .obi_rvalid_o, .obi_rready_i, .obi_rdata_o, .obi_rid_o,
    .obi_err_o, .irq_o,
    .str_in_valid_i, .str_in_ready_o, .str_in_func_i, .str_in_tag_i,
    .str_in_x_i, .str_in_y_i, .str_in_z_i,
    .str_out_valid_o, .str_out_ready_i, .str_out_x_o, .str_out_y_o,
    .str_out_z_o, .str_out_flags_o, .str_out_func_o, .str_out_tag_o,
    .dbg_stage_valid_o (unused_stage_valid),
    .dbg_iter_valid_o  (unused_iter_valid),
    .dbg_iter_idx_o    (unused_iter_idx),
    .dbg_iter_x_o      (unused_iter_x),
    .dbg_iter_y_o      (unused_iter_y),
    .dbg_iter_z_o      (unused_iter_z)
  );

endmodule
"""


def write_wrapper(cfg, path):
    dw = cfg["data_width"]
    iw = dw + cfg["guard_int"] + cfg["guard_frac"]
    path.write_text(WRAPPER_TEMPLATE.format(
        name=cfg["name"], top=cfg["top"], dw=dw, dw_m1=dw - 1,
        iw_m1=iw - 1, fb=cfg["frac_bits"], ns=cfg["num_stages"],
        variant=cfg["variant"], gi=cfg["guard_int"], gf=cfg["guard_frac"],
        ind=cfg["in_depth"], outd=cfg["out_depth"]))


INCLUDES = ["cordic_rom.svh", "cordic_regmap.svh", "cordic_defs.svh",
            "cordic_rom_fx.svh"]


def stage_rtl(work):
    """Copy the RTL next to the config.

    LibreLane refuses to read anything outside the config's own directory tree, so
    dir::../../../rtl is rejected outright. Staging a copy is simpler than arguing
    with it, and it also pins exactly which sources a run used.
    """
    dst = work / "rtl"
    dst.mkdir(parents=True, exist_ok=True)
    for f in SOURCES + INCLUDES:
        shutil.copy(RTL / f, dst / f)
    return dst


def config_for(cfg):
    """LibreLane config. Only keys the flow is known to accept, so an unknown-key
    error cannot waste a run."""
    files = [f"dir::rtl/{s}" for s in SOURCES]
    files.append(f"dir::{cfg['top']}.sv")
    return {
        "DESIGN_NAME": cfg["top"],
        "VERILOG_FILES": files,
        "VERILOG_INCLUDE_DIRS": ["dir::rtl"],
        "VERILOG_DEFINES": ["SYNTHESIS"],
        "CLOCK_PORT": "clk_i",
        "CLOCK_PERIOD": cfg["period_ns"],
        "PNR_SDC_FILE": "dir::cordic.sdc",
        "SIGNOFF_SDC_FILE": "dir::cordic.sdc",
        "FP_CORE_UTIL": cfg["util"],
        "PL_TARGET_DENSITY_PCT": cfg["util"] + 10,
        "PDK": "ihp-sg13g2",
        # Hold repair on a design with this many short register-to-register paths
        # needs more headroom than the default allows; the first attempt died on
        # [RSZ-0060] Max buffer count reached.
        "RSZ_HOLD_MAX_BUFFER_PCT": 75,
        "RSZ_HOLD_SLACK_MARGIN": 0.05,
        # KLAYOUT_DRC_THREADS and KLAYOUT_XOR_THREADS default to unset, which means
        # single-threaded. On a 30k-instance design the maximal sg13g2 DRC runset
        # then takes longer than the other 78 stages put together; the first attempt
        # sat in it for over half an hour. Threading it is the whole fix.
        "KLAYOUT_DRC_THREADS": THREADS,
        "KLAYOUT_XOR_THREADS": THREADS,
    }


def latest_run(run_dir):
    runs = sorted(run_dir.glob("RUN_*"))
    return runs[-1] if runs else None


def harvest(run):
    """Collect metrics from final/metrics.json, or from the per-step files.

    LibreLane writes final/metrics.json only when every stage completes, and the
    signoff DRC stages are slow enough that a run can hold real, finished results
    while still working. Falling back to the per-step files means a stalled or
    aborted signoff does not throw away routing and timing numbers that are
    already valid.

    Two per-step files matter and only one of them is obvious. `or_metrics_out.json`
    is what an OpenROAD step reports on its own, but the post-route signoff STA does
    not write one, so reading only those loses every per-corner slack and the summary
    ends up with nulls where the three signoff corners should be. `state_out.json`
    carries the cumulative metrics dict LibreLane threads through the flow, which is
    what final/metrics.json is a copy of, so it has them. Steps are read in order and
    later ones win, the same precedence the final file would have.
    """
    final = run / "final" / "metrics.json"
    if final.exists():
        return json.loads(final.read_text())

    merged = {}
    # Step directories are zero-padded ("01-" ... "75-"), so a lexical sort is the
    # flow order.
    for step in sorted(p for p in run.iterdir() if p.is_dir()):
        for name, key in (("or_metrics_out.json", None), ("state_out.json", "metrics")):
            path = step / name
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if key is not None:
                data = data.get(key) or {}
            merged.update(data)
    if merged:
        merged["_source"] = ("per-step or_metrics_out.json and state_out.json, "
                             "flow did not reach final")
    return merged


SIGNOFF_CORNER = "nom_slow_1p08V_125C"
CORNERS = ["nom_slow_1p08V_125C", "nom_typ_1p20V_25C", "nom_fast_1p32V_m40C"]


def resolve_flop(netlist_text, inst):
    """Name the RTL register a flattened flop instance implements.

    Same trick scripts/run_pdk.py uses: ABC renames every cell to _NNNNN_, but
    Yosys keeps the original signal name on the flop's Q net, so reading that back
    turns "_85582_" into a real register name.
    """
    m = re.search(r"\b\w+\s+" + re.escape(inst) + r"\s*\((.*?)\);",
                  netlist_text, re.S)
    if not m:
        return None
    conns = dict(re.findall(r"\.(\w+)\(([^)]*)\)", m.group(1)))
    q = (conns.get("Q") or conns.get("Q_N") or "").strip().lstrip("\\").strip()
    return q or None


def worst_reg_path(run, corner=SIGNOFF_CORNER):
    """Pull the worst register-to-register setup path out of the signoff STA.

    Three details make the difference between a diagnostic number and a misleading
    one. First, both ends have to be flops: the worst path overall is an IO path
    whose delay is mostly the SDC's own input-arrival budget, and taking the first
    flop-launched path instead picks up register-to-output paths, which carry the
    output setup budget. That is not a hypothetical, it is what this function used to
    do, and at the typ and fast corners it silently reported a reg-to-output slack
    3.3 ns off the real reg-to-reg one. Second, the worst such path has to be searched
    for rather than assumed first, since the report is ordered by slack over all path
    groups. Third, the clock network appears on both the launch and the capture edge
    of every path report, so the clock-tree buffers have to be dropped or a 43-cell
    datapath reads as 60-odd cells that are mostly buffers.
    """
    rpt = next(run.glob(f"*stapostpnr/{corner}/max.rpt"), None)
    if rpt is None:
        return None
    blk = start = end = slack = None
    for b in rpt.read_text().split("Startpoint:")[1:]:
        head = b.splitlines()[0]
        if "edge-triggered flip-flop" not in head:
            continue
        m = re.search(r"Endpoint:\s*(\S+)\s*\(([^)]*)\)", b)
        if not m or "edge-triggered flip-flop" not in m.group(2):
            continue
        ms = re.search(r"([-\d.]+)\s+slack \((MET|VIOLATED)\)", b)
        if not ms:
            continue
        s = float(ms.group(1))
        if slack is None or s < slack:
            blk, slack, start, end = b, s, head.split("(")[0].strip(), m.group(1)
    if blk is None:
        return None

    cells = []
    for ln in blk.splitlines():
        m = re.search(r"\s(\S+)/(\S+)\s+\((sg13g2_\S+)\)", ln)
        if not m:
            continue
        inst, pin, cell = m.groups()
        if inst.startswith(("clkbuf", "clkload")):
            continue
        if pin in ("X", "Y", "Q", "CLK"):
            continue       # each instance appears twice; count it at its input pin
        cells.append(cell)

    nl = next(run.glob("*detailedrouting/*.nl.v"), None) or \
        next(run.glob("*detailedplacement/*.nl.v"), None)
    text = nl.read_text() if nl else ""
    return {
        "corner": corner,
        "slack_ns": slack,
        "cells": len(cells),
        # `fanout*` and `buf`/`inv` cells on the path are what PnR had to add to
        # drive real wires. Synthesis never charged for them.
        "buffers": sum(1 for c in cells if "buf" in c or c.startswith("sg13g2_inv")),
        "startpoint": resolve_flop(text, start) or start,
        "endpoint": resolve_flop(text, end) or end,
        "cell_histogram": {c: cells.count(c) for c in sorted(set(cells))},
    }


def reg_slack_per_corner(run):
    """Worst reg-to-reg setup slack at each corner.

    LibreLane's metrics carry only the overall worst slack per corner, and here that
    is always an IO path, because the SDC charges a quarter of the period to input
    arrival and output setup. Comparing that against the Fmax in docs/pdk would be
    comparing two different things, since `make pdk` measures register to register.
    So the reg-to-reg number is read out of the path reports instead.
    """
    out = {}
    for corner in CORNERS:
        info = worst_reg_path(run, corner)
        if info and info["slack_ns"] is not None:
            out[corner] = info["slack_ns"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", default=None)
    ap.add_argument("--harvest-only", action="store_true",
                    help="re-summarise the newest existing run without routing again")
    # Routing the two variants in parallel needs them in separate trees, because
    # LibreLane stages the RTL and the config next to each other and a second driver
    # writing into a live work directory would pull them out from under the first.
    # The pipelined variant spends hours in single-threaded Magic DRC, during which
    # nothing else in a sequential run can start.
    ap.add_argument("--build-dir", default=None,
                    help="work tree for this invocation, default build/pnr. Must be "
                         "passed to --harvest-only for the same run as well.")
    args = ap.parse_args(argv)

    global BUILD
    if args.build_dir:
        BUILD = pathlib.Path(args.build_dir)
        if not BUILD.is_absolute():
            BUILD = ROOT / BUILD

    if shutil.which("librelane") is None and not args.harvest_only:
        print("librelane not on PATH", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)

    configs = [dict(DEFAULTS, **c) for c in CONFIGS]
    if args.only:
        wanted = set(args.only)
        configs = [c for c in configs if c["name"] in wanted]
        if not configs:
            print(f"no configuration matched {sorted(wanted)}", file=sys.stderr)
            return 1

    summary = {}
    for cfg in configs:
        work = BUILD / cfg["name"]
        log = BUILD / f"{cfg['name']}.log"

        # --harvest-only exists because the metric list grows faster than a routing
        # run finishes. Re-reading a completed run costs a second; repeating it costs
        # hours, and would produce a different layout from the one already rendered.
        if args.harvest_only:
            print(f"[{cfg['name']}] harvesting the newest existing run", flush=True)
            if log.exists() and "fallback SDC" in log.read_text():
                print("  WARNING: that run fell back to a generic SDC; its timing is "
                      "not trustworthy", file=sys.stderr)
        else:
            work.mkdir(parents=True, exist_ok=True)
            # Both live next to the config, since dir:: resolves relative to it.
            shutil.copy(PNR / "cordic.sdc", work / "cordic.sdc")
            stage_rtl(work)
            write_wrapper(cfg, work / f"{cfg['top']}.sv")
            cfg_path = work / "config.json"
            cfg_path.write_text(json.dumps(config_for(cfg), indent=1))

            print(f"[{cfg['name']}] place and route at {cfg['period_ns']} ns, "
                  f"utilisation {cfg['util']}%", flush=True)
            with log.open("w") as fh:
                rc = subprocess.run(["librelane", "config.json"], cwd=work,
                                    stdout=fh, stderr=subprocess.STDOUT).returncode
            text = log.read_text()
            if "fallback SDC" in text:
                print("  WARNING: LibreLane fell back to a generic SDC; timing from "
                      "this run is not trustworthy", file=sys.stderr)
            if rc != 0:
                print(f"  librelane failed, see {log}", file=sys.stderr)
                tail = "\n".join(text.splitlines()[-40:])
                print(tail, file=sys.stderr)
                return 1

        run = latest_run(work / "runs")
        if run is None:
            print(f"  no run directory under {work / 'runs'}", file=sys.stderr)
            return 1
        metrics = harvest(run)
        if not metrics:
            print(f"  no metrics found under {run}", file=sys.stderr)
            return 1
        picked = {k: metrics.get(k) for k in METRICS}
        picked["run_dir"] = str(run.relative_to(ROOT))
        # Carried explicitly, since it is not one of METRICS. A reader has to be able
        # to tell a metric the flow computed from one it never got to, and a null in
        # magic__drc_error__count means opposite things in those two cases.
        if metrics.get("_source"):
            picked["_source"] = metrics["_source"]
        picked["config"] = cfg
        wpath = worst_reg_path(run)
        if wpath:
            picked["worst_reg_path"] = wpath
            picked["reg_setup_slack_ns"] = reg_slack_per_corner(run)
            print(f"    worst reg-to-reg at the slow corner: "
                  f"{wpath['slack_ns']:+.3f} ns over {wpath['cells']} cells "
                  f"({wpath['buffers']} of them buffers)", flush=True)
            print(f"      {wpath['startpoint']}\n      -> {wpath['endpoint']}",
                  flush=True)
        summary[cfg["name"]] = picked

        gds = next((run / "final" / "gds").glob("*.gds"), None) \
            if (run / "final" / "gds").is_dir() else None
        # An unfinished run has the streamed-out GDS in the step that wrote it, which
        # lands well before the signoff DRC stages that take the longest. Magic's
        # stream-out is the one the flow carries forward, so the plain name is taken
        # ahead of the .magic. and .klayout. copies beside it.
        if gds is None:
            for pat in ("*magic-streamout/*.gds", "*klayout-streamout/*.gds"):
                cands = sorted(run.glob(pat), key=lambda p: len(p.name))
                if cands:
                    gds = cands[0]
                    break
        if gds:
            picked["gds"] = str(gds.relative_to(ROOT))
        for k in ("design__instance__count", "design__instance__area",
                  "design__die__area", "route__drc_errors",
                  "design__lvs_error__count"):
            print(f"    {k:<32} {picked.get(k)}", flush=True)

    path = OUT / "summary.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    # scripts/pnr_fmax.py writes into the same entries and this script rebuilds them
    # from scratch, so anything it owns has to be carried across or a harvest silently
    # deletes a measurement that took a separate STA run to produce.
    for name, entry in summary.items():
        for key in ("postroute_fmax", "wire_rc_control"):
            if key not in entry and key in previous.get(name, {}):
                entry[key] = previous[name][key]
    if previous and args.only:
        merged = dict(previous)
        merged.update(summary)
        summary = merged
    path.write_text(json.dumps(summary, indent=1))
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
