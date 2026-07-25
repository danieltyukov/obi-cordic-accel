/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * GENERATED FILE - DO NOT EDIT.
 * Produced by scripts/gen_regmap.py from scripts/cordic_regmap.py.
 * Regenerate with `make regmap`.
 */


#ifndef CORDIC_REGMAP_H
#define CORDIC_REGMAP_H

#define CORDIC_WINDOW_BYTES     0x1000U
#define CORDIC_MAPPED_BYTES     0x64U
#define CORDIC_ID_MAGIC         0x434f5244U
#define CORDIC_VERSION_MAJOR    1U
#define CORDIC_VERSION_MINOR    0U
#define CORDIC_VERSION_PATCH    0U
#define CORDIC_BAD_ACCESS_DATA  0xbadacce5U

/* Byte offsets from the peripheral base address. */
#define CORDIC_ID             0x000U   /* RO  Identification magic, reads 0x434F5244 ("CORD") */
#define CORDIC_VERSION        0x004U   /* RO  Semantic version of the register interface */
#define CORDIC_CFG0           0x008U   /* RO  Elaborated fixed-point format */
#define CORDIC_CFG1           0x00cU   /* RO  Elaborated microarchitecture and timing */
#define CORDIC_CTRL           0x010U   /* RW  Control. Bits 0 to 4 are write-1-to-trigger and read 0 */
#define CORDIC_STATUS         0x014U   /* RO  Live and sticky status */
#define CORDIC_IRQ            0x018U   /* W1C Interrupt status, write 1 to clear */
#define CORDIC_OP_X           0x020U   /* RW  Operand X in the working fixed-point format */
#define CORDIC_OP_Y           0x024U   /* RW  Operand Y in the working fixed-point format */
#define CORDIC_OP_Z           0x028U   /* RW  Operand Z in the working fixed-point format */
#define CORDIC_CMD            0x02cU   /* RW  Function select and issue trigger */
#define CORDIC_RES_X          0x030U   /* RO  Result X at the head of the output FIFO */
#define CORDIC_RES_Y          0x034U   /* RO  Result Y at the head of the output FIFO */
#define CORDIC_RES_Z          0x038U   /* RO  Result Z at the head of the output FIFO */
#define CORDIC_RES_FLAGS      0x03cU   /* RO  Per-result flags at the head of the output FIFO */
#define CORDIC_K_CIRC         0x040U   /* RO  Circular CORDIC gain K, working format */
#define CORDIC_IK_CIRC        0x044U   /* RO  Reciprocal circular gain 1/K, working format */
#define CORDIC_K_HYP          0x048U   /* RO  Hyperbolic CORDIC gain Kh, working format */
#define CORDIC_IK_HYP         0x04cU   /* RO  Reciprocal hyperbolic gain 1/Kh, working format */
#define CORDIC_LIM_CIRC       0x050U   /* RO  Circular convergence radius, working format */
#define CORDIC_LIM_HYP        0x054U   /* RO  Hyperbolic convergence radius, working format */
#define CORDIC_LIM_LIN        0x058U   /* RO  Linear convergence radius, working format */
#define CORDIC_TANH_LIM_HYP   0x05cU   /* RO  Largest |Y/X| the hyperbolic vectoring mode resolves */
#define CORDIC_SCRATCH        0x060U   /* RW  Read-write scratch word, no hardware effect */

