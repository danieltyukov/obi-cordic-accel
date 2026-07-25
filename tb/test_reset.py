# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Reset, busy and done semantics, and what happens when a busy unit is poked.

The documented choice for issuing while busy is to queue, not to reject: an
operation goes into the input FIFO and starts when the core is free. Only a write
to a full FIFO is dropped, and that latches STATUS.ERR_OVERFLOW, which software
can see coming through STATUS.IN_FULL. Both halves are asserted here.

DONE is sticky, not a pulse. IRQ.DONE sets when a result enters the output FIFO
and stays set until software writes 1 to it, so an interrupt cannot be missed
between the handler being entered and the register being read.
"""

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from cordic_tb import (CordicDut, FUNC, ObiManager, REG, get_field, make_field,
                       rmap, stream_pop, stream_push)


@cocotb.test()
async def test_state_after_hard_reset(dut):
    """Reset leaves a defined, empty, idle state with no interrupt pending."""
    tb = CordicDut(dut)
    await tb.start()

    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "BUSY") == 0
    assert get_field(st, "STATUS", "IN_EMPTY") == 1
    assert get_field(st, "STATUS", "OUT_EMPTY") == 1
    assert get_field(st, "STATUS", "IN_COUNT") == 0
    assert get_field(st, "STATUS", "OUT_COUNT") == 0
    assert get_field(st, "STATUS", "RES_VALID") == 0
    for f in ("ERR_DOMAIN", "ERR_OVERFLOW", "ERR_UNDERFLOW", "ERR_ACCESS"):
        assert get_field(st, "STATUS", f) == 0, f"STATUS.{f} set after reset"
    assert await tb.rd("IRQ") == 0
    assert await tb.rd("CTRL") == 0
    assert dut.irq_o.value == 0
    assert dut.str_out_valid_o.value == 0, "a result is offered after reset"
    assert dut.str_in_ready_o.value == 1, "the input port is not ready after reset"
    tb.obi.check_protocol()


@cocotb.test()
async def test_reset_during_operation(dut):
    """Asserting reset mid-flight leaves the accelerator idle and usable.

    A deep pipeline holding live operations is the case where a missing reset on a
    valid bit would show up: the stale valids would retire as results after reset.
    """
    tb = CordicDut(dut)
    await tb.start()

    # Fill the pipeline, then reset while it is full.
    dut.str_out_ready_i.value = 0
    for i in range(4):
        await stream_push(dut, FUNC["SIN_COS"], 0, 0, tb.model.to_fx(0.2 * i), tag=i)
    await ClockCycles(dut.clk_i, tb.cfg["num_stages"] // 2)
    assert get_field(await tb.rd("STATUS"), "STATUS", "BUSY") == 1, \
        "not busy with operations in flight"

    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, 4)
    dut.rst_ni.value = 1
    await ClockCycles(dut.clk_i, 4)

    tb.obi = ObiManager(dut, use_rready=tb.cfg["use_rready"])
    cocotb.start_soon(tb.obi.monitor())
    await ClockCycles(dut.clk_i, 2)

    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "BUSY") == 0, "still busy after reset"
    assert get_field(st, "STATUS", "OUT_EMPTY") == 1, "a stale result survived reset"
    assert get_field(st, "STATUS", "IN_EMPTY") == 1
    assert dut.str_out_valid_o.value == 0

    # Wait long enough for any stale in-flight operation to have retired, and
    # confirm none does.
    dut.str_out_ready_i.value = 1
    await ClockCycles(dut.clk_i, tb.cfg["num_stages"] + 10)
    assert dut.str_out_valid_o.value == 0, "a pre-reset operation retired after reset"
    dut.str_out_ready_i.value = 0

    # And the accelerator still works.
    z = tb.model.to_fx(0.5)
    got = await tb.run_op(FUNC["SIN_COS"], z=z)
    exp = tb.model.run(FUNC["SIN_COS"], z_fx=z)
    assert (got["x"], got["y"]) == (exp.x, exp.y)
    dut._log.info("reset with a full pipeline leaves no stale results and the "
                  "accelerator works afterwards")
    tb.obi.check_protocol()


@cocotb.test()
async def test_busy_tracks_the_pipeline(dut):
    """BUSY rises with the first operation and falls once nothing is left."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    assert get_field(await tb.rd("STATUS"), "STATUS", "BUSY") == 0

    dut.str_out_ready_i.value = 0
    await stream_push(dut, FUNC["SIN_COS"], 0, 0, tb.model.to_fx(0.5))
    await ClockCycles(dut.clk_i, 2)
    assert get_field(await tb.rd("STATUS"), "STATUS", "BUSY") == 1, \
        "BUSY did not rise for an accepted operation"

    # Let it finish, but leave the result in the output FIFO. BUSY reports work in
    # progress, not unread results, so it must fall while RES_VALID stays high.
    for _ in range(200):
        st = await tb.rd("STATUS")
        if get_field(st, "STATUS", "RES_VALID") == 1:
            break
    assert get_field(st, "STATUS", "RES_VALID") == 1, "no result appeared"
    for _ in range(50):
        st = await tb.rd("STATUS")
        if get_field(st, "STATUS", "BUSY") == 0:
            break
    assert get_field(st, "STATUS", "BUSY") == 0, \
        "BUSY still set with an empty pipeline and a waiting result"
    assert get_field(st, "STATUS", "RES_VALID") == 1
    dut._log.info("BUSY tracks work in flight, independently of unread results")
    tb.obi.check_protocol()


