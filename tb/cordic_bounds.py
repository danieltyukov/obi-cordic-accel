# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Documented error bounds, derived rather than guessed.

For a datapath with N micro-rotations, F fractional bits in the interface format
and G fractional guard bits internally, three things limit accuracy:

  a_last = atan(2**-(N-1))   the rotation the sequence can no longer resolve
  eps_int = 2**-(F+G)        one internal LSB, the truncation step of each shift
  eps_out = 2**-F            one interface LSB, and the final rounding step

A rotation-mode output is a coordinate of a vector of magnitude R, so an angular
slip of a_last and a per-stage truncation walk of at most N*eps_int both scale
with R:

  |error| <= R * (a_last + N * eps_int) + eps_out                            (1)

A vectoring-mode angle is different: the residual sits in y, and turning a
y-residual into an angle divides by the magnitude, so accuracy depends on how
well conditioned the argument is. For circular vectoring,

  |error| <= a_last + N * eps_int / hypot(x, y)                              (2)

which is why atan2 of a vector a few LSBs long carries no usable angle at all,
and why the measured max error in LSBs looks enormous for those inputs while the
hardware is behaving exactly as it should. The hyperbolic and linear vectoring
angles follow the same shape with their own conditioning factor.

SAFETY is applied on top. Every bound in this file was checked against the
bit-accurate model over 40k arguments per function, where the worst observed
error came to 0.52 of the bound at SAFETY = 4, so the margin is real and measured
rather than assumed. tests assert against these bounds directly.

The reference value is always computed from the quantised operands, never the
requested reals. The hardware never sees anything else, and for atan2 in the
third quadrant the difference matters: a y of -1e-10 quantises to zero, which
moves the true answer from -pi to +pi.
"""

import math

SAFETY = 4.0

# Well-conditioned region for the fixed-LSB statistics: the input magnitude must
# reach at least this value. Bound (2) makes the vectoring angle error scale as
# 1/|v|, so a fixed LSB figure only means something once a magnitude is stated.
# Measured over 60k model arguments per function, the max vectoring angle error is:
#
#   |v| >=       ATAN2.z   ATANH.z    LN.z    DIV.z
#   1.0             4.47      8.62   17.06     4.39   LSB
#   0.25            4.98     10.80   17.54     5.76
#   0.0625          8.37     19.64   19.14    10.83
#   0.0039         94.17    192.64   19.14   138.34
#   0.00024      1214.97   3860.80   19.14  2009.69
#
# 1/16 is the chosen line: it keeps two thirds of the representable range and the
# fixed bounds below stay comfortably above the measured numbers there. LN barely
# moves because its operand transform puts x0 = (w+1)/2, never below one half.
WELL_CONDITIONED_MAG = 2.0 ** -4


class BoundCtx:
    """Per-configuration bound constants."""

    def __init__(self, model):
        n = model.num_stages
        self.n = n
        self.eps_int = 1.0 / (1 << model.int_frac)
        self.eps_out = 1.0 / (1 << model.frac_bits)
        self.a_last = math.atan(2.0 ** -(n - 1))
        self.k_circ = model.int_to_real(model.k_circ)
        self.k_hyp = model.int_to_real(model.k_hyp)
        self.walk = self.a_last + n * self.eps_int

    def rotation(self, magnitude):
        """Bound (1) for an output of the given magnitude."""
        return magnitude * self.walk + self.eps_out

    def scale(self, value):
        """Guard against a zero denominator without inventing slack."""
        return max(abs(value), 1e-300)


def bound(ctx, func, key, x, y, z):
    """Absolute error bound for one output of one operation, or None if unbounded.

    x, y and z are the quantised operands as reals.
    """
    n, eps_int, eps_out = ctx.n, ctx.eps_int, ctx.eps_out
    b = None

    if func == "SIN_COS":
        # The initial vector is 1/K, so the result rides the unit circle.
        b = ctx.rotation(1.0)
    elif func == "ROTATE" or (func == "ATAN2" and key == "x"):
        b = ctx.rotation(ctx.k_circ * math.hypot(x, y))
    elif func == "ATAN2" and key == "z":
        b = ctx.a_last + n * eps_int / ctx.scale(math.hypot(x, y))
    elif func in ("SINH_COSH", "EXP"):
        # cosh(z) + |sinh(z)| is exp(|z|).
        b = ctx.rotation(math.exp(abs(z)))
    elif func == "HROTATE":
        b = ctx.rotation(ctx.k_hyp * (abs(x) + abs(y)) * math.exp(abs(z)))
    elif func == "ATANH" and key == "x":
        b = ctx.rotation(ctx.k_hyp * math.sqrt(max(x * x - y * y, 0.0)))
    elif func == "ATANH" and key == "z":
        # d(atanh)/dy = x / (x^2 - y^2), which blows up at the domain edge.
        b = ctx.a_last + n * eps_int * abs(x) / ctx.scale(x * x - y * y) + eps_out
    elif func == "LN":
        # ln(w) = 2*atanh((w-1)/(w+1)), evaluated with x0 = (w+1)/2 and
        # y0 = (w-1)/2, where x0^2 - y0^2 is exactly w.
        b = 2.0 * (ctx.a_last + n * eps_int * (x + 1.0) / (2.0 * ctx.scale(x))) + eps_out
    elif func == "MUL":
        # Linear rotation leaves x alone, so only the y accumulation truncates.
        b = abs(x) * n * eps_int + eps_out
    elif func == "DIV":
        b = n * eps_int / ctx.scale(x) + eps_out

    return None if b is None else b * SAFETY


def well_conditioned(model, func, x_fx, y_fx, z_fx):
    """True when the fixed-LSB statistics should include this argument.

    Only vectoring arguments are excluded, and only when the input magnitude is too
    small for an angle to exist in the format. The derived bound still applies to
    every argument, including the excluded ones.
    """
    limit = WELL_CONDITIONED_MAG
    if func == "ATAN2":
        return math.hypot(model.to_real(x_fx), model.to_real(y_fx)) >= limit
    if func in ("ATANH", "LN", "DIV"):
        return abs(model.to_real(x_fx)) >= limit
    return True


# Fixed bounds in interface LSBs, applied to the well-conditioned subset only.
# These are the headline accuracy numbers; the measured values sit well inside.
LSB_BOUNDS = {
    ("SIN_COS", "x"): 12.0,
    ("SIN_COS", "y"): 12.0,
    ("ROTATE", "x"): 48.0,
    ("ROTATE", "y"): 48.0,
    ("ATAN2", "z"): 24.0,
    ("ATAN2", "x"): 24.0,
    ("SINH_COSH", "x"): 24.0,
    ("SINH_COSH", "y"): 24.0,
    ("EXP", "x"): 40.0,
    ("EXP", "y"): 40.0,
    ("HROTATE", "x"): 64.0,
    ("HROTATE", "y"): 64.0,
    ("ATANH", "z"): 64.0,
    ("ATANH", "x"): 48.0,
    ("LN", "z"): 48.0,
    ("MUL", "y"): 24.0,
    ("DIV", "z"): 32.0,
}