/* Field shifts and masks. CORDIC_<REG>_<FIELD>_{SHIFT,MASK}. */
#define CORDIC_ID_MAGIC_SHIFT              0U
#define CORDIC_ID_MAGIC_MASK               0xffffffffU
#define CORDIC_VERSION_MAJOR_SHIFT         24U
#define CORDIC_VERSION_MAJOR_MASK          0xff000000U
#define CORDIC_VERSION_MINOR_SHIFT         16U
#define CORDIC_VERSION_MINOR_MASK          0x00ff0000U
#define CORDIC_VERSION_PATCH_SHIFT         8U
#define CORDIC_VERSION_PATCH_MASK          0x0000ff00U
#define CORDIC_CFG0_DATA_WIDTH_SHIFT       0U
#define CORDIC_CFG0_DATA_WIDTH_MASK        0x000000ffU
#define CORDIC_CFG0_FRAC_BITS_SHIFT        8U
#define CORDIC_CFG0_FRAC_BITS_MASK         0x0000ff00U
#define CORDIC_CFG0_NUM_STAGES_SHIFT       16U
#define CORDIC_CFG0_NUM_STAGES_MASK        0x00ff0000U
#define CORDIC_CFG0_GUARD_INT_SHIFT        24U
#define CORDIC_CFG0_GUARD_INT_MASK         0x0f000000U
#define CORDIC_CFG0_GUARD_FRAC_SHIFT       28U
#define CORDIC_CFG0_GUARD_FRAC_MASK        0xf0000000U
#define CORDIC_CFG1_VARIANT_SHIFT          0U
#define CORDIC_CFG1_VARIANT_MASK           0x00000001U
#define CORDIC_CFG1_USE_RREADY_SHIFT       1U
#define CORDIC_CFG1_USE_RREADY_MASK        0x00000002U
#define CORDIC_CFG1_IN_DEPTH_SHIFT         4U
#define CORDIC_CFG1_IN_DEPTH_MASK          0x000000f0U
#define CORDIC_CFG1_OUT_DEPTH_SHIFT        8U
#define CORDIC_CFG1_OUT_DEPTH_MASK         0x00000f00U
#define CORDIC_CFG1_LATENCY_SHIFT          12U
#define CORDIC_CFG1_LATENCY_MASK           0x000ff000U
#define CORDIC_CFG1_INTERVAL_SHIFT         20U
#define CORDIC_CFG1_INTERVAL_MASK          0x0ff00000U
#define CORDIC_CTRL_SOFT_RST_SHIFT         0U
#define CORDIC_CTRL_SOFT_RST_MASK          0x00000001U
#define CORDIC_CTRL_POP_SHIFT              1U
#define CORDIC_CTRL_POP_MASK               0x00000002U
#define CORDIC_CTRL_FLUSH_IN_SHIFT         2U
#define CORDIC_CTRL_FLUSH_IN_MASK          0x00000004U
#define CORDIC_CTRL_FLUSH_OUT_SHIFT        3U
#define CORDIC_CTRL_FLUSH_OUT_MASK         0x00000008U
#define CORDIC_CTRL_CLR_ERR_SHIFT          4U
#define CORDIC_CTRL_CLR_ERR_MASK           0x00000010U
#define CORDIC_CTRL_IRQ_EN_DONE_SHIFT      8U
#define CORDIC_CTRL_IRQ_EN_DONE_MASK       0x00000100U
#define CORDIC_CTRL_IRQ_EN_ERR_SHIFT       9U
#define CORDIC_CTRL_IRQ_EN_ERR_MASK        0x00000200U
#define CORDIC_STATUS_BUSY_SHIFT           0U
#define CORDIC_STATUS_BUSY_MASK            0x00000001U
#define CORDIC_STATUS_RES_VALID_SHIFT      1U
#define CORDIC_STATUS_RES_VALID_MASK       0x00000002U
#define CORDIC_STATUS_IN_FULL_SHIFT        2U
#define CORDIC_STATUS_IN_FULL_MASK         0x00000004U
#define CORDIC_STATUS_IN_EMPTY_SHIFT       3U
#define CORDIC_STATUS_IN_EMPTY_MASK        0x00000008U
#define CORDIC_STATUS_OUT_FULL_SHIFT       4U
#define CORDIC_STATUS_OUT_FULL_MASK        0x00000010U
#define CORDIC_STATUS_OUT_EMPTY_SHIFT      5U
#define CORDIC_STATUS_OUT_EMPTY_MASK       0x00000020U
#define CORDIC_STATUS_IN_COUNT_SHIFT       8U
#define CORDIC_STATUS_IN_COUNT_MASK        0x00000f00U
#define CORDIC_STATUS_OUT_COUNT_SHIFT      12U
#define CORDIC_STATUS_OUT_COUNT_MASK       0x0000f000U
#define CORDIC_STATUS_ERR_DOMAIN_SHIFT     16U
#define CORDIC_STATUS_ERR_DOMAIN_MASK      0x00010000U
#define CORDIC_STATUS_ERR_OVERFLOW_SHIFT   17U
#define CORDIC_STATUS_ERR_OVERFLOW_MASK    0x00020000U
#define CORDIC_STATUS_ERR_UNDERFLOW_SHIFT  18U
#define CORDIC_STATUS_ERR_UNDERFLOW_MASK   0x00040000U
#define CORDIC_STATUS_ERR_ACCESS_SHIFT     19U
#define CORDIC_STATUS_ERR_ACCESS_MASK      0x00080000U
#define CORDIC_IRQ_DONE_SHIFT              0U
#define CORDIC_IRQ_DONE_MASK               0x00000001U
#define CORDIC_IRQ_ERR_SHIFT               1U
#define CORDIC_IRQ_ERR_MASK                0x00000002U
#define CORDIC_OP_X_VALUE_SHIFT            0U
#define CORDIC_OP_X_VALUE_MASK             0xffffffffU
#define CORDIC_OP_Y_VALUE_SHIFT            0U
#define CORDIC_OP_Y_VALUE_MASK             0xffffffffU
#define CORDIC_OP_Z_VALUE_SHIFT            0U
#define CORDIC_OP_Z_VALUE_MASK             0xffffffffU
#define CORDIC_CMD_FUNC_SHIFT              0U
#define CORDIC_CMD_FUNC_MASK               0x0000001fU
#define CORDIC_CMD_TAG_SHIFT               8U
#define CORDIC_CMD_TAG_MASK                0x0000ff00U
#define CORDIC_CMD_GO_SHIFT                31U
#define CORDIC_CMD_GO_MASK                 0x80000000U
#define CORDIC_RES_X_VALUE_SHIFT           0U
#define CORDIC_RES_X_VALUE_MASK            0xffffffffU
#define CORDIC_RES_Y_VALUE_SHIFT           0U
#define CORDIC_RES_Y_VALUE_MASK            0xffffffffU
#define CORDIC_RES_Z_VALUE_SHIFT           0U
#define CORDIC_RES_Z_VALUE_MASK            0xffffffffU
#define CORDIC_RES_FLAGS_DOMAIN_ERR_SHIFT  0U
#define CORDIC_RES_FLAGS_DOMAIN_ERR_MASK   0x00000001U
#define CORDIC_RES_FLAGS_SAT_X_SHIFT       1U
#define CORDIC_RES_FLAGS_SAT_X_MASK        0x00000002U
#define CORDIC_RES_FLAGS_SAT_Y_SHIFT       2U
#define CORDIC_RES_FLAGS_SAT_Y_MASK        0x00000004U
#define CORDIC_RES_FLAGS_SAT_Z_SHIFT       3U
#define CORDIC_RES_FLAGS_SAT_Z_MASK        0x00000008U
#define CORDIC_RES_FLAGS_FUNC_SHIFT        8U
#define CORDIC_RES_FLAGS_FUNC_MASK         0x00001f00U
#define CORDIC_RES_FLAGS_TAG_SHIFT         16U
#define CORDIC_RES_FLAGS_TAG_MASK          0x00ff0000U
#define CORDIC_K_CIRC_VALUE_SHIFT          0U
#define CORDIC_K_CIRC_VALUE_MASK           0xffffffffU
#define CORDIC_IK_CIRC_VALUE_SHIFT         0U
#define CORDIC_IK_CIRC_VALUE_MASK          0xffffffffU
#define CORDIC_K_HYP_VALUE_SHIFT           0U
#define CORDIC_K_HYP_VALUE_MASK            0xffffffffU
#define CORDIC_IK_HYP_VALUE_SHIFT          0U
#define CORDIC_IK_HYP_VALUE_MASK           0xffffffffU
#define CORDIC_LIM_CIRC_VALUE_SHIFT        0U
#define CORDIC_LIM_CIRC_VALUE_MASK         0xffffffffU
#define CORDIC_LIM_HYP_VALUE_SHIFT         0U
#define CORDIC_LIM_HYP_VALUE_MASK          0xffffffffU
#define CORDIC_LIM_LIN_VALUE_SHIFT         0U
#define CORDIC_LIM_LIN_VALUE_MASK          0xffffffffU
#define CORDIC_TANH_LIM_HYP_VALUE_SHIFT    0U
#define CORDIC_TANH_LIM_HYP_VALUE_MASK     0xffffffffU
#define CORDIC_SCRATCH_VALUE_SHIFT         0U
#define CORDIC_SCRATCH_VALUE_MASK          0xffffffffU

