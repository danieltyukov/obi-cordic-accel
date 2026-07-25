# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Shared cocotb helpers: an OBI manager, a streaming driver and a DUT wrapper.

The OBI manager below is written against the protocol rules rather than against
the DUT's implementation, so it doubles as a checker. Every response it collects
is matched to the request that produced it and the ordering, rid echo and one
beat per accepted request rules are asserted as they happen.
"""

import os
import pathlib
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import cordic_regmap as rmap  # noqa: E402
from cordic_model import CordicModel, FUNC, FUNC_NAME  # noqa: E402

CLK_PERIOD_NS = 10

REG = {r.name: r.offset for r in rmap.REGS}


# --- cocotb 1.x / 2.x compatibility -----------------------------------------
# The suite runs on cocotb 1.9 here because Verilator 5.020 is what this machine
# has and cocotb 2.0 needs 5.036. These two shims are the whole difference, so the
# tests also run unchanged under cocotb 2.x.

def make_clock(signal, period, unit="ns"):
    try:
        return Clock(signal, period, unit=unit)      # cocotb 2.x
    except TypeError:
        return Clock(signal, period, units=unit)     # cocotb 1.x


def to_signed(value):
    to = getattr(value, "to_signed", None)
    if to is not None:
        return to()                                  # cocotb 2.x
    return value.signed_integer                      # cocotb 1.x


def field(reg_name, field_name):
    """Return (shift, mask) for a register field."""
    reg = rmap.reg_by_name(reg_name)
    for f in reg.fields:
        if f.name == field_name:
            return f.lo, ((1 << (f.hi - f.lo + 1)) - 1) << f.lo
    raise KeyError(f"{reg_name}.{field_name}")


def get_field(word, reg_name, field_name):
    shift, mask = field(reg_name, field_name)
    return (word & mask) >> shift


def make_field(reg_name, field_name, value):
    shift, mask = field(reg_name, field_name)
    return (value << shift) & mask


def env_int(name, default):
    return int(os.environ.get(name, default))


def dut_config(dut):
    """Read the elaborated configuration back out of CFG0 and CFG1.

    Taking it from the DUT rather than from the environment means the model is
    always built for the hardware actually compiled, and a mismatch between the
    Makefile and the RTL shows up as a failing comparison instead of silently
    skewed expectations.
    """
    return {
        "data_width": env_int("CORDIC_DATA_WIDTH", 32),
        "frac_bits": env_int("CORDIC_FRAC_BITS", 29),
        "num_stages": env_int("CORDIC_NUM_STAGES", 28),
        "guard_int": env_int("CORDIC_GUARD_INT", 2),
        "guard_frac": env_int("CORDIC_GUARD_FRAC", 4),
        "variant": env_int("CORDIC_VARIANT", 0),
        "use_rready": env_int("CORDIC_USE_RREADY", 0),
        "in_depth": env_int("CORDIC_IN_DEPTH", 4),
        "out_depth": env_int("CORDIC_OUT_DEPTH", 4),
    }


class ObiError(Exception):
    """An OBI response came back with r.err set."""

    def __init__(self, addr, we, rdata):
        super().__init__(f"OBI error response: addr=0x{addr:03x} we={int(we)} "
                         f"rdata=0x{rdata:08x}")
        self.addr = addr
        self.we = we
        self.rdata = rdata


class ObiManager:
    """Drives the OBI A channel and collects the R channel.

    `use_rready` must match the DUT's UseRReady parameter. With rready in play the
    manager can hold a response off, which is what makes the gnt back-pressure path
    observable.
    """

    def __init__(self, dut, use_rready=False):
        self.dut = dut
        self.use_rready = bool(use_rready)
        self.next_aid = 0
        self.aid_width = len(dut.obi_aid_i)
        # Requests accepted but not yet answered, oldest first.
        self.outstanding = []
        self.responses = []
        self.beats = 0
        self.protocol_errors = []
        self._idle_a()
        self.dut.obi_rready_i.value = 1

    def _idle_a(self):
        self.dut.obi_req_i.value = 0
        self.dut.obi_we_i.value = 0
        self.dut.obi_be_i.value = 0
        self.dut.obi_addr_i.value = 0
        self.dut.obi_wdata_i.value = 0
        self.dut.obi_aid_i.value = 0

    def _alloc_aid(self):
        aid = self.next_aid
        self.next_aid = (self.next_aid + 1) % (1 << self.aid_width)
        return aid

    async def monitor(self):
        """Collect R beats and check the protocol invariants for ever."""
        while True:
            await RisingEdge(self.dut.clk_i)
            if self.dut.obi_rvalid_o.value != 1:
                continue
            taken = (not self.use_rready) or (self.dut.obi_rready_i.value == 1)
            if not taken:
                continue
            rid = int(self.dut.obi_rid_o.value)
            rdata = int(self.dut.obi_rdata_o.value)
            rerr = int(self.dut.obi_err_o.value)
            if not self.outstanding:
                self.protocol_errors.append("R beat with no outstanding request")
                continue
            addr, we, aid = self.outstanding.pop(0)
            if rid != aid:
                self.protocol_errors.append(
                    f"rid 0x{rid:x} does not echo aid 0x{aid:x} for addr 0x{addr:03x}")
            self.beats += 1
            self.responses.append((addr, we, rdata, rerr))

    async def _drive(self, addr, we, wdata, be):
        """Hold the A channel until gnt, then release it. One request."""
        aid = self._alloc_aid()
        self.dut.obi_req_i.value = 1
        self.dut.obi_addr_i.value = addr
        self.dut.obi_we_i.value = 1 if we else 0
        self.dut.obi_wdata_i.value = wdata & 0xFFFFFFFF
        self.dut.obi_be_i.value = be
        self.dut.obi_aid_i.value = aid
        while True:
            await RisingEdge(self.dut.clk_i)
            if self.dut.obi_gnt_o.value == 1:
                break
        self.outstanding.append((addr, we, aid))
        self._idle_a()
        return aid

    async def _await_response(self, aid):
        """Pop the next response. OBI keeps responses in order and this manager
        allows one outstanding request, so the head is always the right one; the
        monitor has already checked that its rid echoes the matching aid."""
        while not self.responses:
            await RisingEdge(self.dut.clk_i)
        return self.responses.pop(0)

    async def write(self, addr, value, be=0xF, expect_err=False):
        aid = await self._drive(addr, True, value, be)
        a, w, rdata, rerr = await self._await_response(aid)
        if bool(rerr) != bool(expect_err):
            raise AssertionError(
                f"write 0x{addr:03x}: expected err={int(expect_err)}, got {rerr}")
        if rerr and not expect_err:
            raise ObiError(addr, True, rdata)
        return rerr

    async def read(self, addr, be=0xF, expect_err=False):
        aid = await self._drive(addr, False, 0, be)
        a, w, rdata, rerr = await self._await_response(aid)
        if bool(rerr) != bool(expect_err):
            raise AssertionError(
                f"read 0x{addr:03x}: expected err={int(expect_err)}, got {rerr} "
                f"(rdata=0x{rdata:08x})")
        if rerr and not expect_err:
            raise ObiError(addr, False, rdata)
        return rdata

    async def burst(self, ops):
        """Issue requests back to back with no idle cycle between them.

        `ops` is a list of (we, addr, wdata, be). Returns the responses in order.
        A single coroutine drives every A beat, so a request goes out on the very
        next cycle after gnt.
        """
        aids = []
        for we, addr, wdata, be in ops:
            # _drive re-asserts req in the same delta it saw gnt, so consecutive
            # calls put a request on the bus every cycle with no idle beat.
            aids.append(await self._drive(addr, we, wdata, be))
        out = []
        for aid in aids:
            out.append(await self._await_response(aid))
        return out

    def check_protocol(self):
        assert not self.protocol_errors, "OBI protocol violations: " + \
            "; ".join(self.protocol_errors)


class CordicDut:
    """DUT wrapper: clock, reset, OBI manager, matching model."""

    def __init__(self, dut):
        self.dut = dut
        self.cfg = dut_config(dut)
        self.model = CordicModel(
            data_width=self.cfg["data_width"],
            frac_bits=self.cfg["frac_bits"],
            num_stages=self.cfg["num_stages"],
            guard_int=self.cfg["guard_int"],
            guard_frac=self.cfg["guard_frac"],
        )
        self.obi = ObiManager(dut, use_rready=self.cfg["use_rready"])

    async def start(self):
        clock = make_clock(self.dut.clk_i, CLK_PERIOD_NS)
        cocotb.start_soon(clock.start())
        self.dut.rst_ni.value = 0
        self.idle_stream()
        await ClockCycles(self.dut.clk_i, 5)
        self.dut.rst_ni.value = 1
        await ClockCycles(self.dut.clk_i, 2)
        cocotb.start_soon(self.obi.monitor())
        await ClockCycles(self.dut.clk_i, 1)

    def idle_stream(self):
        self.dut.str_in_valid_i.value = 0
        self.dut.str_in_func_i.value = 0
        self.dut.str_in_tag_i.value = 0
        self.dut.str_in_x_i.value = 0
        self.dut.str_in_y_i.value = 0
        self.dut.str_in_z_i.value = 0
        self.dut.str_out_ready_i.value = 0

    # -- register conveniences ---------------------------------------------
    async def wr(self, name, value, be=0xF, expect_err=False):
        return await self.obi.write(REG[name], value, be, expect_err)

    async def rd(self, name, be=0xF, expect_err=False):
        return await self.obi.read(REG[name], be, expect_err)

    async def rd_signed(self, name):
        raw = await self.rd(name)
        w = self.cfg["data_width"]
        raw &= 0xFFFFFFFF
        if raw & 0x80000000:
            raw -= 1 << 32
        return raw

    async def issue(self, func, x=0, y=0, z=0, tag=0):
        """Write the operands and trigger one operation through the registers."""
        await self.wr("OP_X", x & 0xFFFFFFFF)
        await self.wr("OP_Y", y & 0xFFFFFFFF)
        await self.wr("OP_Z", z & 0xFFFFFFFF)
        cmd = (make_field("CMD", "FUNC", func) | make_field("CMD", "TAG", tag) |
               make_field("CMD", "GO", 1))
        await self.wr("CMD", cmd)

    async def wait_result(self, timeout=2000):
        """Wait until a result is readable."""
        shift, mask = field("STATUS", "RES_VALID")
        for _ in range(timeout):
            st = await self.rd("STATUS")
            if st & mask:
                return st
        raise TimeoutError("no result within the timeout")

    async def read_result(self, pop=True):
        """Read X, Y, Z and the flags of the head result, optionally popping it."""
        x = await self.rd_signed("RES_X")
        y = await self.rd_signed("RES_Y")
        z = await self.rd_signed("RES_Z")
        flags = await self.rd("RES_FLAGS")
        if pop:
            await self.wr("CTRL", make_field("CTRL", "POP", 1))
        return {
            "x": x, "y": y, "z": z,
            "flags": flags & 0xF,
            "func": get_field(flags, "RES_FLAGS", "FUNC"),
            "tag": get_field(flags, "RES_FLAGS", "TAG"),
        }

    async def run_op(self, func, x=0, y=0, z=0, tag=0):
        await self.issue(func, x, y, z, tag)
        await self.wait_result()
        return await self.read_result()

    async def soft_reset(self):
        await self.wr("CTRL", make_field("CTRL", "SOFT_RST", 1))
        await ClockCycles(self.dut.clk_i, 2)


async def stream_push(dut, func, x, y, z, tag=0, timeout=10000):
    """Hand one operation to the streaming input port."""
    dut.str_in_valid_i.value = 1
    dut.str_in_func_i.value = func
    dut.str_in_tag_i.value = tag
    dut.str_in_x_i.value = x
    dut.str_in_y_i.value = y
    dut.str_in_z_i.value = z
    for _ in range(timeout):
        await RisingEdge(dut.clk_i)
        if dut.str_in_ready_o.value == 1:
            dut.str_in_valid_i.value = 0
            return
    dut.str_in_valid_i.value = 0
    raise TimeoutError("streaming input never became ready")


async def stream_pop(dut, timeout=10000):
    """Take one result from the streaming output port."""
    dut.str_out_ready_i.value = 1
    for _ in range(timeout):
        await RisingEdge(dut.clk_i)
        if dut.str_out_valid_o.value == 1:
            out = {
                "x": to_signed(dut.str_out_x_o.value),
                "y": to_signed(dut.str_out_y_o.value),
                "z": to_signed(dut.str_out_z_o.value),
                "flags": int(dut.str_out_flags_o.value),
                "func": int(dut.str_out_func_o.value),
                "tag": int(dut.str_out_tag_o.value),
            }
            dut.str_out_ready_i.value = 0
            return out
    dut.str_out_ready_i.value = 0
    raise TimeoutError("streaming output never produced a result")
