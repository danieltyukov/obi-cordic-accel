# Baremetal driver

`cordic.c` plus `include/cordic.h`: freestanding, no libc, no floating point, no
allocation. Croc's CVE2 is RV32IMC with no FPU, so a float in the driver would pull
in soft-float routines costing more than the accelerator saves. Everything is
`int32_t` in the fixed-point format the hardware reports through `CFG0`.

`include/cordic_regmap.h` is generated from `scripts/cordic_regmap.py` alongside the
RTL's own offsets, so the driver cannot drift from the hardware.

## Two builds

    make host   # gcc, runs and reports
    make rv32   # riscv64-unknown-elf-gcc, freestanding RV32IMC for Croc
    make all

`make host` compiles `test_cordic.c` against the register-accurate peripheral model
in `host/` and runs it. That is what actually verifies the driver: register offsets
and field positions, the operand-then-GO write order, non-destructive result reads
followed by `CTRL.POP`, flag decoding, gain compensation, queue-full back-off, and
the error paths. It reports 626 checks.

The peripheral model does not compute CORDIC. It answers out of
`host/cordic_vectors.h`, generated from the same bit-accurate model that the RTL is
asserted against operation by operation. A second CORDIC written in C would only
show that two pieces of C agree with each other.

`make rv32` produces a complete, linked RV32IMC image. **It is not executed here:**
this repository carries no Croc simulation. Point `CORDIC_BASE` at the
accelerator's window and run it under Croc's own testbench. The image records its
outcome in the `cordic_test_report` symbol (magic `0x54455354`, then the check and
failure counts and the first failure's details) and returns the failure count in
`a0`, so a testbench can read the result straight out of memory. Define
`CORDIC_TEST_PUTC(c)` to route the log to Croc's UART.

## Toolchain

Verified with `riscv64-unknown-elf-gcc` 13.2.0. The build checks the multilib
itself:

    make check-toolchain

`-march=rv32imc_zicsr -mabi=ilp32` resolves to the `rv32im/ilp32` multilib, which
is present. `libgcc` is linked for `__divdi3`: the fixed-point ratio helpers use a
64-bit intermediate, which is what keeps them exact. Nothing else is linked.

## Fitting Croc's SRAM

Stock Croc has 8 KB of SRAM (`croc_pkg.sv`: `NumSramBanks = 2`,
`SramBankNumWords = 1024`), and the image runs from it with its own stack. The
vector table lives in `.rodata`, so the default build keeps 12 of the 79 vectors:

| `RV_VEC_LIMIT` | image bytes | | `RV_VEC_LIMIT` | image bytes |
|---------------:|------------:|-|---------------:|------------:|
| 8 | 7172 | | 24 | 8324 |
| 12 | 7456 | | 32 | 8904 |
| 16 | 7748 | | 79 | 12288 |

`make rv32-full` builds all 79 against 16 KB, for a Croc with `SramBankNumWords`
raised to 2048. Override `RV_VEC_LIMIT`, `RV_RAM_SIZE` and `RV_STACK_SIZE` to match
whatever you have. The wrapper-check operands are generated first, so they survive
any truncation.

## Call styles

    cordic_submit / cordic_poll   non-blocking; queue work, come back for it
    cordic_exec                   blocking, one operation
    cordic_exec_batch             blocking, keeps the input queue as full as it goes

plus one named wrapper per function (`cordic_sin_cos`, `cordic_atan2`,
`cordic_hypot`, `cordic_sinh_cosh`, `cordic_exp`, `cordic_ln`, `cordic_atanh`,
`cordic_mul`, `cordic_div`, `cordic_rotate`). The wrappers that return a
gain-carrying output (`cordic_hypot`, `cordic_rotate`) undo the gain for you; call
`cordic_exec` with the raw function code if you would rather keep it scaled.

## A note on CTRL

`CTRL`'s write-1-to-trigger bits sit in byte 0 and its persistent interrupt enables
in byte 1, and the driver writes them with byte stores. That split is not
cosmetic: the driver originally wrote whole words, and the host test caught that
every `CTRL.POP` was silently clearing the interrupt enables as a side effect.
