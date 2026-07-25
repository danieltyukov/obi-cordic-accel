#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Draw every matplotlib figure in docs/img from measured data.

Sources, all of them real:
  build/results/accuracy_*.json     RTL simulation, written by tb/test_accuracy.py
  build/results/trajectories.json   RTL simulation, iterative core's debug port
  build/results/throughput_v*.json  RTL simulation, measured retire cycles
  build/results/path_compare_v*.json RTL simulation, register vs streaming
  docs/synth/summary.json           Yosys, generic cells
  docs/pdk/summary.json             Yosys plus OpenROAD on the real IHP SG13G2 PDK,
                                    written by scripts/run_pdk.py: real um^2 and
                                    real MHz at three corners
  docs/pnr/summary.json             LibreLane place and route, written by
                                    scripts/run_pnr.py: post-route die area, DRC and
                                    LVS counts, routed timing

Two studies sweep the bit-accurate model instead of the RTL, and say so on the
figure: error versus stage count and error versus word width would each need dozens
of separate Verilator elaborations. The model is asserted equal to the RTL operation
by operation everywhere else in the suite, which is what makes that substitution
defensible.
"""

import argparse
import json
import math
import pathlib
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = ROOT / "build" / "results"
IMG = ROOT / "docs" / "img"
SYNTH = ROOT / "docs" / "synth"
PDKDIR = ROOT / "docs" / "pdk"
PNRDIR = ROOT / "docs" / "pnr"

# The corner a design has to close on, so the one worth plotting.
SLOW_CORNER = "nom_slow_1p08V_125C"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tb"))

# A muted, colour-blind-safe sequence, dark enough to read on white.
PALETTE = ["#3b6ea5", "#c1633b", "#4f8a63", "#8a5a8f", "#a08a2c", "#5f6b76",
           "#8c4a58", "#3f7f8f", "#7a6a4f", "#6a5acd"]

plt.rcParams.update({
    "figure.dpi": 130,
    "savefig.dpi": 130,
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.6,
    "axes.axisbelow": True,
    "axes.edgecolor": "#4a4a4a",
    "legend.frameon": False,
    "legend.fontsize": 8,
    "figure.autolayout": True,
    "axes.prop_cycle": plt.cycler(color=PALETTE),
})


def load(name, required=True):
    path = RESULTS / name
    if not path.exists():
        if required:
            raise SystemExit(f"missing {path}. Run `make test` first.")
        return None
    return json.loads(path.read_text())


def save(fig, name):
    IMG.mkdir(parents=True, exist_ok=True)
    path = IMG / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path.relative_to(ROOT)}")


def note(fig, text):
    fig.text(0.5, -0.015, text, ha="center", va="top", fontsize=7, color="#5c646e")


# ---------------------------------------------------------------------------
# 1. Error versus input angle, sin and cos
# ---------------------------------------------------------------------------
def plot_error_vs_angle():
    data = load("accuracy_circular_rotation.json")
    lsb = 2.0 ** -data["config"]["frac_bits"]
    rows = data["rows"]
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.0), sharex=True)
    for ax, key, label in ((axes[0], "x", "cos"), (axes[1], "y", "sin")):
        pts = [(r["z"], r["err"] / lsb) for r in rows if r["out"] == key]
        pts.sort()
        z = np.array([p[0] for p in pts])
        e = np.array([p[1] for p in pts])
        ax.plot(z, e, ".", markersize=2.0, alpha=0.75,
                color=PALETTE[0] if key == "x" else PALETTE[1])
        ax.axhline(0.0, color="#4a4a4a", linewidth=0.7)
        for edge, style in ((math.pi / 2, "--"), (-math.pi / 2, "--"),
                            (math.pi, ":"), (-math.pi, ":")):
            ax.axvline(edge, color="#8a8a8a", linestyle=style, linewidth=0.7)
        ax.set_ylabel(f"{label} error (LSB)")
        ax.set_title(f"{label}: max |error| {max(abs(e)):.2f} LSB, "
                     f"RMS {np.sqrt((e ** 2).mean()):.2f} LSB, n={len(e)}")
    axes[1].set_xlabel("input angle z (radians)")
    fig.suptitle("Error versus input angle, measured on the RTL "
                 f"(Q{data['config']['data_width'] - data['config']['frac_bits']}."
                 f"{data['config']['frac_bits']}, "
                 f"{data['config']['num_stages']} stages)", y=1.01)
    note(fig, "Dashed lines mark +-pi/2, where the pi pre-rotation engages; dotted "
              "lines mark +-pi. The error does not step at either, which is the "
              "point: the fold costs nothing in accuracy.")
    save(fig, "error_vs_angle.png")


# ---------------------------------------------------------------------------
# 2. Error histograms, one panel per function
# ---------------------------------------------------------------------------
def plot_error_histograms():
    groups = [
        ("accuracy_circular_rotation.json", "SIN_COS", "x", "cos"),
        ("accuracy_circular_rotation.json", "SIN_COS", "y", "sin"),
        ("accuracy_circular_vectoring.json", "ATAN2", "z", "atan2"),
        ("accuracy_circular_vectoring.json", "ATAN2", "x", "K*hypot"),
        ("accuracy_hyperbolic_rotation.json", "SINH_COSH", "x", "cosh"),
        ("accuracy_hyperbolic_rotation.json", "SINH_COSH", "y", "sinh"),
        ("accuracy_hyperbolic_rotation.json", "EXP", "x", "exp"),
        ("accuracy_hyperbolic_vectoring.json", "ATANH", "z", "atanh"),
        ("accuracy_hyperbolic_vectoring.json", "LN", "z", "ln"),
        ("accuracy_linear.json", "MUL", "y", "multiply"),
        ("accuracy_linear.json", "DIV", "z", "divide"),
        ("accuracy_generic_rotation.json", "ROTATE", "x", "rotate x"),
    ]
    cache = {}
    fig, axes = plt.subplots(4, 3, figsize=(9.0, 8.4))
    frac = None
    for ax, (fname, func, key, label) in zip(axes.flat, groups):
        if fname not in cache:
            cache[fname] = load(fname)
        data = cache[fname]
        frac = data["config"]["frac_bits"]
        lsb = 2.0 ** -frac
        e = np.array([r["err"] / lsb for r in data["rows"]
                      if r["func"] == func and r["out"] == key and r["cond"]])
        if e.size == 0:
            ax.set_axis_off()
            continue
        ax.hist(e, bins=41, color=PALETTE[0], alpha=0.85, edgecolor="none")
        ax.axvline(0.0, color="#4a4a4a", linewidth=0.7)
        ax.set_title(f"{label}\nmax {np.abs(e).max():.1f}, "
                     f"RMS {np.sqrt((e ** 2).mean()):.2f} LSB", fontsize=8.5)
        ax.tick_params(labelsize=7)
    for ax in axes.flat[len(groups):]:
        ax.set_axis_off()
    for ax in axes[-1]:
        ax.set_xlabel("error (LSB)", fontsize=8)
    fig.suptitle(f"Error distribution per function, measured on the RTL against "
                 f"double precision (Q3.{frac})", y=1.005)
    note(fig, "Well-conditioned arguments only, meaning input magnitude at least "
              "1/16 for the vectoring angles. A vectoring angle divides the residual "
              "by the magnitude, so a shorter vector carries no angle to measure.")
    save(fig, "error_histograms.png")


# ---------------------------------------------------------------------------
# 3. Error versus stage count (model sweep)
# ---------------------------------------------------------------------------
def plot_error_vs_stages():
    from cordic_model import CordicModel, FUNC, reference
    import random

    stage_counts = [5] + list(range(15, 41))
    funcs = [("SIN_COS", "x", "cos"), ("SIN_COS", "y", "sin"),
             ("ATAN2", "z", "atan2"), ("EXP", "x", "exp"), ("LN", "z", "ln")]
    n = 240
    curves = {label: [] for _, _, label in funcs}
    reference_line = []

    for ns in stage_counts:
        m = CordicModel(num_stages=ns)
        lsb = 2.0 ** -m.frac_bits
        rng = random.Random(0x5747E5)
        kc = m.int_to_real(m.k_circ)
        kh = m.int_to_real(m.k_hyp)
        lim_hyp = m.int_to_real(m.lim_hyp)
        t = m.int_to_real(m.tanh_lim_hyp)
        ln_lo = (1 - t) / (1 + t)
        worst = {label: 0.0 for _, _, label in funcs}
        for _ in range(n):
            args = {
                "SIN_COS": dict(z_fx=m.to_fx(rng.uniform(-math.pi, math.pi))),
                "ATAN2": None,
                "EXP": dict(z_fx=m.to_fx(rng.uniform(-lim_hyp, lim_hyp))),
                "LN": dict(x_fx=m.to_fx(rng.uniform(max(ln_lo, 0.25), 3.5))),
            }
            th = rng.uniform(-math.pi, math.pi)
            args["ATAN2"] = dict(x_fx=m.to_fx(math.cos(th)),
                                 y_fx=m.to_fx(math.sin(th)))
            for func, key, label in funcs:
                a = args[func]
                r = m.run(FUNC[func], **a)
                if r.domain_error:
                    continue
                real = {k[0]: m.to_real(v) for k, v in a.items()}
                for axis in "xyz":
                    real.setdefault(axis, 0.0)
                ref = reference(func, k_circ=kc, k_hyp=kh, **real)
                if key not in ref:
                    continue
                err = abs(m.to_real(getattr(r, key)) - ref[key]) / lsb
                worst[label] = max(worst[label], err)
        for label in worst:
            curves[label].append(worst[label])
        reference_line.append(math.atan(2.0 ** -(ns - 1)) / lsb)

    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    for i, (_, _, label) in enumerate(funcs):
        ax.semilogy(stage_counts, curves[label], "o-", markersize=3.0,
                    linewidth=1.2, color=PALETTE[i], label=label)
    ax.semilogy(stage_counts, reference_line, "k--", linewidth=1.0,
                label="atan(2^-(N-1)), the unresolved final rotation")
    ax.axvline(28, color="#8a8a8a", linestyle=":", linewidth=0.9)
    # Below the curves rather than up in the legend's corner.
    ax.text(28.4, ax.get_ylim()[0] * 6.0, "default N=28", fontsize=7.5,
            color="#5c646e", rotation=90, va="bottom")
    ax.set_xlabel("micro-rotations N")
    ax.set_ylabel("max |error| over 240 arguments (LSB of Q3.29)")
    ax.set_title("Convergence: error falls with stage count until the format's "
                 "own resolution takes over")
    ax.legend(loc="upper right")
    note(fig, "Swept over the bit-accurate model, not the RTL: 27 stage counts "
              "would mean 27 Verilator elaborations. The model is asserted "
              "bit-identical to the RTL for every operation in the test suite. "
              "The floor near N=30 is where 2**-(N-1) drops below the accumulated "
              "truncation of the internal format.")
    save(fig, "error_vs_stages.png")


# ---------------------------------------------------------------------------
# 4. Max error versus fixed-point width (model sweep)
# ---------------------------------------------------------------------------
def plot_error_vs_width():
    from cordic_model import CordicModel, FUNC, reference
    import random

    widths = list(range(12, 33, 2))
    funcs = [("SIN_COS", "x", "cos"), ("SIN_COS", "y", "sin"),
             ("ATAN2", "z", "atan2"), ("EXP", "x", "exp")]
    abs_err = {label: [] for _, _, label in funcs}
    lsb_err = {label: [] for _, _, label in funcs}
    lsb_size = []

    for w in widths:
        frac = w - 3   # keep three integer bits so pi stays representable
        ns = min(48, max(15, frac))
        m = CordicModel(data_width=w, frac_bits=frac, num_stages=ns)
        lsb = 2.0 ** -frac
        lsb_size.append(lsb)
        rng = random.Random(0x717D7)
        kc = m.int_to_real(m.k_circ)
        kh = m.int_to_real(m.k_hyp)
        lim_hyp = m.int_to_real(m.lim_hyp)
        worst = {label: 0.0 for _, _, label in funcs}
        for _ in range(240):
            th = rng.uniform(-math.pi, math.pi)
            args = {
                "SIN_COS": dict(z_fx=m.to_fx(th)),
                "ATAN2": dict(x_fx=m.to_fx(math.cos(th)),
                              y_fx=m.to_fx(math.sin(th))),
                "EXP": dict(z_fx=m.to_fx(rng.uniform(-lim_hyp, lim_hyp))),
            }
            for func, key, label in funcs:
                a = args[func]
                r = m.run(FUNC[func], **a)
                if r.domain_error:
                    continue
                real = {k[0]: m.to_real(v) for k, v in a.items()}
                for axis in "xyz":
                    real.setdefault(axis, 0.0)
                ref = reference(func, k_circ=kc, k_hyp=kh, **real)
                if key not in ref:
                    continue
                worst[label] = max(worst[label],
                                   abs(m.to_real(getattr(r, key)) - ref[key]))
        for label in worst:
            abs_err[label].append(worst[label])
            lsb_err[label].append(worst[label] / lsb)

    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.0))
    for i, (_, _, label) in enumerate(funcs):
        axes[0].semilogy(widths, abs_err[label], "o-", markersize=3.5,
                         linewidth=1.2, color=PALETTE[i], label=label)
    axes[0].semilogy(widths, lsb_size, "k--", linewidth=1.0, label="one LSB")
    axes[0].set_xlabel("word width W bits (format Q3.(W-3))")
    axes[0].set_ylabel("max absolute error")
    axes[0].set_title("Absolute error scales with the format")
    axes[0].legend(loc="upper right")

    for i, (_, _, label) in enumerate(funcs):
        axes[1].plot(widths, lsb_err[label], "o-", markersize=3.5, linewidth=1.2,
                     color=PALETTE[i], label=label)
    axes[1].set_xlabel("word width W bits")
    axes[1].set_ylabel("max error in LSBs of that format")
    axes[1].set_title("In LSBs, flat once the stage count tracks the format")
    axes[1].legend(loc="upper left")
    fig.suptitle("Accuracy versus fixed-point width, three integer bits throughout, "
                 "N = max(15, W-3)", y=1.02)
    note(fig, "Swept over the bit-accurate model. Absolute error tracks one LSB "
              "across the whole range, so a wider word buys precision "
              "proportionally. In LSBs, sin, cos and atan2 sit near 2.5 once N "
              "follows the format. exp climbs from 1 to 12 LSB over W = 12 to 20 "
              "for a specific reason: N is clamped at 15 below W = 18 (the "
              "hyperbolic sequence needs 5, or 15 and up), so those points carry "
              "more stages than their format warrants, and exp amplifies the "
              "residual by its own derivative on top.")
    save(fig, "error_vs_width.png")


# ---------------------------------------------------------------------------
# 5. CORDIC convergence trajectory, captured from RTL simulation
# ---------------------------------------------------------------------------
def plot_trajectories():
    data = load("trajectories.json")
    trajs = data["trajectories"]
    circ = [t for t in trajs if t["coord"] == 0][:5]
    hyp = [t for t in trajs if t["coord"] == 2][:3]

    fig, axes = plt.subplots(1, 3, figsize=(11.0, 4.0))

    ax = axes[0]
    for i, t in enumerate(circ):
        pts = np.array(t["points"], dtype=float) / (1 << t["int_frac"])
        ax.plot(pts[:, 0], pts[:, 1], "-o", markersize=2.6, linewidth=0.9,
                color=PALETTE[i],
                label=f"{t['func']} z={t['z']:.2f}" if t["mode"] == 0
                      else f"{t['func']} ({t['x']:.2f}, {t['y']:.2f})")
        ax.plot(pts[0, 0], pts[0, 1], "s", markersize=5, color=PALETTE[i],
                markerfacecolor="white")
        ax.plot(pts[-1, 0], pts[-1, 1], "*", markersize=9, color=PALETTE[i])
    th = np.linspace(0, 2 * math.pi, 400)
    ax.plot(np.cos(th), np.sin(th), color="#b0b0b0", linewidth=0.8, zorder=0)
    ax.set_aspect("equal")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_title("Circular: the vector walks to the answer")
    ax.legend(loc="lower left", fontsize=6.8)

    ax = axes[1]
    # One curve per coordinate system and mode, rather than one per probe: the
    # point is the shape of the decay, and five near-identical lines hide it.
    picked = []
    seen = set()
    for t in trajs:
        key = (t["coord"], t["mode"])
        if key in seen:
            continue
        seen.add(key)
        picked.append(t)
    for i, t in enumerate(picked):
        pts = np.array(t["points"], dtype=float) / (1 << t["int_frac"])
        # Rotation drives z to zero, vectoring drives y.
        series = np.abs(pts[:, 2]) if t["mode"] == 0 else np.abs(pts[:, 1])
        series = np.maximum(series, 2.0 ** -(t["int_frac"] + 1))
        arg = (f"z={t['z']:.2f}" if t["mode"] == 0
               else f"({t['x']:.2f}, {t['y']:.2f})")
        ax.semilogy(np.arange(len(series)), series, "-o", markersize=2.4,
                    linewidth=1.0, color=PALETTE[i % len(PALETTE)],
                    label=f"{t['func']} {arg}, drive "
                          f"{'y' if t['mode'] else 'z'} to 0")
    ideal = 2.0 ** -np.arange(len(picked[0]["points"]))
    ax.semilogy(np.arange(len(ideal)), ideal, "k--", linewidth=0.9,
                label="2^-n, one bit per step")
    ax.set_xlabel("micro-rotation index")
    ax.set_ylabel("|residual| being driven to zero")
    ax.set_title("One bit of the answer per micro-rotation")
    ax.legend(loc="lower left", fontsize=6.5)

    ax = axes[2]
    for i, t in enumerate(hyp):
        pts = np.array(t["points"], dtype=float) / (1 << t["int_frac"])
        ax.plot(pts[:, 0], pts[:, 1], "-o", markersize=2.6, linewidth=0.9,
                color=PALETTE[i], label=f"{t['func']} z={t['z']:.2f}")
        ax.plot(pts[0, 0], pts[0, 1], "s", markersize=5, color=PALETTE[i],
                markerfacecolor="white")
        ax.plot(pts[-1, 0], pts[-1, 1], "*", markersize=9, color=PALETTE[i])
    u = np.linspace(-1.3, 1.3, 300)
    ax.plot(np.cosh(u), np.sinh(u), color="#b0b0b0", linewidth=0.8, zorder=0)
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_title("Hyperbolic: along x^2 - y^2 = 1")
    ax.legend(loc="upper left", fontsize=6.8)

    cfg = data["config"]
    fig.suptitle(f"Micro-rotation trajectories, sampled from the iterative core's "
                 f"debug port during RTL simulation "
                 f"({cfg['num_stages']} stages, Q3.{cfg['frac_bits']})", y=1.02)
    note(fig, "Hollow squares are the initial vector, stars the result. Every point "
              "was read out of the RTL one iteration at a time and asserted equal "
              "to the model's trajectory before being plotted.")
    save(fig, "convergence_trajectory.png")


# ---------------------------------------------------------------------------
# 6. Area comparison from Yosys
# ---------------------------------------------------------------------------
def plot_area():
    """Area and flip-flop split on the real IHP SG13G2 process."""
    path = PDKDIR / "summary.json"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run `make pdk` first.")
    s = json.loads(path.read_text())

    order = ["pipe_q3_13_n15", "iter_q3_13_n15", "pipe_q3_29_n16",
             "iter_q3_29_n16", "pipe_q3_29_n28", "iter_q3_29_n28"]
    order = [k for k in order if k in s]
    labels, ff, comb, fmax, colours = [], [], [], [], []
    for k in order:
        c = s[k]["config"]
        labels.append(f"{'pipe' if c['variant'] == 0 else 'iter'}\n"
                      f"Q{c['data_width'] - c['frac_bits']}.{c['frac_bits']}\n"
                      f"N={c['num_stages']}")
        # Flip-flop area is not broken out by the tool, so the split shown is by
        # cell count scaled onto the measured total. Honest and clearly labelled.
        total = s[k]["synth_area_um2"]
        frac_ff = s[k]["flip_flops"] / max(s[k]["cells"], 1)
        ff.append(total * frac_ff)
        comb.append(total * (1 - frac_ff))
        fmax.append(s[k]["corners"]["slow"]["fmax_mhz"])
        colours.append(PALETTE[0] if c["variant"] == 0 else PALETTE[1])

    ff = np.array(ff)
    comb = np.array(comb)
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.4),
                             gridspec_kw={"width_ratios": [1.55, 1]})
    ax = axes[0]
    x = np.arange(len(order))
    ax.bar(x, comb / 1000.0, 0.62, label="combinational (by cell share)",
           color=colours, alpha=0.9)
    ax.bar(x, ff / 1000.0, 0.62, bottom=comb / 1000.0,
           label="flip-flops (by cell share)", color=colours, alpha=0.45,
           hatch="///", edgecolor="white", linewidth=0.4)
    for xi, k in zip(x, order):
        t = s[k]["synth_area_um2"] / 1000.0
        ax.text(xi, t * 1.02, f"{t:,.0f}k", ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylabel("cell area (thousand um^2)")
    ax.set_ylim(0, max((comb + ff) / 1000.0) * 1.16)
    ax.set_title("Mapped cell area on IHP SG13G2 130nm")
    ax.legend(loc="upper left")

    ax = axes[1]
    ax.bar(x, fmax, 0.62, color=colours, alpha=0.9)
    for xi, fv in zip(x, fmax):
        ax.text(xi, fv + 1.5, f"{fv:.1f}", ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylabel("Fmax at the slow corner (MHz)")
    ax.set_ylim(0, max(fmax) * 1.2)
    ax.set_title("Frequency, synthesis estimate")

    ratios = []
    for a, b in (("pipe_q3_29_n28", "iter_q3_29_n28"),
                 ("pipe_q3_29_n16", "iter_q3_29_n16"),
                 ("pipe_q3_13_n15", "iter_q3_13_n15")):
        if a in s and b in s:
            ratios.append(f"{s[a]['config']['num_stages']} stages: "
                          f"{s[a]['synth_area_um2'] / s[b]['synth_area_um2']:.2f}x")
    fig.suptitle("Synthesis estimate over six configurations: real sg13g2 cells and "
                 "real Liberty timing, no placement. Mapped area ratio "
                 + ", ".join(ratios), y=1.02, fontsize=9.5)
    note(fig, "The folded core's area hardly moves between 16 and 28 stages, since "
              "only the angle table grows, while the pipelined core scales with the "
              "stage count. The combinational and register split is apportioned by "
              "cell count, because the tool reports one area total. These are synthesis numbers and\nthey are not what the two routed configurations measure: see docs/img/pnr_comparison.png for the gap.")
    save(fig, "area_comparison.png")


# ---------------------------------------------------------------------------
# 7. Throughput and latency, measured
# ---------------------------------------------------------------------------
def plot_throughput():
    tp = {v: load(f"throughput_v{v}.json", required=(v == 0)) for v in (0, 1)}
    pc = {v: load(f"path_compare_v{v}.json", required=(v == 0)) for v in (0, 1)}
    lat = {v: load(f"latency_v{v}.json", required=(v == 0)) for v in (0, 1)}
    have = [v for v in (0, 1) if tp[v] is not None]

    fig, axes = plt.subplots(1, 3, figsize=(11.4, 4.0))

    ax = axes[0]
    for v in have:
        rc = np.array(tp[v]["retire_cycles"], dtype=float)
        rc -= rc[0]
        ax.plot(np.arange(len(rc)), rc, linewidth=1.4, color=PALETTE[v],
                label=f"{'pipelined' if v == 0 else 'iterative'}, "
                      f"{tp[v]['steady_mean_gap']:.2f} cycles/result")
    ax.set_xlabel("result index")
    ax.set_ylabel("cycles since the first result")
    ax.set_title("Sustained retire rate")
    ax.legend(loc="upper left")

    ax = axes[1]
    for v in have:
        rc = np.array(tp[v]["retire_cycles"], dtype=float)
        gaps = np.diff(rc)
        warm = tp[v]["config"]["num_stages"] + tp[v]["config"]["in_depth"] + 4
        steady = gaps[warm:] if gaps.size > warm else gaps
        ax.plot(np.arange(len(gaps)), gaps, ".", markersize=2.6,
                color=PALETTE[v], alpha=0.7,
                label=f"{'pipelined' if v == 0 else 'iterative'}, "
                      f"steady worst {int(steady.max())}")
    ax.set_yscale("log")
    ax.set_xlabel("result index")
    ax.set_ylabel("cycles since the previous result")
    ax.set_title("Gap between consecutive results")
    ax.legend(loc="center right")

    ax = axes[2]
    names, vals, colours = [], [], []
    for v in have:
        if pc[v] is None:
            continue
        names.append(f"register\n{'pipe' if v == 0 else 'iter'}")
        vals.append(pc[v]["register_per_op"])
        colours.append(PALETTE[5])
        names.append(f"streaming\n{'pipe' if v == 0 else 'iter'}")
        vals.append(pc[v]["stream_per_op"])
        colours.append(PALETTE[v])
    x = np.arange(len(names))
    ax.bar(x, vals, 0.62, color=colours, alpha=0.9)
    for xi, vv in zip(x, vals):
        ax.text(xi, vv * 1.05, f"{vv:.2f}", ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=7.5)
    ax.set_yscale("log")
    ax.set_ylabel("cycles per operation")
    ax.set_title("Register path against streaming path")

    speed = ", ".join(f"{'pipelined' if v == 0 else 'iterative'} "
                      f"{pc[v]['speedup']:.1f}x"
                      for v in have if pc[v] is not None)
    latency = ", ".join(f"{'pipelined' if v == 0 else 'iterative'} "
                        f"{lat[v]['measured_end_to_end']} cycles"
                        for v in have if lat[v] is not None)
    fig.suptitle(f"Measured in RTL simulation. End-to-end latency: {latency}. "
                 f"Streaming speedup: {speed}", y=1.02, fontsize=9.5)
    note(fig, "The register path needs four writes and five reads per operation, so "
              "it cannot come near the pipeline's retire rate whatever the pipeline "
              "does. That gap is the whole reason the streaming port exists.")
    save(fig, "throughput_latency.png")



# ---------------------------------------------------------------------------
# 8. Real IHP SG13G2 area, frequency and throughput
# ---------------------------------------------------------------------------
def plot_ppa():
    path = PDKDIR / "summary.json"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run `make pdk` first.")
    s = json.loads(path.read_text())

    rows = []
    for name, v in s.items():
        cfg = v["config"]
        slow = v["corners"]["slow"]
        # Results per second: the pipelined core retires one per cycle, the folded
        # one once every NumStages+1 cycles. Both numbers are Fmax divided by the
        # measured issue interval, so this is throughput, not a peak claim.
        interval = 1 if cfg["variant"] == 0 else cfg["num_stages"] + 1
        rows.append(dict(
            name=name, variant=cfg["variant"], stages=cfg["num_stages"],
            fmt=f"Q{cfg['data_width'] - cfg['frac_bits']}.{cfg['frac_bits']}",
            area=v["synth_area_um2"], fmax=slow["fmax_mhz"],
            mres=slow["fmax_mhz"] * 1e6 / interval / 1e6, interval=interval,
            corners={c: t["fmax_mhz"] for c, t in v["corners"].items()}))
    rows.sort(key=lambda r: (r["variant"], -r["stages"]))

    fig, axes = plt.subplots(1, 3, figsize=(12.4, 4.3))

    # --- area against frequency, the Pareto view
    ax = axes[0]
    for r in rows:
        c = PALETTE[0] if r["variant"] == 0 else PALETTE[1]
        mk = "o" if r["variant"] == 0 else "s"
        ax.scatter(r["area"] / 1000.0, r["fmax"], s=70, color=c, marker=mk,
                   zorder=3, edgecolor="white", linewidth=0.8)
        ax.annotate(f"{r['fmt']} N={r['stages']}",
                    (r["area"] / 1000.0, r["fmax"]), textcoords="offset points",
                    xytext=(7, -3), fontsize=7.2, color="#3a3a3a")
    # Join only points that share a format, since a line across formats would
    # suggest a sweep that was never run.
    for v, c, mk in ((0, PALETTE[0], "o"), (1, PALETTE[1], "s")):
        for fmt in sorted({r["fmt"] for r in rows}):
            pts = sorted([(r["area"] / 1000.0, r["fmax"]) for r in rows
                          if r["variant"] == v and r["fmt"] == fmt])
            if len(pts) > 1:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], "-", color=c,
                        linewidth=1.0, alpha=0.5)
    for v, label, c, mk in ((0, "pipelined", PALETTE[0], "o"),
                            (1, "iterative", PALETTE[1], "s")):
        ax.scatter([], [], s=70, color=c, marker=mk, label=label)
    ax.set_xlabel("cell area (thousand um^2)")
    ax.set_ylabel("Fmax at the slow corner (MHz)")
    ax.set_title("Area against frequency")
    ax.legend(loc="lower right")

    # --- area against throughput, which is the number that matters
    ax = axes[1]
    for r in rows:
        c = PALETTE[0] if r["variant"] == 0 else PALETTE[1]
        mk = "o" if r["variant"] == 0 else "s"
        ax.scatter(r["area"] / 1000.0, r["mres"], s=70, color=c, marker=mk,
                   zorder=3, edgecolor="white", linewidth=0.8)
        ax.annotate(f"{r['fmt']} N={r['stages']}",
                    (r["area"] / 1000.0, r["mres"]), textcoords="offset points",
                    xytext=(7, -3), fontsize=7.2, color="#3a3a3a")
    for v, label, c, mk in ((0, "pipelined", PALETTE[0], "o"),
                            (1, "iterative", PALETTE[1], "s")):
        ax.scatter([], [], s=70, color=c, marker=mk, label=label)
    ax.set_yscale("log")
    ax.set_xlabel("cell area (thousand um^2)")
    ax.set_ylabel("million results per second, slow corner")
    ax.set_title("Area against throughput")
    ax.legend(loc="lower right")

    # --- corner spread
    ax = axes[2]
    labels = [f"{'pipe' if r['variant'] == 0 else 'iter'}\n{r['fmt']}\nN={r['stages']}"
              for r in rows]
    x = np.arange(len(rows))
    w = 0.26
    for i, (corner, c) in enumerate((("slow", PALETTE[5]), ("typ", PALETTE[0]),
                                    ("fast", PALETTE[2]))):
        vals = [r["corners"][corner] for r in rows]
        ax.bar(x + (i - 1) * w, vals, w, label=corner, color=c, alpha=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=6.8)
    ax.set_ylabel("Fmax (MHz)")
    ax.set_title("Corner spread")
    ax.legend(loc="upper left", ncol=3, fontsize=7.5)

    pipe = next(r for r in rows if r["name"] == "pipe_q3_29_n28")
    itr = next(r for r in rows if r["name"] == "iter_q3_29_n28")
    fig.suptitle(
        f"IHP SG13G2 130nm, real cells and real Liberty timing. At Q3.29 with 28 "
        f"stages the pipelined core is {pipe['area'] / itr['area']:.1f}x the area "
        f"for {pipe['mres'] / itr['mres']:.0f}x the throughput, so "
        f"{(pipe['mres'] / pipe['area']) / (itr['mres'] / itr['area']):.1f}x the "
        f"results per second per um^2.", y=1.03, fontsize=9.5)
    note(fig, "Slow corner is 1.08 V and 125 C, the corner a design closes on. "
              "Throughput is Fmax divided by the measured issue interval, 1 cycle "
              "pipelined and N+1 folded. Folding costs frequency as well as "
              "throughput, because its barrel shifter and angle mux sit inside the "
              "loop where the pipelined core has hardwired shifts.")
    save(fig, "ppa_ihp_sg13g2.png")



# ---------------------------------------------------------------------------
# 9. Synthesis against post-route, per variant
# ---------------------------------------------------------------------------
def plot_pnr():
    """What changes between a synthesis estimate and a routed design, per variant.

    Both directions matter and they are not the same size. Area: synthesis reports
    mapped cells, which is neither the routed cell area nor the die. Timing: the
    synthesis estimate here is drive repair over a virtual placement with wire RC
    guessed from a layer, and the routed number is the same netlist family placed,
    clock-treed, resized against real positions and timed on extracted parasitics.
    """
    ppath = PNRDIR / "summary.json"
    dpath = PDKDIR / "summary.json"
    if not ppath.exists():
        raise SystemExit(f"missing {ppath}. Run `make pnr` first.")
    pnr = json.loads(ppath.read_text())
    pdk = json.loads(dpath.read_text())

    order = [k for k in ("pipe_q3_29_n28", "iter_q3_29_n28") if k in pnr]
    if not order:
        raise SystemExit("no recognised variant in docs/pnr/summary.json")

    # What the routed standard cell area is made of. Enough to separate the clock
    # tree and the resizer's timing repair from the logic they were added to.
    COMPOSITION = (
        ("registers", "sequential_cell"),
        ("combinational", "multi_input_combinational_cell"),
        ("timing repair", "timing_repair_buffer"),
        ("clock tree", ("clock_buffer", "clock_inverter")),
        ("other buffers", "inverter"),
    )

    rows = []
    for k in order:
        v = pnr[k]
        d = pdk.get(k, {})
        cfg = v["config"]

        def area_class(key):
            return v.get(f"design__instance__area__class:{key}") or 0.0

        comp = {}
        for label, keys in COMPOSITION:
            comp[label] = sum(area_class(x) for x in
                              ((keys,) if isinstance(keys, str) else keys))

        # The post-route frequency is the one scripts/pnr_fmax.py measures: the
        # routed netlist re-timed under the same constraint style docs/pdk uses, so
        # the two numbers differ only in the parasitics and the cells PnR added.
        # LibreLane's own slack is not used, because its SDC charges a quarter of the
        # period to IO and 5 percent to setup uncertainty, neither of which docs/pdk
        # applies.
        fm = (v.get("postroute_fmax") or {}).get("slow") or {}
        rows.append(dict(
            name=k,
            label=("pipelined" if cfg["variant"] == 0 else "folded"),
            variant=cfg["variant"],
            synth=d.get("synth_area_um2"),
            stdcell=(v.get("design__instance__area__stdcell")
                     or v.get("design__instance__area__class:standard_cell")),
            die=v.get("design__die__area"),
            util=v.get("design__instance__utilization"),
            drc=v.get("route__drc_errors"),
            power=v.get("power__total"),
            wl=v.get("route__wirelength"),
            comp=comp,
            fmax_pr=fm.get("fmax_mhz"),
            fmax_syn=(d.get("corners", {}).get("slow", {}) or {}).get("fmax_mhz"),
        ))

    fig, axes = plt.subplots(1, 4, figsize=(14.6, 4.4))
    x = np.arange(len(rows))
    labels = [f"{r['label']}\nQ3.29 N=28" for r in rows]
    colours = [PALETTE[0] if r["variant"] == 0 else PALETTE[1] for r in rows]

    # --- three area measures side by side
    ax = axes[0]
    wid = 0.26
    series = (("mapped cells, synthesis", "synth", 0.95),
              ("routed standard cells", "stdcell", 0.6),
              ("routed die", "die", 0.3))
    for i, (name, key, alpha) in enumerate(series):
        vals = [(r[key] or 0) / 1000.0 for r in rows]
        ax.bar(x + (i - 1) * wid, vals, wid, label=name, color=colours,
               alpha=alpha, edgecolor="white", linewidth=0.4)
        for xi, vv in zip(x + (i - 1) * wid, vals):
            if vv:
                ax.text(xi, vv * 1.02, f"{vv:.0f}k", ha="center", fontsize=6.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("area (thousand um^2)")
    ax.set_ylim(0, max(r["die"] or 0 for r in rows) / 1000.0 * 1.22)
    ax.set_title("Mapped, routed and die area")
    ax.legend(loc="upper right", fontsize=7)

    # --- inflation factor
    ax = axes[1]
    for i, (name, num, den, alpha) in enumerate(
            (("routed cells / mapped", "stdcell", "synth", 0.95),
             ("die / mapped", "die", "synth", 0.45))):
        vals = [(r[num] / r[den]) if (r[num] and r[den]) else 0 for r in rows]
        ax.bar(x + (i - 0.5) * 0.34, vals, 0.34, label=name, color=colours,
               alpha=alpha, edgecolor="white", linewidth=0.4)
        for xi, vv in zip(x + (i - 0.5) * 0.34, vals):
            if vv:
                ax.text(xi, vv + 0.06, f"{vv:.2f}x", ha="center", fontsize=7.5)
    ax.axhline(1.0, color="#4a4a4a", linewidth=0.8, linestyle=":")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, max((r["die"] / r["synth"]) for r in rows
                       if r["die"] and r["synth"]) * 1.28)
    ax.set_ylabel("post-route area / mapped cell area")
    ax.set_title("Inflation from synthesis to route")
    ax.legend(loc="upper left", fontsize=7)

    # --- what the routed cell area is made of
    ax = axes[2]
    bottom = np.zeros(len(rows))
    for i, (name, _) in enumerate(COMPOSITION):
        vals = np.array([100.0 * r["comp"][name] / r["stdcell"]
                         if r["stdcell"] else 0.0 for r in rows])
        ax.bar(x, vals, 0.5, bottom=bottom, label=name, color=PALETTE[i + 2],
               edgecolor="white", linewidth=0.5)
        for xi, vv, bb in zip(x, vals, bottom):
            if vv > 4:
                ax.text(xi, bb + vv / 2, f"{vv:.0f}%", ha="center", va="center",
                        fontsize=7, color="white")
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, 132)
    ax.set_ylabel("share of routed standard cell area (%)")
    ax.set_title("What the routed cells are")
    ax.legend(loc="upper center", fontsize=6.6, ncol=3)

    # --- Fmax, synthesis estimate against the routed measurement
    ax = axes[3]
    for i, (name, key, alpha) in enumerate(
            (("synthesis estimate, set_wire_rc", "fmax_syn", 0.95),
             ("routed, extracted parasitics", "fmax_pr", 0.45))):
        vals = [r[key] or 0 for r in rows]
        ax.bar(x + (i - 0.5) * 0.34, vals, 0.34, label=name, color=colours,
               alpha=alpha, edgecolor="white", linewidth=0.4)
        for xi, vv in zip(x + (i - 0.5) * 0.34, vals):
            if vv:
                ax.text(xi, vv + 1.5, f"{vv:.1f}", ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, max(max(r["fmax_syn"] or 0, r["fmax_pr"] or 0)
                       for r in rows) * 1.3)
    ax.set_ylabel("frequency at the slow corner (MHz)")
    ax.set_title("Timing, estimate against routed")
    ax.legend(loc="upper left", fontsize=6.6)

    bits = []
    for r in rows:
        if r["stdcell"] and r["synth"]:
            bits.append(f"{r['label']} {r['stdcell'] / r['synth']:.2f}x cells, "
                        f"{r['die'] / r['synth']:.2f}x die, "
                        f"{r['fmax_pr'] / r['fmax_syn']:.2f}x frequency"
                        if r["fmax_pr"] and r["fmax_syn"] else
                        f"{r['label']} {r['stdcell'] / r['synth']:.2f}x cells")
    fig.suptitle("LibreLane on IHP SG13G2, Q3.29 with 28 stages. Synthesis to route: "
                 + "; ".join(bits), y=1.03, fontsize=9.5)
    note(fig, "The two variants inflate in cell area by almost the same factor, so "
              "the clock tree does not punish the register-heavy design the way a\n"
              "register count would suggest: it is 5 percent of the routed cell area "
              "in both. The die ratios differ because the two floorplans were given\n"
              "different utilisation targets, 35 and 40 percent, which is a choice "
              "and not a measurement. Frequency moves the other way and by more: "
              "both\ndesigns are faster routed than the synthesis estimate said, "
              "because that estimate is drive repair over a virtual placement, "
              "while PnR resizes\nagainst real positions. Both frequencies are "
              "register to register at 1.08 V and 125 C. The routed netlist was "
              "optimised against the period in\nthe LibreLane config and the tool "
              "stopped once it met it, so this is that netlist's path delay, not a "
              "closed-timing Fmax.")
    save(fig, "pnr_comparison.png")


# ---------------------------------------------------------------------------
# 10. The two routed dies at one scale
# ---------------------------------------------------------------------------
def die_dims(entry):
    """The die rectangle in micrometres.

    Recorded by scripts/run_pnr.py into the summary, because it comes from the DEF and
    a clone has the summary without the run tree that holds it. Older summaries
    predate the field, hence the fallback to nothing rather than to a guess: the
    square root of the area metric is not the shape, since neither die is square.
    """
    rect = entry.get("die_um")
    if isinstance(rect, (list, tuple)) and len(rect) == 2:
        return float(rect[0]), float(rect[1])
    return None


def plot_layouts():
    """Both routed variants side by side, at the scale they were rendered at.

    scripts/run_pnr_render.sh writes one PNG per variant over a frame of identical
    micrometres, so the two are already comparable pixel for pixel. Compositing them
    into one figure is what makes the comparison unavoidable: zoom-to-fit would blow
    the smaller die up to the same size and hide the entire point.
    """
    ppath = PNRDIR / "summary.json"
    if not ppath.exists():
        raise SystemExit(f"missing {ppath}. Run `make pnr` first.")
    pnr = json.loads(ppath.read_text())

    order = [k for k in ("pipe_q3_29_n28", "iter_q3_29_n28") if k in pnr]
    tiles = [(k, IMG / f"layout_{k}_scaled.png") for k in order]
    missing = [str(p) for _, p in tiles if not p.exists()]
    if missing:
        raise SystemExit("missing shared-scale renders: " + ", ".join(missing)
                         + ". Run `make layout` first.")

    fig, axes = plt.subplots(1, len(tiles), figsize=(10.6, 5.9))
    axes = np.atleast_1d(axes)
    for ax, (name, path) in zip(axes, tiles):
        v = pnr[name]
        cfg = v["config"]
        label = "pipelined" if cfg["variant"] == 0 else "folded"
        die = v.get("design__die__area")
        cells = (v.get("design__instance__area__stdcell")
                 or v.get("design__instance__area__class:standard_cell"))
        util = v.get("design__instance__utilization")
        fmax = ((v.get("postroute_fmax") or {}).get("slow") or {}).get("fmax_mhz")

        ax.imshow(plt.imread(path))
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for s in ax.spines.values():
            s.set_edgecolor("#4a4a4a")
        head = f"{label}, Q3.29 N=28"
        dims = die_dims(v)
        if dims:
            head += f"\n{dims[0]:.0f} x {dims[1]:.0f} um"
        if die:
            head += f", {die / 1e6:.3f} mm2 of die"
        ax.set_title(head, fontsize=9.5)
        bits = []
        if cells:
            bits.append(f"{cells / 1000:.0f}k um2 of cells")
        if util:
            bits.append(f"{util * 100:.0f}% utilisation")
        if fmax:
            bits.append(f"{fmax:.1f} MHz slow corner")
        if bits:
            ax.set_xlabel(", ".join(bits), fontsize=8)

    fig.suptitle("The same two designs routed, at one shared scale",
                 fontsize=10, y=1.05)
    note(fig, "Both frames cover the same area of silicon, so the folded die is "
              "smaller in the figure because it is smaller on the wafer.\n"
              "Lower metal is hidden on purpose: Metal1 pitch is under a micron "
              "against a die 1.4 mm across, so including it turns either die into a "
              "solid block.\nThe scale bar in each render is 100 um. Frequency is "
              "register to register at 1.08 V and 125 C with extracted parasitics, "
              "measured by scripts/pnr_fmax.py.")
    save(fig, "pnr_layouts.png")


FIGURES = {
    "error_vs_angle": plot_error_vs_angle,
    "error_histograms": plot_error_histograms,
    "error_vs_stages": plot_error_vs_stages,
    "error_vs_width": plot_error_vs_width,
    "convergence_trajectory": plot_trajectories,
    "area_comparison": plot_area,
    "throughput_latency": plot_throughput,
    "ppa_ihp_sg13g2": plot_ppa,
    "pnr_comparison": plot_pnr,
    # Needs the shared-scale renders, so it runs after scripts/run_pnr_render.sh
    # rather than alongside the other figures.
    "pnr_layouts": plot_layouts,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("figures", nargs="*", choices=sorted(FIGURES) + [],
                    help="figures to draw, default all")
    args = ap.parse_args(argv)
    wanted = args.figures or sorted(FIGURES)
    for name in wanted:
        FIGURES[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
