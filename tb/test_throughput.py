# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Measured latency and throughput, and the trajectory capture for the figures.

Latency and issue interval are measured from the RTL, compared against what CFG1
advertises, and written to build/results/ where the timing and throughput figures
are drawn from. Nothing here is asserted against a hard-coded cycle count that
was not also read back out of the hardware.
"""

import json
import os
import pathlib

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from cordic_tb import (CordicDut, FUNC, get_field, make_field, stream_pop,
                       stream_push, to_signed)

RESULT_DIR = pathlib.Path(os.environ.get(
    "CORDIC_RESULT_DIR",
    pathlib.Path(__file__).resolve().parent.parent / "build" / "results"))

N_STREAM = int(os.environ.get("CORDIC_STREAM_OPS", "256"))


def cycles():
    return cocotb.utils.get_sim_time("ns") // 10


def write_results(name, payload):
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    (RESULT_DIR / name).write_text(json.dumps(payload, indent=1))


@cocotb.test()
async def test_latency(dut):
    """Issue-to-result latency, measured cycle by cycle and matched to CFG1."""
    tb = CordicDut(dut)
    await tb.start()
    cfg1 = await tb.rd("CFG1")
    advertised = get_field(cfg1, "CFG1", "LATENCY")

    # Drain everything, then hand over exactly one operation and count.
    await tb.soft_reset()
    dut.str_out_ready_i.value = 1
    z = tb.model.to_fx(0.5)

    dut.str_in_valid_i.value = 1
    dut.str_in_func_i.value = FUNC["SIN_COS"]
    dut.str_in_tag_i.value = 0
    dut.str_in_x_i.value = 0
    dut.str_in_y_i.value = 0
    dut.str_in_z_i.value = z
    while True:
        await RisingEdge(dut.clk_i)
        if dut.str_in_ready_o.value == 1:
            break
    dut.str_in_valid_i.value = 0
    accepted = cycles()

    n = 0
    while dut.str_out_valid_o.value != 1:
        await RisingEdge(dut.clk_i)
        n += 1
        assert n < 500, "no result within 500 cycles"
    done = cycles()
    dut.str_out_ready_i.value = 0

    measured = done - accepted
    dut._log.info(f"variant={tb.cfg['variant']} measured latency {measured} cycles, "
                  f"CFG1 advertises {advertised}")

    # The streaming port sits behind the input FIFO, which costs one cycle, and in
    # front of the output FIFO, which costs another. CFG1 reports the core's own
    # latency, so the end-to-end figure is that plus the two FIFO hops.
    fifo_overhead = 2
    assert measured == advertised + fifo_overhead, (
        f"end-to-end latency {measured} does not equal the advertised core latency "
        f"{advertised} plus {fifo_overhead} FIFO cycles")
    write_results(f"latency_v{tb.cfg['variant']}.json",
                  {"config": tb.cfg, "advertised_core_latency": advertised,
                   "fifo_overhead": fifo_overhead, "measured_end_to_end": measured})


@cocotb.test()
async def test_sustained_streaming_throughput(dut):
    """One result per cycle through the streaming path, for the pipelined variant.

    Two coroutines run concurrently, one pushing and one draining, so the pipeline
    fills and then stays full. The assertion is on the retire interval once full,
    not on the total, so a slow start cannot mask a stall.
    """
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()
    cfg1 = await tb.rd("CFG1")
    interval = get_field(cfg1, "CFG1", "INTERVAL")

    ops = []
    for i in range(N_STREAM):
        z = tb.model.to_fx(-1.5 + 3.0 * i / N_STREAM)
        ops.append((FUNC["SIN_COS"], 0, 0, z, i & 0xFF))

    retire_cycles = []
    results = []

    async def feeder():
        idx = 0
        while idx < len(ops):
            func, x, y, z, tag = ops[idx]
            dut.str_in_valid_i.value = 1
            dut.str_in_func_i.value = func
            dut.str_in_tag_i.value = tag
            dut.str_in_x_i.value = x
            dut.str_in_y_i.value = y
            dut.str_in_z_i.value = z
            await RisingEdge(dut.clk_i)
            if dut.str_in_ready_o.value == 1:
                idx += 1
        dut.str_in_valid_i.value = 0

    async def drainer():
        dut.str_out_ready_i.value = 1
        while len(results) < len(ops):
            await RisingEdge(dut.clk_i)
            if dut.str_out_valid_o.value == 1:
                retire_cycles.append(cycles())
                results.append({
                    "x": to_signed(dut.str_out_x_o.value),
                    "y": to_signed(dut.str_out_y_o.value),
                    "z": to_signed(dut.str_out_z_o.value),
                    "flags": int(dut.str_out_flags_o.value),
                    "func": int(dut.str_out_func_o.value),
                    "tag": int(dut.str_out_tag_o.value),
                })
        dut.str_out_ready_i.value = 0

    f = cocotb.start_soon(feeder())
    d = cocotb.start_soon(drainer())
    await f
    await d

    assert len(results) == len(ops), f"only {len(results)} of {len(ops)} results came back"

    # Every result correct, in order, with the tag preserved.
    for (func, x, y, z, tag), got in zip(ops, results):
        exp = tb.model.run(func, x_fx=x, y_fx=y, z_fx=z, tag=tag)
        assert (got["x"], got["y"], got["z"], got["flags"], got["tag"]) == \
               (exp.x, exp.y, exp.z, exp.flags, tag), \
            f"streaming result mismatch at tag {tag}"

    gaps = [b - a for a, b in zip(retire_cycles, retire_cycles[1:])]
    # Skip the fill phase: judge the steady state, which starts once the pipeline
    # has as many operations in flight as it has stages.
    warm = tb.cfg["num_stages"] + tb.cfg["in_depth"] + 4
    steady = gaps[warm:] if len(gaps) > warm else gaps
    worst = max(steady)
    mean = sum(steady) / len(steady)
    span = retire_cycles[-1] - retire_cycles[0]
    dut._log.info(f"variant={tb.cfg['variant']}: {len(ops)} ops, "
                  f"{len(steady)} steady-state gaps, worst {worst}, mean {mean:.3f}, "
                  f"total span {span} cycles, CFG1 interval {interval}")

    assert worst == interval, (
        f"steady-state retire interval reached {worst} cycles, but CFG1 advertises "
        f"{interval}; the pipeline is stalling")
    if tb.cfg["variant"] == 0:
        assert worst == 1, "pipelined variant did not sustain one result per cycle"

    write_results(f"throughput_v{tb.cfg['variant']}.json", {
        "config": tb.cfg,
        "ops": len(ops),
        "advertised_interval": interval,
        "steady_worst_gap": worst,
        "steady_mean_gap": mean,
        "span_cycles": span,
        "retire_cycles": retire_cycles,
    })


@cocotb.test()
async def test_stage_occupancy_timeline(dut):
    """Capture the per-stage valid timeline, which the pipeline figure is drawn from."""
    tb = CordicDut(dut)
    await tb.start()
    if tb.cfg["variant"] != 0:
        dut._log.info("iterative variant has no per-stage occupancy vector")
        return
    await tb.soft_reset()

    n = tb.cfg["num_stages"]
    width = len(dut.dbg_stage_valid_o)
    assert width == n + 1, f"dbg_stage_valid_o is {width} bits, expected {n + 1}"

    timeline = []
    n_ops = 6

    async def sampler():
        base = cycles()
        for _ in range(n + n_ops + 12):
            await RisingEdge(dut.clk_i)
            timeline.append({
                "cycle": int(cycles() - base),
                "valid": int(dut.dbg_stage_valid_o.value),
            })

    async def feeder():
        for i in range(n_ops):
            await stream_push(dut, FUNC["SIN_COS"], 0, 0,
                              tb.model.to_fx(0.1 * (i + 1)), tag=i)

    dut.str_out_ready_i.value = 1
    s = cocotb.start_soon(sampler())
    await cocotb.start_soon(feeder())
    await s
    dut.str_out_ready_i.value = 0

    # An operation entering at cycle c must show up at stage s at cycle c+s+1.
    issued = [t["cycle"] for t in timeline if t["valid"] & 1]
    assert len(issued) == n_ops, f"saw {len(issued)} issues, expected {n_ops}"
    for c in issued:
        for s in range(n):
            want = c + s + 1
            row = next((t for t in timeline if t["cycle"] == want), None)
            if row is None:
                break
            assert row["valid"] & (1 << (s + 1)), (
                f"an operation issued at cycle {c} is not at stage {s} on cycle "
                f"{want}")
    dut._log.info(f"per-stage timeline: {n_ops} operations tracked through all "
                  f"{n} stages, {len(timeline)} cycles captured")
    write_results("pipeline_timeline.json",
                  {"config": tb.cfg, "num_stages": n, "issued": issued,
                   "timeline": timeline})


@cocotb.test()
async def test_iterative_trajectory(dut):
    """Capture the vector trajectory per iteration, for the convergence figure."""
    tb = CordicDut(dut)
    await tb.start()
    if tb.cfg["variant"] != 1:
        dut._log.info("pipelined variant does not expose a per-iteration trajectory")
        return
    # Ready stays low while sampling, so the result waits in the output FIFO
    # instead of being swallowed by the sampler's own cycles.
    await tb.soft_reset()
    dut.str_out_ready_i.value = 0

    probes = [
        ("SIN_COS", 0.0, 0.0, 1.0),
        ("SIN_COS", 0.0, 0.0, -0.6),
        ("SIN_COS", 0.0, 0.0, 2.5),
        ("ATAN2", 0.6, 0.8, 0.0),
        ("ATAN2", -0.7, 0.3, 0.0),
        ("SINH_COSH", 0.0, 0.0, 0.9),
        ("EXP", 0.0, 0.0, 1.0),
    ]
    captured = []

    for name, x, y, z in probes:
        xf, yf, zf = (tb.model.to_fx(x), tb.model.to_fx(y), tb.model.to_fx(z))
        points = {}

        async def sampler():
            for _ in range(tb.cfg["num_stages"] + 12):
                await RisingEdge(dut.clk_i)
                if dut.dbg_iter_valid_o.value == 1:
                    idx = int(dut.dbg_iter_idx_o.value)
                    points.setdefault(idx, (
                        to_signed(dut.dbg_iter_x_o.value),
                        to_signed(dut.dbg_iter_y_o.value),
                        to_signed(dut.dbg_iter_z_o.value),
                    ))

        s = cocotb.start_soon(sampler())
        await stream_push(dut, FUNC[name], xf, yf, zf)
        await s
        res = await stream_pop(dut)

        # The captured trajectory must match the model's, point for point.
        coord, mode, x0, y0, z0, dom, chk, pi_ctl, dbl, zero = \
            tb.model.pre(FUNC[name], xf, yf, zf)
        expected = tb.model.trajectory(coord, mode, x0, y0, z0)
        got_idx = sorted(points)
        assert got_idx, f"{name}: no trajectory samples captured"
        for i in got_idx:
            assert points[i] == expected[i], (
                f"{name}: trajectory point {i} is {points[i]}, model says "
                f"{expected[i]}")
        assert len(got_idx) == tb.cfg["num_stages"] + 1, (
            f"{name}: captured {len(got_idx)} of "
            f"{tb.cfg['num_stages'] + 1} trajectory points")

        captured.append({
            "func": name, "x": x, "y": y, "z": z,
            "coord": coord, "mode": mode,
            "int_frac": tb.model.int_frac,
            "points": [list(points[i]) for i in got_idx],
            "result": {"x": res["x"], "y": res["y"], "z": res["z"],
                       "flags": res["flags"]},
        })

    dut._log.info(f"captured {len(captured)} trajectories of "
                  f"{tb.cfg['num_stages'] + 1} points each, all matching the model")
    write_results("trajectories.json",
                  {"config": tb.cfg, "frac_bits": tb.cfg["frac_bits"],
                   "trajectories": captured})


@cocotb.test()
async def test_register_path_throughput(dut):
    """Measure how long a register-mapped operation actually takes end to end.

    This is the number that motivates the streaming port: an OBI-mapped issue needs
    four writes and five reads, so the register path cannot come close to the
    pipeline's retire rate no matter how deep the pipeline is.
    """
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    n_ops = 32
    start = cycles()
    for i in range(n_ops):
        got = await tb.run_op(FUNC["SIN_COS"], z=tb.model.to_fx(0.01 * i), tag=i)
        exp = tb.model.run(FUNC["SIN_COS"], z_fx=tb.model.to_fx(0.01 * i), tag=i)
        assert (got["x"], got["y"]) == (exp.x, exp.y)
    span = cycles() - start
    per_op = span / n_ops
    dut._log.info(f"register path: {n_ops} operations in {span} cycles, "
                  f"{per_op:.1f} cycles each")

    # Now the same count through the streaming port, back to back.
    results = []
    s_start = cycles()

    async def feeder():
        for i in range(n_ops):
            await stream_push(dut, FUNC["SIN_COS"], 0, 0,
                              tb.model.to_fx(0.01 * i), tag=i)

    async def drainer():
        dut.str_out_ready_i.value = 1
        while len(results) < n_ops:
            await RisingEdge(dut.clk_i)
            if dut.str_out_valid_o.value == 1:
                results.append(int(dut.str_out_tag_o.value))
        dut.str_out_ready_i.value = 0

    f = cocotb.start_soon(feeder())
    d = cocotb.start_soon(drainer())
    await f
    await d
    s_span = cycles() - s_start
    s_per_op = s_span / n_ops
    dut._log.info(f"streaming path: {n_ops} operations in {s_span} cycles, "
                  f"{s_per_op:.2f} cycles each, "
                  f"{per_op / s_per_op:.1f}x the register path")

    assert s_per_op < per_op, "streaming is not faster than the register path"
    write_results(f"path_compare_v{tb.cfg['variant']}.json", {
        "config": tb.cfg, "ops": n_ops,
        "register_cycles": span, "register_per_op": per_op,
        "stream_cycles": s_span, "stream_per_op": s_per_op,
        "speedup": per_op / s_per_op,
    })


@cocotb.test()
async def test_backpressure_loses_nothing(dut):
    """A stalled consumer must slow the pipeline, never drop or corrupt a result."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    n_ops = 40
    ops = [(FUNC["SIN_COS"], 0, 0, tb.model.to_fx(-1.0 + 2.0 * i / n_ops), i & 0xFF)
           for i in range(n_ops)]
    results = []

    async def feeder():
        for func, x, y, z, tag in ops:
            await stream_push(dut, func, x, y, z, tag=tag)

    async def bursty_drainer():
        """Take results in bursts of three, then stall for seven cycles."""
        while len(results) < n_ops:
            dut.str_out_ready_i.value = 1
            taken = 0
            while taken < 3 and len(results) < n_ops:
                await RisingEdge(dut.clk_i)
                if dut.str_out_valid_o.value == 1:
                    results.append((int(dut.str_out_tag_o.value),
                                    to_signed(dut.str_out_x_o.value),
                                    to_signed(dut.str_out_y_o.value)))
                    taken += 1
            dut.str_out_ready_i.value = 0
            await ClockCycles(dut.clk_i, 7)

    f = cocotb.start_soon(feeder())
    d = cocotb.start_soon(bursty_drainer())
    await f
    await d

    assert len(results) == n_ops, f"{n_ops - len(results)} results lost to backpressure"
    for (func, x, y, z, tag), (gtag, gx, gy) in zip(ops, results):
        exp = tb.model.run(func, x_fx=x, y_fx=y, z_fx=z, tag=tag)
        assert gtag == tag, f"result order broken: got tag {gtag}, expected {tag}"
        assert (gx, gy) == (exp.x, exp.y), f"result corrupted under backpressure at tag {tag}"
    dut._log.info(f"{n_ops} operations survived bursty backpressure in order")
