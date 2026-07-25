# Formal attempts, and what came of them

`make formal`. Needs [SymbiYosys](https://github.com/YosysHQ/sby) and a solver; not
part of `make all`, since both are a separate install.

**Read this first: none of these proofs converges on the hardware they were attempted
on.** The properties are written, the models elaborate, the encodings are generated,
and then the solver runs out of time. That is recorded below with wall clock times so
the attempt can be repeated or improved, and nothing anywhere in this repository
claims a formal result. The evidence for correctness here is the simulation suite:
80 tests, the two cores diffed word for word over 900 operations, and 13 concurrent
assertions live in the RTL. See [Results](#results).

`tb/test_equivalence.py` already runs both variants over 900 directed and random
operations and diffs their results word for word, with `scripts/check_equivalence.py`
comparing the recorded files without the Python model in between. That is real
evidence and it stands on its own.

This is a different kind of claim. Random vectors show that the two agree on the
operations that were tried. A bounded proof shows that no input sequence at all, up to
the bound, can make them disagree, including sequences no test would think to write:
back-to-back issue while the consumer stalls, a new operation arriving in the same
cycle the previous one retires, invalid function encodings, operands at the exact edge
of the convergence domain.

## Why a miter here is not a one-liner

The usual equivalence miter drives two copies of a module with the same inputs and
asserts their outputs match every cycle. That does not work for these two, because
they are not supposed to behave the same cycle by cycle. The pipelined core accepts an
operation every cycle and retires one every cycle after a fixed latency; the folded
core accepts one, spends a cycle per micro-rotation, and only then accepts another.
Comparing their outputs on any given cycle would fail immediately and would mean
nothing.

`cordic_equiv_miter.sv` handles that in three steps:

1. **Issue only when both are ready.** `issue = valid_i && p_ready && i_ready`. Without
   this the solver could feed one core an operation the other never saw, after which
   the two are working on different problems and any comparison is meaningless.
2. **Capture each side's result when it retires**, into that side's own registers.
3. **Compare only when both have retired the same number of operations**, and at least
   one. Each side counts its own retirements, and the comparison is gated on
   `p_cnt == i_cnt && p_cnt != 0`.

Step 3 is what makes a failure diagnostic. Without the operation counter, a mismatch
could just mean the two cores were at different points in the stream. With it, a
counterexample means they genuinely disagreed about the same operation.

Six properties are asserted on that comparison: the three result words, the flag bits,
and the function and tag fields that travel alongside the operation.

## What the proof covers, and what it does not

`cordic_pre` and `cordic_post` sit outside the `Variant` generate in
`rtl/cordic_unit.sv`, so both variants share one instance of each. The miter therefore
proves equivalence of the part that actually differs, which is the core. That is the
right target rather than a gap: the pre- and post-processing is not two
implementations, it is one.

The bound is the real limit. This is bounded model checking, not an unbounded proof, so
the result is "no disagreement within N cycles from reset", not "never". Extending it
to a full proof would need an inductive invariant relating the pipelined core's stage
registers to the folded core's iteration state, which is a much larger piece of work
than the bounded result.

## Two things that had to be worked around

**Yosys's native Verilog front end has no SVA support.** `assert property` with a
clocking event is a syntax error, which is why every Yosys path in this repo passes
`-DSYNTHESIS` to skip the RTL's own concurrent assertions. The miter's properties are
written as immediate assertions inside `always @(posedge clk_i)`, with `disable iff
(!rst_ni)` becoming an `if (rst_ni)` guard. Nothing is lost: every property here is a
same-cycle implication, so there is no temporal operator to translate.

**The comparison has to be shown reachable.** An assertion gated on a condition the
solver can never satisfy passes trivially, and a bound too short to retire an operation
on both sides would produce exactly that: a clean pass that proves nothing.
`equiv_tiny_cover.sby` asks the opposite question in `cover` mode, whether `matched` is
reachable at all. It has to pass for the `bmc` result to carry any weight.

## The OBI protocol properties

`obi_protocol.sby` and `cordic_obi_props.sv` ask a different and much smaller
question: do the bus rules hold for every sequence of traffic up to a bound?
`cordic_obi_regs` is the right unit for it, because the CORDIC datapath is entirely
outside it. The issue port, the result port and the status inputs are all ports, so
the solver drives them freely and what is left is the register file and the
response-holding registers.

Seven rules, each stated at the port boundary rather than over an internal signal,
because the port boundary is the contract a bus manager can observe: no request
accepted while a response is held, no pop of a result the hardware does not have,
`gnt` never falling when `UseRReady` is 0, a response only ever following an accepted
request, `rid` echoing `aid`, an issue lasting exactly one cycle, and a held response
neither changing nor withdrawing when `UseRReady` is 1. Five `cover` properties run
alongside so the rules cannot pass vacuously: if the solver could never reach a served
read, an error response, an issue, a pop or a back-to-back beat, asserting things about
them would prove nothing.

Two reductions are applied and neither weakens the claim. `AddrWidth` drops to 12
because the design decodes `obi_addr_i[11:0]` and explicitly ties everything above it
into `unused_addr_msbs`, so twenty free bits per cycle over the unrolling buy nothing.
`DataWidth` drops to the Q3.5 floor because the rules are about `req`, `gnt`, `rvalid`,
`rid` and `err`, none of which depends on the number format.

It still does not converge.

## Results

Every figure below is wall clock on a 22-core workstation with other work running, and
every attempt was bounded by `timeout` so an external interruption is distinguishable
from real non-convergence.

| Task | Configuration | Bound | Outcome |
|---|---|---|---|
| `obi_protocol.sby` | Q3.5, 5 stages, 12-bit address | 20 | no result. z3 still inside step 0 after 900 s at about 3 GB resident per task |
| `obi_protocol.sby` | same | 8 | no result in 280 s, still inside step 0 |
| `equiv_tiny_1op.sby` | Q3.5, 5 stages, one operation in flight | 14 | see below |
| `equiv_tiny.sby` | Q3.5, 5 stages | 16 | no result in 1,898 s |
| `equiv_q3_13.sby` | Q3.13, 15 stages | 22 | sby exited 16 after 1,696 s, engine returned no status |

The `abc bmc3` engine is not an alternative here: it crashes inside sby's own result
parser with `KeyError: 'asserts'` in `sby_engine_abc.py`, about a second in, before it
gets near the design.

What the shape of the failure says: the OBI properties stall at step 0, before any
unrolling, which is why halving the bound from 20 to 8 changed nothing. That points at
the initial-state constraint rather than the depth, and it is where a next attempt
should start. The equivalence miter is a different problem, and a plainer one: it has
to reason about iterated fixed-point addition across two structurally different
implementations, which is exactly the case bit-blasting handles worst.

## Configurations

| Task | Configuration | Bound | Why |
|---|---|---|---|
| `equiv_tiny.sby` | Q3.5, 5 stages | 16 | the smallest configuration the design supports |
| `equiv_tiny_cover.sby` | Q3.5, 5 stages | 24 | reachability of the comparison itself |
| `equiv_tiny_1op.sby` | Q3.5, 5 stages, one operation in flight | 14 | the smallest question the miter can be asked |
| `equiv_q3_13.sby` | Q3.13, 15 stages | 22 | the configuration the accuracy sweep uses |
| `obi_protocol.sby` | Q3.5, 5 stages, 12-bit address | 20 | bus protocol only, four tasks over the two handshake settings |

Q3.5 with 5 stages is not an arbitrarily shrunken model. It is the floor the
elaboration checks in `rtl/cordic_accel.sv` allow: `DataWidth` at least 8,
`DataWidth - FracBits` at least 3 so pi is representable, and `NumStages` either 5 or
15 and above, because 6 through 14 truncate the hyperbolic repeat sequence and break
Walther's convergence condition. `make lint` elaborates it as one of its parameter
sets. Both cores instantiate the same `cordic_stage` over the same shift and angle
sequence at every configuration, so a proof at one configuration is evidence about the
structure rather than about the number format. The configuration is stated alongside
the result either way.
