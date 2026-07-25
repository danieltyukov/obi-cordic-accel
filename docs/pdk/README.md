# Real IHP SG13G2 130nm results

`make pdk` produces these. The process is the one
[Croc](https://github.com/pulp-platform/croc) taped out in, so the numbers are real
square micrometres and real megahertz, not gate equivalents.

PDK: `IHP-Open-PDK`, `ihp-sg13g2`. Override the location with `IHP_PDK_ROOT`.

## Methodology

In the order a real flow does it:

1. **Yosys** maps to `sg13g2` standard cells against the **slow** corner Liberty
   (`sg13g2_stdcell_slow_1p08V_125C.lib`), which is the corner a design has to close
   on.
2. **OpenROAD's resizer** repairs drive strength and slew. This step is not optional
   and not cosmetic. Straight out of `abc -liberty`, the netlist has minimum-size
   gates driving 0.7 pF nets, with slews reaching 13 ns and a single `nand4_1`
   contributing 4 ns of delay. Timing that netlist gives a number that describes
   Yosys's area-driven cell selection, not the design. After repair the same design
   has no max-slew or max-capacitance violation left.
3. The repair target period is **iterated to convergence**: each pass feeds the
   achieved delay back as the next target. Without that, the reported delay is a
   function of whatever probe period you happened to pick, because the resizer has
   no reason to work harder than the constraint asks. Both variants converge in two
   passes, which the per-configuration reports record.
4. The one repaired netlist is then timed at **all three corners**, as signoff does
   it, rather than synthesising separately per corner.

Constraints are ours, not a fallback: a real driving cell (`sg13g2_inv_4`) on the
inputs, 10 fF of load on the outputs, and `set_wire_rc -layer Metal2` for the wire
estimate.

## What these numbers are not

- **Not post-route.** Wire parasitics are estimated from `set_wire_rc`, not
  extracted, because there is no placement. `make pnr` runs the full LibreLane flow
  for post-route area and DRC/LVS signoff; see `pnr/README.md`.
- **Not the best this design can do.** `abc` maps the adders to ripple carry, and
  the critical path of both variants is dominated by that carry chain (42 of 55
  cells for the pipelined variant, 36 of 52 for the folded one). A carry-select or
  carry-lookahead structure would lift both. The comparison between variants is
  unaffected, since both go through the identical flow.

## Reading the reports

One `.rpt` per configuration, plus `summary.json` for the figures. Each report
carries the configuration, cell and flip-flop counts, area before and after drive
repair, the timing table across all three corners, and the critical path with the
flattened instance names resolved back to the RTL registers they implement. That
last part is what makes the path report diagnostic rather than decorative: ABC
renames everything to `_NNNNN_`, but Yosys leaves the original signal on each flop's
Q net, so the report can say the path ends at
`i_unit.gen_pipelined.i_core.xq[36]` rather than at `_72443_`.
