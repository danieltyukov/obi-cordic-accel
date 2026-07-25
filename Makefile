# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
#
# Top-level build. `make all` runs everything from a clean checkout.
#
#   make venv      create .venv and install requirements
#   make gen       regenerate every generated file (ROM, register map, sw vectors)
#   make lint      Verilator -Wall on the core RTL and on the Croc wrapper
#   make arith     assert the design infers no multiplier, divider or MAC
#   make test      the whole cocotb suite, both variants, both OBI handshakes
#   make synth     Yosys generic cells, six configurations, docs/synth
#   make pdk       real IHP SG13G2 130nm: area in um^2 and Fmax at three
#                  corners via Yosys plus OpenROAD, reports into docs/pdk
#   make pnr       full RTL-to-GDS through LibreLane, post-route area plus
#                  DRC and LVS signoff, reports into docs/pnr
#   make sw        host driver test (runs) and both RV32 images (link)
#   make images    regenerate every figure in docs/img from measured data
#   make check-gen fail if any generated file is out of date
#   make all       gen, lint, test, synth, pdk, sw, images
#
# Simulator note: Verilator, because it is the only open simulator on this machine
# that elaborates the design. Icarus Verilog 12 aborts on an internal assertion when
# a constant function indexes a packed 2D localparam. Verilator 5.020 is installed
# and cocotb 2.0 needs 5.036, so requirements.txt pins cocotb 1.9.2; tb/cordic_tb.py
# carries the two shims that let the suite run on either cocotb generation.

SHELL := /bin/bash
TOP   := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

VENV    := $(TOP)/.venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
VENV_OK := $(VENV)/.installed

RTL_DIR := $(TOP)/rtl
RTL := \
  $(RTL_DIR)/cordic_stage.sv \
  $(RTL_DIR)/cordic_core_pipe.sv \
  $(RTL_DIR)/cordic_core_iter.sv \
  $(RTL_DIR)/cordic_pre.sv \
  $(RTL_DIR)/cordic_post.sv \
  $(RTL_DIR)/cordic_unit.sv \
  $(RTL_DIR)/cordic_fifo.sv \
  $(RTL_DIR)/cordic_obi_regs.sv \
  $(RTL_DIR)/cordic_accel.sv

WRAP_LINT := \
  $(TOP)/integration/croc/lint/obi_pkg.sv \
  $(TOP)/integration/croc/lint/croc_pkg.sv \
  $(TOP)/integration/croc/lint/tb_wrap_lint.sv \
  $(TOP)/integration/croc/cordic_obi_wrap.sv

GENERATED := \
  $(RTL_DIR)/cordic_rom.svh \
  $(RTL_DIR)/cordic_regmap.svh \
  $(TOP)/sw/include/cordic_regmap.h \
  $(TOP)/sw/host/cordic_vectors.h \
  $(TOP)/docs/REGISTERS.md \
  $(TOP)/docs/img/regmap.svg

# Figures that need only simulation and synthesis data. pnr_comparison is drawn
# separately, since it needs a place-and-route result.
PLOTS_NO_PNR := error_vs_angle error_histograms error_vs_stages error_vs_width \
                convergence_trajectory area_comparison throughput_latency \
                ppa_ihp_sg13g2

VERILATOR ?= verilator
YOSYS     ?= yosys

# Sample counts. CI lowers them; a local run gets the full sweep.
ACC_SAMPLES    ?= 1200
DOMAIN_SAMPLES ?= 600
EQUIV_SAMPLES  ?= 900
STREAM_OPS     ?= 256

.PHONY: all venv gen rom regmap sw-vectors check-gen lint lint-core lint-wrap \
        lint-configs test test-smoke test-accuracy test-domain test-obi \
        test-throughput test-equivalence test-reset synth synth-quick sw sw-host \
        sw-rv32 images clean distclean tools help pdk pdk-quick pnr pnr-harvest \
        layout arith formal

all: check-tools gen lint test synth pdk sw images
	@echo
	@echo "==== make all completed ===="

help:
	@sed -n 's/^#   //p' $(lastword $(MAKEFILE_LIST))

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
venv: $(VENV_OK)

$(VENV_OK): $(TOP)/requirements.txt
	python3 -m venv $(VENV)
	$(PIP) -q install --upgrade pip
	$(PIP) -q install -r $(TOP)/requirements.txt
	@touch $@
	@$(PY) -c "import cocotb; print('cocotb', cocotb.__version__)"

