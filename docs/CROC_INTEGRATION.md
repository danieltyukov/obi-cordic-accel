# Dropping this into Croc's user domain

Step by step, for [pulp-platform/croc](https://github.com/pulp-platform/croc). Every
file you need is under `integration/croc/`, and the two `.example` files are complete
and compile, so you can diff them against your own rather than reading prose and
guessing.

Verified against Croc as of the 2026 (`PulpJtagIdCode.version = 4'h1`) generation:
`croc_pkg::SbrObiCfg` with a 32-bit address and data word, `IdWidth` grown to 3 by
`mux_grow_cfg` over the four crossbar managers, `BeFull = 1`, `Integrity = 0`,
`UseRReady = 0`, `CombGnt = 0` and no optional channel fields.

## Contents

- [What you are adding](#what-you-are-adding)
- [1. Copy the RTL](#1-copy-the-rtl)
- [2. Address map](#2-address-map)
- [3. Wire it into user_domain.sv](#3-wire-it-into-user_domainsv)
- [4. Bender](#4-bender)
- [5. Software](#5-software)
- [6. Check it](#6-check-it)
- [Choosing the parameters](#choosing-the-parameters)
- [Using the streaming port](#using-the-streaming-port)
- [Things that will bite you](#things-that-will-bite-you)

## What you are adding

One OBI subordinate occupying a single 4 KB window, plus one interrupt line. It has
no manager port and touches nothing else in the SoC.

```
croc_domain obi_xbar (XbarUser)
  -> user_domain.sv  (addr_decode + obi_demux)
       -> cordic_obi_wrap.sv   struct types to flat OBI, wiring only
            -> cordic_accel.sv  registers, FIFOs, pre, core, post
       -> irq_o -> interrupts_o[0]
```

`cordic_accel` takes flat OBI signals rather than Croc's structs, which is what
keeps it drivable straight from cocotb. `cordic_obi_wrap.sv` is the only place the
two meet: no logic, no registers, so it costs no cycles.

## 1. Copy the RTL

Ten files into a new `rtl/cordic/` in your Croc checkout:

```sh
CROC=/path/to/croc
mkdir -p "$CROC/rtl/cordic"
cp rtl/cordic_rom.svh          "$CROC/rtl/cordic/"   # generated, commit it
cp rtl/cordic_regmap.svh       "$CROC/rtl/cordic/"   # generated, commit it
cp rtl/cordic_defs.svh         "$CROC/rtl/cordic/"
cp rtl/cordic_rom_fx.svh       "$CROC/rtl/cordic/"
cp rtl/cordic_stage.sv         "$CROC/rtl/cordic/"
cp rtl/cordic_core_pipe.sv     "$CROC/rtl/cordic/"
cp rtl/cordic_core_iter.sv     "$CROC/rtl/cordic/"
cp rtl/cordic_pre.sv           "$CROC/rtl/cordic/"
cp rtl/cordic_post.sv          "$CROC/rtl/cordic/"
cp rtl/cordic_unit.sv          "$CROC/rtl/cordic/"
cp rtl/cordic_fifo.sv          "$CROC/rtl/cordic/"
cp rtl/cordic_obi_regs.sv      "$CROC/rtl/cordic/"
cp rtl/cordic_accel.sv         "$CROC/rtl/cordic/"
cp integration/croc/cordic_obi_wrap.sv "$CROC/rtl/cordic/"
```

Four of those are `.svh` includes pulled in from **inside** module bodies, so
`rtl/cordic` has to be on the include search path. Section 4 covers that.

No dependency on `common_cells`, `obi` or anything else is added: `cordic_fifo.sv`
is local precisely so the accelerator stands alone. Croc already carries
`common_cells`, so swap in `fifo_v3` if you would rather; the handshake is the same.

## 2. Address map

Croc's convention is one 4 KB-aligned window per user subordinate, and this
peripheral decodes `addr[11:0]` only, so **any** 4 KB-aligned base works with no
reparameterisation.

In `rtl/user_pkg.sv`, add the enum entry and the rule
(`integration/croc/user_pkg.sv.example` is the whole file):

```systemverilog
typedef enum bit [4:0] {
  UserError  = 0,
  UserRom    = 1,
  UserCordic = 2          // <- added
} user_demux_outputs_e;

localparam croc_pkg::addr_map_rule_t [1:0] UserAddrMap = '{
  '{ idx: UserRom,
     start_addr: croc_pkg::UserBaseAddr,
     end_addr:   croc_pkg::UserBaseAddr + 32'h0000_1000 },
  '{ idx: UserCordic,                                     // <- added
     start_addr: croc_pkg::UserBaseAddr + 32'h0000_1000,
     end_addr:   croc_pkg::UserBaseAddr + 32'h0000_2000 }
};
```

`NumDemuxSbr` is `$size(UserAddrMap) + 1` and needs no change.

With Croc's default `CrocAddrMap`, `UserBaseAddr` is `0x2000_0000`, so the
accelerator lands at:

| | Address |
|---|---|
| Base | `0x2000_1000` |
| Implemented registers | `0x2000_1000` to `0x2000_1063` |
| Unmapped, answers with `r.err` | `0x2000_1064` to `0x2000_1FFF` |

That base is what `sw/test_cordic.c` defaults `CORDIC_BASE` to. The window size is
`CordicWindowBytes` in `rtl/cordic_regmap.svh`, generated from the same definition,
so the two cannot disagree.

## 3. Wire it into `user_domain.sv`

`integration/croc/user_domain.sv.example` is a complete, compiling file. Three
additions to your own:

**The demux fanout**, next to your existing subordinates:

```systemverilog
sbr_obi_req_t user_cordic_obi_req;
sbr_obi_rsp_t user_cordic_obi_rsp;

assign user_cordic_obi_req              = all_user_sbr_obi_req[UserCordic];
assign all_user_sbr_obi_rsp[UserCordic] = user_cordic_obi_rsp;
```

**The instance:**

```systemverilog
logic cordic_irq;

cordic_obi_wrap #(
  .ObiCfg       ( SbrObiCfg     ),
  .obi_req_t    ( sbr_obi_req_t ),
  .obi_rsp_t    ( sbr_obi_rsp_t ),
  .DataWidth    ( 32            ),   // Q3.29
  .FracBits     ( 29            ),
  .NumStages    ( 28            ),
  .Variant      ( 0             ),   // 0 pipelined, 1 iterative
  .GuardInt     ( 2             ),
  .GuardFrac    ( 4             ),
  .InDepth      ( 4             ),
  .OutDepth     ( 4             ),
  .EnableStream ( 1'b0          )
) i_user_cordic (
  .clk_i,
  .rst_ni,
  .obi_req_i ( user_cordic_obi_req ),
  .obi_rsp_o ( user_cordic_obi_rsp ),
  .irq_o     ( cordic_irq          ),

  .str_in_valid_i  ( 1'b0 ),
  .str_in_ready_o  (),
  .str_in_func_i   ( 5'd0 ),
  .str_in_tag_i    ( 8'd0 ),
  .str_in_x_i      ( '0 ),
  .str_in_y_i      ( '0 ),
  .str_in_z_i      ( '0 ),
  .str_out_valid_o (),
  .str_out_ready_i ( 1'b0 ),
  .str_out_x_o     (),
  .str_out_y_o     (),
  .str_out_z_o     (),
  .str_out_flags_o (),
  .str_out_func_o  (),
  .str_out_tag_o   ()
);
```

The streaming ports stay in the port list whether or not `EnableStream` is set, so
turning it on later does not change this wiring.

**The interrupt.** `user_domain` drives `interrupts_o[NumExternalIrqs-1:0]`:

```systemverilog
assign interrupts_o[NumExternalIrqs-1:1] = '0;
assign interrupts_o[0]                   = cordic_irq;
```

`irq_o` is level-sensitive and gated by `CTRL.IRQ_EN_DONE` and `CTRL.IRQ_EN_ERR`,
both of which reset to zero, so the line stays low until software opts in. It drops
when the handler writes 1 to the corresponding `IRQ` bit. Croc routes
`interrupts_o` to CVE2's fast interrupt inputs; check `croc_domain.sv` for which
`mie` bit that ends up being on your generation.

## 4. Bender

`integration/croc/Bender.yml.fragment` has the exact text. Two edits to Croc's
top-level `Bender.yml`.

**Export the include directory**, so the four `.svh` files resolve:

```yaml
export_include_dirs:
  - rtl/cordic
```

**Add the sources** to the target that builds the RTL, after `croc_pkg.sv` and
`user_pkg.sv` and before `user_domain.sv`. The order matters: `cordic_stage.sv` is
instantiated by both cores, and `cordic_obi_wrap.sv` needs `obi_pkg` and `croc_pkg`.

```yaml
- target: rtl
  files:
    - rtl/cordic/cordic_stage.sv
    - rtl/cordic/cordic_core_pipe.sv
    - rtl/cordic/cordic_core_iter.sv
    - rtl/cordic/cordic_pre.sv
    - rtl/cordic/cordic_post.sv
    - rtl/cordic/cordic_unit.sv
    - rtl/cordic/cordic_fifo.sv
    - rtl/cordic/cordic_obi_regs.sv
    - rtl/cordic/cordic_accel.sv
    - rtl/cordic/cordic_obi_wrap.sv
    - rtl/user_domain.sv
```

Then `bender update` and Croc's own `make` targets pick it up.

For a flow that wants a plain file list instead, `integration/croc/sources.txt` is
the same order without the YAML.

## 5. Software

Two files:

```sh
cp sw/include/cordic.h        "$CROC/sw/include/"
cp sw/include/cordic_regmap.h "$CROC/sw/include/"   # generated, commit it
cp sw/cordic.c                "$CROC/sw/src/"
```

Add `cordic.c` to Croc's `sw` build and set the base address:

```c
#include "cordic.h"

int main(void) {
  cordic_t dev;
  if (cordic_init(&dev, 0x20001000u) != CORDIC_OK) {
    return 1;                       // ID register did not read "CORD"
  }

  cordic_fx_t s, c;
  cordic_sin_cos(&dev, cordic_fx_from_ratio(&dev, 1, 2), &s, &c);   // z = 0.5
  // c is cos(0.5) and s is sin(0.5), both in Q3.29
  return 0;
}
```

No libc, no floating point, no allocation: Croc's CVE2 has no FPU, so a float in a
driver would pull in soft-float routines costing more than the accelerator saves.
`libgcc` is needed for `__divdi3`, which the fixed-point ratio helpers use for a
64-bit intermediate.

`sw/test_cordic.c` is a ready self-test. Build it for the target with `make -C sw
rv32` here, or drop it into Croc's `sw` tree. It records its outcome at the
`cordic_test_report` symbol (magic `0x54455354`, then the check and failure counts
and the first failure's details) and returns the failure count in `a0`, so a
testbench can read the result straight out of memory. Define `CORDIC_TEST_PUTC(c)`
to route its log to Croc's UART.

Watch the size: stock Croc has 8 KB of SRAM (`croc_pkg.sv`: `NumSramBanks = 2`,
`SramBankNumWords = 1024`) and the self-test's vector table lives in `.rodata`. The
default build keeps 12 of 79 vectors to fit. `sw/README.md` has the measured table.

## 6. Check it

Before touching Croc, the wrapper is lint-clean here against stand-in Croc packages:

```sh
make lint          # includes lint-wrap, both variants, zero warnings at -Wall
```

`integration/croc/lint/obi_pkg.sv` and `croc_pkg.sv` reproduce the field lists from
Croc's own packages, field for field and in order, so a struct assignment behaves
identically. **They are for linting only.** Never compile them into a Croc build:
Croc brings its own and two definitions of `obi_pkg` would collide.

In Croc, the first thing to check from software is the identification register:

```c
/* 0x2000_1000 must read 0x434F5244, which is "CORD". */
```

If it reads `0xBADCAB1E` the demux sent you to Croc's error subordinate, so the
address rule is wrong or missing. If it reads `0xBADACCE5` you reached the
accelerator but at an unmapped offset inside its window.

Then `CFG0` and `CFG1` report the elaborated format, variant, latency and issue
interval, so software can confirm it is talking to the hardware it was built for
rather than assume.

## Choosing the parameters

| | `Variant = 0`, pipelined | `Variant = 1`, iterative |
|---|---:|---:|
| Cells, Q3.29 N=28 | 55,096 | 11,101 |
| Flip-flops | 4,921 | 1,229 |
| Logic depth | 67 | 59 |
| Result every | 1 cycle | 29 cycles |
| Latency | 30 cycles | 31 cycles |

For a CVE2-only Croc, **take the iterative core**. The register interface needs 57
cycles per operation, so the pipelined core's one-per-cycle retire rate is
unreachable and you would be paying five times the area for nothing. The results are
bit-identical either way, which `tb/test_equivalence.py` asserts over 900
operations, so this is purely an area-versus-throughput decision with no accuracy
consequence.

The pipelined core earns its area only with the streaming port fed by something that
can sustain it.

Smaller again: `DataWidth = 16`, `FracBits = 13`, `NumStages = 15` gives Q3.13 at
5,879 cells iterative or 18,670 pipelined, with about 13 bits of accuracy instead of
29. `NumStages` must be 5, or 15 or more, or the hyperbolic repeat sequence is
truncated and elaboration fails with an explanation; see `docs/DESIGN.md`.

## Using the streaming port

Set `EnableStream = 1'b1` and wire the ports to whatever can keep up. It is a plain
valid/ready pair in each direction:

```systemverilog
// in:  func[4:0], tag[7:0], x, y, z    accepted when valid && ready
// out: x, y, z, flags[3:0], func[4:0], tag[7:0]
```

`tag` is carried through untouched and returned in `RES_FLAGS.TAG`, which is how you
correlate results without depending on ordering, though ordering is in fact
preserved. Both paths share the input FIFO: a register issue wins a tie and the
streaming port simply sees `ready` low that cycle. Likewise `CTRL.POP` wins over the
streaming output, so a result is never handed to two consumers.

Croc has no DMA enabled by default (`croc_pkg::iDMAEnable = 1'b0`). Turn iDMA on, or
feed the port from your own logic in the user domain.

## Things that will bite you

**`CTRL` must be written a byte at a time.** The write-1-to-trigger bits are in
byte 0 and the persistent interrupt enables in byte 1. A full-word write to fire
`CTRL.POP` clears the interrupt enables as a side effect. The driver uses byte
stores for exactly this reason, and the host test is what caught it. CVE2 emits `sb`
with the matching `be` and `cordic_obi_regs` honours it.

**`CMD.GO` needs byte 3.** It sits at bit 31, so a partial write that leaves byte 3
out updates `FUNC` and `TAG` without issuing anything. That is deliberate and lets
you set up a function once and then issue repeatedly, but it means a `sh` to `CMD`
will silently not start an operation.

**Issuing while busy queues, it does not fail.** An operation goes into the input
FIFO. Only a write into a genuinely full FIFO is dropped, and that latches
`STATUS.ERR_OVERFLOW`. Check `STATUS.IN_FULL` first, which is what
`cordic_submit()` does before it writes anything.

**Result reads do not consume.** `RES_X`, `RES_Y`, `RES_Z` and `RES_FLAGS` all read
the head of the output FIFO non-destructively; `CTRL.POP` is what discards it.
Reading them while the queue is empty returns zero and latches
`STATUS.ERR_UNDERFLOW`.

**A domain error returns zeros, not garbage.** `RES_FLAGS.DOMAIN_ERR` set means X, Y
and Z are all zero. Check the flag; do not check for a plausible-looking result.

**`CTRL.SOFT_RST` aborts operations in flight.** As well as flushing both FIFOs and
clearing the sticky errors and interrupt state. It leaves the operand, `CMD` and
`SCRATCH` registers alone. `FLUSH_IN` and `FLUSH_OUT` touch only their own queue and
do not disturb the core.

**Croc's `UseRReady` is 0.** The wrapper ties `rready` high and passes
`UseRReady = 0` to `cordic_accel`, which means `gnt` stays high for ever and a
request is accepted every cycle. If you reconfigure Croc for `UseRReady = 1`, change
the parameter and connect `obi_req_i.rready`; the wrapper's elaboration check will
tell you if you forget. Both configurations are covered by `tb/test_obi.py`.
