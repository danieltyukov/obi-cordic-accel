/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * GENERATED FILE - DO NOT EDIT.
 * Produced by scripts/gen_sw_vectors.py from tb/cordic_model.py.
 * Regenerate with `make sw-vectors`.
 *
 * Test vectors for the C driver. Every expected result word came out of the
 * bit-accurate model that the RTL is asserted against operation by operation, so
 * these are hardware results, not a second implementation's opinion.
 */

#ifndef CORDIC_VECTORS_H
#define CORDIC_VECTORS_H

#include <stdint.h>


#define CORDIC_VEC_DATA_WIDTH 32
#define CORDIC_VEC_FRAC_BITS  29
#define CORDIC_VEC_NUM_STAGES 28
#define CORDIC_VEC_GUARD_INT  2
#define CORDIC_VEC_GUARD_FRAC 4

/* Constants the peripheral model reports, in the working format. */
#define CORDIC_VEC_K_CIRC 884097682
#define CORDIC_VEC_IK_CIRC 326016437
#define CORDIC_VEC_K_HYP 444614671
#define CORDIC_VEC_IK_HYP 648270052
#define CORDIC_VEC_LIM_CIRC 935919873
#define CORDIC_VEC_LIM_HYP 600314558
#define CORDIC_VEC_LIM_LIN 1073741820
#define CORDIC_VEC_TANH_LIM_HYP 433218581

#define CORDIC_VEC_MAX_CHECKS 2

typedef struct {
  const char *label;   /* which wrapper output this is */
  char        out;     /* 'x', 'y' or 'z' */
  int32_t     expected; /* double-precision reference, in the format */
  int32_t     tol_lsb;  /* documented bound, in LSBs */
} cordic_vec_check_t;

/* The note strings are only used by the host build's log. Define
 * CORDIC_VEC_NO_NOTES to drop them, which the RV32 build does: Croc's
 * default SRAM is 8 KB and the strings alone are around 2 KB. */
#if defined(CORDIC_VEC_NO_NOTES)
#define CORDIC_VEC_NOTE(s) 0
#else
#define CORDIC_VEC_NOTE(s) (s)
#endif

typedef struct {
  const char *note;
  uint8_t     func;
  int32_t     x, y, z;          /* operands */
  int32_t     rx, ry, rz;       /* exact result words */
  uint32_t    flags;            /* exact RES_FLAGS bits 3:0 */
  int         n_checks;
  cordic_vec_check_t checks[CORDIC_VEC_MAX_CHECKS];
} cordic_vec_t;

/* 79 vectors are defined. A build may keep only the first
 * CORDIC_VEC_LIMIT of them, which is how the RV32 image fits Croc's
 * default 8 KB SRAM. The wrapper-check operands come first so they
 * always survive truncation. */
#define CORDIC_VEC_TOTAL 79
#if !defined(CORDIC_VEC_LIMIT)
#define CORDIC_VEC_LIMIT CORDIC_VEC_TOTAL
#endif