.PHONY: check-tools
check-tools:
	@fail=0; \
	for t in $(VERILATOR) $(YOSYS) python3 openroad; do \
	  if ! command -v $$t >/dev/null 2>&1; then \
	    echo "missing required tool: $$t"; fail=1; fi; \
	done; \
	if [ ! -d $(IHP_PDK_ROOT) ]; then \
	  echo "IHP SG13G2 PDK not found at $(IHP_PDK_ROOT); set IHP_PDK_ROOT"; fail=1; fi; \
	if ! command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then \
	  echo "note: riscv64-unknown-elf-gcc not found, 'make sw' will skip the RV32 image"; \
	fi; \
	test $$fail -eq 0
	@echo "verilator $$($(VERILATOR) --version | cut -d' ' -f2)"
	@echo "yosys     $$($(YOSYS) -V | cut -d' ' -f2)"

# ---------------------------------------------------------------------------
# Generated files
# ---------------------------------------------------------------------------
gen: rom regmap sw-vectors

rom: $(VENV_OK)
	$(PY) $(TOP)/scripts/gen_cordic_rom.py

regmap: $(VENV_OK)
	$(PY) $(TOP)/scripts/gen_regmap.py

sw-vectors: $(VENV_OK)
	$(PY) $(TOP)/scripts/gen_sw_vectors.py

# Fails if a generated file in the tree does not match what the generator produces.
# CI runs this, so a hand edit to a generated file cannot slip through.
check-gen: $(VENV_OK)
	$(PY) $(TOP)/scripts/gen_cordic_rom.py --check
	$(PY) $(TOP)/scripts/gen_regmap.py --check
	$(PY) $(TOP)/scripts/gen_sw_vectors.py --check

# ---------------------------------------------------------------------------
# Lint. Zero warnings at -Wall is the bar, and it is enforced by -Wall alone
# being enough for Verilator to exit non-zero.
# ---------------------------------------------------------------------------
lint: lint-core lint-wrap lint-configs arith

# The point of CORDIC is that it needs no multiplier, so that is asserted rather than
# claimed. A separate pass on purpose: adding the passes it needs ahead of `synth`
# would perturb the optimisation sequence the reported cell counts came from.
arith: $(VENV_OK)
	@echo "== arithmetic audit"
	$(PY) $(TOP)/scripts/check_arithmetic.py

lint-core:
	@echo "== lint: core RTL, default parameters"
	$(VERILATOR) --lint-only -Wall +incdir+$(RTL_DIR) --top-module cordic_accel $(RTL)

lint-wrap:
	@echo "== lint: Croc integration wrapper, both variants"
	$(VERILATOR) --lint-only -Wall +incdir+$(RTL_DIR) --top-module tb_wrap_lint \
	  $(WRAP_LINT) $(RTL)

# Every parameter combination the design claims to support, because a generate
# branch that is never elaborated is a branch that is never checked.
# One configuration per line, because a make list cannot carry an argument group
# containing spaces through the shell's word splitting.
define LINT_CONFIGS
defaults
-GVariant=1
-GUseRReady=1
-GVariant=1 -GUseRReady=1
-GDataWidth=16 -GFracBits=13 -GNumStages=15
-GVariant=1 -GDataWidth=16 -GFracBits=13 -GNumStages=15
-GNumStages=5
-GNumStages=48
-GInDepth=8 -GOutDepth=2 -GGuardInt=1 -GGuardFrac=6
-GDataWidth=24 -GFracBits=20 -GNumStages=20 -GIdWidth=1
endef
export LINT_CONFIGS

lint-configs:
	@echo "== lint: parameter configurations"
	@set -e; while IFS= read -r cfg; do \
	  [ -n "$$cfg" ] || continue; \
	  printf '   %-62s' "$$cfg"; \
	  args=$$cfg; [ "$$cfg" = defaults ] && args=""; \
	  $(VERILATOR) --lint-only -Wall +incdir+$(RTL_DIR) --top-module cordic_accel \
	    $$args $(RTL) && echo "clean"; \
	done <<< "$$LINT_CONFIGS"

# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
SIM_ENV := PATH=$(VENV)/bin:$$PATH \
           CORDIC_ACC_SAMPLES=$(ACC_SAMPLES) \
           CORDIC_DOMAIN_SAMPLES=$(DOMAIN_SAMPLES) \
           CORDIC_EQUIV_SAMPLES=$(EQUIV_SAMPLES) \
           CORDIC_STREAM_OPS=$(STREAM_OPS)

# $(1) module, $(2) extra environment
define run_sim
	@echo "== sim: $(1) $(2)"
	@$(SIM_ENV) $(2) $(MAKE) -s -C $(TOP)/tb MODULE=$(1)
endef

test: $(VENV_OK) test-smoke test-accuracy test-domain test-obi test-throughput \
      test-equivalence test-reset
	@echo
	@echo "==== every simulation target passed ===="

test-smoke:
	$(call run_sim,test_smoke,)

test-accuracy:
	$(call run_sim,test_accuracy,)

test-domain:
	$(call run_sim,test_domain,)

# Both R-channel handshakes: Croc uses UseRReady=0, and 1 is the path where gnt
# actually has to fall.
test-obi:
	$(call run_sim,test_obi,CORDIC_USE_RREADY=0)
	$(call run_sim,test_obi,CORDIC_USE_RREADY=1)

test-throughput:
	$(call run_sim,test_throughput,CORDIC_VARIANT=0)
	$(call run_sim,test_throughput,CORDIC_VARIANT=1)

# Each variant records its results, then they are diffed word for word.
test-equivalence:
	$(call run_sim,test_equivalence,CORDIC_VARIANT=0)
	$(call run_sim,test_equivalence,CORDIC_VARIANT=1)
	@$(PY) $(TOP)/scripts/check_equivalence.py

test-reset:
	$(call run_sim,test_reset,CORDIC_VARIANT=0)
	$(call run_sim,test_reset,CORDIC_VARIANT=1)

# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------
synth: $(VENV_OK)
	$(PY) $(TOP)/scripts/run_synth.py

# The two headline configurations only, for a quicker turnaround.
synth-quick: $(VENV_OK)
	$(PY) $(TOP)/scripts/run_synth.py --quick

# ---------------------------------------------------------------------------
# Real IHP SG13G2 130nm, the process Croc taped out in
# ---------------------------------------------------------------------------
# Yosys maps to real sg13g2 cells against the slow-corner Liberty, OpenROAD's
# resizer repairs drive strength (unrepaired the netlist has min-size gates driving
# 0.7 pF nets, so its timing means nothing), then the one repaired netlist is timed
# at all three corners. See docs/pdk/README.md.
IHP_PDK_ROOT ?= $(HOME)/.local/share/pdk/IHP-Open-PDK/ihp-sg13g2
export IHP_PDK_ROOT

pdk: $(VENV_OK)
	$(PY) $(TOP)/scripts/run_pdk.py

pdk-quick: $(VENV_OK)
	$(PY) $(TOP)/scripts/run_pdk.py --quick

# Full RTL-to-GDS. Slower and optional; the headline numbers come from `make pdk`,
# and pnr/README.md says why timing is not taken from here.
pnr: $(VENV_OK)
	$(PY) $(TOP)/scripts/run_pnr.py

# Re-read the newest existing routing run into docs/pnr/summary.json. Useful when the
# metric list changes; routing again would take hours and give a different layout from
# the one already rendered and committed.
pnr-harvest: $(VENV_OK)
	$(PY) $(TOP)/scripts/run_pnr.py --harvest-only

layout:
	$(TOP)/scripts/run_pnr_render.sh

# ---------------------------------------------------------------------------
# Formal. Bounded equivalence of the two microarchitectures, which is a stronger
# claim than the random-vector equivalence test in tb/test_equivalence.py.
# Not part of `make all`: SymbiYosys is a separate install, and the bound is deep
# enough that the run is measured in minutes rather than seconds.
# ---------------------------------------------------------------------------
# FORMAL_TIMEOUT bounds each attempt, because none of them converges on the machine
# this was developed on and an unbounded run is indistinguishable from a hang. The
# wall time is printed either way, so an external interruption can be told apart from
# real non-convergence. formal/README.md records what was measured.
FORMAL_TIMEOUT ?= 1800
FORMAL_SBY     ?= obi_protocol equiv_tiny_1op equiv_tiny equiv_q3_13

