/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Register-accurate model of the CORDIC peripheral, for running the driver on a
 * workstation.
 *
 * It implements the register map, both FIFOs, the sticky error bits and the
 * interrupt state, following the same rules the RTL does. What it deliberately
 * does not do is compute CORDIC: results come out of sw/host/cordic_vectors.h,
 * which was generated from the same bit-accurate model that the RTL is asserted
 * against operation by operation. A second CORDIC written in C would only prove
 * that two pieces of C agree.
 *
 * So what this verifies is the driver: register offsets and field positions, the
 * order of the operand writes and the GO trigger, non-destructive result reads
 * followed by POP, flag decoding, gain compensation, queue-full back-off, and the
 * error paths. It does not verify the hardware, which is what tb/ is for.
 */

#include "cordic_sim.h"

#include <stdio.h>
#include <string.h>

#include "cordic_vectors.h"

#define IN_DEPTH 4
#define OUT_DEPTH 4

typedef struct {
  uint8_t func;
  uint8_t tag;
  int32_t x, y, z;
} sim_op_t;

typedef struct {
  int32_t x, y, z;
  uint32_t flags;
  uint8_t func;
  uint8_t tag;
} sim_res_t;

static struct {
  uint32_t op_x, op_y, op_z;
  uint32_t cmd;
  uint32_t scratch;
  uint32_t irq_en_done, irq_en_err;
  uint32_t irq_done, irq_err;
  uint32_t err_domain, err_overflow, err_underflow, err_access;

  sim_op_t inq[IN_DEPTH];
  int in_count;
  sim_res_t outq[OUT_DEPTH];
  int out_count;

  /* Bookkeeping the test inspects. */
  cordic_sim_stats_t stats;
} S;

static void sim_set_err(uint32_t *bit) {
  if (*bit == 0u) {
    *bit = 1u;
    S.irq_err = 1u;
  }
}

/* Find the vector matching an operation. A miss is a bug in the test, not in the
 * driver, so it is loud. */
static const cordic_vec_t *lookup(uint8_t func, int32_t x, int32_t y, int32_t z) {
  for (int i = 0; i < CORDIC_VEC_COUNT; i++) {
    const cordic_vec_t *v = &cordic_vectors[i];
    if (v->func == func && v->x == x && v->y == y && v->z == z) {
      return v;
    }
  }
  return NULL;
}

/* Run the head of the input queue, if the output queue has room. Called on every
 * register access, which is enough: the driver polls. */
static void sim_step(void) {
  while (S.in_count > 0 && S.out_count < OUT_DEPTH) {
    sim_op_t op = S.inq[0];
    memmove(&S.inq[0], &S.inq[1], sizeof(sim_op_t) * (size_t)(S.in_count - 1));
    S.in_count--;

    const cordic_vec_t *v = lookup(op.func, op.x, op.y, op.z);
    sim_res_t r;
    if (v == NULL) {
      fprintf(stderr,
              "cordic_sim: no vector for func=%u x=%d y=%d z=%d. Add it to "
              "scripts/gen_sw_vectors.py.\n",
              op.func, op.x, op.y, op.z);
      S.stats.missing_vectors++;
      r.x = r.y = r.z = 0;
      r.flags = CORDIC_RES_FLAGS_DOMAIN_ERR_MASK;
    } else {
      r.x = v->rx;
      r.y = v->ry;
      r.z = v->rz;
      r.flags = v->flags;
    }
    r.func = op.func;
    r.tag = op.tag;

    S.outq[S.out_count++] = r;
    S.irq_done = 1u;
    S.stats.completed++;
    if (r.flags & CORDIC_RES_FLAGS_DOMAIN_ERR_MASK) {
      sim_set_err(&S.err_domain);
    }
  }
}

static void sim_pop(void) {
  if (S.out_count == 0) {
    sim_set_err(&S.err_underflow);
    return;
  }
  memmove(&S.outq[0], &S.outq[1], sizeof(sim_res_t) * (size_t)(S.out_count - 1));
  S.out_count--;
}

static void sim_soft_reset(void) {
  S.in_count = 0;
  S.out_count = 0;
  S.err_domain = S.err_overflow = S.err_underflow = S.err_access = 0u;
  S.irq_done = S.irq_err = 0u;
}

void cordic_sim_reset(void) {
  memset(&S, 0, sizeof(S));
}

cordic_sim_stats_t cordic_sim_stats(void) {
  return S.stats;
}