@cocotb.test()
async def test_issue_while_busy_queues(dut):
    """Issuing while busy queues the operation rather than rejecting it."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    depth = tb.cfg["in_depth"]
    zs = [tb.model.to_fx(0.1 * (i + 1)) for i in range(depth)]

    # Fill the input FIFO from the register path without draining anything.
    for i, z in enumerate(zs):
        await tb.wr("OP_Z", z & 0xFFFFFFFF)
        await tb.wr("CMD", make_field("CMD", "FUNC", FUNC["SIN_COS"]) |
                    make_field("CMD", "TAG", i) | make_field("CMD", "GO", 1))
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "ERR_OVERFLOW") == 0, (
        f"an issue was dropped while the FIFO still had room (count "
        f"{get_field(st, 'STATUS', 'IN_COUNT')})")

    # Every queued operation must come back, in order, with its tag.
    for i, z in enumerate(zs):
        await tb.wait_result()
        got = await tb.read_result()
        exp = tb.model.run(FUNC["SIN_COS"], z_fx=z, tag=i)
        assert got["tag"] == i, f"queued operation {i} returned tag {got['tag']}"
        assert (got["x"], got["y"]) == (exp.x, exp.y)
    dut._log.info(f"{depth} operations queued through the register path all "
                  f"completed in order")
    tb.obi.check_protocol()


@cocotb.test()
async def test_overflow_when_input_queue_full(dut):
    """A write to a full input queue is dropped and latches ERR_OVERFLOW."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    # The iterative core takes NumStages cycles per operation, so filling the FIFO
    # is easy. The pipelined core drains one per cycle, so the FIFO is filled from
    # the streaming port with the output stalled, which backs the pipeline up.
    dut.str_out_ready_i.value = 0
    n = tb.cfg["in_depth"] + tb.cfg["out_depth"] + tb.cfg["num_stages"] + 8
    pushed = 0
    for _ in range(n):
        dut.str_in_valid_i.value = 1
        dut.str_in_func_i.value = FUNC["SIN_COS"]
        dut.str_in_x_i.value = 0
        dut.str_in_y_i.value = 0
        dut.str_in_z_i.value = tb.model.to_fx(0.3)
        await RisingEdge(dut.clk_i)
        if dut.str_in_ready_o.value == 1:
            pushed += 1
    dut.str_in_valid_i.value = 0
    await ClockCycles(dut.clk_i, 4)

    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "IN_FULL") == 1, (
        f"input FIFO not full after {pushed} pushes with the output stalled")
    # The output FIFO fills too, but only for the pipelined core: the iterative one
    # retires slowly enough that the input queue is always the first to back up.
    if tb.cfg["variant"] == 0:
        assert get_field(st, "STATUS", "OUT_FULL") == 1, "output FIFO not full"

    # A register issue into the full queue must be dropped and reported.
    assert get_field(st, "STATUS", "ERR_OVERFLOW") == 0
    await tb.wr("OP_Z", tb.model.to_fx(0.9) & 0xFFFFFFFF)
    await tb.wr("CMD", make_field("CMD", "FUNC", FUNC["SIN_COS"]) |
                make_field("CMD", "GO", 1))
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "ERR_OVERFLOW") == 1, \
        "an issue into a full input queue did not latch ERR_OVERFLOW"
    irq = await tb.rd("IRQ")
    assert get_field(irq, "IRQ", "ERR") == 1, "IRQ.ERR not raised by the overflow"

    # Draining recovers cleanly.
    dut.str_out_ready_i.value = 1
    await ClockCycles(dut.clk_i, n * 2 + 40)
    dut.str_out_ready_i.value = 0
    await tb.wr("CTRL", make_field("CTRL", "CLR_ERR", 1))
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "IN_FULL") == 0
    assert get_field(st, "STATUS", "BUSY") == 0
    assert get_field(st, "STATUS", "ERR_OVERFLOW") == 0
    dut._log.info(f"overflow reported after {pushed} pushes, then drained clean")
    tb.obi.check_protocol()


