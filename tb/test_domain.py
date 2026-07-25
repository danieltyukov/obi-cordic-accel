# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Convergence-domain behaviour.

Two properties matter and they are tested separately, because they are not
equally strict:

  no false positive. An argument inside the documented domain must never be
  rejected. This is asserted absolutely: one rejection fails the test.

  detection outside. An argument outside the documented domain must set
  RES_FLAGS.DOMAIN_ERR and return zeroes rather than a plausible-looking wrong
  answer. Asserted absolutely once the argument is more than BAND_LSB LSBs past
  the boundary, and the width of that band is itself measured and asserted, so a
  regression that widened it would fail.

The band exists because the vectoring domains are detected from the residual
rather than from a closed-form comparison, which would need a full-width constant
multiplier. See the header of rtl/cordic_post.sv. Inside the band the operation
still converges, so a missed flag yields a correct result, not a wrong one.

Rotation-mode domains are compared against the radius directly and have no band
at all beyond one LSB of quantisation.
"""

import json
import math
import os
import pathlib
import random

import cocotb

from cordic_tb import CordicDut, FUNC, get_field, stream_pop, stream_push

RESULT_DIR = pathlib.Path(os.environ.get(
    "CORDIC_RESULT_DIR",
    pathlib.Path(__file__).resolve().parent.parent / "build" / "results"))

N_RANDOM = int(os.environ.get("CORDIC_DOMAIN_SAMPLES", "600"))

# Widest ambiguous band accepted around a residual-detected boundary, in LSBs.
BAND_LSB = 64


async def run_one(dut, tb, func_name, x=0.0, y=0.0, z=0.0):
    xf, yf, zf = (tb.model.to_fx(x), tb.model.to_fx(y), tb.model.to_fx(z))
    await stream_push(dut, FUNC[func_name], xf, yf, zf)
    res = await stream_pop(dut)
    exp = tb.model.run(FUNC[func_name], x_fx=xf, y_fx=yf, z_fx=zf)
    assert (res["x"], res["y"], res["z"], res["flags"]) == \
           (exp.x, exp.y, exp.z, exp.flags), (
        f"{func_name}: RTL and model disagree for x={x} y={y} z={z}")
    return res


def flagged(res):
    return bool(res["flags"] & 0x1)


async def assert_inside(dut, tb, cases, label):
    """No argument inside the domain may be rejected."""
    bad = []
    for func_name, x, y, z in cases:
        res = await run_one(dut, tb, func_name, x, y, z)
        if flagged(res):
            bad.append((func_name, x, y, z))
    assert not bad, (f"{label}: {len(bad)} in-domain arguments were rejected, "
                     f"first few {bad[:5]}")
    dut._log.info(f"{label}: {len(cases)} in-domain arguments, none rejected")


async def assert_outside(dut, tb, cases, label):
    """Every argument outside the domain must be rejected, with zeroed outputs."""
    bad = []
    for func_name, x, y, z in cases:
        res = await run_one(dut, tb, func_name, x, y, z)
        if not flagged(res):
            bad.append((func_name, x, y, z))
        else:
            assert (res["x"], res["y"], res["z"]) == (0, 0, 0), (
                f"{label}: {func_name} flagged a domain error but left "
                f"non-zero outputs {res}")
    assert not bad, (f"{label}: {len(bad)} out-of-domain arguments were accepted, "
                     f"first few {bad[:5]}")
    dut._log.info(f"{label}: {len(cases)} out-of-domain arguments, all rejected "
                  f"with zeroed outputs")


async def measure_band(dut, tb, make_case, boundary, direction, limit=4096):
    """Steps past `boundary` before the flag settles to the expected value.

    `direction` is +1 when moving outward raises the flag and -1 when moving
    outward lowers the argument.
    """
    lsb = tb.model.to_real(1)
    for k in range(limit):
        arg = boundary + direction * k * lsb
        res = await run_one(dut, tb, *make_case(arg))
        if flagged(res):
            return k
    return None


@cocotb.test()
async def test_hyperbolic_rotation_domain(dut):
    """|z| <= LIM_HYP for sinh, cosh and exp: a direct comparison, no band."""
    rng = random.Random(0xD0A1)
    tb = CordicDut(dut)
    await tb.start()
    lim = tb.model.int_to_real(tb.model.lim_hyp)
    lsb = tb.model.to_real(1)
    hi = tb.model.to_real(tb.model.fx_max)

    inside = []
    for fn in ("SINH_COSH", "EXP", "HROTATE"):
        for z in (0.0, lim, -lim, lim - lsb, -lim + lsb, lsb, -lsb):
            inside.append((fn, 0.0, 0.0, z))
        for _ in range(N_RANDOM // 3):
            inside.append((fn, 0.0, 0.0, rng.uniform(-lim, lim)))
    await assert_inside(dut, tb, inside, "hyperbolic rotation")

    outside = []
    for fn in ("SINH_COSH", "EXP", "HROTATE"):
        for z in (lim + lsb, -lim - lsb, lim * 1.001, -lim * 1.001, hi,
                  tb.model.to_real(tb.model.fx_min)):
            outside.append((fn, 0.0, 0.0, z))
        for _ in range(N_RANDOM // 3):
            outside.append((fn, 0.0, 0.0, rng.uniform(lim + lsb, hi)))
    await assert_outside(dut, tb, outside, "hyperbolic rotation")

    # The rotation-mode check is a plain magnitude comparison against the radius,
    # so it must flip within a single LSB of the boundary.
    band = await measure_band(dut, tb, lambda a: ("SINH_COSH", 0.0, 0.0, a),
                              lim, +1, limit=8)
    assert band == 1, f"hyperbolic rotation boundary took {band} LSBs, expected 1"
    dut._log.info(f"hyperbolic rotation boundary is exact: flag sets {band} LSB out")


@cocotb.test()
async def test_linear_rotation_domain(dut):
    """|z| <= LIM_LIN for multiply: a direct comparison, no band."""
    rng = random.Random(0xD0A2)
    tb = CordicDut(dut)
    await tb.start()
    lim = tb.model.int_to_real(tb.model.lim_lin)
    lsb = tb.model.to_real(1)
    hi = tb.model.to_real(tb.model.fx_max)

    inside = [("MUL", 1.0, 0.0, z) for z in
              (0.0, lim, -lim, lim - lsb, -lim + lsb)]
    for _ in range(N_RANDOM):
        inside.append(("MUL", rng.uniform(-1.0, 1.0), 0.0, rng.uniform(-lim, lim)))
    await assert_inside(dut, tb, inside, "linear rotation")

    outside = [("MUL", 1.0, 0.0, z) for z in (lim + lsb, -lim - lsb, hi,
                                              tb.model.to_real(tb.model.fx_min))]
    for _ in range(N_RANDOM // 2):
        outside.append(("MUL", rng.uniform(-1.0, 1.0), 0.0,
                        rng.uniform(lim + lsb, hi)))
    await assert_outside(dut, tb, outside, "linear rotation")

    band = await measure_band(dut, tb, lambda a: ("MUL", 1.0, 0.0, a),
                              lim, +1, limit=8)
    assert band == 1, f"linear rotation boundary took {band} LSBs, expected 1"


@cocotb.test()
async def test_hyperbolic_vectoring_domain(dut):
    """|y/x| <= TANH_LIM_HYP for atanh, plus the divide-by-zero case."""
    rng = random.Random(0xD0A3)
    tb = CordicDut(dut)
    await tb.start()
    t = tb.model.int_to_real(tb.model.tanh_lim_hyp)
    hi = tb.model.to_real(tb.model.fx_max)

    inside = []
    for xv in (1.0, 0.5, 2.0, 0.25, -1.0, -2.0):
        for r in (0.0, 0.25, -0.25, 0.75, -0.75, t, -t):
            inside.append(("ATANH", xv, r * abs(xv), 0.0))
    for _ in range(N_RANDOM):
        xv = rng.uniform(0.125, hi / 1.5) * rng.choice((1, -1))
        inside.append(("ATANH", xv, rng.uniform(-t, t) * abs(xv), 0.0))
    await assert_inside(dut, tb, inside, "hyperbolic vectoring")

    outside = [("ATANH", 0.0, 0.0, 0.0), ("ATANH", 0.0, 1.0, 0.0),
               ("ATANH", 0.0, -1.0, 0.0)]
    for xv in (1.0, 0.5, 2.0, -1.0):
        for r in (1.0, -1.0, 1.5, -1.5, t * 1.5, -t * 1.5, t + 0.05, -t - 0.05):
            if abs(r * xv) <= hi:
                outside.append(("ATANH", xv, r * abs(xv), 0.0))
    for _ in range(N_RANDOM // 2):
        xv = rng.uniform(0.25, 1.5)
        r = rng.uniform(t + 0.02, 1.9)
        if r * xv <= hi:
            outside.append(("ATANH", xv, r * xv * rng.choice((1, -1)), 0.0))
    await assert_outside(dut, tb, outside, "hyperbolic vectoring")

    band = await measure_band(dut, tb, lambda a: ("ATANH", 1.0, a, 0.0), t, +1)
    assert band is not None and band <= BAND_LSB, (
        f"atanh boundary band is {band} LSBs, above the {BAND_LSB} LSB limit")
    dut._log.info(f"atanh residual-detected boundary band: {band} LSBs")
    return band


@cocotb.test()
async def test_linear_vectoring_domain(dut):
    """|y/x| <= LIM_LIN for divide, plus divide by zero."""
    rng = random.Random(0xD0A4)
    tb = CordicDut(dut)
    await tb.start()
    lim = tb.model.int_to_real(tb.model.lim_lin)
    hi = tb.model.to_real(tb.model.fx_max)

    inside = []
    for xv in (1.0, 0.5, 2.0, -1.0, -2.0, 3.0):
        for r in (0.0, 0.5, -0.5, 1.0, -1.0, lim, -lim):
            if abs(r * xv) <= hi:
                inside.append(("DIV", xv, r * abs(xv), 0.0))
    for _ in range(N_RANDOM):
        xv = rng.uniform(0.125, hi) * rng.choice((1, -1))
        r = rng.uniform(-lim, lim)
        if abs(r * xv) <= hi:
            inside.append(("DIV", xv, r * abs(xv), 0.0))
    await assert_inside(dut, tb, inside, "linear vectoring")

    outside = [("DIV", 0.0, 0.0, 0.0), ("DIV", 0.0, 1.0, 0.0),
               ("DIV", 0.0, -1.0, 0.0)]
    for xv in (1.0, 0.5, -1.0, 1.5):
        for r in (lim + 0.01, -lim - 0.01, 3.0, -3.0):
            if abs(r * xv) <= hi:
                outside.append(("DIV", xv, r * abs(xv), 0.0))
    for _ in range(N_RANDOM // 2):
        xv = rng.uniform(0.5, 1.9)
        r = rng.uniform(lim + 0.01, 3.9)
        if r * xv <= hi:
            outside.append(("DIV", xv, r * xv * rng.choice((1, -1)), 0.0))
    await assert_outside(dut, tb, outside, "linear vectoring")

    band = await measure_band(dut, tb, lambda a: ("DIV", 1.0, a, 0.0), lim, +1)
    assert band is not None and band <= BAND_LSB, (
        f"divide boundary band is {band} LSBs, above the {BAND_LSB} LSB limit")
    dut._log.info(f"divide residual-detected boundary band: {band} LSBs")


@cocotb.test()
async def test_ln_domain(dut):
    """ln needs x > 0 and (x-1)/(x+1) inside the atanh radius."""
    rng = random.Random(0xD0A5)
    tb = CordicDut(dut)
    await tb.start()
    t = tb.model.int_to_real(tb.model.tanh_lim_hyp)
    lo = (1 - t) / (1 + t)
    hi = tb.model.to_real(tb.model.fx_max)
    lsb = tb.model.to_real(1)

    inside = [("LN", v, 0.0, 0.0) for v in
              (lo, lo + lsb, 1.0, 2.0, math.e, hi, hi - lsb, 0.5, 3.0)]
    for _ in range(N_RANDOM):
        inside.append(("LN", rng.uniform(lo, hi), 0.0, 0.0))
    await assert_inside(dut, tb, inside, "ln")

    outside = [("LN", v, 0.0, 0.0) for v in
               (0.0, -lsb, -1.0, tb.model.to_real(tb.model.fx_min),
                lo * 0.5, lo * 0.9, 0.01)]
    for _ in range(N_RANDOM // 2):
        outside.append(("LN", rng.uniform(-hi, -lsb), 0.0, 0.0))
    for _ in range(N_RANDOM // 4):
        outside.append(("LN", rng.uniform(lsb, lo * 0.95), 0.0, 0.0))
    await assert_outside(dut, tb, outside, "ln")

    # Moving down from the lower boundary is what leaves the domain here.
    band = None
    lsb_r = tb.model.to_real(1)
    for k in range(4096):
        res = await run_one(dut, tb, "LN", x=lo - k * lsb_r)
        if flagged(res):
            band = k
            break
    assert band is not None and band <= BAND_LSB, (
        f"ln lower boundary band is {band} LSBs, above the {BAND_LSB} LSB limit")
    dut._log.info(f"ln residual-detected boundary band: {band} LSBs")


@cocotb.test()
async def test_circular_never_errors(dut):
    """Circular rotation and vectoring cover the whole word, so no domain error.

    This is the payoff of the pi fold: with three integer bits, every
    representable angle lands inside the convergence radius after folding, and
    vectoring reaches all four quadrants by reflecting a negative x.
    """
    rng = random.Random(0xD0A6)
    tb = CordicDut(dut)
    await tb.start()
    hi = tb.model.to_real(tb.model.fx_max)
    lo = tb.model.to_real(tb.model.fx_min)

    cases = []
    for z in (0.0, hi, lo, math.pi, -math.pi, math.pi / 2, -math.pi / 2,
              hi - tb.model.to_real(1), lo + tb.model.to_real(1)):
        cases.append(("SIN_COS", 0.0, 0.0, z))
    for _ in range(N_RANDOM):
        cases.append(("SIN_COS", 0.0, 0.0, rng.uniform(lo, hi)))
    for x, y in ((0.0, 0.0), (hi, hi), (lo, lo), (hi, lo), (lo, hi),
                 (0.0, hi), (hi, 0.0), (0.0, lo), (lo, 0.0),
                 (tb.model.to_real(1), tb.model.to_real(-1))):
        cases.append(("ATAN2", x, y, 0.0))
    for _ in range(N_RANDOM):
        cases.append(("ATAN2", rng.uniform(lo, hi), rng.uniform(lo, hi), 0.0))
    await assert_inside(dut, tb, cases, "circular, whole representable range")


@cocotb.test()
async def test_undefined_function_code(dut):
    """Unassigned function codes are reported, not quietly computed."""
    tb = CordicDut(dut)
    await tb.start()
    for code in range(10, 32):
        await stream_push(dut, code, tb.model.to_fx(1.0), 0, tb.model.to_fx(0.5))
        res = await stream_pop(dut)
        assert flagged(res), f"function code {code} is unassigned but was accepted"
        assert (res["x"], res["y"], res["z"]) == (0, 0, 0)
        assert res["func"] == code, "function code not echoed"
    dut._log.info("function codes 10 to 31 all report a domain error")


@cocotb.test()
async def test_domain_error_reaches_status(dut):
    """A domain error latches STATUS.ERR_DOMAIN and raises IRQ.ERR."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "ERR_DOMAIN") == 0, "sticky bit set after reset"

    # sinh of an argument outside the hyperbolic radius.
    lim = tb.model.int_to_real(tb.model.lim_hyp)
    got = await tb.run_op(FUNC["SINH_COSH"], z=tb.model.to_fx(lim * 1.5))
    assert got["flags"] & 0x1, "RES_FLAGS.DOMAIN_ERR not set"
    assert (got["x"], got["y"], got["z"]) == (0, 0, 0)

    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "ERR_DOMAIN") == 1, "STATUS.ERR_DOMAIN not latched"
    irq = await tb.rd("IRQ")
    assert get_field(irq, "IRQ", "ERR") == 1, "IRQ.ERR not raised"

    # CTRL.CLR_ERR clears the sticky bits, and only those.
    from cordic_tb import make_field
    await tb.wr("CTRL", make_field("CTRL", "CLR_ERR", 1))
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "ERR_DOMAIN") == 0, "CTRL.CLR_ERR did not clear"
    tb.obi.check_protocol()

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    (RESULT_DIR / "domain.json").write_text(json.dumps({"config": tb.cfg}))
