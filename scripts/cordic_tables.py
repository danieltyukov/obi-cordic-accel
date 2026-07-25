# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Shared CORDIC constant tables.

This module is the single source of truth for every constant the design needs:
the per-stage micro-rotation angles, the coordinate-system gains, and the
convergence radii. The RTL ROM (rtl/cordic_rom.svh) and the Python golden model
(tb/cordic_model.py) are both derived from here, so they cannot drift apart.

All ROM values are emitted as signed 64-bit integers in Q3.61 format, i.e.
value_int = round(value_real * 2**61). 61 fractional bits is the largest that
still lets pi fit in a signed 64-bit word (pi * 2**61 = 7.24e18 < 2**63).
"""

from fractions import Fraction
from mpmath import mp, mpf, atan, atanh, tanh, sqrt, pi as mp_pi

# Plenty of guard digits: every constant is rounded once, at the very end.
mp.dps = 80

ROM_FRAC = 61          # fractional bits of every ROM entry
ROM_MAX_IDX = 56       # shift amounts 0 .. ROM_MAX_IDX-1 are tabulated
ROM_MAX_STG = 48       # stage counts 0 .. ROM_MAX_STG are tabulated

# Coordinate systems. The value is the `m` of the generalised CORDIC recurrence
# x' = x - m*d*(y >> s);  y' = y + d*(x >> s);  z' = z - d*a_s
COORD_CIRC = 0         # m = +1
COORD_LIN = 1          # m =  0
COORD_HYP = 2          # m = -1

# Micro-rotation modes
MODE_ROT = 0           # drive z to zero
MODE_VEC = 1           # drive y to zero


def q(value, frac=ROM_FRAC):
    """Round a real value to a fixed-point integer with `frac` fraction bits."""
    scaled = mpf(value) * mpf(2) ** frac
    return int(mp.floor(scaled + mpf("0.5")))


def hyp_shift_sequence(n_stages):
    """Shift amounts for `n_stages` hyperbolic stages.

    The hyperbolic recurrence uses shifts 1, 2, 3, ... but the raw sequence does
    not satisfy the CORDIC convergence condition: atanh(2**-4) alone is larger
    than the sum of every remaining term. The classical fix (Walther 1971) is to
    repeat the indices 4, 13, 40, 121, ..., i.e. i_{k+1} = 3*i_k + 1.
    """
    seq = []
    shift = 1
    next_repeat = 4
    while len(seq) < n_stages:
        seq.append(shift)
        if shift == next_repeat:
            seq.append(shift)
            next_repeat = 3 * next_repeat + 1
        shift += 1
    return seq[:n_stages]


def stage_shifts(coord, n_stages):
    """Per-stage shift amount for a coordinate system."""
    if coord == COORD_CIRC:
        return list(range(n_stages))
    if coord == COORD_LIN:
        return list(range(n_stages))
    if coord == COORD_HYP:
        return hyp_shift_sequence(n_stages)
    raise ValueError(coord)


def stage_angles(coord, n_stages):
    """Per-stage micro-rotation angle as an exact mpmath value."""
    shifts = stage_shifts(coord, n_stages)
    if coord == COORD_CIRC:
        return [atan(mpf(2) ** (-s)) for s in shifts]
    if coord == COORD_LIN:
        return [mpf(2) ** (-s) for s in shifts]
    if coord == COORD_HYP:
        return [atanh(mpf(2) ** (-s)) for s in shifts]
    raise ValueError(coord)


def gain(coord, n_stages):
    """Product of the per-stage magnitude scale factors (the CORDIC gain K)."""
    shifts = stage_shifts(coord, n_stages)
    if coord == COORD_LIN:
        return mpf(1)
    sign = 1 if coord == COORD_CIRC else -1
    g = mpf(1)
    for s in shifts:
        g *= sqrt(1 + sign * mpf(2) ** (-2 * s))
    return g


def convergence_radius(coord, n_stages):
    """Sum of the per-stage angles: the reachable |z| for rotation mode."""
    return sum(stage_angles(coord, n_stages), mpf(0))


def convergence_ok(coord, n_stages, rel_tol=mpf("1e-6")):
    """Check the CORDIC convergence condition for a stage sequence.

    A sequence a_0 .. a_{N-1} can reach every angle in [-sum, +sum] only if no
    single step is larger than everything that follows it plus one extra copy of
    the final step:  a_k <= sum_{j>k} a_j + a_{N-1}.

    A relative tolerance is applied because the hyperbolic sequence violates the
    bare inequality in its last steps by a relative O(2**-2s / 3): atanh is
    convex, so atanh(2x) is a hair larger than 2*atanh(x). The worst case in the
    tabulated range is the shift-13 step, short by a relative 4.3e-9, which is
    5.2e-13 in absolute terms or 0.0003 LSB of Q3.29. `guarded_radius` below
    holds a whole final micro-rotation back, so the accepted domain sits well
    inside the reachable one.
    """
    a = stage_angles(coord, n_stages)
    if not a:
        return True
    for k in range(len(a)):
        tail = sum(a[k + 1:], mpf(0)) + a[-1]
        if a[k] > tail * (1 + rel_tol):
            return False
    return True


def guarded_radius(coord, n_stages):
    """Convergence radius with one final micro-rotation held back as margin."""
    a = stage_angles(coord, n_stages)
    if not a:
        return mpf(0)
    return sum(a, mpf(0)) - a[-1]


def good_stage_counts(coord, lo=4, hi=ROM_MAX_STG):
    """Stage counts whose sequence satisfies the convergence condition."""
    return [n for n in range(lo, hi + 1) if convergence_ok(coord, n)]


def rom_tables():
    """Every ROM table, as dicts of index -> signed integer in Q3.61."""
    atan_rom = [q(atan(mpf(2) ** (-i))) for i in range(ROM_MAX_IDX)]
    # atanh(2**0) is infinite; shift 0 is never used by the hyperbolic sequence.
    atanh_rom = [0] + [q(atanh(mpf(2) ** (-i))) for i in range(1, ROM_MAX_IDX)]

    k_circ, ik_circ, k_hyp, ik_hyp = [], [], [], []
    lim_circ, lim_hyp, lim_lin, tanh_lim_hyp = [], [], [], []
    for n in range(ROM_MAX_STG + 1):
        gc = gain(COORD_CIRC, n)
        gh = gain(COORD_HYP, n)
        k_circ.append(q(gc))
        ik_circ.append(q(1 / gc))
        k_hyp.append(q(gh))
        ik_hyp.append(q(1 / gh))
        lim_circ.append(q(convergence_radius(COORD_CIRC, n)))
        lh = convergence_radius(COORD_HYP, n)
        lim_hyp.append(q(lh))
        tanh_lim_hyp.append(q(tanh(lh)))
        lim_lin.append(q(convergence_radius(COORD_LIN, n)))

    hyp_shifts = hyp_shift_sequence(ROM_MAX_STG)

    return {
        "AtanRom": atan_rom,
        "AtanhRom": atanh_rom,
        "KCircRom": k_circ,
        "InvKCircRom": ik_circ,
        "KHypRom": k_hyp,
        "InvKHypRom": ik_hyp,
        "LimCircRom": lim_circ,
        "LimHypRom": lim_hyp,
        "LimLinRom": lim_lin,
        "TanhLimHypRom": tanh_lim_hyp,
        "HypShiftRom": hyp_shifts,
        "PiRom": q(mp_pi),
        "HalfPiRom": q(mp_pi / 2),
    }


def as_fraction(rom_int, frac=ROM_FRAC):
    """Exact rational value of a ROM entry."""
    return Fraction(rom_int, 2 ** frac)


def rom_to_fx(rom_int, frac_bits, rom_frac=ROM_FRAC):
    """Re-round a Q3.61 ROM entry to `frac_bits` fraction bits.

    Mirrors the RTL `cordic_rom_to_fx` function bit for bit: add half an LSB of
    the target format, then arithmetic-shift right.
    """
    shift = rom_frac - frac_bits
    if shift < 0:
        raise ValueError("frac_bits exceeds ROM precision")
    if shift == 0:
        return rom_int
    return (rom_int + (1 << (shift - 1))) >> shift
