/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Baremetal driver for the OBI CORDIC accelerator. See sw/include/cordic.h.
 *
 * Freestanding: no libc call, no floating point, no allocation. The only 64-bit
 * arithmetic is in the fixed-point helpers in the header, where a 64-bit
 * intermediate is what keeps a ratio exact; on RV32 those become __muldi3 and
 * __divdi3 from libgcc, which is why the build links libgcc but nothing else.
 */

#include "cordic.h"

/* CTRL is split by byte on purpose: byte 0 holds the write-1-to-trigger bits and
 * byte 1 the persistent interrupt enables. Writing whole words would mean every
 * POP silently cleared the interrupt enables. */
#define CTRL_TRIGGER_BYTE 0u
#define CTRL_ENABLE_BYTE 1u

/* Field pack and extract helpers, using the generated shifts and masks. */
#define FIELD_GET(word, reg, fld) \
  (((word) & CORDIC_##reg##_##fld##_MASK) >> CORDIC_##reg##_##fld##_SHIFT)
#define FIELD_SET(reg, fld, val)                                     \
  ((((uint32_t)(val)) << CORDIC_##reg##_##fld##_SHIFT) &             \
   CORDIC_##reg##_##fld##_MASK)

/* A poll budget generous enough for the iterative variant at its deepest
 * configuration, plus the queue depth, plus room for bus contention. Each poll is
 * one OBI read, so this is cycles, not iterations of a tight loop. */
static uint32_t default_timeout(const cordic_t *d) {
  uint32_t per_op = (uint32_t)d->latency + 8u;
  return per_op * ((uint32_t)d->in_depth + 2u) + 64u;
}

cordic_status_t cordic_init(cordic_t *d, uintptr_t base) {
  d->base = (volatile uint32_t *)base;

  if (cordic_rd(d, CORDIC_ID) != CORDIC_ID_MAGIC) {
    return CORDIC_ERR_NO_DEVICE;
  }

  uint32_t cfg0 = cordic_rd(d, CORDIC_CFG0);
  d->data_width = (uint8_t)FIELD_GET(cfg0, CFG0, DATA_WIDTH);
  d->frac_bits = (uint8_t)FIELD_GET(cfg0, CFG0, FRAC_BITS);
  d->num_stages = (uint8_t)FIELD_GET(cfg0, CFG0, NUM_STAGES);
  d->guard_int = (uint8_t)FIELD_GET(cfg0, CFG0, GUARD_INT);
  d->guard_frac = (uint8_t)FIELD_GET(cfg0, CFG0, GUARD_FRAC);

  uint32_t cfg1 = cordic_rd(d, CORDIC_CFG1);
  d->variant = (uint8_t)FIELD_GET(cfg1, CFG1, VARIANT);
  d->in_depth = (uint8_t)FIELD_GET(cfg1, CFG1, IN_DEPTH);
  d->out_depth = (uint8_t)FIELD_GET(cfg1, CFG1, OUT_DEPTH);
  d->latency = (uint16_t)FIELD_GET(cfg1, CFG1, LATENCY);
  d->interval = (uint16_t)FIELD_GET(cfg1, CFG1, INTERVAL);

  d->k_circ = (cordic_fx_t)cordic_rd(d, CORDIC_K_CIRC);
  d->ik_circ = (cordic_fx_t)cordic_rd(d, CORDIC_IK_CIRC);
  d->k_hyp = (cordic_fx_t)cordic_rd(d, CORDIC_K_HYP);
  d->ik_hyp = (cordic_fx_t)cordic_rd(d, CORDIC_IK_HYP);
  d->lim_circ = (cordic_fx_t)cordic_rd(d, CORDIC_LIM_CIRC);
  d->lim_hyp = (cordic_fx_t)cordic_rd(d, CORDIC_LIM_HYP);
  d->lim_lin = (cordic_fx_t)cordic_rd(d, CORDIC_LIM_LIN);
  d->tanh_lim_hyp = (cordic_fx_t)cordic_rd(d, CORDIC_TANH_LIM_HYP);

  cordic_reset(d);
  return CORDIC_OK;
}

void cordic_reset(const cordic_t *d) {
  cordic_wr_byte(d, CORDIC_CTRL + CTRL_TRIGGER_BYTE,
                 (uint8_t)(1u << CORDIC_CTRL_SOFT_RST_SHIFT));
}

uint32_t cordic_errors(const cordic_t *d) {
  uint32_t st = cordic_rd(d, CORDIC_STATUS);
  return st & (CORDIC_STATUS_ERR_DOMAIN_MASK | CORDIC_STATUS_ERR_OVERFLOW_MASK |
               CORDIC_STATUS_ERR_UNDERFLOW_MASK | CORDIC_STATUS_ERR_ACCESS_MASK);
}

void cordic_clear_errors(const cordic_t *d) {
  cordic_wr_byte(d, CORDIC_CTRL + CTRL_TRIGGER_BYTE,
                 (uint8_t)(1u << CORDIC_CTRL_CLR_ERR_SHIFT));
}

void cordic_irq_enable(const cordic_t *d, bool on_done, bool on_error) {
  uint32_t word = FIELD_SET(CTRL, IRQ_EN_DONE, on_done ? 1u : 0u) |
                  FIELD_SET(CTRL, IRQ_EN_ERR, on_error ? 1u : 0u);
  cordic_wr_byte(d, CORDIC_CTRL + CTRL_ENABLE_BYTE,
                 (uint8_t)(word >> (8u * CTRL_ENABLE_BYTE)));
}

uint32_t cordic_irq_claim(const cordic_t *d) {
  uint32_t pending = cordic_rd(d, CORDIC_IRQ);
  if (pending != 0u) {
    cordic_wr(d, CORDIC_IRQ, pending); /* write 1 to clear */
  }
  return pending;
}

bool cordic_result_ready(const cordic_t *d) {
  return (cordic_rd(d, CORDIC_STATUS) & CORDIC_STATUS_RES_VALID_MASK) != 0u;
}

bool cordic_busy(const cordic_t *d) {
  return (cordic_rd(d, CORDIC_STATUS) & CORDIC_STATUS_BUSY_MASK) != 0u;
}

cordic_status_t cordic_submit(const cordic_t *d, uint8_t func, cordic_fx_t x,
                             cordic_fx_t y, cordic_fx_t z, uint8_t tag) {
  if (func >= CORDIC_NUM_FUNCS) {
    return CORDIC_ERR_INVAL;
  }
  /* Check before issuing rather than after: a write into a full queue is dropped
   * and only shows up later as STATUS.ERR_OVERFLOW, by which point the caller has
   * lost the operation. */
  if (cordic_rd(d, CORDIC_STATUS) & CORDIC_STATUS_IN_FULL_MASK) {
    return CORDIC_ERR_BUSY;
  }
  cordic_wr(d, CORDIC_OP_X, (uint32_t)x);
  cordic_wr(d, CORDIC_OP_Y, (uint32_t)y);
  cordic_wr(d, CORDIC_OP_Z, (uint32_t)z);
  cordic_wr(d, CORDIC_CMD, FIELD_SET(CMD, FUNC, func) |
                               FIELD_SET(CMD, TAG, tag) |
                               FIELD_SET(CMD, GO, 1));
  return CORDIC_OK;
}

cordic_status_t cordic_poll(const cordic_t *d, cordic_result_t *out) {
  if (!cordic_result_ready(d)) {
    return CORDIC_ERR_TIMEOUT;
  }
  cordic_fx_t x = (cordic_fx_t)cordic_rd(d, CORDIC_RES_X);
  cordic_fx_t y = (cordic_fx_t)cordic_rd(d, CORDIC_RES_Y);
  cordic_fx_t z = (cordic_fx_t)cordic_rd(d, CORDIC_RES_Z);
  uint32_t fl = cordic_rd(d, CORDIC_RES_FLAGS);
  /* Reads are non-destructive; POP is what consumes the entry. Byte 0 only, so
   * the interrupt enables in byte 1 are left alone. */
  cordic_wr_byte(d, CORDIC_CTRL + CTRL_TRIGGER_BYTE,
                 (uint8_t)(1u << CORDIC_CTRL_POP_SHIFT));

  if (out != NULL) {
    out->x = x;
    out->y = y;
    out->z = z;
    out->flags = fl & (CORDIC_RES_FLAGS_DOMAIN_ERR_MASK |
                       CORDIC_RES_FLAGS_SAT_X_MASK |
                       CORDIC_RES_FLAGS_SAT_Y_MASK |
                       CORDIC_RES_FLAGS_SAT_Z_MASK);
    out->func = (uint8_t)FIELD_GET(fl, RES_FLAGS, FUNC);
    out->tag = (uint8_t)FIELD_GET(fl, RES_FLAGS, TAG);
  }
  if (fl & CORDIC_RES_FLAGS_DOMAIN_ERR_MASK) {
    return CORDIC_ERR_DOMAIN;
  }
  return CORDIC_OK;
}

cordic_status_t cordic_exec(const cordic_t *d, uint8_t func, cordic_fx_t x,
                            cordic_fx_t y, cordic_fx_t z, cordic_result_t *out,
                            uint32_t timeout_polls) {
  cordic_status_t rc = cordic_submit(d, func, x, y, z, 0u);
  if (rc != CORDIC_OK) {
    return rc;
  }
  uint32_t budget = (timeout_polls != 0u) ? timeout_polls : default_timeout(d);
  while (budget-- != 0u) {
    if (cordic_result_ready(d)) {
      return cordic_poll(d, out);
    }
  }
  return CORDIC_ERR_TIMEOUT;
}

cordic_status_t cordic_exec_batch(const cordic_t *d, const cordic_op_t *in,
                                  cordic_result_t *out, size_t n,
                                  uint32_t timeout_polls) {
  if (in == NULL || out == NULL) {
    return CORDIC_ERR_INVAL;
  }
  uint32_t budget = (timeout_polls != 0u) ? timeout_polls
                                          : default_timeout(d) * (uint32_t)(n + 1u);
  size_t issued = 0;
  size_t taken = 0;
  cordic_status_t worst = CORDIC_OK;

  while (taken < n) {
    /* Keep the queue as full as it will go; results come back in issue order, so
     * the tag is only a cross-check. */
    while (issued < n &&
           cordic_submit(d, in[issued].func, in[issued].x, in[issued].y,
                         in[issued].z, (uint8_t)(issued & 0xFFu)) == CORDIC_OK) {
      issued++;
    }
    if (cordic_result_ready(d)) {
      cordic_status_t rc = cordic_poll(d, &out[taken]);
      if (rc != CORDIC_OK && worst == CORDIC_OK) {
        worst = rc;
      }
      taken++;
      continue;
    }
    if (budget-- == 0u) {
      return CORDIC_ERR_TIMEOUT;
    }
  }
  return worst;
}

/* ------------------------------------------------------------------------- */
/* Convenience wrappers                                                      */
/* ------------------------------------------------------------------------- */

cordic_status_t cordic_sin_cos(const cordic_t *d, cordic_fx_t angle,
                              cordic_fx_t *sin_out, cordic_fx_t *cos_out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_SIN_COS, 0, 0, angle, &r, 0);
  if (rc == CORDIC_OK) {
    if (cos_out != NULL) {
      *cos_out = r.x;
    }
    if (sin_out != NULL) {
      *sin_out = r.y;
    }
  }
  return rc;
}

cordic_status_t cordic_atan2(const cordic_t *d, cordic_fx_t y, cordic_fx_t x,
                            cordic_fx_t *angle_out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_ATAN2, x, y, 0, &r, 0);
  if (rc == CORDIC_OK && angle_out != NULL) {
    *angle_out = r.z;
  }
  return rc;
}

cordic_status_t cordic_hypot(const cordic_t *d, cordic_fx_t x, cordic_fx_t y,
                            cordic_fx_t *mag_out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_ATAN2, x, y, 0, &r, 0);
  if (rc == CORDIC_OK && mag_out != NULL) {
    /* Circular vectoring leaves the magnitude scaled by K. */
    *mag_out = cordic_ungain(d, r.x, d->k_circ);
  }
  return rc;
}

cordic_status_t cordic_sinh_cosh(const cordic_t *d, cordic_fx_t arg,
                                cordic_fx_t *sinh_out, cordic_fx_t *cosh_out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_SINH_COSH, 0, 0, arg, &r, 0);
  if (rc == CORDIC_OK) {
    if (cosh_out != NULL) {
      *cosh_out = r.x;
    }
    if (sinh_out != NULL) {
      *sinh_out = r.y;
    }
  }
  return rc;
}

