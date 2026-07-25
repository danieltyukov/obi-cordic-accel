# Contributing

Thanks for looking. This is a hardware repository, so "it builds" is a low bar: the
useful contribution is one that comes with a measurement, and the measurement has to
be reproducible by someone else on the same tools.

- [What you need](#what-you-need)
- [Set up](#set-up)
- [The loop](#the-loop)
- [Lint](#lint)
- [The cocotb suite](#the-cocotb-suite)
- [Generated files](#generated-files)
- [Synthesis and STA against the PDK](#synthesis-and-sta-against-the-pdk)
- [Place and route](#place-and-route)
- [Figures](#figures)
- [The RV32 driver](#the-rv32-driver)
- [Formal](#formal)
- [What a good pull request looks like here](#what-a-good-pull-request-looks-like-here)
- [How numbers are reported](#how-numbers-are-reported)
- [Commit messages](#commit-messages)
- [Licence and provenance](#licence-and-provenance)

## What you need

| For | Tool | Version this was developed against |
|---|---|---|
| everything | Python | 3.12.3, and CI pins 3.12 |
| simulation and lint | Verilator | 5.020 |
| synthesis | Yosys | 0.33 |
| real-silicon PPA | `openroad`, IHP SG13G2 PDK | OpenROAD 26Q3-771-g7cfb2105c9 |
| place and route | LibreLane, KLayout, Magic, netgen | LibreLane 3.0.0.dev44, KLayout 0.30.4 |
| RV32 driver | `riscv64-unknown-elf-gcc`, optionally picolibc | GCC 13.2.0 |
| formal | SymbiYosys (`sby`) plus a solver | yosys-smtbmc with z3 |

Only Python and Verilator are needed to run the test suite. Everything below
simulation degrades gracefully: `make sw` skips the RV32 image out loud when the cross
compiler is absent, `make images` skips the layout renders when there is no GDS, and
`make formal` skips entirely when `sby` is not on PATH. A skip always says so on
stdout rather than passing quietly.

**Verilator is the only simulator.** Icarus Verilog 12 cannot build this design: it
aborts with an internal assertion at `netmisc.cc:1821` when a constant function
indexes a packed 2D localparam, and separately folds `$atan` in a constant function to
zero without complaining. Both defects are written up in
[docs/DESIGN.md](docs/DESIGN.md) under "Tool support". Do not spend an afternoon on it.

Verilator 5.020 is what is installed here, and cocotb 2.0 requires 5.036 or newer, so
`requirements.txt` pins cocotb 1.9.2. `tb/cordic_tb.py` carries shims for both cocotb
generations, so the suite also runs unchanged on cocotb 2.x with a newer Verilator. If
you upgrade one, upgrade the other.

## Set up

```sh
git clone https://github.com/danieltyukov/obi-cordic-accel
cd obi-cordic-accel
make venv
```

`make venv` creates `.venv/` and installs `requirements.txt` into it. Nothing is
installed outside the repository, and every Make target that needs Python uses
`.venv/bin/python` explicitly, so you never have to remember to activate anything.

If you want a shell with it active:

```sh
source .venv/bin/activate
```

`make check-tools` reports what is missing before a long run starts, including the PDK
location, which defaults to `$HOME/.local/share/pdk/IHP-Open-PDK/ihp-sg13g2` and is
overridden with `IHP_PDK_ROOT`.

## The loop

The whole flow, in the order `make all` runs it:

```sh
make gen         # regenerate the ROM, register map and software vectors
make lint        # Verilator -Wall over 10 parameter configurations, plus the wrapper
make test        # the cocotb suite, both variants, both OBI handshakes
make synth       # Yosys generic cells, 6 configurations, reports into docs/synth
make pdk         # real IHP SG13G2 130nm, area and Fmax at 3 corners, docs/pdk
make sw          # host driver test (runs) and both RV32 images (link)
make images      # redraw every figure from the measured data
```

`make all` is all of those. Measured from a clean clone on a 22-core workstation with
other work running: 638 s, 791 s and 977 s on three runs, so call it 10 to 17 minutes.
`make pnr` takes hours and is deliberately not part of it.

Before you open a pull request, `make all` should complete and `git status` should be
clean. A dirty tree after `make all` means a generated file, a synthesis report or a
figure in your branch no longer matches what the tools produce, and CI will fail on
exactly that. Every committed generated file, synthesis report and figure is
byte-reproducible from a clean clone, which is what makes that check worth running
rather than a formality.

## Lint

```sh
make lint          # everything below
make lint-core     # the core RTL at default parameters
make lint-wrap     # the Croc integration wrapper, both variants
make lint-configs  # 10 parameter configurations
make arith         # assert the design infers no multiplier, divider or MAC
```

**Zero warnings at `-Wall` is the bar**, not a goal. Verilator exits non-zero on any
warning at `-Wall`, so there is no warning budget to argue about.

`lint-configs` elaborates every parameter combination the design claims to support,
because a generate branch that is never elaborated is a branch that is never checked.
If you add a parameter or a new legal combination, add it to the `LINT_CONFIGS` list
in the Makefile in the same commit.

`make arith` stops Yosys before cell mapping and asserts `$mul`, `$div`, `$mod`,
`$pow` and `$macc` are all absent, then prints what the design does infer. The whole
point of CORDIC is that it needs no multiplier, so that is asserted rather than
claimed. If your change makes the design infer one, the audit fails and it is telling
you something real.

## The cocotb suite

```sh
make test            # everything
make test-accuracy   # one suite
```

The suites are `test_smoke`, `test_accuracy`, `test_domain`, `test_obi`,
`test_throughput`, `test_equivalence` and `test_reset`. Several run more than once
under different elaboration parameters, which is why `make test` runs more
simulations than there are files.

One module directly, which is the fast way to iterate:

```sh
make -C tb MODULE=test_obi
make -C tb MODULE=test_obi CORDIC_USE_RREADY=1
make -C tb MODULE=test_throughput CORDIC_VARIANT=1
make -C tb WAVES=1 MODULE=test_smoke      # writes tb/dump.vcd
```

Elaboration parameters are environment variables read by both the Makefile and the
Python model, so the model always matches the hardware that was compiled:
`CORDIC_DATA_WIDTH`, `CORDIC_FRAC_BITS`, `CORDIC_NUM_STAGES`, `CORDIC_GUARD_INT`,
`CORDIC_GUARD_FRAC`, `CORDIC_VARIANT`, `CORDIC_USE_RREADY`, `CORDIC_IN_DEPTH`,
`CORDIC_OUT_DEPTH`. Each combination builds into its own `tb/sim_build/` directory, so
switching between them does not keep invalidating the Verilator build.

Sample counts are variables, so a local run gets the full sweep and CI gets a shorter
one over the same tests:

```sh
make test ACC_SAMPLES=300 DOMAIN_SAMPLES=200 EQUIV_SAMPLES=400 STREAM_OPS=128
```

Only the randomised arguments are sampled. Every directed and edge case runs at any
setting, so a reduced run is a smaller sweep and not a weaker suite.

### Writing a test

Three things are expected of a new test here.

**Assert bit-exactness against the model, not a tolerance.** `tb/cordic_model.py` is
bit-accurate, and every result the RTL produces is asserted equal to it word for word.
Accuracy against `math` in double precision is measured separately and reported in
LSBs, so the accuracy numbers in the README are accuracy and not correctness.

**Assert a bound you can derive.** `tb/cordic_bounds.py` holds the two error bounds,
one for rotation and one for vectoring, with the measurements that justify them. A new
function needs its bound written down, not a constant picked because it passed.

**Record what you measured.** Suites write JSON into `build/results/`, and the figures
are drawn from those files rather than from numbers typed into a plotting script. A
test that measures something worth putting in the README has to write it out.

The OBI manager in `tb/cordic_tb.py` checks the bus rules continuously while every
test runs, so a protocol violation fails whichever suite happened to be running. There
are also 13 concurrent assertions in the RTL, enabled through Verilator's `--assert`
in every simulation, which means they also hold inside Croc's own testbench without
that testbench having to know the rules.

## Generated files

Four things are generated and committed: the CORDIC constant tables
(`rtl/cordic_rom.svh`), the register map (`rtl/cordic_regmap.svh`,
`sw/include/cordic_regmap.h`, `docs/REGISTERS.md`, `docs/img/regmap.svg`), and the
software test vectors (`sw/host/cordic_vectors.h`).

```sh
make gen        # regenerate them
make check-gen  # fail if any committed copy is stale
```

**Never hand-edit a generated file.** Edit the generator and rerun `make gen`. The
register map is defined once, in `scripts/cordic_regmap.py`, and everything else is
derived from it, so hardware, driver, tests and documentation cannot disagree.
`make check-gen` runs in CI and fails on a hand edit or a generator change without a
regeneration.

Everything generated is committed so that a clone builds without running a generator.

## Synthesis and STA against the PDK

Two separate flows, and they answer different questions.

```sh
make synth        # Yosys generic cells (abc -g cmos4), 6 configurations
make synth-quick  # the two headline configurations only
```

`make synth` produces gate equivalents rather than areas. It is kept because it is
what someone without the PDK can reproduce, and because the structural checks are
asserted inside the Yosys script itself: no inferred latch before or after technology
mapping, no blackbox, no combinational loop, no multiply-driven or undriven wire, no
unmapped memory, no tristate. CI fails if the committed reports under `docs/synth/`
differ from a fresh run, which is what stops the numbers quoted in the README from
going stale.

```sh
make pdk        # real IHP SG13G2 130nm, 6 configurations
make pdk-quick  # the two headline configurations only
.venv/bin/python scripts/run_pdk.py --only pipe_q3_29_n28
```

`make pdk` maps to real `sg13g2` standard cells against the slow-corner Liberty, runs
OpenROAD's resizer to repair drive strength, iterates the repair target period to
convergence, and then times the one repaired netlist at all three corners.
[docs/pdk/README.md](docs/pdk/README.md) explains why each of those steps is there and
what happens if you skip one. The short version: an unrepaired `abc -liberty` netlist
has minimum-size gates driving 0.7 pF nets, and timing it measures Yosys's area-driven
cell selection rather than the design.

**These results are a synthesis estimate, and the README says so everywhere they
appear.** Wire parasitics come from `set_wire_rc -layer Metal2`, not from extraction,
because there is no placement.

If you write your own OpenSTA script against this PDK, three things will bite you:

- both `read_lef` calls, the technology LEF then the standard cell LEF, must come
  before `read_verilog`, or OpenROAD stops with `[ERROR ORD-2010]`
- `remove_from_collection` does not exist in this build. List the ports explicitly
- `sg13g2_sdfrbpq_*` warnings are scan flops and are harmless

Invoke it as `openroad -no_init -exit your.tcl`, and Fmax is
`1 / (period - worst_slack)`.

## Place and route

```sh
make pnr          # both variants, RTL to GDS through LibreLane. Hours, not minutes
make pnr-harvest  # re-read the newest existing run into docs/pnr/summary.json
make layout       # render the routed dies at a shared scale, plus detail crops
.venv/bin/python scripts/pnr_fmax.py   # re-time the routed netlists
```

Read [docs/pnr/README.md](docs/pnr/README.md) before you run this. It records which
metric each reported number comes from, why the post-route frequency has to be
measured separately rather than divided out of LibreLane's leftover slack, and the two
limits on that measurement.

`make pnr-harvest` exists because re-reading a finished run costs a second while
repeating it costs hours and produces a different layout from the one already rendered
and committed. Both the harvest and the Fmax measurement work on an unfinished run:
everything they need is written by step 55 of 75.

A `null` in the Magic DRC, KLayout DRC or LVS fields of `summary.json` means the stage
had not finished. **It does not mean the stage passed**, and nothing in the README may
report it that way.

Two settings are there because of failures worth knowing about. `KLAYOUT_DRC_THREADS`
and `KLAYOUT_XOR_THREADS` default to unset, meaning single-threaded, and the maximal
sg13g2 DRC runset then takes longer than every other stage put together. And
`PNR_SDC_FILE` and `SIGNOFF_SDC_FILE` must point at a real SDC or the timing results
are not worth reading; `pnr/cordic.sdc` is that file here.

## Figures

```sh
make images                                          # every figure
.venv/bin/python scripts/gen_plots.py error_vs_angle # one figure
```

Every figure is drawn from measured data on disk: `build/results/` from the
simulations, `docs/synth/summary.json`, `docs/pdk/summary.json` and
`docs/pnr/summary.json`. `make images` fails if the simulation or synthesis data is
missing, since both are cheap to produce. The PnR figures are treated differently
because routing takes hours: `docs/pnr/summary.json` is committed, so the charts always
redraw, while `scripts/run_pnr_render.sh` skips the layout renders with a message when
KLayout, the PDK or the GDS the summary names is absent. That is the case in a clone
and on a CI runner, and the committed renders are kept rather than overwritten.

KLayout reports a missing layout as a `RuntimeError` and still exits 0, so if you touch
that script keep the check that an empty die extent is a hard error. Without it a
missing GDS reads as a successful render, the shared scale comes out 0 um/px, and the
committed figures get quietly replaced.

`scripts/check_svg.py` runs at the end and fails on a malformed SVG. It uses
`defusedxml` on purpose: the stdlib XML parsers resolve external entities.

If a figure carries a number, its caption has to say which flow produced it.
`docs/img/area_comparison.png` says "synthesis estimate" on the figure itself, because
someone will screenshot it without the surrounding paragraph.

## The RV32 driver

```sh
make sw                    # host test (runs) and both RV32 images (link)
make -C sw host            # gcc, links the peripheral model, runs the test
make -C sw rv32            # freestanding RV32IMC
make -C sw rv32-picolibc   # RV32IMC against picolibc
```

The host build is what verifies the driver: it compiles `test_cordic.c` against the
register-accurate peripheral model in `sw/host/` and runs it. The model answers out of
vectors generated from the same bit-accurate model the RTL is asserted against, rather
than from a second CORDIC written in C, which would only show that two pieces of C
agree with each other.

The cross toolchain is `gcc-riscv64-unknown-elf` plus `picolibc-riscv64-unknown-elf`
on Debian and Ubuntu. The freestanding link needs only gcc and libgcc; the picolibc
link needs the separately packaged libc, so `make sw` attempts it only when
`picolibc.specs` is findable and says out loud when it is not. Croc boots
freestanding, so that is the link mode that matters.

**Neither RV32 image is executed here.** This repository carries no Croc simulation.
The image records its outcome at the `cordic_test_report` symbol and returns the
failure count in `a0`, so Croc's own testbench can read the result out of memory. Do
not describe it as tested.

The driver is compiled with `-Wall -Wextra -Werror -Wshadow -Wconversion
-Wsign-conversion -Wstrict-prototypes -Wmissing-prototypes -Wpointer-arith -Wcast-qual
-Wundef`. No floating point, no libc, no allocation: Croc's CVE2 has no FPU, so a
float in a driver pulls in soft-float routines costing more than the accelerator
saves.

## Formal

```sh
make formal                       # every task, each bounded by FORMAL_TIMEOUT
make formal FORMAL_SBY=equiv_tiny # one task
cd formal && sby -f equiv_tiny.sby
```

**None of these proofs converges on the hardware they were attempted on.** The
properties are written, the models elaborate, the encodings are generated, and the
solver runs out of time. [formal/README.md](formal/README.md) records every attempt
with its configuration, its bound and its wall clock, and nothing anywhere in this
repository claims a formal result.

If you land a converging run, the bar for reporting it is in that file already: state
which task, which configuration, which bound, and what the bound does and does not
cover. A bounded model check gives "no disagreement within N cycles from reset", not
"never", and it has to be written that way. `equiv_tiny_cover.sby` asks whether the
comparison is reachable at all, and it has to pass for the `bmc` result to carry any
weight, because an assertion gated on an unreachable condition passes trivially.

Every attempt is bounded by `timeout` so an external interruption is distinguishable
from real non-convergence, and the wall clock is printed either way. Keep that
property if you change the target.

## What a good pull request looks like here

- **It states what it measured and how.** "Faster" is not a claim. "78.6 MHz post-route
  at the slow corner, `make pnr` then `scripts/pnr_fmax.py`, summary.json committed" is.
- **It reruns whatever its change invalidates.** Touching the RTL means `make synth`
  and the committed reports under `docs/synth/`. Touching a generator means `make gen`.
  Touching a plotting script or the data behind it means `make images`. CI checks all
  three, so a stale artefact fails there rather than being noticed later.
- **`make all` completes and leaves the tree clean.** That is the single check that
  covers most of the above.
- **New RTL comes with a test, and new behaviour with an assertion.** A concurrent
  assertion in the RTL is preferred over a testbench check when the property is one
  the module owns, because it then holds in every simulation, including Croc's.
- **A new parameter combination goes into `LINT_CONFIGS`.**
- **Docs change in the same commit as the thing they describe.** The README quotes
  measured numbers; if your change moves one, move it in the README too.
- **Small commits, each one buildable.** The history here is one change per commit with
  a message saying what changed and why, and it is worth keeping that way.

CI runs six jobs: lint and generated files, simulation, synthesis, committed PDK
results are consistent, driver, and figures. The PDK and PnR flows themselves do not
run on a hosted runner, since the PDK is a large external tree and OpenROAD comes from
a container. What CI does instead is check that the committed artefacts are
self-consistent with the figures drawn from them.

If your change needs a tool CI does not have, say so in the pull request and include
the local run's output.

## How numbers are reported

This is the part of the repository that is easiest to get wrong, so it is written
down.

- **Label post-synthesis and post-route separately, always.** They differ here by 1.31x
  on cell area and up to 1.88x on frequency, and they are not interchangeable. Every
  table says which one it is.
- **Name the corner, and check which one you mean.** `make pdk` times against
  `sg13g2_stdcell_{slow_1p08V_125C, typ_1p20V_25C, fast_1p65V_m40C}.lib`, so its three
  corners are 1.08 V / 125 C, 1.20 V / 25 C and **1.65 V** / -40 C. LibreLane names its
  own corners `nom_slow_1p08V_125C`, `nom_typ_1p20V_25C` and `nom_fast_1p32V_m40C`, so
  the fast one carries a different voltage in its name than the Liberty file
  `scripts/run_pdk.py` and `scripts/pnr_fmax.py` actually read. Slow and typ agree
  between the two; fast does not. A frequency without a corner means nothing, and a
  fast-corner number needs to say which fast.
- **Nothing here has been fabricated.** These are tool outputs on a real PDK. The
  design has no pad ring and has had no analog or reliability signoff. Renders are
  captioned as hardened layouts, never as silicon or as a die photo.
- **A skipped check is not a passed check.** Report the skip.
- **Scope every claim to what was actually run.** Which variant, which configuration,
  how many samples, which bound. "Bit-identical" in this README is followed by "over
  900 operations, recorded and diffed word for word", and that is the pattern.
- **Do not round a failure away.** The pipelined variant does not close DRC, and the
  README says so in the signoff table, in the summary row and under "What this does
  not claim", rather than reporting the two variants as one clean result.

## Commit messages

Conventional Commit prefixes: `feat`, `fix`, `docs`, `test`, `ci`, `chore`, `formal`.
The subject describes the change. Bodies are welcome and are the right place for a
measurement or for why an approach was abandoned.

Do not add generated-by, session or AI co-author trailers to commits, pull request
bodies, tags or changelog entries. Commit messages describe the change.

## Licence and provenance

Apache-2.0. New files carry the two-line header the rest of the tree uses:

```
// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
```

By contributing you agree your contribution is licensed under Apache-2.0.

If you bring in code or a field list from another project, record it in
[NOTICE](NOTICE) with the source and its licence, the way the Croc-derived scaffolding
under `integration/croc/` is recorded. That scaffolding is Solderpad SHL-0.51 and only
the CORDIC-specific parts of those files are covered by this repository's licence.