@cocotb.test()
async def test_done_is_sticky_and_interrupt_masked(dut):
    """IRQ.DONE is sticky, write-1-to-clear, and gated by CTRL.IRQ_EN_DONE."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    assert await tb.rd("IRQ") == 0
    assert dut.irq_o.value == 0

    z = tb.model.to_fx(0.5)
    await tb.issue(FUNC["SIN_COS"], z=z)
    await tb.wait_result()

    irq = await tb.rd("IRQ")
    assert get_field(irq, "IRQ", "DONE") == 1, "IRQ.DONE not set by a completion"
    # Still masked, so no interrupt on the pin.
    assert dut.irq_o.value == 0, "irq_o asserted with IRQ_EN_DONE clear"

    # Sticky: reading STATUS or the result must not clear it.
    await tb.rd("STATUS")
    await tb.rd("RES_X")
    assert get_field(await tb.rd("IRQ"), "IRQ", "DONE") == 1, \
        "IRQ.DONE was cleared by an unrelated read"

    # Unmask and the pin follows.
    await tb.wr("CTRL", make_field("CTRL", "IRQ_EN_DONE", 1))
    await ClockCycles(dut.clk_i, 2)
    assert dut.irq_o.value == 1, "irq_o did not follow IRQ_EN_DONE"

    # Write 1 to clear.
    await tb.wr("IRQ", make_field("IRQ", "DONE", 1))
    await ClockCycles(dut.clk_i, 2)
    assert get_field(await tb.rd("IRQ"), "IRQ", "DONE") == 0, "write 1 did not clear"
    assert dut.irq_o.value == 0

    # Writing 0 must not clear.
    await tb.wr("CTRL", make_field("CTRL", "POP", 1))
    await tb.issue(FUNC["SIN_COS"], z=z)
    await tb.wait_result()
    assert get_field(await tb.rd("IRQ"), "IRQ", "DONE") == 1
    await tb.wr("IRQ", 0)
    assert get_field(await tb.rd("IRQ"), "IRQ", "DONE") == 1, \
        "writing 0 cleared a W1C bit"
    await tb.wr("IRQ", make_field("IRQ", "DONE", 1))
    assert get_field(await tb.rd("IRQ"), "IRQ", "DONE") == 0
    dut._log.info("IRQ.DONE is sticky, write-1-to-clear and correctly masked")
    tb.obi.check_protocol()


@cocotb.test()
async def test_result_read_is_non_destructive(dut):
    """Reading a result does not consume it; only CTRL.POP does."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    z = tb.model.to_fx(0.25)
    await tb.issue(FUNC["SIN_COS"], z=z, tag=0x3C)
    await tb.wait_result()

    first = await tb.read_result(pop=False)
    second = await tb.read_result(pop=False)
    assert first == second, "repeated result reads returned different values"
    assert get_field(await tb.rd("STATUS"), "STATUS", "OUT_COUNT") == 1

    await tb.wr("CTRL", make_field("CTRL", "POP", 1))
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "OUT_COUNT") == 0, "CTRL.POP did not consume"
    assert get_field(st, "STATUS", "RES_VALID") == 0
    dut._log.info("result reads are non-destructive; CTRL.POP consumes")
    tb.obi.check_protocol()


