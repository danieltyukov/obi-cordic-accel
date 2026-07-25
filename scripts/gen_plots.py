#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Draw every matplotlib figure in docs/img from measured data.

Sources, all of them real:
  build/results/accuracy_*.json     RTL simulation, written by tb/test_accuracy.py
  build/results/trajectories.json   RTL simulation, iterative core's debug port
  build/results/throughput_v*.json  RTL simulation, measured retire cycles
  build/results/path_compare_v*.json RTL simulation, register vs streaming
  docs/synth/summary.json           Yosys, written by scripts/run_synth.py

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

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for i, (_, _, label) in enumerate(funcs):
        ax.semilogy(stage_counts, curves[label], "o-", markersize=3.0,
                    linewidth=1.2, color=PALETTE[i], label=label)
    ax.semilogy(stage_counts, reference_line, "k--", linewidth=1.0,
                label="atan(2^-(N-1)), the unresolved final rotation")
    ax.axvline(28, color="#8a8a8a", linestyle=":", linewidth=0.9)
    ax.text(28.3, ax.get_ylim()[1] * 0.35, "default N=28", fontsize=7.5,
            color="#5c646e", rotation=90, va="top")
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
    axes[1].set_title("In LSBs it stays roughly flat, which is the useful result")
    axes[1].legend(loc="upper left")
    fig.suptitle("Accuracy versus fixed-point width, three integer bits throughout, "
                 "N = max(15, W-3)", y=1.02)
    note(fig, "Swept over the bit-accurate model. Error in LSBs barely moves with "
              "width because both the micro-rotation residual and the truncation "
              "walk scale with the format, so a wider word buys proportionally "
              "more precision rather than relatively better behaviour.")
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
    path = SYNTH / "summary.json"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run `make synth` first.")
    s = json.loads(path.read_text())

    order = ["pipe_q3_13_n15", "iter_q3_13_n15", "pipe_q3_29_n16",
             "iter_q3_29_n16", "pipe_q3_29_n28", "iter_q3_29_n28"]
    order = [k for k in order if k in s]
    labels = []
    for k in order:
        c = s[k]["config"]
        labels.append(f"{'pipe' if c['variant'] == 0 else 'iter'}\n"
                      f"Q{c['data_width'] - c['frac_bits']}.{c['frac_bits']}\n"
                      f"N={c['num_stages']}")
    ff = np.array([s[k]["num_ffs"] for k in order])
    comb = np.array([s[k]["num_cells"] - s[k]["num_ffs"] for k in order])
    depth = np.array([s[k]["longest_path"] for k in order])
    colours = [PALETTE[0] if "pipe" in k else PALETTE[1] for k in order]

    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.4),
                             gridspec_kw={"width_ratios": [1.55, 1]})
    ax = axes[0]
    x = np.arange(len(order))
    ax.bar(x, comb, 0.62, label="combinational cells", color=colours, alpha=0.9)
    ax.bar(x, ff, 0.62, bottom=comb, label="flip-flops", color=colours, alpha=0.45,
           hatch="///", edgecolor="white", linewidth=0.4)
    for xi, k in zip(x, order):
        total = s[k]["num_cells"]
        ax.text(xi, total * 1.02, f"{total:,}", ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylabel("gate-equivalent cells")
    ax.set_ylim(0, max(comb + ff) * 1.16)
    ax.set_title("Area: pipelined against iterative")
    ax.legend(loc="upper left")

    ax = axes[1]
    ax.bar(x, depth, 0.62, color=colours, alpha=0.9)
    for xi, dv in zip(x, depth):
        ax.text(xi, dv + 1.0, str(dv), ha="center", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylabel("longest register-to-register path (gates)")
    ax.set_ylim(0, max(depth) * 1.2)
    ax.set_title("Logic depth")

    ratios = []
    for a, b in (("pipe_q3_29_n28", "iter_q3_29_n28"),
                 ("pipe_q3_29_n16", "iter_q3_29_n16"),
                 ("pipe_q3_13_n15", "iter_q3_13_n15")):
        if a in s and b in s:
            ratios.append(f"{s[a]['config']['num_stages']} stages: "
                          f"{s[a]['num_cells'] / s[b]['num_cells']:.2f}x")
    fig.suptitle("Yosys, technology-independent mapping. Pipelined / iterative cell "
                 "ratio " + ", ".join(ratios), y=1.02, fontsize=9.5)
    note(fig, "Gate-equivalent counts from abc -g cmos4, not IHP 130nm areas, but "
              "directly comparable because every configuration goes through the same "
              "script. The iterative core's depth is only a little lower despite far "
              "fewer adders: its barrel shifter and angle mux sit in the loop.")
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


FIGURES = {
    "error_vs_angle": plot_error_vs_angle,
    "error_histograms": plot_error_histograms,
    "error_vs_stages": plot_error_vs_stages,
    "error_vs_width": plot_error_vs_width,
    "convergence_trajectory": plot_trajectories,
    "area_comparison": plot_area,
    "throughput_latency": plot_throughput,
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