static uint32_t status_word(void) {
  uint32_t st = 0u;
  if (S.in_count > 0) {
    st |= CORDIC_STATUS_BUSY_MASK;
  }
  if (S.out_count > 0) {
    st |= CORDIC_STATUS_RES_VALID_MASK;
  }
  if (S.in_count >= IN_DEPTH) {
    st |= CORDIC_STATUS_IN_FULL_MASK;
  }
  if (S.in_count == 0) {
    st |= CORDIC_STATUS_IN_EMPTY_MASK;
  }
  if (S.out_count >= OUT_DEPTH) {
    st |= CORDIC_STATUS_OUT_FULL_MASK;
  }
  if (S.out_count == 0) {
    st |= CORDIC_STATUS_OUT_EMPTY_MASK;
  }
  st |= ((uint32_t)S.in_count << CORDIC_STATUS_IN_COUNT_SHIFT) &
        CORDIC_STATUS_IN_COUNT_MASK;
  st |= ((uint32_t)S.out_count << CORDIC_STATUS_OUT_COUNT_SHIFT) &
        CORDIC_STATUS_OUT_COUNT_MASK;
  st |= S.err_domain << CORDIC_STATUS_ERR_DOMAIN_SHIFT;
  st |= S.err_overflow << CORDIC_STATUS_ERR_OVERFLOW_SHIFT;
  st |= S.err_underflow << CORDIC_STATUS_ERR_UNDERFLOW_SHIFT;
  st |= S.err_access << CORDIC_STATUS_ERR_ACCESS_SHIFT;
  return st;
}

uint32_t cordic_mmio_read(const cordic_t *d, uint32_t off) {
  (void)d;
  S.stats.reads++;
  sim_step();
  const sim_res_t *head = (S.out_count > 0) ? &S.outq[0] : NULL;

  switch (off) {
    case CORDIC_ID:
      return CORDIC_ID_MAGIC;
    case CORDIC_VERSION:
      return ((uint32_t)CORDIC_VERSION_MAJOR << 24) |
             ((uint32_t)CORDIC_VERSION_MINOR << 16) |
             ((uint32_t)CORDIC_VERSION_PATCH << 8);
    case CORDIC_CFG0:
      return (((uint32_t)CORDIC_VEC_DATA_WIDTH) << CORDIC_CFG0_DATA_WIDTH_SHIFT) |
             (((uint32_t)CORDIC_VEC_FRAC_BITS) << CORDIC_CFG0_FRAC_BITS_SHIFT) |
             (((uint32_t)CORDIC_VEC_NUM_STAGES) << CORDIC_CFG0_NUM_STAGES_SHIFT) |
             (((uint32_t)CORDIC_VEC_GUARD_INT) << CORDIC_CFG0_GUARD_INT_SHIFT) |
             (((uint32_t)CORDIC_VEC_GUARD_FRAC) << CORDIC_CFG0_GUARD_FRAC_SHIFT);
    case CORDIC_CFG1:
      return (((uint32_t)IN_DEPTH) << CORDIC_CFG1_IN_DEPTH_SHIFT) |
             (((uint32_t)OUT_DEPTH) << CORDIC_CFG1_OUT_DEPTH_SHIFT) |
             (((uint32_t)CORDIC_VEC_NUM_STAGES) << CORDIC_CFG1_LATENCY_SHIFT) |
             (1u << CORDIC_CFG1_INTERVAL_SHIFT);
    case CORDIC_CTRL:
      return (S.irq_en_done << CORDIC_CTRL_IRQ_EN_DONE_SHIFT) |
             (S.irq_en_err << CORDIC_CTRL_IRQ_EN_ERR_SHIFT);
    case CORDIC_STATUS:
      return status_word();
    case CORDIC_IRQ:
      return (S.irq_done << CORDIC_IRQ_DONE_SHIFT) |
             (S.irq_err << CORDIC_IRQ_ERR_SHIFT);
    case CORDIC_OP_X:
      return S.op_x;
    case CORDIC_OP_Y:
      return S.op_y;
    case CORDIC_OP_Z:
      return S.op_z;
    case CORDIC_CMD:
      return S.cmd & (CORDIC_CMD_FUNC_MASK | CORDIC_CMD_TAG_MASK);
    case CORDIC_RES_X:
      if (head == NULL) {
        sim_set_err(&S.err_underflow);
        return 0u;
      }
      return (uint32_t)head->x;
    case CORDIC_RES_Y:
      if (head == NULL) {
        sim_set_err(&S.err_underflow);
        return 0u;
      }
      return (uint32_t)head->y;
    case CORDIC_RES_Z:
      if (head == NULL) {
        sim_set_err(&S.err_underflow);
        return 0u;
      }
      return (uint32_t)head->z;
    case CORDIC_RES_FLAGS:
      if (head == NULL) {
        sim_set_err(&S.err_underflow);
        return 0u;
      }
      return head->flags |
             (((uint32_t)head->func << CORDIC_RES_FLAGS_FUNC_SHIFT) &
              CORDIC_RES_FLAGS_FUNC_MASK) |
             (((uint32_t)head->tag << CORDIC_RES_FLAGS_TAG_SHIFT) &
              CORDIC_RES_FLAGS_TAG_MASK);
    case CORDIC_K_CIRC:
      return (uint32_t)CORDIC_VEC_K_CIRC;
    case CORDIC_IK_CIRC:
      return (uint32_t)CORDIC_VEC_IK_CIRC;
    case CORDIC_K_HYP:
      return (uint32_t)CORDIC_VEC_K_HYP;
    case CORDIC_IK_HYP:
      return (uint32_t)CORDIC_VEC_IK_HYP;
    case CORDIC_LIM_CIRC:
      return (uint32_t)CORDIC_VEC_LIM_CIRC;
    case CORDIC_LIM_HYP:
      return (uint32_t)CORDIC_VEC_LIM_HYP;
    case CORDIC_LIM_LIN:
      return (uint32_t)CORDIC_VEC_LIM_LIN;
    case CORDIC_TANH_LIM_HYP:
      return (uint32_t)CORDIC_VEC_TANH_LIM_HYP;
    case CORDIC_SCRATCH:
      return S.scratch;
    default:
      sim_set_err(&S.err_access);
      return CORDIC_BAD_ACCESS_DATA;
  }
}

