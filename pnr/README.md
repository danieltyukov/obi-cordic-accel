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
