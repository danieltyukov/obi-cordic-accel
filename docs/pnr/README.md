# Place and route: methodology and what the numbers mean

`make pnr` runs both microarchitectures from RTL to GDS through LibreLane on the IHP
SG13G2 open PDK, the same 130nm process Croc taped out in. `make layout` renders the
result. `scripts/run_pnr.py` is the driver and `pnr/cordic.sdc` is the constraint file.

`make pdk` stops after synthesis. This goes further, and the reason it is worth doing
is not the pictures. A synthesis-only area comparison between a pipelined and a folded
design is systematically unfair to the pipelined one, because synthesis charges it for
cell area but not for the clock tree, the timing-repair buffering, or the routing that
its much larger register count demands. Those only appear after placement and routing.
Measuring both variants through the same flow and comparing their inflation factors is
the only way to see how much of the folded variant's apparent area advantage survives
physical implementation.

## What is actually measured

| Number | Where it comes from | What it is |
|---|---|---|
| routed standard-cell area | `design__instance__area__class:standard_cell` | cell area after resizing, clock tree and repair, excluding fill |
| die area | `design__die__area` | the whole die, so it includes whitespace at the target utilisation |
| routed cell count | `design__instance__count__class:standard_cell` | excludes the fill cells, which are placement filler and not logic |
| router DRC | `route__drc_errors` | OpenROAD's detailed router, after it iterates to convergence |
| GDS cross-check | `design__xor_difference__count` | Magic and KLayout each stream out a GDS; the flow XORs them |
| Magic DRC | `magic__drc_error__count` | the sg13g2 Magic runset against the streamed-out GDS |
| post-route timing | `*stapostpnr/<corner>/max.rpt` | all three corners, with parasitics extracted by OpenRCX |

## Two things this deliberately does not claim

**The post-route frequency is not the same measurement as the Fmax in
[docs/pdk](../pdk/).** `make pdk` iterates the clock period until slack reaches zero,
so its Fmax is the frequency at which the design just closes. This flow routes for one
fixed target period and reports the slack left over. Dividing into that slack implies
a frequency, but only under the assumption that a tighter target would not have made
the tool place, size and buffer differently, and it would have. Both numbers appear in
the README, labelled, and neither is presented as the other.

Within that limit the comparison is still informative, because both flows measure the
same thing on the same design: register to register, at the slow corner, 1.08 V and
125 C.

**Timing here is register to register, not the headline slack.** The worst path in
every one of these runs is an IO path, because `pnr/cordic.sdc` charges a quarter of
the clock period to input arrival and another quarter to output setup. That is a
deliberate budget for a peripheral sitting on a SoC bus, not a property of the logic,
so the headline `timing__setup__ws` describes the constraint rather than the design.
`scripts/run_pnr.py` reads the worst register-to-register path out of the path reports
instead, and resolves its endpoints back to RTL register names.

## What is not checked

The LibreLane Classic flow for `ihp-sg13g2` includes `Magic.DRC` but **no LVS step**,
and no KLayout DRC step either. So there is no layout-versus-schematic result here, and
none is claimed. The checks that do run are the router's own DRC, the Magic DRC
runset, and the Magic-against-KLayout GDS XOR.

Nothing here is a mock-up: every number and every figure comes out of the flow. Nor is
any of it silicon. These are tool outputs on a real PDK, not a tapeout: the design has
not been manufactured, has no pad ring, and has had no analog or reliability signoff.

## Reproducing

```
make pnr           # both variants, RTL to GDS. Hours, not minutes.
make pnr-harvest   # re-read the newest existing run into summary.json
make layout        # render the GDS figures from the run
```

`make pnr-harvest` exists because the list of metrics worth recording grew several
times while a routing run was in flight. Re-reading a finished run costs a second;
repeating it costs hours and would produce a different layout from the one already
rendered and committed.

Two settings in `scripts/run_pnr.py` are there because of failures worth recording:

- `RSZ_HOLD_MAX_BUFFER_PCT` and a split setup/hold clock uncertainty in
  `pnr/cordic.sdc`. A single `set_clock_uncertainty` without `-setup` applies to hold
  analysis as well, so every short path needed five percent of the clock period in
  padding, and post-CTS hold repair ran out of buffers with `[RSZ-0060] Max buffer
  count reached` at stage 37 of 79.
- `KLAYOUT_XOR_THREADS`. KLayout's threading options default to unset, meaning
  single-threaded.
