# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""OBI v1.6 subordinate protocol compliance.

Signals exercised: req, gnt, addr, we, be, wdata, aid on the A channel, and
rvalid, rdata, rid, err on the R channel. Optional fields are not implemented, so
there is nothing to test there; Croc's SbrObiCfg sets OptionalCfg to zero.

The ObiManager in cordic_tb.py checks the standing invariants continuously while
every test runs: one R beat per accepted A beat, in order, with rid echoing aid,
and never an R beat without an outstanding request. Each test below adds a
specific scenario on top.

Run this module twice, once with CORDIC_USE_RREADY=0 (Croc's configuration, where
a response must be taken the cycle it is offered) and once with 1 (where the
response waits for rready and gnt drops while one is held). `make test` does both.
"""

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from cordic_tb import (CordicDut, FUNC, ObiManager, REG, get_field, make_field,
                       rmap)

RO_REGS = [r.name for r in rmap.REGS if r.access == "RO"]
RW_REGS = [r.name for r in rmap.REGS if r.access in ("RW", "W1C")]

# Offsets inside the 4 KB window with nothing behind them.
UNMAPPED = [rmap.MAPPED_BYTES, rmap.MAPPED_BYTES + 4, 0x100, 0x400, 0x800,
            rmap.WINDOW_BYTES - 4]


@cocotb.test()
async def test_reset_values(dut):
    """Every register reads its documented reset value."""
    tb = CordicDut(dut)
    await tb.start()
    assert await tb.rd("ID") == rmap.MAGIC
    maj, minr, pat = rmap.VERSION
    assert await tb.rd("VERSION") == (maj << 24) | (minr << 16) | (pat << 8)
    for name in ("CTRL", "IRQ", "OP_X", "OP_Y", "OP_Z", "CMD", "SCRATCH"):
        assert await tb.rd(name) == 0, f"{name} is not zero after reset"
    st = await tb.rd("STATUS")
    for f, want in (("BUSY", 0), ("RES_VALID", 0), ("IN_FULL", 0), ("IN_EMPTY", 1),
                    ("OUT_FULL", 0), ("OUT_EMPTY", 1), ("IN_COUNT", 0),
                    ("OUT_COUNT", 0), ("ERR_DOMAIN", 0), ("ERR_OVERFLOW", 0),
                    ("ERR_UNDERFLOW", 0), ("ERR_ACCESS", 0)):
        got = get_field(st, "STATUS", f)
        assert got == want, f"STATUS.{f} is {got} after reset, expected {want}"
    assert dut.irq_o.value == 0, "irq_o is asserted after reset"
    tb.obi.check_protocol()


@cocotb.test()
async def test_back_to_back(dut):
    """A request accepted every cycle, with no idle beat, still answers in order."""
    tb = CordicDut(dut)
    await tb.start()
    ops = [(False, REG["ID"], 0, 0xF),
           (False, REG["VERSION"], 0, 0xF),
           (True, REG["SCRATCH"], 0xDEADBEEF, 0xF),
           (False, REG["SCRATCH"], 0, 0xF),
           (True, REG["OP_X"], 0x00001234, 0xF),
           (False, REG["OP_X"], 0, 0xF),
           (False, REG["CFG0"], 0, 0xF),
           (False, REG["CFG1"], 0, 0xF)]
    before = tb.obi.beats
    rsp = await tb.obi.burst(ops)
    assert tb.obi.beats - before == len(ops), "one R beat per A beat not honoured"
    maj, minr, pat = rmap.VERSION
    assert rsp[0][2] == rmap.MAGIC
    assert rsp[1][2] == (maj << 24) | (minr << 16) | (pat << 8)
    assert rsp[3][2] == 0xDEADBEEF, f"scratch readback {rsp[3][2]:#x}"
    assert rsp[5][2] == 0x1234
    assert all(r[3] == 0 for r in rsp), "unexpected error response"
    tb.obi.check_protocol()

    # Sustained rate: with UseRReady low, gnt is high for ever, so 64 requests
    # take 64 cycles plus one for the last response.
    start = cocotb.utils.get_sim_time("ns")
    await tb.obi.burst([(False, REG["ID"], 0, 0xF)] * 64)
    span = (cocotb.utils.get_sim_time("ns") - start) / 10
    dut._log.info(f"64 back-to-back reads took {span:.0f} cycles "
                  f"(use_rready={tb.cfg['use_rready']})")
    if not tb.cfg["use_rready"]:
        assert span <= 70, f"64 back-to-back reads took {span} cycles, expected ~65"
    tb.obi.check_protocol()


@cocotb.test()
async def test_gnt_stall_and_delayed_rvalid(dut):
    """With rready in play, gnt drops while a response is held, then recovers.

    This is the case OBI's optional rready exists for. With UseRReady low the DUT
    cannot stall, and the test instead asserts that gnt stays high throughout,
    which is the property a manager that ignores rready depends on.
    """
    tb = CordicDut(dut)
    await tb.start()

    if not tb.cfg["use_rready"]:
        dut.obi_rready_i.value = 0
        saw_low = False
        for _ in range(40):
            await RisingEdge(dut.clk_i)
            dut.obi_req_i.value = 1
            dut.obi_addr_i.value = REG["ID"]
            dut.obi_we_i.value = 0
            if dut.obi_gnt_o.value == 0:
                saw_low = True
        dut.obi_req_i.value = 0
        dut.obi_rready_i.value = 1
        await ClockCycles(dut.clk_i, 4)
        assert not saw_low, ("gnt dropped even though UseRReady is 0, so a manager "
                             "that does not drive rready could stall")
        dut._log.info("UseRReady=0: gnt stayed high for 40 cycles of continuous req")
        # The manager's bookkeeping is stale after driving the bus by hand.
        tb.obi = ObiManager(dut, use_rready=False)
        cocotb.start_soon(tb.obi.monitor())
        await ClockCycles(dut.clk_i, 2)
        assert await tb.rd("ID") == rmap.MAGIC, "bus unusable after the manual drive"
        return

    # UseRReady = 1. Hold rready low, issue one request, and watch gnt fall.
    dut.obi_rready_i.value = 0
    dut.obi_req_i.value = 1
    dut.obi_addr_i.value = REG["ID"]
    dut.obi_we_i.value = 0
    dut.obi_be_i.value = 0xF
    dut.obi_aid_i.value = 1
    while dut.obi_gnt_o.value != 1:
        await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)          # request accepted here
    dut.obi_req_i.value = 0

    # The response is now offered and must be held, unchanged, until rready.
    held = 0
    while dut.obi_rvalid_o.value != 1:
        await RisingEdge(dut.clk_i)
    first = (int(dut.obi_rdata_o.value), int(dut.obi_rid_o.value),
             int(dut.obi_err_o.value))
    for _ in range(12):
        await RisingEdge(dut.clk_i)
        assert dut.obi_rvalid_o.value == 1, "rvalid dropped before rready"
        now = (int(dut.obi_rdata_o.value), int(dut.obi_rid_o.value),
               int(dut.obi_err_o.value))
        assert now == first, f"held response changed from {first} to {now}"
        assert dut.obi_gnt_o.value == 0, "gnt high while a response is unclaimed"
        held += 1
    assert first[0] == rmap.MAGIC and first[1] == 1
    dut._log.info(f"UseRReady=1: response held unchanged for {held} cycles, "
                  f"gnt low throughout")

    dut.obi_rready_i.value = 1
    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    assert dut.obi_rvalid_o.value == 0, "rvalid still high after rready"

    tb.obi = ObiManager(dut, use_rready=True)
    cocotb.start_soon(tb.obi.monitor())
    await ClockCycles(dut.clk_i, 2)
    assert await tb.rd("ID") == rmap.MAGIC, "bus unusable after the stall"
    assert await tb.rd("VERSION") != 0
    tb.obi.check_protocol()


@cocotb.test()
async def test_byte_enables(dut):
    """Partial writes touch only the enabled bytes; be = 0 changes nothing."""
    rng = random.Random(0xBE)
    tb = CordicDut(dut)
    await tb.start()

    await tb.wr("SCRATCH", 0x00000000)
    for be, wdata, want in [(0x1, 0xFFFFFFFF, 0x000000FF),
                            (0x2, 0x0000AA00, 0x0000AAFF),
                            (0x4, 0x00BB0000, 0x00BBAAFF),
                            (0x8, 0xCC000000, 0xCCBBAAFF),
                            (0x0, 0x00000000, 0xCCBBAAFF),
                            (0x5, 0x11223344, 0xCC22AA44),
                            (0xA, 0x55667788, 0x55227744)]:
        await tb.wr("SCRATCH", wdata, be=be)
        got = await tb.rd("SCRATCH")
        assert got == want, (f"be={be:#x} wdata={wdata:#010x}: scratch is "
                             f"{got:#010x}, expected {want:#010x}")

    # Random byte-enable soak against a software shadow.
    shadow = await tb.rd("SCRATCH")
    for _ in range(120):
        be = rng.randrange(16)
        wdata = rng.getrandbits(32)
        mask = 0
        for b in range(4):
            if be & (1 << b):
                mask |= 0xFF << (8 * b)
        shadow = (shadow & ~mask) | (wdata & mask)
        await tb.wr("SCRATCH", wdata, be=be)
        got = await tb.rd("SCRATCH")
        assert got == shadow, (f"be={be:#x}: scratch is {got:#010x}, "
                              f"shadow {shadow:#010x}")

    # A read's byte enables do not narrow the returned word: OBI subordinates
    # return the whole word and the manager selects.
    for be in (0x1, 0x3, 0x8, 0xF):
        assert await tb.rd("ID", be=be) == rmap.MAGIC, \
            f"read with be={be:#x} did not return the full word"
    tb.obi.check_protocol()
    dut._log.info("byte enables: 7 directed plus 120 random writes match the shadow")


@cocotb.test()
async def test_read_only_writes_error(dut):
    """A write to a read-only register errors and changes nothing."""
    tb = CordicDut(dut)
    await tb.start()
    for name in RO_REGS:
        before = await tb.rd(name)
        await tb.wr(name, 0xFFFFFFFF, expect_err=True)
        after = await tb.rd(name)
        assert after == before, (f"write to read-only {name} changed it from "
                                 f"{before:#010x} to {after:#010x}")
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "ERR_ACCESS") == 1, \
        "STATUS.ERR_ACCESS not latched by a read-only write"
    dut._log.info(f"{len(RO_REGS)} read-only registers all reject writes with r.err")
    tb.obi.check_protocol()


@cocotb.test()
async def test_reserved_bits(dut):
    """Reserved bits ignore writes and read back zero; W1S bits always read zero."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    for name in RW_REGS:
        writable = 0
        readable = 0
        reg = rmap.reg_by_name(name)
        for f in reg.fields:
            m = ((1 << (f.hi - f.lo + 1)) - 1) << f.lo
            writable |= m
            if f.access != "W1S":
                readable |= m
        # Writing all ones must leave nothing outside `readable` set. CTRL's and
        # IRQ's trigger and clear bits are covered by their own tests.
        if name in ("CTRL", "IRQ"):
            continue
        await tb.wr(name, 0xFFFFFFFF)
        got = await tb.rd(name)
        assert got & ~readable == 0, (f"{name}: bits {got & ~readable:#010x} outside "
                                      f"the readable mask {readable:#010x} read back "
                                      f"as one")
        await tb.wr(name, 0)

    # CTRL: the five trigger bits read back zero even in the cycle they fire.
    await tb.wr("CTRL", 0xFFFFFFFF)
    ctrl = await tb.rd("CTRL")
    trig = 0
    for f in rmap.reg_by_name("CTRL").fields:
        if f.access == "W1S":
            trig |= ((1 << (f.hi - f.lo + 1)) - 1) << f.lo
    assert ctrl & trig == 0, f"CTRL trigger bits read back as {ctrl & trig:#x}"
    assert get_field(ctrl, "CTRL", "IRQ_EN_DONE") == 1
    assert get_field(ctrl, "CTRL", "IRQ_EN_ERR") == 1
    await tb.wr("CTRL", 0)
    assert await tb.rd("CTRL") == 0
    dut._log.info("reserved bits read zero and ignore writes across every RW register")
    tb.obi.check_protocol()


