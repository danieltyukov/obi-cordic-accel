# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
#
# cocotb testbench. Verilator is the simulator: it is the only open tool on this
# machine that elaborates the design correctly. Icarus Verilog 12 folds constant
# functions over packed arrays to the wrong value and is therefore unusable here
# (see docs/DESIGN.md, "Tool support").

TOPDIR    := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))/..
SIM       ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL  ?= cordic_accel
MODULE    ?= test_smoke

# Elaboration parameters. Exported so the Python side builds a model matching the
# hardware actually compiled.
CORDIC_DATA_WIDTH  ?= 32
CORDIC_FRAC_BITS   ?= 29
CORDIC_NUM_STAGES  ?= 28
CORDIC_GUARD_INT   ?= 2
CORDIC_GUARD_FRAC  ?= 4
CORDIC_VARIANT     ?= 0
CORDIC_USE_RREADY  ?= 0
CORDIC_IN_DEPTH    ?= 4
CORDIC_OUT_DEPTH   ?= 4

export CORDIC_DATA_WIDTH CORDIC_FRAC_BITS CORDIC_NUM_STAGES
export CORDIC_GUARD_INT CORDIC_GUARD_FRAC CORDIC_VARIANT
export CORDIC_USE_RREADY CORDIC_IN_DEPTH CORDIC_OUT_DEPTH

VERILOG_SOURCES := \
  $(TOPDIR)/rtl/cordic_stage.sv \
  $(TOPDIR)/rtl/cordic_core_pipe.sv \
  $(TOPDIR)/rtl/cordic_core_iter.sv \
  $(TOPDIR)/rtl/cordic_pre.sv \
  $(TOPDIR)/rtl/cordic_post.sv \
  $(TOPDIR)/rtl/cordic_unit.sv \
  $(TOPDIR)/rtl/cordic_fifo.sv \
  $(TOPDIR)/rtl/cordic_obi_regs.sv \
  $(TOPDIR)/rtl/cordic_accel.sv

# Distinct build directory per configuration, so the parameter sweeps in the test
# suite do not keep invalidating each other's Verilator build.
SIM_BUILD ?= sim_build/$(SIM)_$(TOPLEVEL)_w$(CORDIC_DATA_WIDTH)_f$(CORDIC_FRAC_BITS)_n$(CORDIC_NUM_STAGES)_v$(CORDIC_VARIANT)_r$(CORDIC_USE_RREADY)_i$(CORDIC_IN_DEPTH)_o$(CORDIC_OUT_DEPTH)

VERILOG_INCLUDE_DIRS += $(TOPDIR)/rtl
COMPILE_ARGS += -Wno-fatal
COMPILE_ARGS += -GDataWidth=$(CORDIC_DATA_WIDTH)
COMPILE_ARGS += -GFracBits=$(CORDIC_FRAC_BITS)
COMPILE_ARGS += -GNumStages=$(CORDIC_NUM_STAGES)
COMPILE_ARGS += -GGuardInt=$(CORDIC_GUARD_INT)
COMPILE_ARGS += -GGuardFrac=$(CORDIC_GUARD_FRAC)
COMPILE_ARGS += -GVariant=$(CORDIC_VARIANT)
COMPILE_ARGS += -GUseRReady=$(CORDIC_USE_RREADY)
COMPILE_ARGS += -GInDepth=$(CORDIC_IN_DEPTH)
COMPILE_ARGS += -GOutDepth=$(CORDIC_OUT_DEPTH)

ifeq ($(WAVES),1)
VERILATOR_TRACE := 1
export VERILATOR_TRACE
endif

include $(shell cocotb-config --makefiles)/Makefile.sim