static const cordic_vec_t cordic_vectors[] = {
#if 0 < CORDIC_VEC_LIMIT
  { /* [0] SIN_COS: wrapper: sin/cos(0) */
    CORDIC_VEC_NOTE("wrapper: sin/cos(0)"), 0,
    0, 0, 0,
    536870912, -2, 2, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', 536870912, 27}, {CORDIC_VEC_NOTE("sin"), 'y', 0, 27}} },
#endif
#if 1 < CORDIC_VEC_LIMIT
  { /* [1] ATAN2: wrapper: atan2(0, 1) and hypot(1, 0) */
    CORDIC_VEC_NOTE("wrapper: atan2(0, 1) and hypot(1, 0)"), 2,
    536870912, 0, 0,
    884097682, 3, -2, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', 0, 23}, {CORDIC_VEC_NOTE("hypot"), 'x', 536870912, 28}} },
#endif
#if 2 < CORDIC_VEC_LIMIT
  { /* [2] EXP: wrapper: exp(0) */
    CORDIC_VEC_NOTE("wrapper: exp(0)"), 6,
    0, 0, 0,
    536870914, 536870914, -2, 0x0u,
    1, {{CORDIC_VEC_NOTE("exp"), 'x', 536870912, 27}} },
#endif
#if 3 < CORDIC_VEC_LIMIT
  { /* [3] LN: wrapper: ln(1) */
    CORDIC_VEC_NOTE("wrapper: ln(1)"), 7,
    536870912, 0, 0,
    444614671, -1, 4, 0x0u,
    1, {{CORDIC_VEC_NOTE("ln"), 'z', 0, 50}} },
#endif
#if 4 < CORDIC_VEC_LIMIT
  { /* [4] MUL: wrapper: 1 * 1 */
    CORDIC_VEC_NOTE("wrapper: 1 * 1"), 8,
    536870912, 0, 536870912,
    536870912, 536870916, -4, 0x0u,
    1, {{CORDIC_VEC_NOTE("mul"), 'y', 536870912, 11}} },
#endif
#if 5 < CORDIC_VEC_LIMIT
  { /* [5] DIV: wrapper: 1 / 2 */
    CORDIC_VEC_NOTE("wrapper: 1 / 2"), 9,
    1073741824, 536870912, 0,
    1073741824, -8, 268435460, 0x0u,
    1, {{CORDIC_VEC_NOTE("div"), 'z', 268435456, 8}} },
#endif
#if 6 < CORDIC_VEC_LIMIT
  { /* [6] ROTATE: wrapper: rotate identity */
    CORDIC_VEC_NOTE("wrapper: rotate identity"), 1,
    536870912, 0, 0,
    884097682, -3, 2, 0x0u,
    2, {{CORDIC_VEC_NOTE("rot_x"), 'x', 536870912, 28}, {CORDIC_VEC_NOTE("rot_y"), 'y', 0, 28}} },
#endif
#if 7 < CORDIC_VEC_LIMIT
  { /* [7] EXP: wrapper: exp out of domain */
    CORDIC_VEC_NOTE("wrapper: exp out of domain"), 6,
    0, 0, 900471837,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 8 < CORDIC_VEC_LIMIT
  { /* [8] LN: wrapper: ln(0), out of domain */
    CORDIC_VEC_NOTE("wrapper: ln(0), out of domain"), 7,
    0, 0, 0,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 9 < CORDIC_VEC_LIMIT
  { /* [9] DIV: wrapper: divide by zero */
    CORDIC_VEC_NOTE("wrapper: divide by zero"), 9,
    0, 536870912, 0,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 10 < CORDIC_VEC_LIMIT
  { /* [10] SIN_COS: sin/cos(+0.5000) */
    CORDIC_VEC_NOTE("sin/cos(+0.5000)"), 0,
    0, 0, 268435456,
    471148552, 257389623, 3, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', 471148550, 27}, {CORDIC_VEC_NOTE("sin"), 'y', 257389626, 27}} },
#endif
#if 11 < CORDIC_VEC_LIMIT
  { /* [11] SIN_COS: sin/cos(-0.5000) */
    CORDIC_VEC_NOTE("sin/cos(-0.5000)"), 0,
    0, 0, -268435456,
    471148552, -257389623, -3, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', 471148550, 27}, {CORDIC_VEC_NOTE("sin"), 'y', -257389626, 27}} },
#endif
#if 12 < CORDIC_VEC_LIMIT
  { /* [12] SIN_COS: sin/cos(+1.0000) */
    CORDIC_VEC_NOTE("sin/cos(+1.0000)"), 0,
    0, 0, 536870912,
    290072591, 451761296, -1, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', 290072592, 27}, {CORDIC_VEC_NOTE("sin"), 'y', 451761295, 27}} },
#endif
#if 13 < CORDIC_VEC_LIMIT
  { /* [13] SIN_COS: sin/cos(-1.0000) */
    CORDIC_VEC_NOTE("sin/cos(-1.0000)"), 0,
    0, 0, -536870912,
    290072591, -451761296, 1, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', 290072592, 27}, {CORDIC_VEC_NOTE("sin"), 'y', -451761295, 27}} },
#endif
#if 14 < CORDIC_VEC_LIMIT
  { /* [14] SIN_COS: sin/cos(+0.7854) */
    CORDIC_VEC_NOTE("sin/cos(+0.7854)"), 0,
    0, 0, 421657428,
    379625060, 379625065, -3, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', 379625063, 27}, {CORDIC_VEC_NOTE("sin"), 'y', 379625062, 27}} },
#endif
#if 15 < CORDIC_VEC_LIMIT
  { /* [15] SIN_COS: sin/cos(+1.5708) */
    CORDIC_VEC_NOTE("sin/cos(+1.5708)"), 0,
    0, 0, 843314857,
    2, 536870913, 3, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', 0, 27}, {CORDIC_VEC_NOTE("sin"), 'y', 536870912, 27}} },
#endif
#if 16 < CORDIC_VEC_LIMIT
  { /* [16] SIN_COS: sin/cos(-1.5708) */
    CORDIC_VEC_NOTE("sin/cos(-1.5708)"), 0,
    0, 0, -843314857,
    2, -536870912, -3, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', 0, 27}, {CORDIC_VEC_NOTE("sin"), 'y', -536870912, 27}} },
#endif
#if 17 < CORDIC_VEC_LIMIT
  { /* [17] SIN_COS: sin/cos(+3.1416) */
    CORDIC_VEC_NOTE("sin/cos(+3.1416)"), 0,
    0, 0, 1686629713,
    -536870912, -2, -2, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', -536870912, 27}, {CORDIC_VEC_NOTE("sin"), 'y', 0, 27}} },
#endif
#if 18 < CORDIC_VEC_LIMIT
  { /* [18] SIN_COS: sin/cos(-3.1416) */
    CORDIC_VEC_NOTE("sin/cos(-3.1416)"), 0,
    0, 0, -1686629713,
    -536870912, 2, 2, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', -536870912, 27}, {CORDIC_VEC_NOTE("sin"), 'y', 0, 27}} },
#endif
#if 19 < CORDIC_VEC_LIMIT
  { /* [19] SIN_COS: sin/cos(+2.5000) */
    CORDIC_VEC_NOTE("sin/cos(+2.5000)"), 0,
    0, 0, 1342177280,
    -430110706, 321302283, -3, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', -430110704, 27}, {CORDIC_VEC_NOTE("sin"), 'y', 321302286, 27}} },
#endif
#if 20 < CORDIC_VEC_LIMIT
  { /* [20] SIN_COS: sin/cos(-2.5000) */
    CORDIC_VEC_NOTE("sin/cos(-2.5000)"), 0,
    0, 0, -1342177280,
    -430110706, -321302283, 3, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', -430110704, 27}, {CORDIC_VEC_NOTE("sin"), 'y', -321302286, 27}} },
#endif
#if 21 < CORDIC_VEC_LIMIT
  { /* [21] SIN_COS: sin/cos(+3.9000) */
    CORDIC_VEC_NOTE("sin/cos(+3.9000)"), 0,
    0, 0, 2093796557,
    -389731939, -369241644, 2, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', -389731938, 27}, {CORDIC_VEC_NOTE("sin"), 'y', -369241645, 27}} },
#endif
#if 22 < CORDIC_VEC_LIMIT
  { /* [22] SIN_COS: sin/cos(-3.9000) */
    CORDIC_VEC_NOTE("sin/cos(-3.9000)"), 0,
    0, 0, -2093796557,
    -389731939, 369241644, -2, 0x0u,
    2, {{CORDIC_VEC_NOTE("cos"), 'x', -389731938, 27}, {CORDIC_VEC_NOTE("sin"), 'y', 369241645, 27}} },
#endif
#if 23 < CORDIC_VEC_LIMIT
  { /* [23] ATAN2: atan2(+1.00, +0.00) */
    CORDIC_VEC_NOTE("atan2(+1.00, +0.00)"), 2,
    0, 536870912, 0,
    884097682, -3, 843314859, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', 843314857, 23}, {CORDIC_VEC_NOTE("hypot"), 'x', 536870912, 28}} },
#endif
#if 24 < CORDIC_VEC_LIMIT
  { /* [24] ATAN2: atan2(+0.00, -1.00) */
    CORDIC_VEC_NOTE("atan2(+0.00, -1.00)"), 2,
    -536870912, 0, 0,
    884097682, 3, 1686629711, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', 1686629713, 23}, {CORDIC_VEC_NOTE("hypot"), 'x', 536870912, 28}} },
#endif
#if 25 < CORDIC_VEC_LIMIT
  { /* [25] ATAN2: atan2(-1.00, +0.00) */
    CORDIC_VEC_NOTE("atan2(-1.00, +0.00)"), 2,
    0, -536870912, 0,
    884097682, 3, -843314859, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', -843314857, 23}, {CORDIC_VEC_NOTE("hypot"), 'x', 536870912, 28}} },
#endif
#if 26 < CORDIC_VEC_LIMIT
  { /* [26] ATAN2: atan2(+1.00, +1.00) */
    CORDIC_VEC_NOTE("atan2(+1.00, +1.00)"), 2,
    536870912, 536870912, 0,
    1250302932, 8, 421657425, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', 421657428, 21}, {CORDIC_VEC_NOTE("hypot"), 'x', 759250125, 37}} },
#endif
#if 27 < CORDIC_VEC_LIMIT
  { /* [27] ATAN2: atan2(+1.00, -1.00) */
    CORDIC_VEC_NOTE("atan2(+1.00, -1.00)"), 2,
    -536870912, 536870912, 0,
    1250302932, 8, 1264972282, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', 1264972285, 21}, {CORDIC_VEC_NOTE("hypot"), 'x', 759250125, 37}} },
#endif
#if 28 < CORDIC_VEC_LIMIT
  { /* [28] ATAN2: atan2(-1.00, -1.00) */
    CORDIC_VEC_NOTE("atan2(-1.00, -1.00)"), 2,
    -536870912, -536870912, 0,
    1250302932, 8, -1264972288, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', -1264972285, 21}, {CORDIC_VEC_NOTE("hypot"), 'x', 759250125, 37}} },
#endif
#if 29 < CORDIC_VEC_LIMIT
  { /* [29] ATAN2: atan2(-1.00, +1.00) */
    CORDIC_VEC_NOTE("atan2(-1.00, +1.00)"), 2,
    536870912, -536870912, 0,
    1250302932, 8, -421657431, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', -421657428, 21}, {CORDIC_VEC_NOTE("hypot"), 'x', 759250125, 37}} },
#endif
#if 30 < CORDIC_VEC_LIMIT
  { /* [30] ATAN2: atan2(+0.80, +0.60) */
    CORDIC_VEC_NOTE("atan2(+0.80, +0.60)"), 2,
    322122547, 429496730, 0,
    884097682, 4, 497837827, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', 497837830, 23}, {CORDIC_VEC_NOTE("hypot"), 'x', 536870912, 28}} },
#endif
#if 31 < CORDIC_VEC_LIMIT
  { /* [31] ATAN2: atan2(-0.80, -0.60) */
    CORDIC_VEC_NOTE("atan2(-0.80, -0.60)"), 2,
    -322122547, -429496730, 0,
    884097682, 4, -1188791886, 0x0u,
    2, {{CORDIC_VEC_NOTE("atan2"), 'z', -1188791883, 23}, {CORDIC_VEC_NOTE("hypot"), 'x', 536870912, 28}} },
#endif
#if 32 < CORDIC_VEC_LIMIT
  { /* [32] ATAN2: atan2(0, 0), defined as zero */
    CORDIC_VEC_NOTE("atan2(0, 0), defined as zero"), 2,
    0, 0, 0,
    0, 0, 0, 0x0u,
    1, {{CORDIC_VEC_NOTE("hypot"), 'x', 0, 5}} },
#endif
#if 33 < CORDIC_VEC_LIMIT
  { /* [33] SINH_COSH: sinh/cosh(+0.000000) */
    CORDIC_VEC_NOTE("sinh/cosh(+0.000000)"), 3,
    0, 0, 0,
    536870912, 2, -2, 0x0u,
    2, {{CORDIC_VEC_NOTE("cosh"), 'x', 536870912, 27}, {CORDIC_VEC_NOTE("sinh"), 'y', 0, 27}} },
#endif
#if 34 < CORDIC_VEC_LIMIT
  { /* [34] SINH_COSH: sinh/cosh(+0.250000) */
    CORDIC_VEC_NOTE("sinh/cosh(+0.250000)"), 3,
    0, 0, 134217728,
    553735693, 135620212, -7, 0x0u,
    2, {{CORDIC_VEC_NOTE("cosh"), 'x', 553735692, 34}, {CORDIC_VEC_NOTE("sinh"), 'y', 135620205, 34}} },
#endif
#if 35 < CORDIC_VEC_LIMIT
  { /* [35] EXP: exp(+0.250000) */
    CORDIC_VEC_NOTE("exp(+0.250000)"), 6,
    0, 0, 134217728,
    689355906, 689355906, -7, 0x0u,
    1, {{CORDIC_VEC_NOTE("exp"), 'x', 689355896, 34}} },
#endif
#if 36 < CORDIC_VEC_LIMIT
  { /* [36] SINH_COSH: sinh/cosh(-0.250000) */
    CORDIC_VEC_NOTE("sinh/cosh(-0.250000)"), 3,
    0, 0, -134217728,
    553735693, -135620212, 7, 0x0u,
    2, {{CORDIC_VEC_NOTE("cosh"), 'x', 553735692, 34}, {CORDIC_VEC_NOTE("sinh"), 'y', -135620205, 34}} },
#endif
#if 37 < CORDIC_VEC_LIMIT
  { /* [37] EXP: exp(-0.250000) */
    CORDIC_VEC_NOTE("exp(-0.250000)"), 6,
    0, 0, -134217728,
    418115481, 418115481, 7, 0x0u,
    1, {{CORDIC_VEC_NOTE("exp"), 'x', 418115487, 34}} },
#endif
#if 38 < CORDIC_VEC_LIMIT
  { /* [38] SINH_COSH: sinh/cosh(+0.900000) */
    CORDIC_VEC_NOTE("sinh/cosh(+0.900000)"), 3,
    0, 0, 483183821,
    769382390, 551106964, 5, 0x0u,
    2, {{CORDIC_VEC_NOTE("cosh"), 'x', 769382395, 61}, {CORDIC_VEC_NOTE("sinh"), 'y', 551106971, 61}} },
#endif
#if 39 < CORDIC_VEC_LIMIT
  { /* [39] EXP: exp(+0.900000) */
    CORDIC_VEC_NOTE("exp(+0.900000)"), 6,
    0, 0, 483183821,
    1320489353, 1320489353, 5, 0x0u,
    1, {{CORDIC_VEC_NOTE("exp"), 'x', 1320489366, 61}} },
#endif
#if 40 < CORDIC_VEC_LIMIT
  { /* [40] SINH_COSH: sinh/cosh(-0.900000) */
    CORDIC_VEC_NOTE("sinh/cosh(-0.900000)"), 3,
    0, 0, -483183821,
    769382390, -551106964, -5, 0x0u,
    2, {{CORDIC_VEC_NOTE("cosh"), 'x', 769382395, 61}, {CORDIC_VEC_NOTE("sinh"), 'y', -551106971, 61}} },
#endif
#if 41 < CORDIC_VEC_LIMIT
  { /* [41] EXP: exp(-0.900000) */
    CORDIC_VEC_NOTE("exp(-0.900000)"), 6,
    0, 0, -483183821,
    218275426, 218275426, -5, 0x0u,
    1, {{CORDIC_VEC_NOTE("exp"), 'x', 218275424, 61}} },
#endif
#if 42 < CORDIC_VEC_LIMIT
  { /* [42] SINH_COSH: sinh/cosh(+1.118173) */
    CORDIC_VEC_NOTE("sinh/cosh(+1.118173)"), 3,
    0, 0, 600314558,
    908959036, 733468577, -1, 0x0u,
    2, {{CORDIC_VEC_NOTE("cosh"), 'x', 908959036, 75}, {CORDIC_VEC_NOTE("sinh"), 'y', 733468576, 75}} },
#endif
#if 43 < CORDIC_VEC_LIMIT
  { /* [43] EXP: exp(+1.118173) */
    CORDIC_VEC_NOTE("exp(+1.118173)"), 6,
    0, 0, 600314558,
    1642427613, 1642427613, -1, 0x0u,
    1, {{CORDIC_VEC_NOTE("exp"), 'x', 1642427612, 75}} },
#endif
#if 44 < CORDIC_VEC_LIMIT
  { /* [44] SINH_COSH: sinh/cosh(-1.118173) */
    CORDIC_VEC_NOTE("sinh/cosh(-1.118173)"), 3,
    0, 0, -600314558,
    908959037, -733468577, 1, 0x0u,
    2, {{CORDIC_VEC_NOTE("cosh"), 'x', 908959036, 75}, {CORDIC_VEC_NOTE("sinh"), 'y', -733468576, 75}} },
#endif
#if 45 < CORDIC_VEC_LIMIT
  { /* [45] EXP: exp(-1.118173) */
    CORDIC_VEC_NOTE("exp(-1.118173)"), 6,
    0, 0, -600314558,
    175490460, 175490460, 1, 0x0u,
    1, {{CORDIC_VEC_NOTE("exp"), 'x', 175490459, 75}} },
#endif
#if 46 < CORDIC_VEC_LIMIT
  { /* [46] SINH_COSH: sinh out of domain */
    CORDIC_VEC_NOTE("sinh out of domain"), 3,
    0, 0, 900471837,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 47 < CORDIC_VEC_LIMIT
  { /* [47] EXP: exp out of domain */
    CORDIC_VEC_NOTE("exp out of domain"), 6,
    0, 0, -900471837,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 48 < CORDIC_VEC_LIMIT
  { /* [48] LN: ln(0.106848) */
    CORDIC_VEC_NOTE("ln(0.106848)"), 7,
    57363699, 0, 0,
    145334066, 0, -1200629117, 0x0u,
    1, {{CORDIC_VEC_NOTE("ln"), 'z', -1200629115, 109}} },
#endif
#if 49 < CORDIC_VEC_LIMIT
  { /* [49] LN: ln(0.500000) */
    CORDIC_VEC_NOTE("ln(0.500000)"), 7,
    268435456, 0, 0,
    314390049, -4, -372130546, 0x0u,
    1, {{CORDIC_VEC_NOTE("ln"), 'z', -372130559, 57}} },
#endif
#if 50 < CORDIC_VEC_LIMIT
  { /* [50] LN: ln(2.718282) */
    CORDIC_VEC_NOTE("ln(2.718282)"), 7,
    1459366444, 0, 0,
    733045666, -8, 536870923, 0x0u,
    1, {{CORDIC_VEC_NOTE("ln"), 'z', 536870912, 46}} },
#endif
#if 51 < CORDIC_VEC_LIMIT
  { /* [51] LN: ln(2.000000) */
    CORDIC_VEC_NOTE("ln(2.000000)"), 7,
    1073741824, 0, 0,
    628780098, 7, 372130546, 0x0u,
    1, {{CORDIC_VEC_NOTE("ln"), 'z', 372130559, 47}} },
#endif
#if 52 < CORDIC_VEC_LIMIT
  { /* [52] LN: ln(3.500000) */
    CORDIC_VEC_NOTE("ln(3.500000)"), 7,
    1879048192, 0, 0,
    831797884, 8, 672571988, 0x0u,
    1, {{CORDIC_VEC_NOTE("ln"), 'z', 672571997, 45}} },
#endif
#if 53 < CORDIC_VEC_LIMIT
  { /* [53] LN: ln(-1), out of domain */
    CORDIC_VEC_NOTE("ln(-1), out of domain"), 7,
    -536870912, 0, 0,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 54 < CORDIC_VEC_LIMIT
  { /* [54] ATANH: atanh(+0.0000) */
    CORDIC_VEC_NOTE("atanh(+0.0000)"), 5,
    536870912, 0, 0,
    444614671, -1, 2, 0x0u,
    1, {{CORDIC_VEC_NOTE("atanh"), 'z', 0, 27}} },
#endif
#if 55 < CORDIC_VEC_LIMIT
  { /* [55] ATANH: atanh(+0.5000) */
    CORDIC_VEC_NOTE("atanh(+0.5000)"), 5,
    536870912, 268435456, 0,
    385047600, 3, 294906487, 0x0u,
    1, {{CORDIC_VEC_NOTE("atanh"), 'z', 294906491, 30}} },
#endif
#if 56 < CORDIC_VEC_LIMIT
  { /* [56] ATANH: atanh(-0.5000) */
    CORDIC_VEC_NOTE("atanh(-0.5000)"), 5,
    536870912, -268435456, 0,
    385047600, 3, -294906494, 0x0u,
    1, {{CORDIC_VEC_NOTE("atanh"), 'z', -294906491, 30}} },
#endif
#if 57 < CORDIC_VEC_LIMIT
  { /* [57] ATANH: atanh(+0.7500) */
    CORDIC_VEC_NOTE("atanh(+0.7500)"), 5,
    1073741824, 805306368, 0,
    588169925, 0, 522351279, 0x0u,
    1, {{CORDIC_VEC_NOTE("atanh"), 'z', 522351278, 28}} },
#endif
#if 58 < CORDIC_VEC_LIMIT
  { /* [58] ATANH: atanh(+0.5000) */
    CORDIC_VEC_NOTE("atanh(+0.5000)"), 5,
    -536870912, 268435456, 0,
    385047600, 3, -294906494, 0x0u,
    1, {{CORDIC_VEC_NOTE("atanh"), 'z', -294906491, 30}} },
#endif
#if 59 < CORDIC_VEC_LIMIT
  { /* [59] ATANH: atanh(+0.8069) */
    CORDIC_VEC_NOTE("atanh(+0.8069)"), 5,
    536870912, 433218581, 0,
    262608847, 1, 600314559, 0x0u,
    1, {{CORDIC_VEC_NOTE("atanh"), 'z', 600314558, 41}} },
#endif
#if 60 < CORDIC_VEC_LIMIT
  { /* [60] ATANH: atanh out of domain */
    CORDIC_VEC_NOTE("atanh out of domain"), 5,
    536870912, 510027366, 0,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 61 < CORDIC_VEC_LIMIT
  { /* [61] ATANH: atanh with a zero denominator */
    CORDIC_VEC_NOTE("atanh with a zero denominator"), 5,
    0, 268435456, 0,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 62 < CORDIC_VEC_LIMIT
  { /* [62] MUL: +1.500 * +0.500 */
    CORDIC_VEC_NOTE("+1.500 * +0.500"), 8,
    805306368, 0, 268435456,
    805306368, 402653190, -4, 0x0u,
    1, {{CORDIC_VEC_NOTE("mul"), 'y', 402653184, 15}} },
#endif
#if 63 < CORDIC_VEC_LIMIT
  { /* [63] MUL: -2.000 * +0.250 */
    CORDIC_VEC_NOTE("-2.000 * +0.250"), 8,
    -1073741824, 0, 134217728,
    -1073741824, -268435464, -4, 0x0u,
    1, {{CORDIC_VEC_NOTE("mul"), 'y', -268435456, 18}} },
#endif
#if 64 < CORDIC_VEC_LIMIT
  { /* [64] MUL: +2.500 * -0.750 */
    CORDIC_VEC_NOTE("+2.500 * -0.750"), 8,
    1342177280, 0, -402653184,
    1342177280, -1006632950, -4, 0x0u,
    1, {{CORDIC_VEC_NOTE("mul"), 'y', -1006632960, 22}} },
#endif
#if 65 < CORDIC_VEC_LIMIT
  { /* [65] MUL: +0.000 * +1.000 */
    CORDIC_VEC_NOTE("+0.000 * +1.000"), 8,
    0, 0, 536870912,
    0, 0, -4, 0x0u,
    1, {{CORDIC_VEC_NOTE("mul"), 'y', 0, 4}} },
#endif
#if 66 < CORDIC_VEC_LIMIT
  { /* [66] MUL: +1.000 * +2.000 */
    CORDIC_VEC_NOTE("+1.000 * +2.000"), 8,
    536870912, 0, 1073741820,
    536870912, 1073741820, 0, 0x0u,
    1, {{CORDIC_VEC_NOTE("mul"), 'y', 1073741820, 11}} },
#endif
#if 67 < CORDIC_VEC_LIMIT
  { /* [67] MUL: multiply out of domain */
    CORDIC_VEC_NOTE("multiply out of domain"), 8,
    536870912, 0, 1610612730,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 68 < CORDIC_VEC_LIMIT
  { /* [68] DIV: +0.500 / +1.000 */
    CORDIC_VEC_NOTE("+0.500 / +1.000"), 9,
    536870912, 268435456, 0,
    536870912, -4, 268435460, 0x0u,
    1, {{CORDIC_VEC_NOTE("div"), 'z', 268435456, 11}} },
#endif
#if 69 < CORDIC_VEC_LIMIT
  { /* [69] DIV: -0.500 / +1.000 */
    CORDIC_VEC_NOTE("-0.500 / +1.000"), 9,
    536870912, -268435456, 0,
    536870912, -4, -268435452, 0x0u,
    1, {{CORDIC_VEC_NOTE("div"), 'z', -268435456, 11}} },
#endif
#if 70 < CORDIC_VEC_LIMIT
  { /* [70] DIV: +1.000 / -2.000 */
    CORDIC_VEC_NOTE("+1.000 / -2.000"), 9,
    -1073741824, 536870912, 0,
    1073741824, -8, -268435452, 0x0u,
    1, {{CORDIC_VEC_NOTE("div"), 'z', -268435456, 8}} },
#endif
#if 71 < CORDIC_VEC_LIMIT
  { /* [71] DIV: +3.000 / +2.000 */
    CORDIC_VEC_NOTE("+3.000 / +2.000"), 9,
    1073741824, 1610612736, 0,
    1073741824, -8, 805306372, 0x0u,
    1, {{CORDIC_VEC_NOTE("div"), 'z', 805306368, 8}} },
#endif
#if 72 < CORDIC_VEC_LIMIT
  { /* [72] DIV: +0.000 / +1.000 */
    CORDIC_VEC_NOTE("+0.000 / +1.000"), 9,
    536870912, 0, 0,
    536870912, -4, 4, 0x0u,
    1, {{CORDIC_VEC_NOTE("div"), 'z', 0, 11}} },
#endif
#if 73 < CORDIC_VEC_LIMIT
  { /* [73] DIV: divide out of domain */
    CORDIC_VEC_NOTE("divide out of domain"), 9,
    536870912, 1610612736, 0,
    0, 0, 0, 0x1u,
    0, {{0, 0, 0, 0}} },
#endif
#if 74 < CORDIC_VEC_LIMIT
  { /* [74] ROTATE: rotate by +0.5000 */
    CORDIC_VEC_NOTE("rotate by +0.5000"), 1,
    536870912, 0, 268435456,
    775868711, 423859002, 3, 0x0u,
    2, {{CORDIC_VEC_NOTE("rot_x"), 'x', 471148550, 28}, {CORDIC_VEC_NOTE("rot_y"), 'y', 257389626, 28}} },
#endif
#if 75 < CORDIC_VEC_LIMIT
  { /* [75] ROTATE: rotate by -0.5000 */
    CORDIC_VEC_NOTE("rotate by -0.5000"), 1,
    0, 536870912, -268435456,
    423859002, 775868711, -3, 0x0u,
    2, {{CORDIC_VEC_NOTE("rot_x"), 'x', 257389626, 28}, {CORDIC_VEC_NOTE("rot_y"), 'y', 471148550, 28}} },
#endif
#if 76 < CORDIC_VEC_LIMIT
  { /* [76] ROTATE: rotate by +1.0472 */
    CORDIC_VEC_NOTE("rotate by +1.0472"), 1,
    268435456, 268435456, 562209904,
    -161801102, 603849947, 2, 0x0u,
    2, {{CORDIC_VEC_NOTE("rot_x"), 'x', -98254196, 21}, {CORDIC_VEC_NOTE("rot_y"), 'y', 366689652, 21}} },
#endif
#if 77 < CORDIC_VEC_LIMIT
  { /* [77] HROTATE: hyperbolic rotate by +0.3000 */
    CORDIC_VEC_NOTE("hyperbolic rotate by +0.3000"), 4,
    268435456, 0, 161061274,
    232386420, 67697095, 1, 0x0u,
    2, {{CORDIC_VEC_NOTE("hrot_x"), 'x', 280605921, 23}, {CORDIC_VEC_NOTE("hrot_y"), 'y', 81744044, 23}} },
#endif
#if 78 < CORDIC_VEC_LIMIT
  { /* [78] HROTATE: hyperbolic rotate by -0.3000 */
    CORDIC_VEC_NOTE("hyperbolic rotate by -0.3000"), 4,
    0, 268435456, -161061274,
    -67697095, 232386420, -1, 0x0u,
    2, {{CORDIC_VEC_NOTE("hrot_x"), 'x', -81744044, 23}, {CORDIC_VEC_NOTE("hrot_y"), 'y', 280605921, 23}} },
#endif
};

#define CORDIC_VEC_COUNT ((int)(sizeof(cordic_vectors) / sizeof(cordic_vectors[0])))

#endif /* CORDIC_VECTORS_H */