@cocotb.test()
async def test_unmapped_and_unaligned(dut):
    """Unmapped offsets and unaligned addresses error without wedging the bus."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    for off in UNMAPPED:
        rdata = await tb.obi.read(off, expect_err=True)
        assert rdata == rmap.BAD_ACCESS_DATA, \
            f"unmapped read at {off:#05x} returned {rdata:#010x}"
        await tb.obi.write(off, 0x12345678, expect_err=True)

    for base in (REG["ID"], REG["SCRATCH"], REG["STATUS"]):
        for lsbs in (1, 2, 3):
            rdata = await tb.obi.read(base + lsbs, expect_err=True)
            assert rdata == rmap.BAD_ACCESS_DATA, \
                f"unaligned read at {base + lsbs:#05x} returned {rdata:#010x}"
            await tb.obi.write(base + lsbs, 0xA5A5A5A5, expect_err=True)

    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "ERR_ACCESS") == 1

    # An unaligned write must not have disturbed the target register.
    assert await tb.rd("SCRATCH") == 0, "an unaligned write reached SCRATCH"
    assert await tb.rd("ID") == rmap.MAGIC, "the bus is unusable after the faults"
    dut._log.info(f"{len(UNMAPPED)} unmapped and 9 unaligned accesses all faulted "
                  f"cleanly")
    tb.obi.check_protocol()


@cocotb.test()
async def test_faults_interleaved_with_traffic(dut):
    """Faulting accesses mixed into a back-to-back stream keep the responses aligned.

    This is the case where a subordinate that mishandles errors loses response
    ordering, so the rid echo check in the monitor is doing real work here.
    """
    rng = random.Random(0xFA17)
    tb = CordicDut(dut)
    await tb.start()
    await tb.wr("SCRATCH", 0x0F0F0F0F)

    good = [(False, REG["ID"], 0, 0xF, rmap.MAGIC, 0),
            (False, REG["SCRATCH"], 0, 0xF, 0x0F0F0F0F, 0)]
    bad = [(False, rmap.MAPPED_BYTES, 0, 0xF, rmap.BAD_ACCESS_DATA, 1),
           (False, REG["ID"] + 2, 0, 0xF, rmap.BAD_ACCESS_DATA, 1),
           (True, REG["ID"], 0xFFFF, 0xF, None, 1)]

    plan = []
    for _ in range(60):
        plan.append(rng.choice(good + bad))
    rsp = await tb.obi.burst([(w, a, d, b) for w, a, d, b, _, _ in plan])
    assert len(rsp) == len(plan)
    for (w, a, d, b, want_data, want_err), (ra, rw, rdata, rerr) in zip(plan, rsp):
        assert rerr == want_err, (f"{'write' if w else 'read'} {a:#05x}: err={rerr}, "
                                  f"expected {want_err}")
        if want_data is not None and not w:
            assert rdata == want_data, (f"read {a:#05x}: {rdata:#010x}, expected "
                                        f"{want_data:#010x}")
    tb.obi.check_protocol()
    dut._log.info(f"{len(plan)} interleaved good and faulting accesses stayed in order")


@cocotb.test()
async def test_no_deadlock_under_random_traffic(dut):
    """Random traffic over the whole window, including issues, never deadlocks."""
    rng = random.Random(0x0B1)
    tb = CordicDut(dut)
    await tb.start()

    for i in range(500):
        off = rng.choice(
            [r.offset for r in rmap.REGS] +
            [rng.randrange(0, rmap.WINDOW_BYTES) for _ in range(3)])
        we = rng.random() < 0.5
        be = rng.randrange(16)
        wdata = rng.getrandbits(32)
        aligned = (off % 4) == 0
        mapped = off < rmap.MAPPED_BYTES
        ro = mapped and aligned and any(
            r.offset == off and r.access == "RO" for r in rmap.REGS)
        expect_err = (not aligned) or (not mapped) or (we and ro)
        if we:
            await tb.obi.write(off, wdata, be=be, expect_err=expect_err)
        else:
            await tb.obi.read(off, be=be, expect_err=expect_err)

    # Everything still works, and every request got exactly one answer.
    assert not tb.obi.outstanding, "requests left unanswered"
    assert await tb.rd("ID") == rmap.MAGIC
    tb.obi.check_protocol()
    dut._log.info(f"500 random accesses, {tb.obi.beats} R beats, no deadlock")


@cocotb.test()
async def test_aid_echo_across_widths(dut):
    """rid echoes aid for every value the configured IdWidth can hold."""
    tb = CordicDut(dut)
    await tb.start()
    width = len(dut.obi_aid_i)
    for aid in range(1 << width):
        tb.obi.next_aid = aid
        got = await tb.rd("ID")
        assert got == rmap.MAGIC
    tb.obi.check_protocol()
    dut._log.info(f"aid echo verified for all {1 << width} values of a "
                  f"{width}-bit aid")


@cocotb.test()
async def test_write_sampled_only_on_gnt(dut):
    """A-channel payload is sampled on req and gnt, not from the idle bus.

    After the handshake the manager drops req and drives a different wdata. If the
    subordinate latched anything outside the handshake, SCRATCH would hold the
    later value.
    """
    tb = CordicDut(dut)
    await tb.start()
    await tb.wr("SCRATCH", 0x11111111)
    assert await tb.rd("SCRATCH") == 0x11111111

    dut.obi_req_i.value = 1
    dut.obi_we_i.value = 1
    dut.obi_be_i.value = 0xF
    dut.obi_addr_i.value = REG["SCRATCH"]
    dut.obi_wdata_i.value = 0x22222222
    dut.obi_aid_i.value = 0
    while dut.obi_gnt_o.value != 1:
        await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    # Handshake done. Now drive junk with req low for a while.
    dut.obi_req_i.value = 0
    dut.obi_wdata_i.value = 0x33333333
    dut.obi_addr_i.value = REG["OP_X"]
    dut.obi_we_i.value = 1
    await ClockCycles(dut.clk_i, 8)
    dut.obi_we_i.value = 0
    dut.obi_be_i.value = 0

    tb.obi = ObiManager(dut, use_rready=tb.cfg["use_rready"])
    cocotb.start_soon(tb.obi.monitor())
    await ClockCycles(dut.clk_i, 2)
    assert await tb.rd("SCRATCH") == 0x22222222, \
        "SCRATCH does not hold the handshaken value"
    assert await tb.rd("OP_X") == 0, "a write landed while req was low"
    dut._log.info("A-channel payload is only sampled on req and gnt")
    tb.obi.check_protocol()


@cocotb.test()
async def test_issue_through_registers_full_flow(dut):
    """A full register-path operation, including the partial CMD write rule."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    z = tb.model.to_fx(0.75)
    await tb.wr("OP_Z", z & 0xFFFFFFFF)
    # GO sits in byte 3, so a write that leaves byte 3 out updates FUNC and TAG
    # without starting anything.
    cmd = (make_field("CMD", "FUNC", FUNC["SIN_COS"]) |
           make_field("CMD", "TAG", 0x27) | make_field("CMD", "GO", 1))
    await tb.wr("CMD", cmd, be=0x7)
    await ClockCycles(dut.clk_i, 40)
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "RES_VALID") == 0, \
        "a CMD write without byte 3 issued an operation"
    assert get_field(await tb.rd("CMD"), "CMD", "FUNC") == FUNC["SIN_COS"]
    assert get_field(await tb.rd("CMD"), "CMD", "TAG") == 0x27

    # Now with byte 3 included.
    await tb.wr("CMD", cmd)
    await tb.wait_result()
    got = await tb.read_result()
    exp = tb.model.run(FUNC["SIN_COS"], z_fx=z, tag=0x27)
    assert (got["x"], got["y"], got["z"]) == (exp.x, exp.y, exp.z)
    assert got["tag"] == 0x27 and got["func"] == FUNC["SIN_COS"]
    assert await tb.rd("CMD") & (1 << 31) == 0, "CMD.GO does not read back as zero"
    dut._log.info("register-path issue: GO needs byte 3, tag and func are echoed")
    tb.obi.check_protocol()