formal:
	@command -v sby >/dev/null 2>&1 || { \
	  echo "sby (SymbiYosys) not on PATH; skipping the formal attempts"; \
	  exit 0; }
	@cd $(TOP)/formal && for f in $(FORMAL_SBY); do \
	  echo "== formal: $$f, bounded at $(FORMAL_TIMEOUT)s"; \
	  start=$$(date +%s); \
	  timeout $(FORMAL_TIMEOUT) sby -f $$f.sby; rc=$$?; \
	  el=$$(( $$(date +%s) - start )); \
	  if [ $$rc -eq 124 ]; then \
	    echo "   $$f: no result in $${el}s, the solver did not converge"; \
	  elif [ $$rc -ne 0 ]; then \
	    echo "   $$f: sby exited $$rc after $${el}s"; \
	  else \
	    echo "   $$f: PASS in $${el}s"; \
	  fi; \
	done

# ---------------------------------------------------------------------------
# Software
# ---------------------------------------------------------------------------
sw: sw-host sw-rv32

sw-host: sw-vectors
	@echo "== sw: host driver test"
	$(MAKE) -s -C $(TOP)/sw host
	$(TOP)/build/sw/test_cordic_host

# Skipped rather than failed when the cross toolchain is absent, and it says so.
# The freestanding link needs only gcc and libgcc, so it runs wherever the cross
# compiler does. The picolibc link needs a libc that ships separately
# (picolibc-riscv64-unknown-elf on Debian and Ubuntu), so it is attempted only when
# picolibc.specs is actually findable, and skipped out loud otherwise.
sw-rv32: sw-vectors
	@if ! command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then \
	  echo "== sw: RV32 image SKIPPED, riscv64-unknown-elf-gcc not on PATH"; \
	elif riscv64-unknown-elf-gcc -specs=picolibc.specs -E -x c /dev/null -o /dev/null \
	     >/dev/null 2>&1; then \
	  echo "== sw: RV32 images, freestanding and picolibc"; \
	  $(MAKE) -s -C $(TOP)/sw rv32 rv32-picolibc; \
	else \
	  echo "== sw: RV32 image, freestanding only"; \
	  echo "   picolibc.specs not found; install picolibc-riscv64-unknown-elf for the"; \
	  echo "   second link mode. Croc boots freestanding, so this is the one that matters."; \
	  $(MAKE) -s -C $(TOP)/sw rv32; \
	fi

# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
# The plots need build/results, which the simulation targets write, and
# docs/synth/summary.json, which make synth writes.
images: $(VENV_OK)
	@if [ ! -d $(TOP)/build/results ]; then \
	  echo "build/results is missing; run 'make test' first"; exit 1; fi
	@if [ ! -f $(TOP)/docs/synth/summary.json ]; then \
	  echo "docs/synth/summary.json is missing; run 'make synth' first"; exit 1; fi
	@if [ ! -f $(TOP)/docs/pdk/summary.json ]; then \
	  echo "docs/pdk/summary.json is missing; run 'make pdk' first"; exit 1; fi
	$(PY) $(TOP)/scripts/gen_plots.py $(PLOTS_NO_PNR)
	$(PY) $(TOP)/scripts/gen_svg.py
	$(PY) $(TOP)/scripts/gen_regmap.py
	@# The PnR figures and the layout renders need a place-and-route result. Skipped
	@# rather than failed when there is none, since PnR takes far longer than the rest
	@# of the flow and the other figures should not be held hostage to it.
	@if [ -f $(TOP)/docs/pnr/summary.json ]; then \
	  $(PY) $(TOP)/scripts/gen_plots.py pnr_comparison; \
	  $(TOP)/scripts/run_pnr_render.sh; \
	  $(PY) $(TOP)/scripts/gen_plots.py pnr_layouts; \
	else \
	  echo "docs/pnr/summary.json is missing; skipping the PnR figures and layout renders (run 'make pnr')"; \
	fi
	$(PY) $(TOP)/scripts/check_svg.py

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
clean:
	rm -rf $(TOP)/build $(TOP)/tb/sim_build $(TOP)/tb/results.xml \
	       $(TOP)/tb/__pycache__ $(TOP)/scripts/__pycache__ \
	       $(TOP)/obj_dir $(TOP)/tb/dump.vcd
	$(MAKE) -s -C $(TOP)/sw clean || true

distclean: clean
	rm -rf $(VENV)
