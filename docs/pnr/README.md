# Place and route: methodology and what the numbers mean

`make pnr` runs both microarchitectures from RTL to GDS through LibreLane on the IHP
SG13G2 open PDK, the same 130nm process Croc taped out in. `make layout` renders the
result. `scripts/run_pnr.py` is the driver and `pnr/cordic.sdc` is the constraint file.

`make pdk` stops after synthesis. This goes further, and the reason it is worth doing
is not the pictures. Every PPA number a synthesis run produces is an estimate of a
quantity that only exists after placement, and the estimate is wrong in both
directions at once: it understates area, because there is no clock tree, no timing
repair and no floorplan, and it understates frequency, because drive repair over a
virtual placement cannot size gates against distances it does not know. Routing both
variants through the same flow is what turns that from an assertion into two numbers
per variant.

## What is actually measured

| Number | Where it comes from | What it is |
|---|---|---|
| routed standard-cell area | `design__instance__area__stdcell` | cell area after resizing, clock tree and repair, excluding fill |
| die area | `design__die__area` | the whole die, so it includes whitespace at the target utilisation |
| routed cell count | `design__instance__count__stdcell` | excludes the fill cells, which are placement filler and not logic |
| cell composition | `design__instance__area__class:*` | registers, combinational logic, clock tree and timing-repair buffers separately |
| router DRC | `route__drc_errors` | OpenROAD's detailed router, after it iterates to convergence |
| GDS cross-check | `design__xor_difference__count` | Magic and KLayout each stream out a GDS; the flow XORs them |
| Magic DRC | `magic__drc_error__count` | the sg13g2 Magic runset against the streamed-out GDS |
| KLayout DRC | `klayout__drc_error__count` | the sg13g2 KLayout runset, 477 rules |
| LVS | `design__lvs_error__count` | netgen, extracted layout against the post-route netlist |
| post-route Fmax | `scripts/pnr_fmax.py` | the routed netlist re-timed on extracted parasitics |

## Why the post-route frequency is measured separately

LibreLane reports the slack left over at the one period the design was routed for.
Dividing into that slack gives a number, but not one that can be set beside the Fmax
in [docs/pdk](../pdk/), for two reasons that compound. `pnr/cordic.sdc` charges a
quarter of the clock period to input arrival and another quarter to output setup,
which is a deliberate budget for a peripheral sitting on a SoC bus, and it adds five
percent of the period as setup uncertainty. `make pdk` applies neither. So the
leftover slack carries the IO budget, the uncertainty and the routed target all at
once, and comparing it against a synthesis Fmax says nothing about what changed
between the two.

`scripts/pnr_fmax.py` re-times the routed netlist under the same constraint style
`make pdk` uses, against the parasitics OpenRCX extracted from the routed design
instead of a `set_wire_rc` estimate. What is left between the two numbers is then the
parasitics and the cells PnR added, which is the thing worth measuring. Both are
register to register, at the same three corners, from the same Liberty files.

Two limits on that number, both real:

- **It is the routed netlist's path delay, not a closed-timing Fmax.** The netlist was
  optimised against the period in the LibreLane config and the tool stopped once it
  met it. A tighter target would have produced a different netlist, and this
  measurement cannot say whether a better one.
- **The worst path overall is still an IO path**, so the register-to-register path is
  searched for rather than taken from the top of the report. `scripts/run_pnr.py`
  requires both ends of the path to be flops and resolves them back to RTL register
  names.

## What is not silicon

Every number and every figure here comes out of the flow, and none of it is a
mock-up. None of it is silicon either. These are tool outputs on a real PDK, not a
tapeout: the design has not been manufactured, has no pad ring, and has had no analog
or reliability signoff. The signoff that does run is the router's own DRC iterated to
convergence, the Magic and KLayout DRC runsets, a Magic-against-KLayout GDS XOR, and
netgen LVS of the extracted layout against the post-route netlist.

## Reproducing

```
make pnr           # both variants, RTL to GDS. Hours, not minutes.
make pnr-harvest   # re-read the newest existing run into summary.json
make layout        # render the GDS figures from the run
.venv/bin/python scripts/pnr_fmax.py   # re-time the routed netlists
```

`make pnr-harvest` exists because the list of metrics worth recording grew several
times while a routing run was in flight. Re-reading a finished run costs a second;
repeating it costs hours and would produce a different layout from the one already
rendered and committed. Both the harvest and the Fmax measurement work on an
unfinished run: everything they need is written by step 55 of 75, and the signoff DRC
stages after it are what dominate the wall clock.

Settings that are there because of failures worth recording:

- `RSZ_HOLD_MAX_BUFFER_PCT` and a split setup/hold clock uncertainty in
  `pnr/cordic.sdc`. A single `set_clock_uncertainty` without `-setup` applies to hold
  analysis as well, so every short path needed five percent of the clock period in
  padding, and post-CTS hold repair ran out of buffers with `[RSZ-0060] Max buffer
  count reached` at stage 37 of 75.
- `KLAYOUT_DRC_THREADS` and `KLAYOUT_XOR_THREADS`. KLayout's threading options default
  to unset, meaning single-threaded, and the maximal sg13g2 DRC runset then takes
  longer than every other stage put together.
- `--build-dir`, so the two variants can route at once. LibreLane stages the RTL and
  the config next to each other, so a second driver writing into a live work directory
  would pull them out from under the first.

Magic's DRC stays single-threaded whatever the config says, and it scales badly: 7
minutes 43 seconds for the folded variant's 30k instances against 2 hours 7 minutes for
the pipelined variant's 166k. That is why a `summary.json` entry can carry routing and
timing results with its Magic DRC, KLayout DRC and LVS counts still `null`: the harvest
works on an unfinished run, and everything the routing and timing numbers need is
written by step 55 of 75. A null in those fields means the stage had not finished. It
does not mean the stage passed, and the README quotes it that way.

The two runs differ in where their metrics come from. The folded run completes cleanly
and writes `final/metrics.json`. The pipelined run reaches all 75 stages but ends with
two deferred DRC errors and never writes one, so its metrics are merged from the
per-step files. The `_source` field in `summary.json` records which of the two a given
entry came from.
