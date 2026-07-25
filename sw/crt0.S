/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Minimal RV32 startup for the freestanding driver test.
 *
 * Enough to reach main() with a stack and a zeroed .bss, and to park the core on
 * return with main's exit code in a0. Croc's own bootrom and testbench provide
 * the real entry sequence; this exists so `make sw` can prove the driver and test
 * actually link into a complete RV32 image.
 */

    .section .text.init, "ax"
    .globl _start
    .type _start, @function
_start:
    /* No interrupts, no traps expected. */
    csrw  mie, zero
    csrw  mstatus, zero

    /* norelax around the gp and sp setup: the linker would otherwise try to make
     * these gp-relative, and gp is not valid yet. It also stops _stack_top from
     * being reached through a gp offset that cannot span a larger RAM. */
    .option push
    .option norelax
    la    gp, __global_pointer$
    la    sp, _stack_top
    .option pop

    /* Clear .bss. */
    la    a0, _sbss
    la    a1, _ebss
1:  bgeu  a0, a1, 2f
    sw    zero, 0(a0)
    addi  a0, a0, 4
    j     1b

    /* Copy .data from LMA to VMA. Identical here, but harmless and correct if a
     * linker script ever splits them. */
2:  la    a0, _sidata
    la    a1, _sdata
    la    a2, _edata
3:  bgeu  a1, a2, 4f
    lw    a3, 0(a0)
    sw    a3, 0(a1)
    addi  a0, a0, 4
    addi  a1, a1, 4
    j     3b

4:  call  main
    /* Leave the exit code in a0 and stop. Croc's testbench watches for this. */
    .globl _exit
_exit:
5:  wfi
    j     5b
    .size _start, . - _start
