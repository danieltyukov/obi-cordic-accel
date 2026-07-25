# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Numerical accuracy of every function, measured against double precision.

Structure of each test: build a stimulus list of random arguments inside the
documented domain plus the awkward cases (zero, the exact domain boundaries, the
largest and smallest representable words, negatives, all four quadrants), push it
all through the streaming port so the pipeline stays full, then compare each result
against `math`. Max absolute error and RMS error are reported in LSBs of the
working format and asserted against a bound.

Two bounds are checked, both defined in tb/cordic_bounds.py:

  a derived absolute bound, asserted on every single argument. It accounts for the
  conditioning of the operation, which matters enormously in vectoring mode: the
  angle of a vector only a few LSBs long simply does not exist in the format, so a
  fixed LSB bound there would be meaningless rather than strict.

  a fixed bound in interface LSBs, asserted on the well-conditioned subset. These
  are the headline accuracy numbers quoted in the README.

Every result is also compared bit for bit against the model. A mismatch there is a
hardware bug and fails immediately, separately from any accuracy question.

The reference is evaluated at the quantised operands, never the requested reals,
because that is all the hardware ever sees. For atan2 in the third quadrant the
distinction is not academic: a y of -1e-10 quantises to zero, which moves the true
answer from -pi to +pi.

The results file this test writes is also the raw data behind the accuracy figures,
so the plots come from a real simulation rather than a re-run of the model.
"""

import json
import math
import os
import pathlib
import random

import cocotb

from cordic_bounds import (BoundCtx, LSB_BOUNDS, SAFETY, WELL_CONDITIONED_MAG,
                           bound, well_conditioned)
from cordic_tb import CordicDut, FUNC, stream_pop, stream_push
from cordic_model import reference

RESULT_DIR = pathlib.Path(os.environ.get(
    "CORDIC_RESULT_DIR",
    pathlib.Path(__file__).resolve().parent.parent / "build" / "results"))

# How many random arguments per function. Overridable so CI can run a smaller
# sweep than a local full run.
N_RANDOM = int(os.environ.get("CORDIC_ACC_SAMPLES", "1200"))

class Stats:
    """Absolute-error accumulator, reported in LSBs."""

    def __init__(self, lsb):
        self.lsb = lsb
        self.n = 0
        self.max_abs = 0.0
        self.sum_sq = 0.0
        self.worst = None

    def add(self, got, expected, args):
        err = abs(got - expected)
        self.n += 1
        self.sum_sq += err * err
        if err > self.max_abs:
            self.max_abs = err
            self.worst = (args, got, expected)

    @property
    def max_lsb(self):
        return self.max_abs / self.lsb

    @property
    def rms_lsb(self):
        return (math.sqrt(self.sum_sq / self.n) / self.lsb) if self.n else 0.0

    def summary(self):
        return {"n": self.n, "max_lsb": self.max_lsb, "rms_lsb": self.rms_lsb,
                "max_abs": self.max_abs}


async def sweep(dut, tb, cases, log_name):
    """Push every case through the streaming port and collect the results.

    Issue and collection are interleaved one at a time. That is slower than
    saturating the pipeline but keeps the pairing of stimulus to result trivially
    correct; test_throughput.py is the test that proves full-rate operation.
    """
    out = []
    for func_name, x, y, z in cases:
        xf = tb.model.to_fx(x)
        yf = tb.model.to_fx(y)
        zf = tb.model.to_fx(z)
        await stream_push(dut, FUNC[func_name], xf, yf, zf, tag=len(out) & 0xFF)
        res = await stream_pop(dut)
        assert res["func"] == FUNC[func_name], "function code not echoed"
        # Compare against the model too: any mismatch means the RTL and the
        # model disagree bit for bit, which is a hardware bug, not an accuracy
        # question.
        exp = tb.model.run(FUNC[func_name], x_fx=xf, y_fx=yf, z_fx=zf,
                           tag=len(out) & 0xFF)
        assert (res["x"], res["y"], res["z"], res["flags"]) == \
               (exp.x, exp.y, exp.z, exp.flags), (
            f"{func_name}: RTL {(res['x'], res['y'], res['z'], res['flags'])} != "
            f"model {(exp.x, exp.y, exp.z, exp.flags)} for "
            f"x={x} y={y} z={z} (fx {xf} {yf} {zf})")
        out.append((func_name, xf, yf, zf, res))
    return out


def evaluate(tb, collected, outputs, ctx, stats_by):
    """Compare against double precision, checking the derived bound on every case.

    Returns (rows, violations). `rows` is the raw error data the plots are drawn
    from; `violations` lists any argument whose error exceeded its derived bound.
    """
    rows = []
    violations = []
    for func_name, xf, yf, zf, res in collected:
        if res["flags"] & 0x1:
            continue  # domain error, covered by test_domain.py
        x = tb.model.to_real(xf)
        y = tb.model.to_real(yf)
        z = tb.model.to_real(zf)
        try:
            ref = reference(func_name, x=x, y=y, z=z,
                            k_circ=ctx.k_circ, k_hyp=ctx.k_hyp)
        except (ValueError, ZeroDivisionError):
            # The reference itself is undefined here (ln of zero, division by
            # zero); the hardware reports those through the domain flag, which the
            # branch above already skipped.
            continue
        cond = well_conditioned(tb.model, func_name, xf, yf, zf)
        for key in outputs:
            if key not in ref:
                continue
            # A saturated output is a range limit, not an accuracy failure.
            if res["flags"] & (1 << (1 + "xyz".index(key))):
                continue
            got = tb.model.to_real(res[key])
            err = abs(got - ref[key])
            lim = bound(ctx, func_name, key, x, y, z)
            if lim is not None and err > lim:
                violations.append(
                    f"{func_name}.{key} error {err:.4e} exceeds the derived bound "
                    f"{lim:.4e} at x={x!r} y={y!r} z={z!r}")
            if cond:
                stats_by[(func_name, key)].add(got, ref[key], (x, y, z))
            rows.append({"func": func_name, "out": key, "x": x, "y": y, "z": z,
                         "got": got, "ref": ref[key], "err": got - ref[key],
                         "bound": lim, "cond": cond})
    return rows, violations


def write_results(name, payload):
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULT_DIR / name
    path.write_text(json.dumps(payload))
    return path


async def run_group(dut, name, cases, outputs):
    """Shared body: sweep, evaluate, assert both bounds, persist, log."""
    tb = CordicDut(dut)
    await tb.start()
    lsb = 1.0 / (1 << tb.cfg["frac_bits"])
    ctx = BoundCtx(tb.model)

    stats_by = {}
    for func_name, _, _, _ in cases:
        for key in outputs:
            stats_by.setdefault((func_name, key), Stats(lsb))

    collected = await sweep(dut, tb, cases, name)
    rows, violations = evaluate(tb, collected, outputs, ctx, stats_by)

    summary = {}
    failures = list(violations[:8])
    for (func_name, key), st in sorted(stats_by.items()):
        if st.n == 0:
            continue
        limit = LSB_BOUNDS.get((func_name, key))
        summary[f"{func_name}.{key}"] = dict(st.summary(), bound_lsb=limit)
        dut._log.info(f"{func_name}.{key}: n={st.n} max={st.max_lsb:.2f} LSB "
                      f"({st.max_abs:.3e}) rms={st.rms_lsb:.2f} LSB "
                      f"bound={limit} LSB")
        if limit is not None and st.max_lsb > limit:
            failures.append(f"{func_name}.{key} max error {st.max_lsb:.2f} LSB "
                            f"exceeds the {limit} LSB bound, worst case {st.worst}")

    write_results(f"accuracy_{name}.json",
                  {"config": tb.cfg, "summary": summary, "rows": rows,
                   "safety": SAFETY, "well_conditioned_mag": WELL_CONDITIONED_MAG})
    tb.obi.check_protocol()
    dut._log.info(f"{name}: {len(rows)} comparisons, "
                  f"{len(violations)} derived-bound violations")
    assert not failures, "; ".join(failures)


def edge_values(m):
    """Representable extremes and a few exact values."""
    return [m.to_real(m.fx_max), m.to_real(m.fx_min), 0.0,
            m.to_real(1), m.to_real(-1), 1.0, -1.0, 0.5, -0.5]


@cocotb.test()
async def test_circular_rotation(dut):
    """sin and cos over the whole representable angle range, all four quadrants."""
    rng = random.Random(0x5111C05)
    tb = CordicDut(dut)
    m = tb.model
    hi = m.to_real(m.fx_max)
    lo = m.to_real(m.fx_min)

    cases = []
    # Deliberate cases first: quadrant boundaries, the pi fold trip points, the
    # extremes of the word.
    for z in [0.0, math.pi / 2, -math.pi / 2, math.pi, -math.pi,
              math.pi / 4, 3 * math.pi / 4, -3 * math.pi / 4,
              math.pi / 2 + 1e-6, math.pi / 2 - 1e-6,
              1.7432866, -1.7432866, hi, lo, m.to_real(1), m.to_real(-1)]:
        cases.append(("SIN_COS", 0.0, 0.0, max(lo, min(hi, z))))
    # One block per quadrant so no quadrant can be under-sampled.
    quads = [(0, math.pi / 2), (math.pi / 2, math.pi),
             (-math.pi / 2, 0), (-math.pi, -math.pi / 2)]
    per = N_RANDOM // 4
    for a, b in quads:
        for _ in range(per):
            cases.append(("SIN_COS", 0.0, 0.0, rng.uniform(a, b)))
    # And beyond pi, where only the fold makes convergence possible.
    for _ in range(N_RANDOM // 4):
        cases.append(("SIN_COS", 0.0, 0.0, rng.uniform(math.pi, hi)))
        cases.append(("SIN_COS", 0.0, 0.0, rng.uniform(lo, -math.pi)))

    await run_group(dut, "circular_rotation", cases, ("x", "y"))


@cocotb.test()
async def test_circular_vectoring(dut):
    """atan2 and magnitude over all four quadrants and the axes."""
    rng = random.Random(0xA7A2)
    tb = CordicDut(dut)
    m = tb.model
    # Keep the magnitude inside the format: K*hypot must stay representable.
    lim = m.to_real(m.fx_max) / (m.int_to_real(m.k_circ) * math.sqrt(2.0)) * 0.99

    cases = []
    for x, y in [(1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0), (0.0, 0.0),
                 (1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0),
                 (m.to_real(1), 0.0), (m.to_real(-1), 0.0),
                 (lim, 0.0), (-lim, 0.0), (0.0, lim), (0.0, -lim),
                 (m.to_real(1), m.to_real(1)), (m.to_real(-1), m.to_real(-1))]:
        cases.append(("ATAN2", x, y, 0.0))
    for sx in (1, -1):
        for sy in (1, -1):
            for _ in range(N_RANDOM // 4):
                r = rng.uniform(m.to_real(8), lim)
                th = rng.uniform(0, math.pi / 2)
                cases.append(("ATAN2", sx * r * math.cos(th),
                              sy * r * math.sin(th), 0.0))

    await run_group(dut, "circular_vectoring", cases, ("x", "z"))


@cocotb.test()
async def test_generic_rotation(dut):
    """Generic circular rotation, whose outputs carry the gain K."""
    rng = random.Random(0x120747E)
    tb = CordicDut(dut)
    m = tb.model
    hi = m.to_real(m.fx_max)
    # |output| = K*hypot(x,y) must stay representable.
    rmax = hi / (m.int_to_real(m.k_circ) * 1.001)

    cases = []
    for _ in range(N_RANDOM):
        r = rng.uniform(0.0, rmax)
        ph = rng.uniform(-math.pi, math.pi)
        cases.append(("ROTATE", r * math.cos(ph), r * math.sin(ph),
                      rng.uniform(-math.pi, math.pi)))
    for x, y, z in [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, math.pi),
                    (rmax, 0.0, math.pi / 2), (-rmax, 0.0, -math.pi / 2)]:
        cases.append(("ROTATE", x, y, z))

    await run_group(dut, "generic_rotation", cases, ("x", "y"))


@cocotb.test()
async def test_hyperbolic_rotation(dut):
    """sinh, cosh and exp over the hyperbolic domain, boundaries included."""
    rng = random.Random(0x51413)
    tb = CordicDut(dut)
    m = tb.model
    lim = m.int_to_real(m.lim_hyp)

    cases = []
    for z in [0.0, lim, -lim, lim - m.to_real(1), -(lim - m.to_real(1)),
              m.to_real(1), m.to_real(-1), 0.5, -0.5, 1.0, -1.0]:
        cases.append(("SINH_COSH", 0.0, 0.0, z))
        cases.append(("EXP", 0.0, 0.0, z))
    for _ in range(N_RANDOM // 2):
        z = rng.uniform(-lim, lim)
        cases.append(("SINH_COSH", 0.0, 0.0, z))
        cases.append(("EXP", 0.0, 0.0, z))

    await run_group(dut, "hyperbolic_rotation", cases, ("x", "y"))


@cocotb.test()
async def test_hyperbolic_vectoring(dut):
    """atanh and ln, including right up to the domain boundary."""
    rng = random.Random(0xA7A9)
    tb = CordicDut(dut)
    m = tb.model
    t = m.int_to_real(m.tanh_lim_hyp)
    hi = m.to_real(m.fx_max)
    ln_lo = (1 - t) / (1 + t)

    cases = []
    # atanh: x fixed at a few magnitudes, y swept over the legal ratio band.
    for xv in (1.0, 0.5, 2.0, 0.125):
        for ratio in (0.0, 0.5, -0.5, t * 0.999, -t * 0.999, t, -t):
            cases.append(("ATANH", xv, ratio * xv, 0.0))
    for _ in range(N_RANDOM // 2):
        xv = rng.uniform(m.to_real(1 << 12), hi / 1.5)
        ratio = rng.uniform(-t, t)
        cases.append(("ATANH", xv, ratio * xv, 0.0))
        # negative x takes the reflection path
        cases.append(("ATANH", -xv, -ratio * xv, 0.0))

    for xv in [1.0, ln_lo, ln_lo * 1.0001, 2.0, 0.5, math.e, hi * 0.999,
               m.to_real(m.fx_max)]:
        cases.append(("LN", xv, 0.0, 0.0))
    for _ in range(N_RANDOM // 2):
        cases.append(("LN", rng.uniform(ln_lo, hi), 0.0, 0.0))

    await run_group(dut, "hyperbolic_vectoring", cases, ("x", "z"))


@cocotb.test()
async def test_linear(dut):
    """Multiply and divide, including the smallest legal denominators."""
    rng = random.Random(0x11EA2)
    tb = CordicDut(dut)
    m = tb.model
    hi = m.to_real(m.fx_max)
    lim = m.int_to_real(m.lim_lin)

    cases = []
    for x, z in [(0.0, 0.0), (1.0, 1.0), (1.0, -1.0), (-1.0, 1.0), (-1.0, -1.0),
                 (hi, 0.0), (0.0, lim), (hi / 2, lim * 0.999),
                 (m.to_real(1), lim), (2.0, 0.5), (-2.0, -0.5)]:
        cases.append(("MUL", x, 0.0, z))
    for _ in range(N_RANDOM // 2):
        z = rng.uniform(-lim, lim)
        x = rng.uniform(-hi, hi)
        # keep the product representable
        if abs(x * z) > hi:
            x = x / (abs(z) + 1e-9) * 0.9
        cases.append(("MUL", x, 0.0, z))

    for x, y in [(1.0, 0.0), (1.0, 0.5), (1.0, -0.5), (-1.0, 0.5), (-1.0, -0.5),
                 (2.0, 1.0), (0.5, 0.25), (hi, hi / 2),
                 (1.0, lim * 0.999), (1.0, -lim * 0.999)]:
        cases.append(("DIV", x, y, 0.0))
    for _ in range(N_RANDOM // 2):
        x = rng.uniform(m.to_real(1 << 14), hi)
        if rng.random() < 0.5:
            x = -x
        y = rng.uniform(-lim, lim) * abs(x)
        if abs(y) > hi:
            continue
        cases.append(("DIV", x, y, 0.0))

    await run_group(dut, "linear", cases, ("y", "z"))


@cocotb.test()
async def test_generic_hyperbolic_rotation(dut):
    """Generic hyperbolic rotation, whose outputs carry the gain Kh."""
    rng = random.Random(0x4270)
    tb = CordicDut(dut)
    m = tb.model
    lim = m.int_to_real(m.lim_hyp)
    hi = m.to_real(m.fx_max)

    cases = []
    for _ in range(N_RANDOM):
        z = rng.uniform(-lim, lim)
        # |out| <= Kh*(|x|+|y|)*e^|z|, so scale the vector to keep it in range.
        scale = hi / (math.exp(abs(z)) * 2.2)
        cases.append(("HROTATE", rng.uniform(-scale, scale),
                      rng.uniform(-scale, scale), z))
    for x, y, z in [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, lim),
                    (1.0, 0.0, -lim), (0.0, 0.0, 0.5)]:
        cases.append(("HROTATE", x, y, z))

    await run_group(dut, "generic_hyperbolic_rotation", cases, ("x", "y"))