@cocotb.test()
async def test_flush_and_soft_reset(dut):
    """FLUSH_IN, FLUSH_OUT and SOFT_RST each do exactly what they say."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    # Queue several results without reading them, then flush the output side.
    dut.str_out_ready_i.value = 0
    for i in range(min(3, tb.cfg["out_depth"])):
        await stream_push(dut, FUNC["SIN_COS"], 0, 0, tb.model.to_fx(0.1 * (i + 1)),
                          tag=i)
    await ClockCycles(dut.clk_i, tb.cfg["num_stages"] * 3 + 20)
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "OUT_COUNT") > 0, "no results queued to flush"

    await tb.wr("CTRL", make_field("CTRL", "FLUSH_OUT", 1))
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "OUT_COUNT") == 0, "FLUSH_OUT left results behind"
    assert get_field(st, "STATUS", "RES_VALID") == 0

    # Queue input-side work behind a stalled pipeline, then flush the input side.
    for i in range(tb.cfg["in_depth"]):
        await tb.wr("OP_Z", tb.model.to_fx(0.4) & 0xFFFFFFFF)
        await tb.wr("CMD", make_field("CMD", "FUNC", FUNC["SIN_COS"]) |
                    make_field("CMD", "GO", 1))
    await tb.wr("CTRL", make_field("CTRL", "FLUSH_IN", 1))
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "IN_COUNT") == 0, "FLUSH_IN left operations queued"

    # SOFT_RST clears both queues, the sticky errors and the interrupt state, and
    # leaves the operand registers alone.
    await tb.wr("OP_X", 0x0BADC0DE)
    await tb.obi.read(rmap.MAPPED_BYTES, expect_err=True)   # latch ERR_ACCESS
    assert get_field(await tb.rd("STATUS"), "STATUS", "ERR_ACCESS") == 1
    await tb.wr("CTRL", make_field("CTRL", "SOFT_RST", 1))
    await ClockCycles(dut.clk_i, 2)
    st = await tb.rd("STATUS")
    for f in ("ERR_DOMAIN", "ERR_OVERFLOW", "ERR_UNDERFLOW", "ERR_ACCESS"):
        assert get_field(st, "STATUS", f) == 0, f"SOFT_RST left STATUS.{f} set"
    assert get_field(st, "STATUS", "IN_COUNT") == 0
    assert get_field(st, "STATUS", "OUT_COUNT") == 0
    assert await tb.rd("IRQ") == 0
    assert await tb.rd("OP_X") == 0x0BADC0DE, "SOFT_RST cleared an operand register"
    dut._log.info("FLUSH_IN, FLUSH_OUT and SOFT_RST behave as documented")
    tb.obi.check_protocol()


@cocotb.test()
async def test_gain_and_limit_registers(dut):
    """The advertised gains and radii match the model's constants exactly.

    These are what software uses to undo the gain on ROTATE and on the vectoring
    magnitude, so a wrong constant here is a silently wrong answer for the caller.
    """
    tb = CordicDut(dut)
    await tb.start()
    m = tb.model
    checks = [("K_CIRC", m.k_circ), ("IK_CIRC", m.inv_k_circ),
              ("K_HYP", m.k_hyp), ("IK_HYP", m.inv_k_hyp)]
    for name, internal in checks:
        got = await tb.rd_signed(name)
        want = (internal + (1 << (m.guard_frac - 1))) >> m.guard_frac
        assert got == want, f"{name} reads {got}, expected {want}"
        dut._log.info(f"{name} = {got} = {m.to_real(got):.10f}")

    # Radii read back truncated, so writing one straight back as an operand is
    # accepted rather than rejected one LSB out of range.
    for name, internal in [("LIM_CIRC", m.lim_circ), ("LIM_HYP", m.lim_hyp),
                           ("LIM_LIN", m.lim_lin),
                           ("TANH_LIM_HYP", m.tanh_lim_hyp)]:
        got = await tb.rd_signed(name)
        want = internal >> m.guard_frac
        assert got == want, f"{name} reads {got}, expected {want}"
        dut._log.info(f"{name} = {got} = {m.to_real(got):.10f}")

    # The round trip: LIM_HYP written back as an operand must be accepted.
    lim = await tb.rd_signed("LIM_HYP")
    got = await tb.run_op(FUNC["SINH_COSH"], z=lim)
    assert got["flags"] & 0x1 == 0, \
        "sinh rejected an argument equal to the advertised LIM_HYP"
    got = await tb.run_op(FUNC["SINH_COSH"], z=lim + 1)
    assert got["flags"] & 0x1 == 1, \
        "sinh accepted an argument one LSB past LIM_HYP"
    dut._log.info("LIM_HYP is exactly the largest accepted argument")
    tb.obi.check_protocol()