/* Function codes for the CMD.FUNC field. */
#define CORDIC_FUNC_SIN_COS      0U   /* circular rotation: X = cos(Z), Y = sin(Z) */
#define CORDIC_FUNC_ROTATE       1U   /* circular rotation: X, Y = K * R(Z) * (X,Y) */
#define CORDIC_FUNC_ATAN2        2U   /* circular vectoring: Z = atan2(Y,X), X = K * hypot(X,Y) */
#define CORDIC_FUNC_SINH_COSH    3U   /* hyperbolic rotation: X = cosh(Z), Y = sinh(Z) */
#define CORDIC_FUNC_HROTATE      4U   /* hyperbolic rotation: X, Y = Kh * Rh(Z) * (X,Y) */
#define CORDIC_FUNC_ATANH        5U   /* hyperbolic vectoring: Z = atanh(Y/X), X = Kh * sqrt(X^2 - Y^2) */
#define CORDIC_FUNC_EXP          6U   /* hyperbolic rotation: X = Y = exp(Z) */
#define CORDIC_FUNC_LN           7U   /* hyperbolic vectoring: Z = ln(X) */
#define CORDIC_FUNC_MUL          8U   /* linear rotation: Y = X * Z */
#define CORDIC_FUNC_DIV          9U   /* linear vectoring: Z = Y / X */
#define CORDIC_NUM_FUNCS         10U

#endif /* CORDIC_REGMAP_H */