@cocotb.test()
async def test_result_underflow(dut):
    """Reading or popping an empty result queue is reported, not silently served."""
    tb = CordicDut(dut)
    await tb.start()
    await tb.soft_reset()

    for name in ("RES_X", "RES_Y", "RES_Z", "RES_FLAGS"):
        assert await tb.rd(name) == 0, f"{name} is not zero while empty"
    st = await tb.rd("STATUS")
    assert get_field(st, "STATUS", "ERR_UNDERFLOW") == 1, \
        "reading an empty result queue did not latch ERR_UNDERFLOW"

    await tb.wr("CTRL", make_field("CTRL", "CLR_ERR", 1))
    assert get_field(await tb.rd("STATUS"), "STATUS", "ERR_UNDERFLOW") == 0
    await tb.wr("CTRL", make_field("CTRL", "POP", 1))
    assert get_field(await tb.rd("STATUS"), "STATUS", "ERR_UNDERFLOW") == 1, \
        "popping an empty result queue did not latch ERR_UNDERFLOW"
    dut._log.info("empty-queue reads and pops both latch STATUS.ERR_UNDERFLOW")
    tb.obi.check_protocol()


@cocotb.test()
async def test_narrow_format_sign_extension(dut):
    """Operand and result words sign-extend to 32 bits for narrow formats."""
    tb = CordicDut(dut)
    await tb.start()
    w = tb.cfg["data_width"]
    if w >= 32:
        dut._log.info("DataWidth is 32, nothing to sign-extend")
        return
    await tb.wr("OP_X", (1 << (w - 1)) & 0xFFFFFFFF)   # most negative
    got = await tb.rd("OP_X")
    want = (-(1 << (w - 1))) & 0xFFFFFFFF
    assert got == want, f"OP_X read back {got:#010x}, expected {want:#010x}"
    dut._log.info(f"OP_X sign-extends a {w}-bit word to 32 bits")
    tb.obi.check_protocol()
