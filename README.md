# obi-cordic-accel

[![ci](https://github.com/danieltyukov/obi-cordic-accel/actions/workflows/ci.yml/badge.svg)](https://github.com/danieltyukov/obi-cordic-accel/actions/workflows/ci.yml)
[![licence](https://img.shields.io/badge/licence-Apache--2.0-blue.svg)](LICENSE)

A pipelined CORDIC arithmetic accelerator with an OBI subordinate register
interface, built as a drop-in `user_domain` peripheral for the
[Croc](https://github.com/pulp-platform/croc) open-source RISC-V SoC.

Eleven functions from one datapath with no multiplier anywhere in it: **sin, cos,
atan2, magnitude, sinh, cosh, atanh, exp, ln, multiply, divide**. All three CORDIC
coordinate systems, both micro-rotation modes, full four-quadrant argument handling,
and two interchangeable microarchitectures that produce bit-identical results.

![Block diagram](docs/img/block_diagram.svg)

## At a glance

| | |
|---|---|
| Functions | 11, across circular, linear and hyperbolic coordinates, rotation and vectoring |
| Format | Q3.29 in 32 bits by default, parameterised; Q3.13 in 16 bits also verified |
| Accuracy | 4.5 LSB worst case for sin and cos, 1.5 RMS, measured against double precision |
| Interfaces | OBI v1.6 subordinate over a 4 KB window, plus a valid/ready streaming port |
| Pipelined core | 1 result per cycle, 30 cycles end-to-end latency, 55,096 cells |
| Iterative core | 1 result per 29 cycles, 31 cycles end-to-end latency, 11,101 cells |
| Verification | 71 tests: 17,536 accuracy comparisons, 4,200 domain arguments, 28 OBI protocol tests, bit-identity between both cores over 900 operations, plus 13 concurrent assertions in the RTL |
| Tooling | Verilator lint clean at `-Wall` over 10 configurations, Yosys over 6, RV32 driver image links |

## Contents

- [Why](#why)
- [Functions](#functions)
- [Accuracy](#accuracy)
- [Register map](#register-map)
- [The two microarchitectures](#the-two-microarchitectures)
- [Streaming](#streaming)
- [Synthesis](#synthesis)
- [Software](#software)
- [Simulating and testing](#simulating-and-testing)
- [Repository layout](#repository-layout)
- [What this does not claim](#what-this-does-not-claim)
- [Licence](#licence)

## Why

CVE2, the core Croc ships with, is RV32IMC with no FPU and no divider worth the
name. Anything trigonometric, hyperbolic or logarithmic costs hundreds of cycles in
software. CORDIC computes all of it with shifts and adds, one bit of the answer per
micro-rotation, so an accelerator that fits in a few thousand gates can replace a
whole libm.

The single recurrence that makes that work, for stage `s` with shift `s` and
micro-rotation angle `a_s`:

```
x' = x - m*d*(y >> s)      m = +1 circular, 0 linear, -1 hyperbolic
y' = y +   d*(x >> s)      d = sign(z) rotating, -sign(y) vectoring
z' = z -   d*a_s
```

`rtl/cordic_stage.sv` is that, and nothing else. Both cores instantiate the same
module over the same sequence, which is why they are bit-identical rather than
merely equivalent.

## Functions


| `FUNC` | Name | System | Mode | Operands | Result | Convergence domain | Gain |
|-------:|------|--------|------|----------|--------|--------------------|------|
| 0 | `SIN_COS` | circular | rotation | Z = angle in radians | X = cos(Z), Y = sin(Z) | whole representable range of Z | compensated, x0 preloaded with 1/K |
| 1 | `ROTATE` | circular | rotation | X, Y = vector, Z = angle | X, Y = K * R(Z) * (X,Y) | whole representable range of Z | exposed as K_CIRC |
| 2 | `ATAN2` | circular | vectoring | X, Y = vector | Z = atan2(Y,X), X = K * hypot(X,Y) | all four quadrants, no restriction | Z exact, X scaled by K_CIRC |
| 3 | `SINH_COSH` | hyperbolic | rotation | Z = argument | X = cosh(Z), Y = sinh(Z) | \|Z\| <= LIM_HYP | compensated, x0 preloaded with 1/Kh |
| 4 | `HROTATE` | hyperbolic | rotation | X, Y = vector, Z = argument | X, Y = Kh * Rh(Z) * (X,Y) | \|Z\| <= LIM_HYP | exposed as K_HYP |
| 5 | `ATANH` | hyperbolic | vectoring | X, Y = vector | Z = atanh(Y/X), X = Kh * sqrt(X^2 - Y^2) | X != 0 and \|Y/X\| <= TANH_LIM_HYP | Z exact, X scaled by K_HYP |
| 6 | `EXP` | hyperbolic | rotation | Z = exponent | X = Y = exp(Z) | \|Z\| <= LIM_HYP | compensated, x0 = y0 = 1/Kh |
| 7 | `LN` | hyperbolic | vectoring | X = argument | Z = ln(X) | X > 0 and (X-1)/(X+1) within TANH_LIM_HYP | exact, no gain |
| 8 | `MUL` | linear | rotation | X, Z = factors | Y = X * Z | \|Z\| <= LIM_LIN | none, gain is 1 |
| 9 | `DIV` | linear | vectoring | Y = numerator, X = denominator | Z = Y / X | X != 0 and \|Y/X\| <= LIM_LIN | none, gain is 1 |

`FUNC` codes 10 to 31 are unassigned and are reported through
`RES_FLAGS.DOMAIN_ERR` rather than quietly computed.

The convergence constants, exactly as the hardware reports them for the default 28
stages:

| Register | Value (Q3.29) | Decimal | Meaning |
|----------|--------------:|--------:|---------|
| `K_CIRC` | 884097682 | 1.6467602588 | circular gain, `prod sqrt(1 + 2**-2s)` |
| `IK_CIRC` | 326016437 | 0.6072529349 | `1/K`, preloaded for gain-free sin and cos |
| `K_HYP` | 444614671 | 0.8281593602 | hyperbolic gain, `prod sqrt(1 - 2**-2s)` |
| `IK_HYP` | 648270052 | 1.2074970677 | `1/Kh`, preloaded for sinh, cosh and exp |
| `LIM_CIRC` | 935919873 | 1.7432866115 | `sum atan(2**-s)`, 99.88 degrees |
| `LIM_HYP` | 600314558 | 1.1181729995 | `sum atanh(2**-s)` |
| `LIM_LIN` | 1073741820 | 1.9999999925 | `sum 2**-s` |
| `TANH_LIM_HYP` | 433218581 | 0.8069324885 | `tanh(LIM_HYP)`, largest `abs(Y/X)` for atanh |

Two things about that table are worth spelling out.

**Full four quadrants, no error case.** The bare circular recurrence reaches only
`LIM_CIRC`, about 99.9 degrees, so quadrants two and three are unreachable. Since
`R(z) = R(z - pi) * R(pi)` and `R(pi) = -I`, subtracting pi and negating the initial
vector fixes it for one subtract and two negations. After the fold the residual angle
never exceeds 1.5708 rad, inside the 1.7433 radius, so **every representable angle
converges** and `SIN_COS` has no error case at all.
`tb/test_domain.py::test_circular_never_errors` asserts that over 1,219 arguments
spanning the whole word. Vectoring covers all four quadrants the same way, by
negating a negative x and adding back the appropriate `+-pi`.

**The radii read back exactly.** `LIM_HYP` is quantised down to the interface format,
so the value software reads is exactly the largest argument the hardware accepts.
Rounding to the internal format first left the register's own value one LSB out of
range and rejected, which the domain test caught.

Everything about the theory, including why hyperbolic iterations 4 and 13 have to
repeat and which stage counts that makes legal, is in [docs/DESIGN.md](docs/DESIGN.md).

## Accuracy

Measured on the RTL against `math` in double precision, 17,536 comparisons. Every
result is separately asserted bit-exact against the model, so these numbers are
accuracy, not correctness. In LSBs of Q3.29, where one LSB is 1.863e-9:

| Function | Output | n | Max error | RMS | Asserted bound |
|----------|--------|--:|----------:|----:|---------------:|
| `SIN_COS` | cos | 1816 | **4.49** | 1.54 | 12 |
| `SIN_COS` | sin | 1816 | **4.34** | 1.82 | 12 |
| `ATAN2` | atan2 | 1164 | **5.33** | 2.37 | 24 |
| `ATAN2` | K*hypot | 1164 | **1.18** | 0.47 | 24 |
| `ROTATE` | x | 1205 | **14.37** | 3.77 | 48 |
| `ROTATE` | y | 1205 | **15.11** | 3.78 | 48 |
| `SINH_COSH` | cosh | 611 | **10.32** | 3.44 | 24 |
| `SINH_COSH` | sinh | 611 | **13.53** | 5.72 | 24 |
| `EXP` | exp | 611 | **23.39** | 6.74 | 40 |
| `HROTATE` | x | 1205 | **11.31** | 3.08 | 64 |
| `HROTATE` | y | 1205 | **10.36** | 3.01 | 64 |
| `ATANH` | atanh | 1210 | **9.73** | 4.66 | 64 |
| `ATANH` | Kh*sqrt | 1210 | **1.40** | 0.41 | 48 |
| `LN` | ln | 608 | **19.20** | 9.57 | 48 |
| `MUL` | product | 611 | **17.00** | 5.00 | 24 |
| `DIV` | quotient | 524 | **5.55** | 2.34 | 32 |

![Error versus input angle](docs/img/error_vs_angle.png)

The error does not step at `+-pi/2` where the fold engages, which is the point: the
quadrant handling costs nothing in accuracy.

![Error distribution per function](docs/img/error_histograms.png)

A **second, stricter bound** is asserted on every single argument, not just the
well-conditioned ones. It carries the conditioning of the operation, which matters
enormously in vectoring mode: the residual sits in `y`, and turning a y-residual into
an angle divides by the magnitude, so

```
rotation:   |error| <= R * (atan(2**-(N-1)) + N*2**-(F+G)) + 2**-F
vectoring:  |error| <= atan(2**-(N-1)) + N*2**-(F+G) / hypot(x, y)
```

which is why `atan2` of a vector a few LSBs long carries no usable angle at all, and
why the LSB figures above are quoted over the region where an angle exists (input
magnitude at least 1/16). Zero violations of the derived bound over the whole sweep;
the worst observed error came to 0.52 of it. Both forms live in
`tb/cordic_bounds.py` with the measurements that justify them.

![Convergence versus stage count](docs/img/error_vs_stages.png)

![Accuracy versus word width](docs/img/error_vs_width.png)

Those two sweep the bit-accurate model rather than the RTL, and say so on the
figure: 27 stage counts and 11 word widths would be that many separate Verilator
elaborations. The model is asserted bit-identical to the RTL for every operation
everywhere else in the suite.

The trajectory the datapath actually walks, read out of the iterative core's debug
port one micro-rotation at a time during simulation and asserted against the model
point by point before being plotted:

![Convergence trajectory](docs/img/convergence_trajectory.png)

## Register map

One 4 KB window. Offsets `0x000` to `0x063` are implemented; the rest of the window
answers with `r.err` and `0xBADACCE5`, so a stray access is reported rather than
aliased.

![Register map](docs/img/regmap.svg)


### Register summary

| Offset | Name | Access | Description |
|--------|------|--------|-------------|
| `0x000` | `ID` | RO | Identification magic, reads 0x434F5244 ("CORD") |
| `0x004` | `VERSION` | RO | Semantic version of the register interface |
| `0x008` | `CFG0` | RO | Elaborated fixed-point format |
| `0x00C` | `CFG1` | RO | Elaborated microarchitecture and timing |
| `0x010` | `CTRL` | RW | Control. Bits 0 to 4 are write-1-to-trigger and read 0 |
| `0x014` | `STATUS` | RO | Live and sticky status |
| `0x018` | `IRQ` | W1C | Interrupt status, write 1 to clear |
| `0x020` | `OP_X` | RW | Operand X in the working fixed-point format |
| `0x024` | `OP_Y` | RW | Operand Y in the working fixed-point format |
| `0x028` | `OP_Z` | RW | Operand Z in the working fixed-point format |
| `0x02C` | `CMD` | RW | Function select and issue trigger |
| `0x030` | `RES_X` | RO | Result X at the head of the output FIFO |
| `0x034` | `RES_Y` | RO | Result Y at the head of the output FIFO |
| `0x038` | `RES_Z` | RO | Result Z at the head of the output FIFO |
| `0x03C` | `RES_FLAGS` | RO | Per-result flags at the head of the output FIFO |
| `0x040` | `K_CIRC` | RO | Circular CORDIC gain K, working format |
| `0x044` | `IK_CIRC` | RO | Reciprocal circular gain 1/K, working format |
| `0x048` | `K_HYP` | RO | Hyperbolic CORDIC gain Kh, working format |
| `0x04C` | `IK_HYP` | RO | Reciprocal hyperbolic gain 1/Kh, working format |
| `0x050` | `LIM_CIRC` | RO | Circular convergence radius, working format |
| `0x054` | `LIM_HYP` | RO | Hyperbolic convergence radius, working format |
| `0x058` | `LIM_LIN` | RO | Linear convergence radius, working format |
| `0x05C` | `TANH_LIM_HYP` | RO | Largest \|Y/X\| the hyperbolic vectoring mode resolves |
| `0x060` | `SCRATCH` | RW | Read-write scratch word, no hardware effect |
| `0x064` .. `0xFFC` | unmapped | - | Reads return `0xBADACCE5` with `r.err`, writes take `r.err` |

### Bit fields

#### `VERSION` at `0x004` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `31:24` | `MAJOR` | RO | Major version |
| `23:16` | `MINOR` | RO | Minor version |
| `15:8` | `PATCH` | RO | Patch version |
| others | reserved | RO | Read 0, writes ignored |

#### `CFG0` at `0x008` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `31:28` | `GUARD_FRAC` | RO | Fractional guard bits of the internal datapath |
| `27:24` | `GUARD_INT` | RO | Integer guard bits of the internal datapath |
| `23:16` | `NUM_STAGES` | RO | CORDIC micro-rotations per operation |
| `15:8` | `FRAC_BITS` | RO | Fractional bits of the fixed-point word |
| `7:0` | `DATA_WIDTH` | RO | Fixed-point word width in bits |

#### `CFG1` at `0x00C` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `27:20` | `INTERVAL` | RO | Minimum cycles between accepted operations |
| `19:12` | `LATENCY` | RO | Issue-to-result latency in clock cycles |
| `11:8` | `OUT_DEPTH` | RO | Output FIFO depth in entries |
| `7:4` | `IN_DEPTH` | RO | Input FIFO depth in entries |
| `1` | `USE_RREADY` | RO | 1 if the OBI R channel implements rready |
| `0` | `VARIANT` | RO | 0 = fully pipelined, 1 = iterative |
| others | reserved | RO | Read 0, writes ignored |

#### `CTRL` at `0x010` (RW)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `9` | `IRQ_EN_ERR` | RW | Route IRQ.ERR to the interrupt output |
| `8` | `IRQ_EN_DONE` | RW | Route IRQ.DONE to the interrupt output |
| `4` | `CLR_ERR` | W1S | Clear the sticky STATUS.ERR_* bits |
| `3` | `FLUSH_OUT` | W1S | Drop every completed but unread result |
| `2` | `FLUSH_IN` | W1S | Drop every queued but unstarted operation |
| `1` | `POP` | W1S | Discard the result at the head of the output FIFO |
| `0` | `SOFT_RST` | W1S | Abort every operation in flight, flush both FIFOs, clear the sticky errors and the IRQ state. Operand, CMD and SCRATCH registers are left alone |
| others | reserved | RO | Read 0, writes ignored |

#### `STATUS` at `0x014` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `19` | `ERR_ACCESS` | RO | Sticky: an unmapped, unaligned or illegal access occurred |
| `18` | `ERR_UNDERFLOW` | RO | Sticky: a result was read or popped while empty |
| `17` | `ERR_OVERFLOW` | RO | Sticky: an issue was dropped, input FIFO was full |
| `16` | `ERR_DOMAIN` | RO | Sticky: an operand was outside the convergence domain |
| `15:12` | `OUT_COUNT` | RO | Results waiting in the output FIFO |
| `11:8` | `IN_COUNT` | RO | Operations queued in the input FIFO |
| `5` | `OUT_EMPTY` | RO | Output FIFO holds no result |
| `4` | `OUT_FULL` | RO | Output FIFO cannot accept another result |
| `3` | `IN_EMPTY` | RO | Input FIFO holds no operation |
| `2` | `IN_FULL` | RO | Input FIFO cannot accept another operation |
| `1` | `RES_VALID` | RO | At least one result is readable |
| `0` | `BUSY` | RO | Operations are queued or in flight |
| others | reserved | RO | Read 0, writes ignored |

#### `IRQ` at `0x018` (W1C)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `1` | `ERR` | W1C | One of the sticky STATUS.ERR_* bits was set |
| `0` | `DONE` | W1C | A result was pushed into the output FIFO |
| others | reserved | RO | Read 0, writes ignored |

#### `CMD` at `0x02C` (RW)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `31` | `GO` | W1S | Queue an operation from OP_X, OP_Y, OP_Z and FUNC |
| `15:8` | `TAG` | RW | Free-form tag returned in RES_FLAGS.TAG |
| `4:0` | `FUNC` | RW | Function code, see the function table |
| others | reserved | RO | Read 0, writes ignored |

#### `RES_FLAGS` at `0x03C` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `23:16` | `TAG` | RO | Tag supplied in CMD.TAG |
| `12:8` | `FUNC` | RO | Function code of this result |
| `3` | `SAT_Z` | RO | Result Z saturated to the format limit |
| `2` | `SAT_Y` | RO | Result Y saturated to the format limit |
| `1` | `SAT_X` | RO | Result X saturated to the format limit |
| `0` | `DOMAIN_ERR` | RO | Operand outside the convergence domain, X/Y/Z forced to 0 |
| others | reserved | RO | Read 0, writes ignored |


The map is defined once, in `scripts/cordic_regmap.py`, and generated into the RTL
offsets, the C driver header, [docs/REGISTERS.md](docs/REGISTERS.md) and the figure
above. Hardware, driver, tests and documentation cannot disagree, and `make check-gen`
fails if any of them is stale.

### OBI

Targets **OBI v1.6** (`pulp-platform/obi`, `doc/OBI-v1.6.0.pdf`) as Croc configures
it in `croc_pkg::SbrObiCfg`: 32-bit address and data, `IdWidth` 3, `BeFull = 1`,
`Integrity = 0`, `CombGnt = 0`, `UseRReady = 0`, no optional channel fields.

Signals implemented: `req`, `gnt`, `addr`, `we`, `be`, `wdata`, `aid` on the A
channel; `rvalid`, `rdata`, `rid`, `err` on the R channel.

Rules honoured, and asserted continuously by the testbench manager while every test
runs:

- a request is accepted only on `req && gnt`, and `wdata`, `be`, `we` and `aid` are
  sampled then and nowhere else, so a manager may change them freely afterwards
- exactly one R beat per accepted A beat, in order, with `rid` echoing `aid`
- at most one transaction outstanding, so ordering is structural
- with `UseRReady = 0`, `gnt` never depends on a response being consumed, so a
  manager that ignores `rready` cannot deadlock the bus

`UseRReady` is a parameter and both settings are tested. At 1 the response waits for
`rready`, which is the only configuration in which `gnt` has to fall; measured held
unchanged for 12 cycles with `gnt` low throughout, then recovering.

Error responses, each also latching `STATUS.ERR_ACCESS`: an unaligned address, an
offset above `0x063`, and a write to any of the 17 read-only registers.

## The two microarchitectures

`Variant` selects one. Both instantiate the same `cordic_stage` over the same shift
and angle sequence, so results are **bit-identical**, asserted over 900 operations by
recording both runs and diffing the files word for word.

| | Pipelined (`Variant = 0`) | Iterative (`Variant = 1`) |
|---|---|---|
| Structure | N register banks, shifts are wiring | one stage reused, barrel shifter in the loop |
| Cells, Q3.29 N=28 | 55,096 | 11,101 |
| Flip-flops | 4,921 | 1,229 |
| Logic depth | 67 gates | 59 gates |
| Retire interval | **1 cycle** | 29 cycles |
| Latency, end to end | 30 cycles | 31 cycles |

![Area comparison](docs/img/area_comparison.png)

The revealing number is logic depth: folding gives back 5x the area but only 12
percent of the depth, because the iterative core's barrel shifter and angle mux sit
inside the loop where the pipelined core has hardwired shifts. Folding buys area, not
clock frequency.

Flow control in the pipelined core is one global enable, not per-stage skid buffers:

```systemverilog
assign pipe_en = !(vq[NumStages-1] && !ready_i);
```

The pipeline freezes as a whole when the tail holds a result the consumer will not
take. One high-fanout net instead of a ready chain through 28 stages, and nothing is
dropped, which `test_backpressure_loses_nothing` asserts under a consumer that takes
three results then stalls for seven cycles.

Measured occupancy, cell by cell from `dbg_stage_valid_o` during simulation:

![Pipeline timing](docs/img/pipeline_timing.svg)

## Streaming

A register-mapped issue costs four writes and five reads. **Measured: 57 cycles per
operation.** The pipelined core retires one per cycle, so nothing reachable over a
register interface can keep it fed, whatever the pipeline does.

Hence a valid/ready streaming port in each direction, for a DMA engine or another
accelerator in the user domain:

| Path | Cycles per operation | Speedup |
|---|---:|---:|
| Registers, pipelined core | 57.0 | |
| Streaming, pipelined core | **1.94** | 29.4x |
| Registers, iterative core | 60.0 | |
| Streaming, iterative core | 29.09 | 2.1x |

![Throughput and latency](docs/img/throughput_latency.png)

The pipelined core sustained a **retire interval of exactly 1 cycle** over 219
consecutive steady-state results, mean 1.000, worst case 1. An 8-bit `tag` travels
with each operation and comes back in `RES_FLAGS.TAG`. Both paths share the input
FIFO: a register issue wins a tie and the streaming port sees `ready` low for that
cycle. `CTRL.POP` likewise wins over the streaming output, so a result is never
handed to two consumers.

## Synthesis

Yosys 0.33, technology-independent mapping (`abc -g cmos4`). Reports are committed
under [docs/synth/](docs/synth/) and CI fails if they differ from a fresh run.

| Configuration | Cells | Flip-flops | Combinational | Logic depth |
|---|---:|---:|---:|---:|
| pipelined, Q3.29, 28 stages | 55,096 | 4,921 | 50,175 | 67 |
| iterative, Q3.29, 28 stages | 11,101 | 1,229 | 9,872 | 59 |
| pipelined, Q3.29, 16 stages | 35,217 | 3,277 | 31,940 | 65 |
| iterative, Q3.29, 16 stages | 10,510 | 1,229 | 9,281 | 53 |
| pipelined, Q3.13, 15 stages | 18,670 | 1,988 | 16,682 | 46 |
| iterative, Q3.13, 15 stages | 5,879 | 748 | 5,131 | 39 |

Asserted inside the Yosys script itself, so a regression fails the run rather than
appearing in a report nobody reads:

- **no inferred latches** anywhere: `$dlatch`, `$_DLATCH_*`, `$sr` and `$_SR_*` all
  asserted empty, before and after technology mapping
- **no blackboxes**: `hierarchy -check` plus a check that every remaining cell is a
  Yosys primitive
- `check -assert`: no combinational loop, no multiply-driven wire, no undriven wire
- no unmapped memory, no tristate

These are gate equivalents, not IHP 130nm areas. They are directly comparable
between configurations because every one goes through the same script; they are not a
substitute for Croc's OpenROAD flow with the real library, and no timing closure is
claimed.

## Software

A freestanding baremetal driver: no libc, no floating point, no allocation. Croc's
CVE2 has no FPU, so a float in a driver would pull in soft-float routines costing more
than the accelerator saves.

```c
#include "cordic.h"

cordic_t dev;
cordic_init(&dev, 0x20001000u);           /* probes ID, caches CFG and the gains */

cordic_fx_t s, c;
cordic_sin_cos(&dev, cordic_fx_from_ratio(&dev, 1, 2), &s, &c);   /* z = 0.5 */

cordic_fx_t q;
if (cordic_div(&dev, num, den, &q) == CORDIC_ERR_DOMAIN) {
  /* den was zero or the quotient exceeded LIM_LIN */
}
```

Three call styles plus a named wrapper per function:

- `cordic_submit` / `cordic_poll`, non-blocking; queue work and come back for it
- `cordic_exec`, blocking, one operation
- `cordic_exec_batch`, blocking, keeps the input queue as full as it will go

`cordic_hypot` and `cordic_rotate` divide the gain out for you; call `cordic_exec`
with the raw function code to keep the scaled value.

Verified by building the identical source two ways. `make sw` compiles it against a
register-accurate peripheral model and runs it: **626 checks, 0 failures**, covering
register sequencing, non-destructive reads followed by `POP`, flag decoding, gain
compensation, queue-full back-off, batching, underflow, domain errors and the
interrupt path. The model answers out of vectors generated from the same bit-accurate
model the RTL is asserted against, rather than from a second CORDIC written in C.

`make sw` also links a complete RV32IMC image, 7,428 bytes of text, which fits stock
Croc's 8 KB SRAM with a 512-byte stack. **It is not executed:** this repository has no
Croc simulation. It records its outcome at the `cordic_test_report` symbol and returns
the failure count in `a0` so Croc's own testbench can read the result out of memory.
`sw/README.md` has the details.

That host test earned its keep immediately: it found that writing `CTRL` as a whole
word to fire `POP` also cleared the interrupt enables, since they share the register.
`CTRL` now keeps its triggers in byte 0 and its enables in byte 1 and the driver uses
byte stores, which is what the byte-enable support in `cordic_obi_regs` is for.

## Simulating and testing

```sh
make venv        # .venv plus requirements
make lint        # Verilator -Wall, 10 configurations plus the Croc wrapper
make test        # the whole suite, both variants, both OBI handshakes
make synth       # Yosys over 6 configurations
make sw          # host driver test (runs) and RV32 image (links)
make images      # redraw every figure from the measured data
make all         # all of the above
```

| Target | What it establishes |
|---|---|
| `test-accuracy` | 17,536 comparisons against double precision, plus bit-exact against the model |
| `test-domain` | 4,200 in-domain arguments never rejected; every out-of-domain one rejected with zeroed outputs; the ambiguous band measured |
| `test-obi` | 14 tests in each handshake configuration, 28 total |
| `test-throughput` | Retire interval asserted against what `CFG1` advertises, per-stage occupancy checked cell by cell |
| `test-equivalence` | Both cores' results diffed word for word |
| `test-reset` | Reset with a full pipeline, busy, sticky done, queueing, overflow, interrupts |

Alongside those, **13 concurrent assertions** live in the RTL and are evaluated in
every simulation through Verilator's `--assert`: the OBI rules in
`cordic_obi_regs.sv`, the FIFO invariants in `cordic_fifo.sv`, and two properties in
`cordic_core_pipe.sv` aimed at the global-enable scheme, since its whole claim is
that a stalled consumer costs throughput and nothing else. Asserting them inside the
RTL means they hold in Croc's own testbench too, without that testbench having to
know the rules.

**Simulator, stated plainly: Verilator only.** Icarus Verilog 12 cannot build this
design, aborting with an internal assertion (`netmisc.cc:1821`) when a constant
function indexes a packed 2D localparam, and separately folding `$atan` in a constant
function to zero without complaining. Verilator 5.020 is what is installed here and
cocotb 2.0 needs 5.036, so `requirements.txt` pins cocotb 1.9.2; `tb/cordic_tb.py`
carries two shims so the suite runs unchanged on either cocotb generation.

Waveforms: `make -C tb WAVES=1 MODULE=test_smoke`.

## Repository layout

```
rtl/                       9 modules plus 4 include files, no external dependencies
  cordic_stage.sv          the only copy of the arithmetic
  cordic_core_pipe.sv      fully pipelined
  cordic_core_iter.sv      iterative, shares cordic_stage
  cordic_pre.sv            function decode, the pi fold, rotation-mode radius checks
  cordic_post.sv           residual convergence check, rounding, saturation
  cordic_unit.sv           pre + core + post
  cordic_fifo.sv           local, so the repository stands alone
  cordic_obi_regs.sv       OBI v1.6 subordinate
  cordic_accel.sv          top level
  cordic_rom.svh           generated constant tables
  cordic_regmap.svh        generated offsets
integration/croc/          drop-in wrapper, example user_pkg and user_domain,
                           Bender fragment, and stand-in Croc packages for lint
tb/                        cocotb suite, the bit-accurate model, the error bounds
sw/                        driver, self-test, host peripheral model, RV32 build
scripts/                   constant and register-map generators, synthesis, figures
docs/                      DESIGN.md, CROC_INTEGRATION.md, REGISTERS.md, img/, synth/
```

Everything generated is committed and `make check-gen` fails if any of it is stale,
so a clone needs no generator run to build.

## What this does not claim

- **The RV32 image is never executed here.** It compiles and links; running it needs
  Croc's own testbench.
- **Synthesis is technology-independent.** Gate-equivalent counts, comparable between
  configurations, not IHP 130nm areas. No timing closure is claimed.
- **Icarus Verilog does not work.** Not a limitation of the tool's SystemVerilog
  coverage in general, but two specific defects documented in
  [docs/DESIGN.md](docs/DESIGN.md).
- **The vectoring-mode angle bounds are conditional on magnitude.** The LSB figures
  in the accuracy table hold for input magnitudes of at least 1/16. Below that an
  angle genuinely does not exist in the format, and the derived bound, which is
  asserted on every argument, says so quantitatively.

## Licence

Apache-2.0, copyright 2026 Daniel Tyukov. See [LICENSE](LICENSE).

The example `user_pkg.sv` and `user_domain.sv` under `integration/croc/` reproduce
scaffolding from `pulp-platform/croc`, which is Solderpad SHL-0.51; only the
CORDIC-specific parts of those two files are covered by this repository's licence.
`integration/croc/lint/obi_pkg.sv` and `croc_pkg.sv` reproduce field lists from the
same source for the purpose of linting the integration wrapper.
