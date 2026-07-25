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