cordic_status_t cordic_exp(const cordic_t *d, cordic_fx_t arg,
                          cordic_fx_t *out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_EXP, 0, 0, arg, &r, 0);
  if (rc == CORDIC_OK && out != NULL) {
    *out = r.x;
  }
  return rc;
}

cordic_status_t cordic_ln(const cordic_t *d, cordic_fx_t arg, cordic_fx_t *out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_LN, arg, 0, 0, &r, 0);
  if (rc == CORDIC_OK && out != NULL) {
    *out = r.z;
  }
  return rc;
}

cordic_status_t cordic_atanh(const cordic_t *d, cordic_fx_t y, cordic_fx_t x,
                            cordic_fx_t *out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_ATANH, x, y, 0, &r, 0);
  if (rc == CORDIC_OK && out != NULL) {
    *out = r.z;
  }
  return rc;
}

cordic_status_t cordic_mul(const cordic_t *d, cordic_fx_t a, cordic_fx_t b,
                          cordic_fx_t *out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_MUL, a, 0, b, &r, 0);
  if (rc == CORDIC_OK && out != NULL) {
    *out = r.y;
  }
  return rc;
}

cordic_status_t cordic_div(const cordic_t *d, cordic_fx_t num, cordic_fx_t den,
                          cordic_fx_t *out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_DIV, den, num, 0, &r, 0);
  if (rc == CORDIC_OK && out != NULL) {
    *out = r.z;
  }
  return rc;
}

cordic_status_t cordic_rotate(const cordic_t *d, cordic_fx_t x, cordic_fx_t y,
                             cordic_fx_t angle, cordic_fx_t *x_out,
                             cordic_fx_t *y_out) {
  cordic_result_t r;
  cordic_status_t rc = cordic_exec(d, CORDIC_FUNC_ROTATE, x, y, angle, &r, 0);
  if (rc == CORDIC_OK) {
    /* Generic rotation carries the gain; undo it so the caller sees a plain
     * rotation. Use CORDIC_FUNC_ROTATE directly to keep the scaled result. */
    if (x_out != NULL) {
      *x_out = cordic_ungain(d, r.x, d->k_circ);
    }
    if (y_out != NULL) {
      *y_out = cordic_ungain(d, r.y, d->k_circ);
    }
  }
  return rc;
}
