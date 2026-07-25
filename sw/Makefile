# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
#
# Two builds of one driver and one test program.
#
#   make host   gcc, links the register-accurate peripheral model in host/, runs
#               the test and reports. This is what verifies the driver.
#   make rv32   riscv64-unknown-elf-gcc, freestanding RV32IMC for Croc's CVE2.
#               Compiles and links, but is not executed: this repository has no
#               Croc simulation. Run it under Croc's own testbench.
#   make all    both.

TOPDIR   := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BUILD    ?= $(TOPDIR)/../build/sw
INC      := -I$(TOPDIR)/include -I$(TOPDIR)/host

WARN := -Wall -Wextra -Werror -Wshadow -Wconversion -Wsign-conversion \
        -Wstrict-prototypes -Wmissing-prototypes -Wpointer-arith \
        -Wcast-qual -Wundef

# --- host build -------------------------------------------------------------
HOST_CC     ?= gcc
HOST_CFLAGS := -std=c11 -O2 -g $(WARN) $(INC) -DCORDIC_HOST_SIM
HOST_SRCS   := $(TOPDIR)/cordic.c $(TOPDIR)/test_cordic.c $(TOPDIR)/host/cordic_sim.c
HOST_BIN    := $(BUILD)/test_cordic_host

# --- rv32 build -------------------------------------------------------------
# Croc's CVE2 is RV32IMC with Zicsr. Check the toolchain has the multilib with
#   riscv64-unknown-elf-gcc -print-multi-lib
RV_PREFIX ?= riscv64-unknown-elf-
RV_CC     := $(RV_PREFIX)gcc
RV_SIZE   := $(RV_PREFIX)size
RV_OBJDUMP:= $(RV_PREFIX)objdump
RV_ARCH   ?= rv32imc_zicsr
# How many of the generated vectors the target image carries. The table lives in
# .rodata and Croc's default SRAM is 8 KB (croc_pkg.sv: 2 banks of 1024 words), so
# the full set does not fit. The host build always runs all of them.
# The image lives in SRAM alongside its own stack, and stock Croc has 8 KB, so the
# default keeps 12 vectors. Measured totals at 64K RAM, for reference:
#   limit  8 -> 7172 bytes    limit 24 -> 8324
#   limit 12 -> 7456          limit 32 -> 8904
#   limit 16 -> 7748          limit 79 -> 12288
# `make rv32-full` builds all 79 against 16 KB, for a Croc with SramBankNumWords
# raised to 2048. The host build always runs the complete set.
RV_VEC_LIMIT ?= 12
# Target RAM. The default matches stock Croc: two SRAM banks of 1024 words.
RV_RAM_ORIGIN ?= 0x10000000
RV_RAM_SIZE   ?= 8K
RV_STACK_SIZE ?= 512
RV_ABI    ?= ilp32
# Freestanding: no libc, no start files. libgcc still comes in, for the 64-bit
# divide the fixed-point ratio helpers use.
# CORDIC_VEC_NO_NOTES drops the vector table's descriptive strings, which the
# target has nothing to print them to anyway.
RV_CFLAGS := -std=c11 -Os -g $(WARN) $(INC) \
             -march=$(RV_ARCH) -mabi=$(RV_ABI) \
             -ffreestanding -fno-builtin -fno-common \
             -ffunction-sections -fdata-sections \
             -DCORDIC_VEC_NO_NOTES -DCORDIC_VEC_LIMIT=$(RV_VEC_LIMIT)
# A single RWX LOAD segment is exactly right for a baremetal image running from
# SRAM, so the warning about it is noise here.
RV_LD_SCRIPT := $(BUILD)/link.ld
RV_LDFLAGS := -nostartfiles -nostdlib -Wl,--gc-sections \
              -Wl,--no-warn-rwx-segments \
              -T$(RV_LD_SCRIPT) -Wl,-Map=$(BUILD)/test_cordic_rv32.map
RV_LIBS   := -lgcc
RV_SRCS   := $(TOPDIR)/cordic.c $(TOPDIR)/test_cordic.c $(TOPDIR)/crt0.S
# The generated table's full length, so rv32-full can ask for all of it.
CORDIC_VEC_TOTAL := $(shell sed -n 's/^#define CORDIC_VEC_TOTAL \([0-9]*\).*/\1/p' \
                      $(TOPDIR)/host/cordic_vectors.h)
RV_ELF    := $(BUILD)/test_cordic_rv32.elf

.PHONY: all host rv32 rv32-full run clean check-toolchain

all: host rv32

$(BUILD):
	@mkdir -p $(BUILD)

host: $(HOST_BIN)

$(HOST_BIN): $(HOST_SRCS) $(TOPDIR)/include/cordic.h \
             $(TOPDIR)/include/cordic_regmap.h $(TOPDIR)/host/cordic_vectors.h | $(BUILD)
	$(HOST_CC) $(HOST_CFLAGS) $(HOST_SRCS) -o $@

run: $(HOST_BIN)
	$(HOST_BIN)

check-toolchain:
	@if ! command -v $(RV_CC) >/dev/null 2>&1; then \
	  echo "$(RV_CC) not found on PATH"; exit 1; fi
	@echo "$(RV_CC): $$($(RV_CC) -dumpversion)"
	@if ! $(RV_CC) -march=$(RV_ARCH) -mabi=$(RV_ABI) -E -x c /dev/null -o /dev/null \
	     >/dev/null 2>&1; then \
	  echo "no multilib for -march=$(RV_ARCH) -mabi=$(RV_ABI); available:"; \
	  $(RV_CC) -print-multi-lib; exit 1; fi
	@echo "multilib for $(RV_ARCH)/$(RV_ABI) is present"

rv32: check-toolchain $(RV_ELF)

$(RV_LD_SCRIPT): $(TOPDIR)/link.ld.in | $(BUILD)
	$(RV_CC) -E -P -x c \
	  -DCORDIC_RAM_ORIGIN=$(RV_RAM_ORIGIN) \
	  -DCORDIC_RAM_LENGTH=$(RV_RAM_SIZE) \
	  -DCORDIC_STACK_SIZE=$(RV_STACK_SIZE) \
	  $< -o $@

$(RV_ELF): $(RV_SRCS) $(RV_LD_SCRIPT) $(TOPDIR)/include/cordic.h \
           $(TOPDIR)/include/cordic_regmap.h $(TOPDIR)/host/cordic_vectors.h | $(BUILD)
	$(RV_CC) $(RV_CFLAGS) $(RV_LDFLAGS) $(RV_SRCS) $(RV_LIBS) -o $@
	@$(RV_SIZE) $@
	@$(RV_OBJDUMP) -d $@ > $(BUILD)/test_cordic_rv32.dis
	@echo "disassembly in $(BUILD)/test_cordic_rv32.dis"

# Every vector, for a Croc with more than the default SRAM.
rv32-full:
	$(MAKE) -f $(TOPDIR)/Makefile rv32 RV_VEC_LIMIT=$(CORDIC_VEC_TOTAL) \
	  RV_RAM_SIZE=16K BUILD=$(BUILD)/full

clean:
	rm -rf $(BUILD)
