# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Bit-accurate model of the CORDIC datapath, plus a double-precision reference.

Two independent things live here:

`CordicModel` reproduces the RTL exactly, integer for integer. It is what the
equivalence and domain tests compare against, and what the offline studies (error
versus stage count, error versus word width) are swept over, since sweeping RTL
elaborations would take hours.

`reference()` computes the same functions in double precision from `math`. That is
the yardstick for the accuracy numbers: the RTL is measured against it, never
against the model.

Python's `>>` on a negative int floors, which is what `>>>` does on a signed
SystemVerilog value, so the shift semantics line up without any special casing.
"""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import cordic_tables as ct  # noqa: E402
import cordic_regmap as rmap  # noqa: E402

COORD_CIRC = ct.COORD_CIRC
COORD_LIN = ct.COORD_LIN
COORD_HYP = ct.COORD_HYP
MODE_ROT = ct.MODE_ROT
MODE_VEC = ct.MODE_VEC

# Function codes, taken straight from the register-map definition.
FUNC = {fn.name: fn.code for fn in rmap.FUNCS}
FUNC_NAME = {fn.code: fn.name for fn in rmap.FUNCS}

PI_NONE, PI_ADD, PI_SUB = 0b00, 0b10, 0b11

FLAG_DOM = 1 << 0
FLAG_SAT_X = 1 << 1
FLAG_SAT_Y = 1 << 2
FLAG_SAT_Z = 1 << 3


class Result:
    """One completed operation, as the hardware would report it."""

    __slots__ = ("x", "y", "z", "flags", "func", "tag", "resid_y", "resid_x")

    def __init__(self, x, y, z, flags, func, tag, resid_x=0, resid_y=0):
        self.x, self.y, self.z = x, y, z
        self.flags, self.func, self.tag = flags, func, tag
        self.resid_x, self.resid_y = resid_x, resid_y

    @property
    def domain_error(self):
        return bool(self.flags & FLAG_DOM)

    def __repr__(self):
        return (f"Result(x={self.x}, y={self.y}, z={self.z}, "
                f"flags=0x{self.flags:x}, func={FUNC_NAME.get(self.func, self.func)}, "
                f"tag={self.tag})")


class CordicModel:
    """Bit-accurate model of cordic_pre + core + cordic_post."""

    def __init__(self, data_width=32, frac_bits=29, num_stages=28,
                 guard_int=2, guard_frac=4,
                 resid_shift_margin=1, resid_floor_mul=4):
        assert data_width - frac_bits >= 3, "need sign plus two integer bits for pi"
        assert guard_frac >= 1 and guard_int >= 1
        self.data_width = data_width
        self.frac_bits = frac_bits
        self.num_stages = num_stages
        self.guard_int = guard_int
        self.guard_frac = guard_frac
        self.resid_shift_margin = resid_shift_margin
        self.resid_floor_mul = resid_floor_mul

        self.int_frac = frac_bits + guard_frac
        self.int_width = data_width + guard_int + guard_frac

        rom = ct.rom_tables()
        n = num_stages
        to = self._rom_to_int
        self.pi = to(rom["PiRom"])
        self.half_pi = to(rom["HalfPiRom"])
        self.inv_k_circ = to(rom["InvKCircRom"][n])
        self.inv_k_hyp = to(rom["InvKHypRom"][n])
        self.k_circ = to(rom["KCircRom"][n])
        self.k_hyp = to(rom["KHypRom"][n])
        self.lim_circ = to(rom["LimCircRom"][n])
        self.lim_hyp = to(rom["LimHypRom"][n])
        self.lim_lin = to(rom["LimLinRom"][n])
        self.tanh_lim_hyp = to(rom["TanhLimHypRom"][n])
        self.half = 1 << (self.int_frac - 1)

        self.shifts = {c: ct.stage_shifts(c, n) for c in (COORD_CIRC, COORD_LIN, COORD_HYP)}
        self.angles = {
            COORD_CIRC: [ct.rom_to_fx(rom["AtanRom"][s], self.int_frac)
                         for s in self.shifts[COORD_CIRC]],
            COORD_HYP: [ct.rom_to_fx(rom["AtanhRom"][s], self.int_frac)
                        for s in self.shifts[COORD_HYP]],
            COORD_LIN: [(1 << (self.int_frac - s)) if s <= self.int_frac else 0
                        for s in self.shifts[COORD_LIN]],
        }
        self.resid_floor = resid_floor_mul * num_stages

    # -- fixed-point helpers ------------------------------------------------
    def _rom_to_int(self, v):
        return ct.rom_to_fx(v, self.int_frac)

    def wrap(self, v):
        """Two's complement wrap to the internal datapath width."""
        m = 1 << self.int_width
        v &= m - 1
        return v - m if v >= (m >> 1) else v

    @property
    def fx_max(self):
        return (1 << (self.data_width - 1)) - 1

    @property
    def fx_min(self):
        return -(1 << (self.data_width - 1))

    def to_fx(self, real):
        """Real value to an interface word, saturating (test-bench convenience)."""
        v = int(math.floor(real * (1 << self.frac_bits) + 0.5))
        return max(self.fx_min, min(self.fx_max, v))

    def to_real(self, fx):
        return fx / float(1 << self.frac_bits)

    def int_to_real(self, v):
        return v / float(1 << self.int_frac)

    def widen(self, fx):
        return fx << self.guard_frac

    # -- datapath -----------------------------------------------------------
    def micro_rotation(self, coord, mode, x, y, z, shift, angle):
        positive = (y < 0) if mode == MODE_VEC else (z >= 0)
        x_sh = x >> shift
        y_sh = y >> shift
        if coord == COORD_CIRC:
            xn = x - y_sh if positive else x + y_sh
        elif coord == COORD_HYP:
            xn = x + y_sh if positive else x - y_sh
        else:
            xn = x
        yn = y + x_sh if positive else y - x_sh
        zn = z - angle if positive else z + angle
        return self.wrap(xn), self.wrap(yn), self.wrap(zn)

    def trajectory(self, coord, mode, x0, y0, z0):
        """Every intermediate vector, index 0 being the initial one."""
        pts = [(x0, y0, z0)]
        x, y, z = x0, y0, z0
        for s in range(self.num_stages):
            x, y, z = self.micro_rotation(coord, mode, x, y, z,
                                          self.shifts[coord][s], self.angles[coord][s])
            pts.append((x, y, z))
        return pts

    # -- pre ----------------------------------------------------------------
    def pre(self, func, x_fx, y_fx, z_fx):
        """Returns (coord, mode, x0, y0, z0, dom, chk, pi_ctl, dbl, zero)."""
        xw = self.wrap(self.widen(x_fx))
        yw = self.wrap(self.widen(y_fx))
        zw = self.wrap(self.widen(z_fx))

        coord, mode = COORD_CIRC, MODE_ROT
        x0, y0, z0 = xw, yw, zw
        dom = chk = dbl = zero_res = False
        pi_ctl = PI_NONE

        if func == FUNC["SIN_COS"]:
            x0, y0 = self.inv_k_circ, 0
        elif func == FUNC["ROTATE"]:
            pass
        elif func == FUNC["ATAN2"]:
            mode, z0 = MODE_VEC, 0
            if xw < 0:
                x0, y0 = -xw, -yw
                pi_ctl = PI_SUB if yw < 0 else PI_ADD
            # atan2(0, 0) has no value; vectoring cannot resolve it either, since
            # d comes from sign(y) and y never moves when x is zero too.
            if xw == 0 and yw == 0:
                zero_res = True
        elif func == FUNC["SINH_COSH"]:
            coord, x0, y0 = COORD_HYP, self.inv_k_hyp, 0
        elif func == FUNC["HROTATE"]:
            coord = COORD_HYP
        elif func == FUNC["ATANH"]:
            coord, mode, z0, chk = COORD_HYP, MODE_VEC, 0, True
            if xw < 0:
                x0, y0 = -xw, -yw
            if x0 == 0:
                dom = True
        elif func == FUNC["EXP"]:
            coord, x0, y0 = COORD_HYP, self.inv_k_hyp, self.inv_k_hyp
        elif func == FUNC["LN"]:
            coord, mode, chk, dbl = COORD_HYP, MODE_VEC, True, True
            x0 = self.wrap((xw >> 1) + self.half)
            y0 = self.wrap((xw >> 1) - self.half)
            z0 = 0
            if xw <= 0:
                dom = True
        elif func == FUNC["MUL"]:
            coord, y0 = COORD_LIN, 0
        elif func == FUNC["DIV"]:
            coord, mode, z0, chk = COORD_LIN, MODE_VEC, 0, True
            if xw < 0:
                x0, y0 = -xw, -yw
            if x0 == 0:
                dom = True
        else:
            dom = True

        if mode == MODE_ROT:
            if coord == COORD_CIRC:
                if z0 > self.half_pi:
                    z0, x0, y0 = z0 - self.pi, -x0, -y0
                elif z0 < -self.half_pi:
                    z0, x0, y0 = z0 + self.pi, -x0, -y0
                if abs(z0) > self.lim_circ:
                    dom = True
            elif coord == COORD_LIN:
                if abs(z0) > self.lim_lin:
                    dom = True
            else:
                if abs(z0) > self.lim_hyp:
                    dom = True

        return (coord, mode, self.wrap(x0), self.wrap(y0), self.wrap(z0),
                dom, chk, pi_ctl, dbl, zero_res)

    # -- post ---------------------------------------------------------------
    def pack(self, v):
        """Round to the interface format and saturate. Returns (word, saturated)."""
        r = (v + (1 << (self.guard_frac - 1))) >> self.guard_frac
        if r > self.fx_max:
            return self.fx_max, True
        if r < self.fx_min:
            return self.fx_min, True
        return r, False

    def residual_threshold(self, coord):
        last = self.shifts[coord][self.num_stages - 1]
        return max(0, last - self.resid_shift_margin)

    def post(self, coord, mode, x, y, z, dom, chk, pi_ctl, dbl, zero_res, func, tag):
        resid_x, resid_y = x, y
        if chk:
            sh = self.residual_threshold(coord)
            if abs(y) > (abs(x) >> sh) + self.resid_floor:
                dom = True

        z1 = z
        if pi_ctl & 0b10:
            z1 = self.wrap(z - self.pi if (pi_ctl & 1) else z + self.pi)
        if dbl:
            z1 = self.wrap(z1 << 1)

        xo, sx = self.pack(x)
        yo, sy = self.pack(y)
        zo, sz = self.pack(z1)

        flags = 0
        if dom:
            xo = yo = zo = 0
            flags |= FLAG_DOM
        elif zero_res:
            xo = yo = zo = 0
        else:
            if sx:
                flags |= FLAG_SAT_X
            if sy:
                flags |= FLAG_SAT_Y
            if sz:
                flags |= FLAG_SAT_Z
        return Result(xo, yo, zo, flags, func, tag, resid_x, resid_y)

    # -- whole operation ----------------------------------------------------
    def run(self, func, x_fx=0, y_fx=0, z_fx=0, tag=0):
        (coord, mode, x0, y0, z0,
         dom, chk, pi_ctl, dbl, zero_res) = self.pre(func, x_fx, y_fx, z_fx)
        x, y, z = x0, y0, z0
        for s in range(self.num_stages):
            x, y, z = self.micro_rotation(coord, mode, x, y, z,
                                          self.shifts[coord][s], self.angles[coord][s])
        return self.post(coord, mode, x, y, z, dom, chk, pi_ctl, dbl, zero_res,
                         func, tag)

    # -- documented convergence domains ------------------------------------
    def domain(self, func_name):
        """Closed-form accepted domain, as real numbers. Keys depend on the func."""
        lim_hyp = self.int_to_real(self.lim_hyp)
        lim_lin = self.int_to_real(self.lim_lin)
        lim_circ = self.int_to_real(self.lim_circ)
        t = self.int_to_real(self.tanh_lim_hyp)
        fx_hi = self.to_real(self.fx_max)
        fx_lo = self.to_real(self.fx_min)
        if func_name in ("SIN_COS", "ROTATE"):
            # The pi fold plus three integer bits covers the whole word.
            return {"z": (fx_lo, fx_hi), "note": f"residual after fold <= {lim_circ:.6f}"}
        if func_name == "ATAN2":
            return {"note": "unrestricted, all four quadrants"}
        if func_name in ("SINH_COSH", "HROTATE", "EXP"):
            return {"z": (-lim_hyp, lim_hyp)}
        if func_name == "ATANH":
            return {"ratio": (-t, t), "x": "nonzero"}
        if func_name == "LN":
            lo = (1 - t) / (1 + t)
            hi = (1 + t) / (1 - t)
            return {"x": (lo, min(hi, fx_hi))}
        if func_name == "MUL":
            return {"z": (-lim_lin, lim_lin)}
        if func_name == "DIV":
            return {"ratio": (-lim_lin, lim_lin), "x": "nonzero"}
        raise KeyError(func_name)


