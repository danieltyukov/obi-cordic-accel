# Place and route

Full RTL-to-GDS through [LibreLane](https://github.com/librelane/librelane) on the
real IHP SG13G2 130nm PDK, the process Croc taped out in.

`make pnr` runs it. `scripts/run_pnr.py` writes a config per variant, runs the flow,
collects `final/metrics.json`, and renders the layout with KLayout.

## Why this exists alongside `make pdk`

`make pdk` stops after synthesis and drive-strength repair, so its wire parasitics
are estimated rather than extracted. That is enough for a fair comparison between the
two variants, and it is what the headline area and Fmax numbers come from.

Place and route adds the two things synthesis cannot tell you:

- **The synthesis-to-route area inflation, per variant.** Cells occupy less than the
  die they end up needing. The deeply pipelined variant has four times the registers
  and far more wiring than the folded one, so the two do not inflate by the same
  factor. A synthesis-only comparison systematically flatters the pipelined design,
  and measuring the delta is what corrects for that.
- **DRC and LVS signoff, and a real layout.** The accelerator is meant to be dropped
  into a real chip, so a routed, DRC-clean layout of it is the honest end of the
  claim rather than a promise.

## Timing from this flow

Timing numbers quoted in the README come from `make pdk`, not from here, and
deliberately so: LibreLane warns that it is using a generic fallback SDC unless one
is supplied, and timing from constraints you did not write is not a claim worth
making. `scripts/run_pnr.py` supplies `pnr/cordic.sdc` explicitly, so the fallback
warning should not appear; if it does, treat that run's timing as unreliable and use
the `make pdk` numbers.

## Result: the folded variant, Q3.29, 28 stages

Real numbers from the flow, at a 22 ns target and 40 percent core utilisation.
`docs/pnr/summary.json` carries the full metric set.

| | Value | Against synthesis |
|---|---:|---:|
| Synthesis cell area (`make pdk`) | 135,442 um2 | |
| Post-route standard-cell area | 179,027 um2 | **1.32x** |
| Post-route die area | 383,154 um2 | **2.83x** |
| Core utilisation | 0.501 | |
| Standard cells placed | 10,835 | 8,390 mapped |
| Fill cells | 19,179 | |
| Routed wirelength | 418,654 um | |
| Fmax at typ, synthesis estimate | 75.2 MHz | |
| Fmax at typ, post-route | **67.7 MHz** | **0.90x** |
| Setup worst slack at typ, 22 ns | +7.23 ns | |
| Hold worst slack at typ | +0.231 ns | |
| Router DRC errors | **0** | after 5 iterations, 3767 to 0 |
| Magic DRC errors | **0** | |
| Antenna violating nets | 6 | |
| Power at typ, 22 ns | 17.2 mW | |

Two things worth taking from that.

**Post-route timing is 10 percent worse than the synthesis estimate.** 67.7 MHz
against 75.2, because extracted parasitics replace the `set_wire_rc` estimate. That is
the honest size of the gap between what `make pdk` reports and what a routed design
does, and it applies to every Fmax number in this repository. The direction is the one
you would expect and the magnitude is modest, which is what makes the `make pdk`
numbers usable for comparison even though they are not signoff.

**The standard-cell area grows 1.32x from synthesis to route**, before any die
overhead. That is timing repair and clock tree: 1,311 timing-repair buffers and 476
clock buffers and inverters were inserted, none of which exist in the mapped netlist
the synthesis area is measured from. The die is 2.83x the mapped cell area once
utilisation is accounted for.

Because that inflation comes from buffering, it should hit the pipelined variant
harder: it has four times the registers, so four times the clock tree. That
measurement is not in yet, and the honest statement is that the 4.5x synthesis area
ratio between the variants is therefore a **lower bound** on the post-route ratio, not
an estimate of it.

## Two things that cost time, recorded so they do not cost it twice

**Hold repair explodes if setup uncertainty is applied to hold.** The first attempt
died at stage 37 with `[RSZ-0060] Max buffer count reached` during post-CTS hold
repair. The cause was in the SDC, not the design: `set_clock_uncertainty` without
`-setup` applies to both checks, so every short register-to-register path in a design
that has thousands of them needed padding by 5 percent of the period. Splitting it
into `-setup` at 5 percent of the period and `-hold` at a fixed 50 ps, and giving the
IO ports a `-min` input and output delay so they are not treated as arriving at time
zero, fixes it: the same design then reports no setup and no hold violations after
CTS.

**LibreLane will not read outside the config's own directory.** `dir::../../rtl/...`
is rejected with a `PermissionError`, so `scripts/run_pnr.py` stages a copy of the RTL
next to the config it writes. That also pins exactly which sources a run used.

**Magic DRC is the long pole**, well over ten minutes on the folded variant at 0.135
mm2. That is normal for a full-hierarchy DRC on this process and not a sign of
trouble; the KLayout DRC in the same flow is much quicker.

## Parameters through a wrapper, not chparam

LibreLane drives Yosys without exposing `chparam`, so `scripts/run_pnr.py` generates a
thin wrapper per configuration that instantiates `cordic_accel` with fixed
parameters, and sets `DESIGN_NAME` to the wrapper. That keeps the RTL free of
flow-specific `ifdef`s, and since the wrapper only passes ports through it adds
nothing to place and route. The observation ports are terminated inside it and marked
`set_false_path` in the SDC, since a real integration leaves them unconnected.
