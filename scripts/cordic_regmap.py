# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""The OBI register map, defined once.

scripts/gen_regmap.py turns this into the RTL offsets (rtl/cordic_regmap.svh),
the driver header (sw/include/cordic_regmap.h), the README table and the
register-map figure. Nothing else hard-codes an offset or a bit position, so the
hardware, the driver, the tests and the documentation cannot disagree.

Access codes:
  RO   read-only, writes take an OBI error response
  RW   read-write
  W1C  read, write 1 to clear a bit
  W1S  write 1 to trigger; the bit self-clears and always reads back 0
"""

from collections import namedtuple

Field = namedtuple("Field", "name hi lo access desc")
Reg = namedtuple("Reg", "name offset access desc fields")

WINDOW_BYTES = 0x1000       # Croc wants subordinate windows on 4 KB multiples
MAPPED_BYTES = 0x64         # first unmapped offset inside the window

MAGIC = 0x434F5244          # "CORD"
VERSION = (1, 0, 0)         # major, minor, patch


def f(name, hi, lo, access, desc):
    return Field(name, hi, lo, access, desc)


REGS = [
    Reg("ID", 0x00, "RO", "Identification magic, reads 0x434F5244 (\"CORD\")", [
        f("MAGIC", 31, 0, "RO", "Constant 0x434F5244"),
    ]),
    Reg("VERSION", 0x04, "RO", "Semantic version of the register interface", [
        f("MAJOR", 31, 24, "RO", "Major version"),
        f("MINOR", 23, 16, "RO", "Minor version"),
        f("PATCH", 15, 8, "RO", "Patch version"),
    ]),
    Reg("CFG0", 0x08, "RO", "Elaborated fixed-point format", [
        f("DATA_WIDTH", 7, 0, "RO", "Fixed-point word width in bits"),
        f("FRAC_BITS", 15, 8, "RO", "Fractional bits of the fixed-point word"),
        f("NUM_STAGES", 23, 16, "RO", "CORDIC micro-rotations per operation"),
        f("GUARD_INT", 27, 24, "RO", "Integer guard bits of the internal datapath"),
        f("GUARD_FRAC", 31, 28, "RO", "Fractional guard bits of the internal datapath"),
    ]),
    Reg("CFG1", 0x0C, "RO", "Elaborated microarchitecture and timing", [
        f("VARIANT", 0, 0, "RO", "0 = fully pipelined, 1 = iterative"),
        f("USE_RREADY", 1, 1, "RO", "1 if the OBI R channel implements rready"),
        f("IN_DEPTH", 7, 4, "RO", "Input FIFO depth in entries"),
        f("OUT_DEPTH", 11, 8, "RO", "Output FIFO depth in entries"),
        f("LATENCY", 19, 12, "RO", "Issue-to-result latency in clock cycles"),
        f("INTERVAL", 27, 20, "RO", "Minimum cycles between accepted operations"),
    ]),
    Reg("CTRL", 0x10, "RW", "Control. Bits 0 to 4 are write-1-to-trigger and read 0", [
        f("SOFT_RST", 0, 0, "W1S", "Abort every operation in flight, flush both FIFOs, clear the sticky errors and the IRQ state. Operand, CMD and SCRATCH registers are left alone"),
        f("POP", 1, 1, "W1S", "Discard the result at the head of the output FIFO"),
        f("FLUSH_IN", 2, 2, "W1S", "Drop every queued but unstarted operation"),
        f("FLUSH_OUT", 3, 3, "W1S", "Drop every completed but unread result"),
        f("CLR_ERR", 4, 4, "W1S", "Clear the sticky STATUS.ERR_* bits"),
        f("IRQ_EN_DONE", 8, 8, "RW", "Route IRQ.DONE to the interrupt output"),
        f("IRQ_EN_ERR", 9, 9, "RW", "Route IRQ.ERR to the interrupt output"),
    ]),
    Reg("STATUS", 0x14, "RO", "Live and sticky status", [
        f("BUSY", 0, 0, "RO", "Operations are queued or in flight"),
        f("RES_VALID", 1, 1, "RO", "At least one result is readable"),
        f("IN_FULL", 2, 2, "RO", "Input FIFO cannot accept another operation"),
        f("IN_EMPTY", 3, 3, "RO", "Input FIFO holds no operation"),
        f("OUT_FULL", 4, 4, "RO", "Output FIFO cannot accept another result"),
        f("OUT_EMPTY", 5, 5, "RO", "Output FIFO holds no result"),
        f("IN_COUNT", 11, 8, "RO", "Operations queued in the input FIFO"),
        f("OUT_COUNT", 15, 12, "RO", "Results waiting in the output FIFO"),
        f("ERR_DOMAIN", 16, 16, "RO", "Sticky: an operand was outside the convergence domain"),
        f("ERR_OVERFLOW", 17, 17, "RO", "Sticky: an issue was dropped, input FIFO was full"),
        f("ERR_UNDERFLOW", 18, 18, "RO", "Sticky: a result was read or popped while empty"),
        f("ERR_ACCESS", 19, 19, "RO", "Sticky: an unmapped, unaligned or illegal access occurred"),
    ]),
    Reg("IRQ", 0x18, "W1C", "Interrupt status, write 1 to clear", [
        f("DONE", 0, 0, "W1C", "A result was pushed into the output FIFO"),
        f("ERR", 1, 1, "W1C", "One of the sticky STATUS.ERR_* bits was set"),
    ]),
    Reg("OP_X", 0x20, "RW", "Operand X in the working fixed-point format", [
        f("VALUE", 31, 0, "RW", "Signed fixed-point operand X"),
    ]),
    Reg("OP_Y", 0x24, "RW", "Operand Y in the working fixed-point format", [
        f("VALUE", 31, 0, "RW", "Signed fixed-point operand Y"),
    ]),
    Reg("OP_Z", 0x28, "RW", "Operand Z in the working fixed-point format", [
        f("VALUE", 31, 0, "RW", "Signed fixed-point operand Z"),
    ]),
    Reg("CMD", 0x2C, "RW", "Function select and issue trigger", [
        f("FUNC", 4, 0, "RW", "Function code, see the function table"),
        f("TAG", 15, 8, "RW", "Free-form tag returned in RES_FLAGS.TAG"),
        f("GO", 31, 31, "W1S", "Queue an operation from OP_X, OP_Y, OP_Z and FUNC"),
    ]),
    Reg("RES_X", 0x30, "RO", "Result X at the head of the output FIFO", [
        f("VALUE", 31, 0, "RO", "Signed fixed-point result X"),
    ]),
    Reg("RES_Y", 0x34, "RO", "Result Y at the head of the output FIFO", [
        f("VALUE", 31, 0, "RO", "Signed fixed-point result Y"),
    ]),
    Reg("RES_Z", 0x38, "RO", "Result Z at the head of the output FIFO", [
        f("VALUE", 31, 0, "RO", "Signed fixed-point result Z"),
    ]),
    Reg("RES_FLAGS", 0x3C, "RO", "Per-result flags at the head of the output FIFO", [
        f("DOMAIN_ERR", 0, 0, "RO", "Operand outside the convergence domain, X/Y/Z forced to 0"),
        f("SAT_X", 1, 1, "RO", "Result X saturated to the format limit"),
        f("SAT_Y", 2, 2, "RO", "Result Y saturated to the format limit"),
        f("SAT_Z", 3, 3, "RO", "Result Z saturated to the format limit"),
        f("FUNC", 12, 8, "RO", "Function code of this result"),
        f("TAG", 23, 16, "RO", "Tag supplied in CMD.TAG"),
    ]),
    Reg("K_CIRC", 0x40, "RO", "Circular CORDIC gain K, working format", [
        f("VALUE", 31, 0, "RO", "prod sqrt(1 + 2**-2s) over the elaborated stages"),
    ]),
    Reg("IK_CIRC", 0x44, "RO", "Reciprocal circular gain 1/K, working format", [
        f("VALUE", 31, 0, "RO", "1 / K_CIRC"),
    ]),
    Reg("K_HYP", 0x48, "RO", "Hyperbolic CORDIC gain Kh, working format", [
        f("VALUE", 31, 0, "RO", "prod sqrt(1 - 2**-2s) over the elaborated stages"),
    ]),
    Reg("IK_HYP", 0x4C, "RO", "Reciprocal hyperbolic gain 1/Kh, working format", [
        f("VALUE", 31, 0, "RO", "1 / K_HYP"),
    ]),
    Reg("LIM_CIRC", 0x50, "RO", "Circular convergence radius, working format", [
        f("VALUE", 31, 0, "RO", "sum atan(2**-s) in radians"),
    ]),
    Reg("LIM_HYP", 0x54, "RO", "Hyperbolic convergence radius, working format", [
        f("VALUE", 31, 0, "RO", "sum atanh(2**-s)"),
    ]),
    Reg("LIM_LIN", 0x58, "RO", "Linear convergence radius, working format", [
        f("VALUE", 31, 0, "RO", "sum 2**-s"),
    ]),
    Reg("TANH_LIM_HYP", 0x5C, "RO", "Largest |Y/X| the hyperbolic vectoring mode resolves", [
        f("VALUE", 31, 0, "RO", "tanh(LIM_HYP)"),
    ]),
    Reg("SCRATCH", 0x60, "RW", "Read-write scratch word, no hardware effect", [
        f("VALUE", 31, 0, "RW", "Free for software; also the byte-enable test target"),
    ]),
]

# Function codes written to CMD.FUNC.
#   name, code, coord, mode, operands used, result of interest, domain
Func = namedtuple("Func", "name code coord mode operands result domain gain")

FUNCS = [
    Func("SIN_COS", 0, "circular", "rotation", "Z = angle in radians",
         "X = cos(Z), Y = sin(Z)", "whole representable range of Z",
         "compensated, x0 preloaded with 1/K"),
    Func("ROTATE", 1, "circular", "rotation", "X, Y = vector, Z = angle",
         "X, Y = K * R(Z) * (X,Y)", "whole representable range of Z",
         "exposed as K_CIRC"),
    Func("ATAN2", 2, "circular", "vectoring", "X, Y = vector",
         "Z = atan2(Y,X), X = K * hypot(X,Y)", "all four quadrants, no restriction",
         "Z exact, X scaled by K_CIRC"),
    Func("SINH_COSH", 3, "hyperbolic", "rotation", "Z = argument",
         "X = cosh(Z), Y = sinh(Z)", "|Z| <= LIM_HYP",
         "compensated, x0 preloaded with 1/Kh"),
    Func("HROTATE", 4, "hyperbolic", "rotation", "X, Y = vector, Z = argument",
         "X, Y = Kh * Rh(Z) * (X,Y)", "|Z| <= LIM_HYP",
         "exposed as K_HYP"),
    Func("ATANH", 5, "hyperbolic", "vectoring", "X, Y = vector",
         "Z = atanh(Y/X), X = Kh * sqrt(X^2 - Y^2)",
         "X != 0 and |Y/X| <= TANH_LIM_HYP", "Z exact, X scaled by K_HYP"),
    Func("EXP", 6, "hyperbolic", "rotation", "Z = exponent",
         "X = Y = exp(Z)", "|Z| <= LIM_HYP",
         "compensated, x0 = y0 = 1/Kh"),
    Func("LN", 7, "hyperbolic", "vectoring", "X = argument",
         "Z = ln(X)", "X > 0 and (X-1)/(X+1) within TANH_LIM_HYP",
         "exact, no gain"),
    Func("MUL", 8, "linear", "rotation", "X, Z = factors",
         "Y = X * Z", "|Z| <= LIM_LIN", "none, gain is 1"),
    Func("DIV", 9, "linear", "vectoring", "Y = numerator, X = denominator",
         "Z = Y / X", "X != 0 and |Y/X| <= LIM_LIN", "none, gain is 1"),
]

NUM_FUNCS = 10

# Data returned for an unmapped, unaligned or illegal access, alongside r.err.
BAD_ACCESS_DATA = 0xBADACCE5


def reg_by_name(name):
    for r in REGS:
        if r.name == name:
            return r
    raise KeyError(name)


def check():
    """Sanity-check the map: offsets aligned, ordered, in range, fields disjoint."""
    seen = set()
    prev = -4
    for r in REGS:
        assert r.offset % 4 == 0, f"{r.name} offset not word aligned"
        assert r.offset > prev, f"{r.name} offset out of order"
        assert r.offset < MAPPED_BYTES, f"{r.name} outside the mapped range"
        assert r.offset not in seen, f"{r.name} duplicate offset"
        seen.add(r.offset)
        prev = r.offset
        used = 0
        for fl in r.fields:
            assert 0 <= fl.lo <= fl.hi <= 31, f"{r.name}.{fl.name} bad range"
            mask = ((1 << (fl.hi - fl.lo + 1)) - 1) << fl.lo
            assert not (used & mask), f"{r.name}.{fl.name} overlaps another field"
            used |= mask
    assert MAPPED_BYTES % 4 == 0
    assert WINDOW_BYTES % 0x1000 == 0
    codes = [fn.code for fn in FUNCS]
    assert codes == sorted(codes) and len(set(codes)) == len(codes)
    assert len(FUNCS) == NUM_FUNCS
    return True


check()
