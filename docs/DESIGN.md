# Design

CORDIC theory as this implementation actually uses it, the fixed-point choices, the
two microarchitectures, and the verification plan.

## Contents

- [The generalised recurrence](#the-generalised-recurrence)
- [Circular coordinates](#circular-coordinates)
- [Hyperbolic coordinates and the repeated iterations](#hyperbolic-coordinates-and-the-repeated-iterations)
- [Linear coordinates](#linear-coordinates)
- [Gain](#gain)
- [Convergence domains](#convergence-domains)
- [Full-range arguments: the pi fold](#full-range-arguments-the-pi-fold)
- [Detecting non-convergence without a multiplier](#detecting-non-convergence-without-a-multiplier)
- [Fixed-point format](#fixed-point-format)
- [Accuracy](#accuracy)
- [The two microarchitectures](#the-two-microarchitectures)
- [Constant generation and tool support](#constant-generation-and-tool-support)
- [Verification plan](#verification-plan)

## The generalised recurrence

One recurrence covers all three coordinate systems (Walther, 1971). For stage `s`
with shift amount `s`, micro-rotation angle `a_s`, and direction `d` in `{-1, +1}`:

```
x' = x - m*d*(y >> s)
y' = y +   d*(x >> s)
z' = z -   d*a_s
```

`m` selects the coordinate system and, with it, the angle table:

| `m` | System | `a_s` | Invariant | Shift sequence |
|----:|--------|-------|-----------|----------------|
| +1 | circular | `atan(2**-s)` | `x**2 + y**2` scaled by K | 0, 1, 2, 3, ... |
| 0 | linear | `2**-s` | `x` unchanged | 0, 1, 2, 3, ... |
| -1 | hyperbolic | `atanh(2**-s)` | `x**2 - y**2` scaled by Kh | 1, 2, 3, 4, **4**, 5, ... |

`d` comes from the mode:

- **rotation** drives `z` to zero, `d = sign(z)`, and the vector ends rotated by the
  original `z`.
- **vectoring** drives `y` to zero, `d = -sign(y)`, and `z` ends holding the angle
  the vector started at.

That is the whole datapath. `rtl/cordic_stage.sv` is nine lines of arithmetic and
there is no multiplier anywhere in the design, which is the reason to use CORDIC in
the first place. Both cores instantiate that one module, so they cannot drift.

`make arith` asserts the no-multiplier property rather than leaving it as a claim:
Yosys is stopped after `proc` and `flatten`, before any cell mapping, and asked to
assert `$mul`, `$div`, `$mod`, `$pow` and `$macc` are absent. It then prints what the
design does infer, which describes the two microarchitectures more precisely than
prose can:

| Configuration | Arithmetic inferred |
|---|---|
| pipelined Q3.29 N=28 | mux 366, add 95, sub 89, pmux 45, neg 8 |
| iterative Q3.29 N=28 | mux 252, add 15, sub 8, pmux 9, neg 8, `sshr` 2 |
| pipelined Q3.13 N=15 | mux 236, add 56, sub 50, pmux 27, neg 8 |
| iterative Q3.13 N=15 | mux 200, add 15, sub 8, pmux 9, neg 8, `sshr` 2 |

The folded core has a sixth of the adders and the only two `sshr` cells in the whole
design, which are its two barrel shifters. The pipelined core has none at all,
because its shift amounts are elaboration-time constants and become wiring. That one
table is the area-versus-frequency trade-off in its rawest form, before any tool has
mapped a cell.

## Circular coordinates

Each stage is a rotation by `atan(2**-s)` scaled by `sqrt(1 + 2**-2s)`:

```
x' = x - d*(y >> s) = cos(a_s)*(x - d*tan(a_s)*y) / cos(a_s)
y' = y + d*(x >> s)
```

The `cos` factor is what the gain accounts for. After N stages,

```
x_N = K * (x_0*cos(z_0) - y_0*sin(z_0))
y_N = K * (y_0*cos(z_0) + x_0*sin(z_0))
z_N = 0
```

in rotation mode, and in vectoring mode

```
x_N = K * sqrt(x_0**2 + y_0**2)
y_N = 0
z_N = z_0 + atan(y_0 / x_0)
```

Loading `x_0 = 1/K`, `y_0 = 0` gives `cos(z)` and `sin(z)` with the gain already
undone, which is what `SIN_COS` does. Loading `z_0 = 0` and letting vectoring run
gives `atan2` in `z` and `K*hypot` in `x`, which is `ATAN2`.

## Hyperbolic coordinates and the repeated iterations

Substituting `m = -1` and `a_s = atanh(2**-s)` gives, in rotation mode,

```
x_N = Kh * (x_0*cosh(z_0) + y_0*sinh(z_0))
y_N = Kh * (y_0*cosh(z_0) + x_0*sinh(z_0))
```

with `Kh = prod sqrt(1 - 2**-2s) < 1`. The shift starts at 1, not 0, because
`atanh(1)` is infinite.

**Why 4 and 13 repeat.** A CORDIC sequence `a_0 .. a_{N-1}` can reach every angle in
`[-sum, +sum]` only if no single step is bigger than everything left after it:

```
a_k <= sum_{j>k} a_j + a_{N-1}                                            (C)
```

For circular stages this holds automatically, because `atan` is concave and
`atan(2x) < 2*atan(x)`. `atanh` is convex, so it fails. With the bare sequence
1, 2, 3, 4, 5, ... and 28 stages:

```
atanh(2**-4)                = 0.06258157
sum_{s=5..26} atanh(2**-s)  = 0.06265575   plus a_last, which is negligible
```

That one is fine, but continue and the shortfall compounds; by shift 13 the
condition is violated outright. The classical fix is to repeat the indices

```
i_1 = 4,  i_{k+1} = 3*i_k + 1  ->  4, 13, 40, 121, ...
```

so the sequence becomes 1, 2, 3, 4, **4**, 5, ..., 12, 13, **13**, 14, ...
`hyp_shift_sequence()` in `scripts/cordic_tables.py` generates it and
`convergence_ok()` checks (C) for every stage count.

**Which stage counts are legal.** A repeat only helps once it is complete, so
truncating the sequence mid-pair leaves (C) violated. Checked numerically, the
condition holds for `NumStages` of 5, and 15 or more; for 6 through 14 the shift-4
step exceeds its tail by a relative 1.1e-4, which is not negligible. `cordic_accel`
rejects those at elaboration:

```
if (NumStages != 5 && NumStages < 15)
  $fatal(1, "NumStages %0d truncates the hyperbolic repeat sequence; use 5, or 15 or more");
```

(C) is checked with a relative tolerance of 1e-6, because the last two steps of any
hyperbolic sequence violate it by a relative `O(2**-2s / 3)` from the convexity of
`atanh` itself. The worst case in the tabulated range is the shift-13 step, short by
4.3e-9 relative, which is 5.2e-13 absolute or 0.0003 LSB of Q3.29. The accepted
radius is quantised down from the raw sum in any case, so there is real margin.

**exp and ln.** Two identities, no extra hardware:

- `exp(z) = cosh(z) + sinh(z)`, so starting a hyperbolic rotation from
  `x_0 = y_0 = 1/Kh` leaves `exp(z)` in **both** x and y.
- `ln(w) = 2*atanh((w-1)/(w+1))`, so a hyperbolic vectoring from `x_0 = (w+1)/2`,
  `y_0 = (w-1)/2` leaves `ln(w)/2` in z, doubled on the way out. Halving both
  components leaves the ratio alone and keeps `x_0` inside the format for every
  representable `w`; without it, `w+1` would overflow Q3.29 for `w > 3`.
  A pleasant side effect: `x_0**2 - y_0**2` works out to exactly `w`, so the
  magnitude output is `Kh*sqrt(w)`.

## Linear coordinates

`m = 0` leaves x alone, so `y` accumulates `x*z` and `z` accumulates `y/x`:

```
rotation:   y_N = y_0 + x_0*z_0,  used with y_0 = 0 for multiply
vectoring:  z_N = z_0 + y_0/x_0,  used with z_0 = 0 for divide
```

The shift sequence starts at 0 rather than 1, which puts the radius at
`sum_{s=0}^{N-1} 2**-s = 2 - 2**-(N-1)`, just under 2 rather than just under 1. That
one choice doubles the usable range of both multiply and divide for free.

Divide is binary long division here, one quotient bit per stage, which is why it
costs the same N cycles as everything else.

## Gain

The gains for the elaborated 28 stages, exactly as the hardware reports them:

| Register | Value (Q3.29) | Decimal |
|----------|--------------:|--------:|
| `K_CIRC` | 884097682 | 1.6467602588 |
| `IK_CIRC` | 326016437 | 0.6072529349 |
| `K_HYP` | 444614671 | 0.8281593602 |
| `IK_HYP` | 648270052 | 1.2074970677 |

Both approaches to gain are used, chosen per function rather than globally:

**Pre-scaled.** `SIN_COS`, `SINH_COSH` and `EXP` load the initial vector from a
hardwired `1/K` or `1/Kh` constant, so their outputs are gain-free. This costs
nothing: the initial vector is a constant either way, so a different constant is
free. The same trick cannot work for a caller-supplied vector, which would need a
real multiplier.

**Exposed.** `ROTATE`, `HROTATE` and the magnitude output of `ATAN2` and `ATANH`
carry the gain, and the four registers above report it so software can divide it
out. `cordic_hypot()` and `cordic_rotate()` in the driver do exactly that;
`cordic_exec()` with the raw function code keeps the scaled value if you would
rather fold the gain into a later constant.

**Gain-free by construction.** Every vectoring-mode angle (`ATAN2`, `ATANH`, `LN`)
and both linear results carry no gain at all, because `z` accumulates angles rather
than being scaled by the rotations.

`tb/test_reset.py::test_gain_and_limit_registers` asserts every one of these
constants against the model, because a wrong gain constant is a silently wrong
answer for the caller rather than a visible failure.

## Convergence domains

Radii for the elaborated 28 stages, as `LIM_*` report them:

| Register | Value (Q3.29) | Decimal | What it bounds |
|----------|--------------:|--------:|----------------|
| `LIM_CIRC` | 935919873 | 1.7432866115 | `sum atan(2**-s)`, 99.88 degrees |
| `LIM_HYP` | 600314558 | 1.1181729995 | `sum atanh(2**-s)` |
| `LIM_LIN` | 1073741820 | 1.9999999925 | `sum 2**-s` |
| `TANH_LIM_HYP` | 433218581 | 0.8069324885 | `tanh(LIM_HYP)`, the largest `|y/x|` for atanh |

Per function:

| Function | Domain | Enforced |
|----------|--------|----------|
| `SIN_COS`, `ROTATE` | the whole representable range of z | never fails, see the pi fold below |
| `ATAN2` | unrestricted, all four quadrants | never fails |
| `SINH_COSH`, `HROTATE`, `EXP` | `|z| <= LIM_HYP` | compared against the radius in `cordic_pre` |
| `ATANH` | `X != 0` and `|Y/X| <= TANH_LIM_HYP` | residual check in `cordic_post` |
| `LN` | `X` in `[0.10684822, 4)` | residual check; the upper closed-form bound is 9.359, so the format binds first |
| `MUL` | `|Z| <= LIM_LIN` | compared against the radius in `cordic_pre` |
| `DIV` | `X != 0` and `|Y/X| <= LIM_LIN` | residual check |

The radii are quantised **down** to the interface format and then widened, so the
value read from `LIM_HYP` is exactly the largest argument the hardware accepts.
Rounding to the internal format first left the register's own value one LSB out of
range and rejected, which `tb/test_domain.py` caught.

When a domain error is detected, X, Y and Z are all forced to zero and
`RES_FLAGS.DOMAIN_ERR` is set. Returning the non-converged vector would look like a
plausible answer; zero plus a flag cannot be mistaken for one.

## Full-range arguments: the pi fold

The bare circular recurrence reaches only `|z| <= 1.7433` rad, so quadrants two and
three are unreachable. Since `R(z) = R(z - pi) * R(pi)` and `R(pi) = -I`, folding is
a subtract and two negations:

```
if      (z >  pi/2) { z -= pi; x0 = -x0; y0 = -y0; }
else if (z < -pi/2) { z += pi; x0 = -x0; y0 = -y0; }
```

After the fold the residual angle is at most `max(pi/2, |z_max| - pi)`. With three
integer bits `z_max` is just under 4, so `4 - pi = 0.858` and `pi/2 = 1.5708`, both
inside 1.7433. **Every representable angle converges**, and circular rotation has no
error case at all. `tb/test_domain.py::test_circular_never_errors` asserts that over
1219 arguments spanning the whole word.

`cordic_pre` still compares the folded angle against `LIM_CIRC`, which is dead code
at three integer bits but becomes live if `DataWidth - FracBits` is raised: with four
integer bits, `8 - pi = 4.86` exceeds the radius and the accepted range narrows to
`|z| <= pi/2 + LIM_CIRC = 3.314`.

Vectoring needs `x > 0`. Negating both components rotates by pi and leaves the ratio
untouched, so the post stage adds back `+pi` when the original y was non-negative
and `-pi` when it was negative. That covers all four quadrants of `atan2` at the cost
of one add.

**One genuine edge case.** `atan2(0, 0)` cannot be resolved by vectoring at all:
`d` comes from `sign(y)`, and with `x` zero as well `y` never moves, so `z` ratchets
up by every micro-rotation and ends at the full radius, 1.7433. The first version of
this design did exactly that. `cordic_pre` now flags the all-zero vector and
`cordic_post` returns an exact zero, matching what C's `atan2` does for `(+-0, +0)`.
It is a defined answer, not an error, so no flag is raised.

## Detecting non-convergence without a multiplier

The rotation-mode domains are one comparison against a constant. The vectoring ones
are not: `|y/x| <= T` needs a full-width multiply by the constant `T`, which would be
the single largest block in the iterative variant, larger than the datapath it
guards.

Instead the residual is inspected. Vectoring drives `y` to zero, so on convergence
`|y|` ends below the granularity of the last micro-rotation, about
`|x| * 2**-s_last`, while a non-converging argument leaves `|y|` stuck far above it:

```
threshold = (|x| >> (s_last - ResidShiftMargin)) + ResidFloorMul * NumStages
dom_err   = |y| > threshold
```

One shift, one add, one compare. It also tests the thing that actually matters,
which is whether this operation converged, rather than a closed-form bound that is
only a proxy for it.

Characterised against the bit-accurate model over 380k arguments with
`ResidShiftMargin = 1` and `ResidFloorMul = 4`:

- **no false positives at all.** Nothing inside the documented domain is ever
  rejected, across dense sweeps of `ATANH` (including the negative-x reflection),
  `DIV`, `LN`, hyperbolic rotation and the full circular range.
- **detection outside** is guaranteed once the argument is past the boundary by
  11 LSBs for `ATANH`, 16 for `DIV`, 9 for `LN`. Inside that band the operation
  still converges, so a missed flag returns a correct result rather than a wrong
  one.

`tb/test_domain.py` re-measures the band on the RTL and fails if it exceeds 64 LSBs,
so a change that widened it would not pass quietly.

## Fixed-point format

Parameters: `DataWidth` (W), `FracBits` (F). One sign bit, `W - F - 1` integer
magnitude bits, F fractional bits. The default is **Q3.29** in 32 bits: range
`[-4.0, +3.999999998]`, LSB 1.863e-9.

**Why three integer bits are the floor.** Several quantities have to be
representable at once:

| Quantity | Largest value | Needs |
|----------|--------------:|-------|
| `pi`, for the fold and the atan2 correction | 3.14159 | 2 magnitude bits |
| `exp(LIM_HYP)` | 3.0596 | 2 |
| `cosh(LIM_HYP)` | 1.6899 | 1 |
| `LIM_LIN`, the divide and multiply radius | 2.0 | 2 |
| `2*LIM_HYP`, the ln result | 2.2363 | 2 |

`pi` is the binding one, so `DataWidth - FracBits >= 3` is an elaboration check
rather than a suggestion. Two integer bits would make the fold impossible and take
four-quadrant sin and cos with it.

**Guard bits.** The internal datapath is `GuardInt = 2` integer bits and
`GuardFrac = 4` fractional bits wider, so 38 bits for Q3.29:

- the four fractional guard bits cut the truncation walk by 16x. Each stage's
  arithmetic shift truncates, and over N stages the error reaches `N * 2**-(F+G)`,
  which is `N/2**G` output LSBs: 1.75 rather than 28.
- the two integer guard bits absorb the magnitude growth in vectoring mode, where
  `x` ends at `K*hypot(x,y)` and can reach 9.3 before the output stage rounds and
  saturates it back into range.

Output conversion rounds half up and saturates, with `RES_FLAGS.SAT_X/Y/Z` reporting
which coordinate clipped. Saturation is a range event, not an error, so it does not
set `DOMAIN_ERR`.

**Tested formats.** Q3.29 with 28 stages is the default. Q3.13 in 16 bits with 15
stages is the small configuration, and both are covered by `make lint` and by the
synthesis sweep. `FracBits + GuardFrac <= 56` is checked at elaboration, from the
ROM's own precision.

## Accuracy

Three things limit it, for N stages, F fractional bits and G fractional guard bits:

```
a_last  = atan(2**-(N-1))    the rotation the sequence can no longer resolve
eps_int = 2**-(F+G)          one internal LSB, the truncation step of each shift
eps_out = 2**-F              one interface LSB, and the final rounding step
```

A **rotation-mode** output is a coordinate of a vector of magnitude R, so both the
angular slip and the truncation walk scale with R:

```
|error| <= R * (a_last + N*eps_int) + eps_out
```

A **vectoring-mode angle** behaves differently, and the difference matters. The
residual sits in `y`, and turning a y-residual into an angle divides by the
magnitude:

```
|error| <= a_last + N*eps_int / hypot(x, y)
```

So `atan2` of a vector a few LSBs long carries no usable angle at all, and quoting a
fixed LSB figure for it would be meaningless rather than strict. `tb/cordic_bounds.py`
implements both forms, applies a safety factor of 4, and `tb/test_accuracy.py`
asserts the result on **every** argument. Measured over 40k model arguments per
function, the worst observed error came to 0.52 of the bound, so the margin is
measured rather than assumed.

Alongside that, a fixed LSB bound is asserted over the well-conditioned region,
input magnitude at least 1/16, which is where the headline numbers in the README
come from. The magnitude-versus-error table that justifies where that line sits is
in `tb/cordic_bounds.py`.

`docs/img/error_vs_stages.png` and `error_vs_width.png` sweep the model rather than
the RTL, and say so on the figure: 27 stage counts and 11 word widths would be that
many separate Verilator elaborations. The model is asserted bit-identical to the RTL
for every operation everywhere else in the suite, which is what makes the
substitution defensible.

## The two microarchitectures

Both instantiate the same `cordic_stage` over the same shift and angle sequence, so
they are bit-identical rather than merely equivalent. `Variant` picks one.

**Pipelined, `cordic_core_pipe.sv`.** N register banks, one per stage. Each stage's
shift amount is a compile-time constant, so `x >> s` is wiring; circular and linear
share shift `s` and hyperbolic uses the repeat sequence, so a stage needs at most a
two-way mux ahead of its adders.

Flow control is a single global enable rather than per-stage skid buffers. The
pipeline freezes as a whole when the final stage holds a result the consumer will not
take:

```systemverilog
assign pipe_en = !(vq[NumStages-1] && !ready_i);
```

One high-fanout enable net instead of a ready chain running back through every
stage, and nothing is ever dropped. The datapath registers take no reset, only the
valid bits do, which keeps the reset tree off `3*NumStages` wide words; they are only
ever read behind a valid bit.

**Iterative, `cordic_core_iter.sv`.** One stage reused N times: three registers, one
adder set, but now two barrel shifters and a mux over the angle table. Accepting a
new operation in the `StDone` cycle rather than after it saves a cycle per operation.

Measured, from `make test` and `make pdk`, on the real IHP SG13G2 130nm process:

| | Pipelined | Iterative | Ratio |
|---|---:|---:|---:|
| Cells, Q3.29 N=28 | 40,413 | 8,390 | 4.8x |
| Flip-flops | 4,921 | 1,229 | 4.0x |
| Area | 607,385 um2 | 135,442 um2 | 4.5x |
| Fmax, slow corner | 61.6 MHz | 48.5 MHz | 1.27x |
| Retire interval | 1 cycle | 29 cycles | 29x |
| Throughput | 61.6 M results/s | 1.67 M results/s | 36.9x |
| Results/s per mm2 | 101.4 M | 12.3 M | 8.2x |
| Latency, end to end | 30 cycles | 31 cycles | |

**Folding is a worse deal than 1/N**, and it takes real timing to see why. It costs
frequency as well as throughput: the folded core runs 27 percent slower at Q3.29,
because its barrel shifter and angle mux sit inside the loop, in series with the same
carry chain the pipelined core has to itself. So 4.5x the area buys 36.9x the
throughput.

The penalty is width-dependent. At Q3.13 the two run at the same speed, 95.9 against
98.1 MHz, because a 22-bit internal datapath needs one fewer mux level in the shifter
than a 38-bit one. The throughput gap narrows to 15.6x for 2.85x the area, so the
folded core is a relatively better proposition at narrow formats.

The folded core's **area barely moves with the stage count**: 134,857 um2 at 16
stages against 135,442 at 28, a factor of 1.004 for 1.75x the micro-rotations,
because only the angle table and its mux grow. The pipelined core scales 1.535x over
the same change. That is the property folding exists for, measured rather than
asserted.

**Why the streaming port exists.** A register-mapped issue costs four writes and
five reads, measured at 57 cycles per operation. The pipelined core retires one per
cycle. Nothing reachable over a register interface can keep it fed, so the streaming
port takes one operation per cycle from a DMA engine or another accelerator:
measured 1.94 cycles per operation against 57, a 29.4x gap.

## What the critical path actually runs through

`make pdk` reports the path with the flattened instance names resolved back to the
RTL registers they implement, so this is read off the tool rather than reasoned about.
At the slow corner, Q3.29 with 28 stages:

| | Pipelined | Iterative |
|---|---|---|
| Startpoint | `i_in_fifo.rptr_q[0]` | `i_unit.gen_iterative.i_core.ar_q[0]` |
| Endpoint | `i_unit.gen_pipelined.i_core.xq[36]` | `i_unit.gen_iterative.i_core.xr_q[37]` |
| Cells | 55 | 52 |
| Carry chain (AOI/OAI) | 42 | 36 |
| Mux (shift or select) | 1 | 3 |
| XOR/XNOR (sum bits) | 3 | 2 |

**The adder's carry chain dominates both.** Not the shift network, not the angle
lookup, which is the answer to the question you would actually ask about a CORDIC.
`abc` maps the adders to ripple carry, so 42 of 55 cells on the pipelined path are
the AOI/OAI pairs a carry chain becomes, ending at bit 36 of a 38-bit word, which is
the far end of that chain.

What differs is what sits **in series** with it:

- The pipelined path starts at the input FIFO's read pointer, so one cycle covers the
  FIFO read, `cordic_pre`'s pi fold (a subtract) and stage 0's own add. Three adds in
  series. Registering `cordic_pre` would shorten this, at the cost of one cycle of
  latency and a wider pipeline.
- The folded path starts at the coordinate-system bit of the attribute register and
  runs through the shift and angle muxes before reaching the same carry chain. Three
  mux cells rather than one. Nothing shortens this without unfolding, which is
  precisely the point: the barrel shifter is the price of reusing one stage.

The obvious next optimisation, then, is not architectural but arithmetic: a
carry-select or carry-lookahead adder would lift both variants. It is left undone
deliberately, since it would change the comparison for neither variant's benefit and
`abc`'s ripple carry is what an integrator will actually get from this flow.

## Constant generation and tool support

Nothing in the synthesisable path calls a real-valued system function, for two
independent reasons:

- **Yosys does not implement them.** `$atan` and `$ln` are simply unavailable, so a
  design that computes its tables that way cannot be synthesised at all.
- **Icarus Verilog folds them wrongly, without complaining.** A constant function
  containing `$atan(2.0 ** -real'(i))` returns 0. The first probe of this design
  computed `atan(1) * 2**29` as `0` and left the output register at `x`, silently.

So `scripts/cordic_tables.py` computes every constant in arbitrary precision with
mpmath, `scripts/gen_cordic_rom.py` emits them into `rtl/cordic_rom.svh` as integer
literals in Q3.61, and `cordic_rom_to_fx()` re-rounds to the working format with a
shift and an add. 61 fractional bits is the most that still fits `pi` in a signed
64-bit word. `make check-gen` regenerates and diffs, so a stale ROM fails the build.

Two further Yosys 0.33 limitations shaped the RTL, and both are worth knowing about
before writing anything that has to pass through it:

- **Packed 2D localparams do not parse.** `localparam logic [55:0][63:0] Rom = {...}`
  is a syntax error. The generated tables are flat vectors, read back through the
  accessors in `cordic_rom_fx.svh`, which is the only place the layout is spelled
  out.
- **Packed 2D signal declarations do not parse either.** The pipeline registers and
  the angle tables are flat as well, with genvar-constant part-selects so no shifter
  is inferred.

The same reasoning put the shared definitions in include files rather than a
package, included **inside** each module body: module-local localparams work in every
tool, whereas `$unit`-scope declarations shared across separately compiled files
depend on file ordering and on support that older Yosys releases lack.

Simulator, stated plainly: **Verilator only**. Icarus Verilog 12 cannot build this
design at all, aborting with an internal assertion (`netmisc.cc:1821`,
`packed_dims.size() == 1`) when a constant function indexes a packed 2D localparam.
Verilator 5.020 is what is installed and cocotb 2.0 requires 5.036, so the suite pins
cocotb 1.9.2; `tb/cordic_tb.py` carries two small shims so it runs unchanged on
either cocotb generation.

## Verification plan

| Area | Where | What it establishes |
|------|-------|---------------------|
| Numerical accuracy | `tb/test_accuracy.py` | 17,536 comparisons against double precision across all eleven functions, plus a bit-exact check against the model on every one. Both the derived and the fixed bound asserted. |
| Convergence domains | `tb/test_domain.py` | No in-domain argument rejected over 4,237 arguments; every out-of-domain argument rejected with zeroed outputs; the ambiguous band measured, not assumed. |
| OBI protocol | `tb/test_obi.py` | 14 tests in each of the two R-channel handshake configurations. The manager doubles as a checker, asserting one beat per accepted beat, in order, with rid echoing aid, continuously. |
| Throughput and latency | `tb/test_throughput.py` | Retire interval asserted against what `CFG1` advertises, not against a hard-coded number. Per-stage occupancy checked cell by cell. |
| Variant equivalence | `tb/test_equivalence.py` plus `scripts/check_equivalence.py` | Both variants record the same stimulus and the files are diffed word for word, without the model in between. |
| Reset and handshake | `tb/test_reset.py` | Reset asserted with a full pipeline leaves no stale result. Busy, done, queueing, overflow and the interrupt path. |
| Concurrent assertions | `rtl/cordic_obi_regs.sv`, `cordic_fifo.sv`, `cordic_core_pipe.sv` | 13 properties evaluated in every simulation via Verilator's `--assert`, so the OBI and structural rules hold in any integration's own testbench too. |
| Lint | `make lint` | Zero Verilator warnings at `-Wall` over 10 parameter configurations plus the Croc wrapper against stand-in Croc packages. |
| Synthesis | `make synth` | Six configurations, generic cells. No inferred latch, no combinational loop, no unmapped submodule, asserted inside the Yosys script itself. |
| Silicon | `make pdk` | Six configurations on real IHP SG13G2 130nm cells: area in um2 and Fmax at all three corners, with the repair target iterated to convergence so Fmax is a measurement rather than a function of the probe period. |
| Place and route | `make pnr` | Full RTL-to-GDS through LibreLane, both variants: post-route area, post-route timing at all three corners with extracted parasitics, router and Magic and KLayout DRC, a Magic-against-KLayout GDS XOR, and netgen LVS. The folded variant is clean on all of them; the pipelined variant's Magic DRC had not finished, and is reported as unfinished rather than passed. |
| Bounded equivalence | `make formal` | A SymbiYosys miter proving the two cores cannot disagree within a bound, for one operation in flight. Stronger than random vectors over what it covers, and narrower. [formal/README.md](../formal/README.md) states the bound, the configuration, and what did not converge. |
| Driver | `make sw` | The identical driver source runs on the host against a register-accurate peripheral model, 626 checks, and links as a complete RV32IMC image. |

Two things this repository does **not** establish, said plainly:

- **The RV32 image is never executed.** There is no Croc simulation here. It
  compiles and links, and it records its outcome at a known symbol so Croc's own
  testbench can read it, but nothing in this repository runs it.
- **The IHP timing in `make pdk` stops after synthesis and drive repair.** Wire
  parasitics are estimated by `set_wire_rc`, not extracted, because there is no
  placement. `make pnr` routes the two Q3.29 N=28 configurations the rest of the way
  and `scripts/pnr_fmax.py` re-times the routed netlists comparably; the gap runs to
  1.31x on cell area and 1.88x on frequency, in opposite directions.
  [../docs/pnr/README.md](pnr/README.md) states what the routed frequency does and
  does not claim.
- **Fmax is set by ripple-carry adders.** That is `abc`'s mapping, not the
  architecture, and it is reported rather than worked around. Both variants are
  affected identically, so the comparison between them holds.
- **`make synth` remains technology-independent** and is kept for anyone without the
  PDK. Those counts are gate equivalents, not areas.
