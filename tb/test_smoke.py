# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Bring-up test: reset state, identification, one operation each way."""

import cocotb
from cocotb.triggers import ClockCycles

from cordic_tb import CordicDut, FUNC, REG, get_field, stream_push, stream_pop
import cordic_regmap as rmap


@cocotb.test()
async def test_identity(dut):
    tb = CordicDut(dut)
    await tb.start()
    assert await tb.rd("ID") == rmap.MAGIC, "ID magic mismatch"
    cfg0 = await tb.rd("CFG0")
    assert get_field(cfg0, "CFG0", "DATA_WIDTH") == tb.cfg["data_width"]
    assert get_field(cfg0, "CFG0", "FRAC_BITS") == tb.cfg["frac_bits"]
    assert get_field(cfg0, "CFG0", "NUM_STAGES") == tb.cfg["num_stages"]
    cfg1 = await tb.rd("CFG1")
    assert get_field(cfg1, "CFG1", "VARIANT") == tb.cfg["variant"]
    tb.obi.check_protocol()
    dut._log.info(f"config {tb.cfg}, CFG1 latency="
                  f"{get_field(cfg1, 'CFG1', 'LATENCY')} interval="
                  f"{get_field(cfg1, 'CFG1', 'INTERVAL')}")


@cocotb.test()
async def test_register_path_sin_cos(dut):
    tb = CordicDut(dut)
    await tb.start()
    z = tb.model.to_fx(0.5)
    got = await tb.run_op(FUNC["SIN_COS"], z=z)
    exp = tb.model.run(FUNC["SIN_COS"], z_fx=z)
    assert got["x"] == exp.x, f"cos: got {got['x']}, model {exp.x}"
    assert got["y"] == exp.y, f"sin: got {got['y']}, model {exp.y}"
    assert got["flags"] == exp.flags
    tb.obi.check_protocol()
    dut._log.info(f"cos(0.5)={tb.model.to_real(got['x']):.10f} "
                  f"sin(0.5)={tb.model.to_real(got['y']):.10f}")


@cocotb.test()
async def test_stream_path_exp(dut):
    tb = CordicDut(dut)
    await tb.start()
    z = tb.model.to_fx(1.0)
    await stream_push(dut, FUNC["EXP"], 0, 0, z, tag=0x5A)
    out = await stream_pop(dut)
    exp = tb.model.run(FUNC["EXP"], z_fx=z, tag=0x5A)
    assert out["x"] == exp.x, f"exp: got {out['x']}, model {exp.x}"
    assert out["tag"] == 0x5A
    assert out["func"] == FUNC["EXP"]
    dut._log.info(f"exp(1.0)={tb.model.to_real(out['x']):.10f}")
