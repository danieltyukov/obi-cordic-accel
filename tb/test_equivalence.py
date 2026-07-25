# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Bit-identity between the pipelined and iterative variants.

One simulation contains one elaboration, so the two variants cannot be compared
inside a single run. The comparison is done in two steps instead:

  1. Each variant runs the same fixed, deterministic stimulus list and records
     every result word to build/results/equivalence_v{0,1}.json.
  2. `make test` runs both, then scripts/check_equivalence.py diffs the two files
     and fails on the first differing word.

Step 1 also asserts each variant against the shared bit-accurate model as it goes,
which already implies identity transitively. The file diff is kept because it
proves it directly, without the model in the middle.

The stimulus deliberately mixes coordinate systems and modes operation by
operation. Nothing in the datapath is shared between operations, but a pipelined
core holds several in flight at once, so interleaving is exactly where an
attribute that failed to travel with its operands would show up.
"""

import json
import os
import pathlib
import random

import cocotb

from cordic_tb import CordicDut, FUNC, stream_pop, stream_push

RESULT_DIR = pathlib.Path(os.environ.get(
    "CORDIC_RESULT_DIR",
    pathlib.Path(__file__).resolve().parent.parent / "build" / "results"))

N_CASES = int(os.environ.get("CORDIC_EQUIV_SAMPLES", "900"))

# Fixed seed: both variants must see byte-identical stimulus.
SEED = 0xE0417


def build_stimulus(model, n):
    """A deterministic mix of every function, in-domain and out.

    Depends only on the fixed-point format, not on the microarchitecture, so both
    variants generate the same list.
    """
    rng = random.Random(SEED)
    hi = model.to_real(model.fx_max)
    lo = model.to_real(model.fx_min)
    lim_hyp = model.int_to_real(model.lim_hyp)
    lim_lin = model.int_to_real(model.lim_lin)
    t = model.int_to_real(model.tanh_lim_hyp)
    ln_lo = (1 - t) / (1 + t)

    cases = []

    def add(name, x=0.0, y=0.0, z=0.0):
        cases.append((FUNC[name], model.to_fx(x), model.to_fx(y), model.to_fx(z)))

    # Directed corners first: extremes, zeros, exact boundaries and out-of-domain
    # arguments, so the domain flag path is compared too.
    for z in (0.0, hi, lo, 1.0, -1.0, lim_hyp, -lim_hyp,
              lim_hyp * 1.5, lim_lin, lim_lin * 1.5, model.to_real(1)):
        add("SIN_COS", z=z)
        add("SINH_COSH", z=z)
        add("EXP", z=z)
        add("MUL", x=1.5, z=z)
    for x, y in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0),
                 (hi, hi), (lo, lo), (1.0, 0.5), (-1.0, -0.5), (1.0, 1.5),
                 (model.to_real(1), model.to_real(-1))):
        add("ATAN2", x=x, y=y)
        add("ATANH", x=x, y=y)
        add("DIV", x=x, y=y)
        add("ROTATE", x=x / 4, y=y / 4, z=0.7)
        add("HROTATE", x=x / 8, y=y / 8, z=0.3)
    for w in (0.0, -1.0, ln_lo, ln_lo * 0.5, 1.0, 2.0, hi):
        add("LN", x=w)
    for code in (10, 17, 31):
        cases.append((code, model.to_fx(1.0), 0, model.to_fx(0.5)))

    # Then a random interleave across all ten functions.
    names = ["SIN_COS", "ROTATE", "ATAN2", "SINH_COSH", "HROTATE", "ATANH",
             "EXP", "LN", "MUL", "DIV"]
    while len(cases) < n:
        name = rng.choice(names)
        if name in ("SIN_COS",):
            add(name, z=rng.uniform(lo, hi))
        elif name == "ROTATE":
            add(name, x=rng.uniform(-1.0, 1.0), y=rng.uniform(-1.0, 1.0),
                z=rng.uniform(lo, hi))
        elif name == "ATAN2":
            add(name, x=rng.uniform(lo, hi), y=rng.uniform(lo, hi))
        elif name in ("SINH_COSH", "EXP"):
            add(name, z=rng.uniform(-lim_hyp * 1.3, lim_hyp * 1.3))
        elif name == "HROTATE":
            add(name, x=rng.uniform(-0.5, 0.5), y=rng.uniform(-0.5, 0.5),
                z=rng.uniform(-lim_hyp * 1.3, lim_hyp * 1.3))
        elif name == "ATANH":
            xv = rng.uniform(-2.0, 2.0)
            add(name, x=xv, y=rng.uniform(-1.2, 1.2) * abs(xv))
        elif name == "LN":
            add(name, x=rng.uniform(-0.5, hi))
        elif name == "MUL":
            add(name, x=rng.uniform(-2.0, 2.0), z=rng.uniform(-2.5, 2.5))
        else:  # DIV
            xv = rng.uniform(-3.0, 3.0)
            add(name, x=xv, y=rng.uniform(-2.5, 2.5) * abs(xv))
    return cases[:n]


@cocotb.test()
async def test_record_for_equivalence(dut):
    """Run the shared stimulus and record every result word."""
    tb = CordicDut(dut)
    await tb.start()

    cases = build_stimulus(tb.model, N_CASES)
    records = []
    mismatch = []

    for i, (func, xf, yf, zf) in enumerate(cases):
        tag = i & 0xFF
        await stream_push(dut, func, xf, yf, zf, tag=tag)
        res = await stream_pop(dut)
        exp = tb.model.run(func, x_fx=xf, y_fx=yf, z_fx=zf, tag=tag)
        if (res["x"], res["y"], res["z"], res["flags"], res["func"], res["tag"]) != \
           (exp.x, exp.y, exp.z, exp.flags, func, tag):
            mismatch.append(
                f"case {i} func={func} x={xf} y={yf} z={zf}: RTL "
                f"{(res['x'], res['y'], res['z'], res['flags'], res['func'], res['tag'])} "
                f"model {(exp.x, exp.y, exp.z, exp.flags, func, tag)}")
        records.append([func, xf, yf, zf, res["x"], res["y"], res["z"],
                        res["flags"], res["tag"]])

    assert not mismatch, f"{len(mismatch)} model mismatches, first: {mismatch[0]}"

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULT_DIR / f"equivalence_v{tb.cfg['variant']}.json"
    path.write_text(json.dumps({
        "config": tb.cfg,
        "seed": SEED,
        "n_cases": len(records),
        "records": records,
    }))
    dut._log.info(f"variant={tb.cfg['variant']}: {len(records)} results recorded to "
                  f"{path.name}, all matching the model")


@cocotb.test()
async def test_interleaved_functions_in_flight(dut):
    """A pipeline full of different functions at once keeps every one correct.

    Ten operations, each a different coordinate system or mode, are pushed
    back to back so a pipelined core holds all of them simultaneously. If the
    attribute vector did not travel beside its own operands, results would come
    back computed under a neighbour's coordinate system.
    """
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()
    m = tb.model

    plan = [
        ("SIN_COS", 0.0, 0.0, 0.9),
        ("MUL", 1.25, 0.0, 0.5),
        ("SINH_COSH", 0.0, 0.0, 0.8),
        ("ATAN2", 0.6, 0.8, 0.0),
        ("DIV", 2.0, 1.0, 0.0),
        ("ATANH", 1.0, 0.6, 0.0),
        ("EXP", 0.0, 0.0, 0.4),
        ("LN", 2.5, 0.0, 0.0),
        ("ROTATE", 0.5, 0.25, 1.2),
        ("HROTATE", 0.4, 0.2, 0.3),
    ]
    fx = [(FUNC[n], m.to_fx(x), m.to_fx(y), m.to_fx(z)) for n, x, y, z in plan]

    results = []

    async def feeder():
        for i, (func, x, y, z) in enumerate(fx):
            await stream_push(dut, func, x, y, z, tag=i)

    async def drainer():
        from cocotb.triggers import RisingEdge
        from cordic_tb import to_signed
        dut.str_out_ready_i.value = 1
        while len(results) < len(fx):
            await RisingEdge(dut.clk_i)
            if dut.str_out_valid_o.value == 1:
                results.append((int(dut.str_out_tag_o.value),
                                int(dut.str_out_func_o.value),
                                to_signed(dut.str_out_x_o.value),
                                to_signed(dut.str_out_y_o.value),
                                to_signed(dut.str_out_z_o.value),
                                int(dut.str_out_flags_o.value)))
        dut.str_out_ready_i.value = 0

    f = cocotb.start_soon(feeder())
    d = cocotb.start_soon(drainer())
    await f
    await d

    for i, ((func, x, y, z), got) in enumerate(zip(fx, results)):
        exp = tb.model.run(func, x_fx=x, y_fx=y, z_fx=z, tag=i)
        assert got == (i, func, exp.x, exp.y, exp.z, exp.flags), (
            f"interleaved operation {i} ({plan[i][0]}) came back as {got}, "
            f"expected {(i, func, exp.x, exp.y, exp.z, exp.flags)}")
    dut._log.info(f"{len(plan)} operations of {len(set(p[0] for p in plan))} "
                  f"different functions in flight together, all correct and in order")