/* `be` mirrors the OBI byte enables: bit b allows byte b of the word through. */
/* `be` mirrors the OBI byte enables: bit b allows byte b of the word through. */
static void sim_write(uint32_t off, uint32_t val, uint32_t be) {
  switch (off) {
    case CORDIC_CTRL:
      /* Byte 0 carries the write-1-to-trigger bits, byte 1 the persistent
       * interrupt enables, exactly as cordic_obi_regs splits them. */
      if (be & 0x1u) {
        if (val & CORDIC_CTRL_SOFT_RST_MASK) {
          sim_soft_reset();
        }
        if (val & CORDIC_CTRL_POP_MASK) {
          sim_pop();
        }
        if (val & CORDIC_CTRL_FLUSH_IN_MASK) {
          S.in_count = 0;
        }
        if (val & CORDIC_CTRL_FLUSH_OUT_MASK) {
          S.out_count = 0;
        }
        if (val & CORDIC_CTRL_CLR_ERR_MASK) {
          S.err_domain = S.err_overflow = S.err_underflow = S.err_access = 0u;
        }
      }
      if (be & 0x2u) {
        S.irq_en_done = (val & CORDIC_CTRL_IRQ_EN_DONE_MASK) ? 1u : 0u;
        S.irq_en_err = (val & CORDIC_CTRL_IRQ_EN_ERR_MASK) ? 1u : 0u;
      }
      break;
    case CORDIC_IRQ:
      if (be & 0x1u) {
        if (val & CORDIC_IRQ_DONE_MASK) {
          S.irq_done = 0u;
        }
        if (val & CORDIC_IRQ_ERR_MASK) {
          S.irq_err = 0u;
        }
      }
      break;
    case CORDIC_OP_X:
      S.op_x = val;
      break;
    case CORDIC_OP_Y:
      S.op_y = val;
      break;
    case CORDIC_OP_Z:
      S.op_z = val;
      break;
    case CORDIC_CMD:
      S.cmd = val;
      /* GO lives in byte 3, so a write that leaves byte 3 out updates FUNC and
       * TAG without issuing. */
      if ((be & 0x8u) && (val & CORDIC_CMD_GO_MASK)) {
        if (S.in_count >= IN_DEPTH) {
          sim_set_err(&S.err_overflow);
          S.stats.dropped++;
        } else {
          sim_op_t op;
          op.func = (uint8_t)((val & CORDIC_CMD_FUNC_MASK) >>
                              CORDIC_CMD_FUNC_SHIFT);
          op.tag = (uint8_t)((val & CORDIC_CMD_TAG_MASK) >> CORDIC_CMD_TAG_SHIFT);
          op.x = (int32_t)S.op_x;
          op.y = (int32_t)S.op_y;
          op.z = (int32_t)S.op_z;
          S.inq[S.in_count++] = op;
          S.stats.issued++;
        }
      }
      break;
    case CORDIC_SCRATCH:
      S.scratch = val;
      break;
    default:
      /* Every other mapped offset is read-only, and anything unmapped faults. */
      sim_set_err(&S.err_access);
      break;
  }
}

void cordic_mmio_write(const cordic_t *d, uint32_t off, uint32_t val) {
  (void)d;
  S.stats.writes++;
  sim_step();
  sim_write(off, val, 0xFu);
  sim_step();
}

void cordic_mmio_write_byte(const cordic_t *d, uint32_t off, uint8_t val) {
  (void)d;
  S.stats.writes++;
  sim_step();
  uint32_t word_off = off & ~3u;
  uint32_t lane = off & 3u;
  sim_write(word_off, (uint32_t)val << (8u * lane), 1u << lane);
  sim_step();
}

int cordic_sim_irq_pending(void) {
  return (int)((S.irq_done & S.irq_en_done) | (S.irq_err & S.irq_en_err));
}