def reference(func_name, x=0.0, y=0.0, z=0.0, k_circ=1.0, k_hyp=1.0):
    """Double-precision reference. Returns a dict of the outputs that carry meaning.

    k_circ and k_hyp scale the results the hardware leaves un-compensated, so a
    caller can compare against the hardware's own gain constants.
    """
    if func_name == "SIN_COS":
        return {"x": math.cos(z), "y": math.sin(z)}
    if func_name == "ROTATE":
        return {"x": k_circ * (x * math.cos(z) - y * math.sin(z)),
                "y": k_circ * (y * math.cos(z) + x * math.sin(z))}
    if func_name == "ATAN2":
        return {"z": math.atan2(y, x), "x": k_circ * math.hypot(x, y)}
    if func_name == "SINH_COSH":
        return {"x": math.cosh(z), "y": math.sinh(z)}
    if func_name == "HROTATE":
        return {"x": k_hyp * (x * math.cosh(z) + y * math.sinh(z)),
                "y": k_hyp * (y * math.cosh(z) + x * math.sinh(z))}
    if func_name == "ATANH":
        return {"z": math.atanh(y / x), "x": k_hyp * math.sqrt(x * x - y * y)}
    if func_name == "EXP":
        return {"x": math.exp(z), "y": math.exp(z)}
    if func_name == "LN":
        return {"z": math.log(x)}
    if func_name == "MUL":
        return {"y": x * z}
    if func_name == "DIV":
        return {"z": y / x}
    raise KeyError(func_name)
