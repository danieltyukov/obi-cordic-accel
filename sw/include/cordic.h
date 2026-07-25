/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Baremetal driver for the OBI CORDIC accelerator.
 *
 * Freestanding by design: no libc, no floating point, no dynamic allocation. Croc
 * runs a CVE2 (RV32IMC, no FPU), so a float in a driver would pull in soft-float
 * routines and cost more than the accelerator saves. Every operand and result is a
 * plain int32_t holding a fixed-point value in the format the hardware reports
 * through CFG0.
 *
 * Register offsets and field positions come from cordic_regmap.h, which is
 * generated from scripts/cordic_regmap.py alongside the RTL, so the driver cannot
 * drift from the hardware.
 *
 * Three call styles:
 *   cordic_submit / cordic_poll   non-blocking, for queueing work and coming back
 *   cordic_exec                   blocking, one operation, simplest to use
 *   cordic_exec_batch             blocking, queues up to the FIFO depth at a time
 */

#ifndef CORDIC_H
#define CORDIC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "cordic_regmap.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/* Types                                                                     */
/* ------------------------------------------------------------------------- */

/** A fixed-point word in the accelerator's working format. */
typedef int32_t cordic_fx_t;

/** Per-result flags, mirroring RES_FLAGS. */
typedef enum {
  CORDIC_FLAG_NONE = 0u,
  /** Operand outside the convergence domain. X, Y and Z are zero. */
  CORDIC_FLAG_DOMAIN = 1u << 0,
  CORDIC_FLAG_SAT_X = 1u << 1,
  CORDIC_FLAG_SAT_Y = 1u << 2,
  CORDIC_FLAG_SAT_Z = 1u << 3,
} cordic_flags_t;

/** Return codes. Negative values are errors. */
typedef enum {
  CORDIC_OK = 0,
  /** RES_FLAGS.DOMAIN_ERR was set: the operand was out of domain. */
  CORDIC_ERR_DOMAIN = -1,
  /** The input queue was full, so nothing was issued. */
  CORDIC_ERR_BUSY = -2,
  /** No result arrived within the caller's timeout. */
  CORDIC_ERR_TIMEOUT = -3,
  /** The ID register did not read back the expected magic. */
  CORDIC_ERR_NO_DEVICE = -4,
  /** A function code or argument the driver rejects before issuing. */
  CORDIC_ERR_INVAL = -5,
} cordic_status_t;

/** One completed operation. */
typedef struct {
  cordic_fx_t x;
  cordic_fx_t y;
  cordic_fx_t z;
  uint32_t flags; /**< cordic_flags_t bits */
  uint8_t func;
  uint8_t tag;
} cordic_result_t;

/**
 * Device handle. Fill it with cordic_init(): it caches the elaborated format and
 * the gain and radius constants so that the hot path needs no extra reads.
 */
typedef struct {
  volatile uint32_t *base;
  uint8_t data_width;
  uint8_t frac_bits;
  uint8_t num_stages;
  uint8_t guard_int;
  uint8_t guard_frac;
  uint8_t variant;   /**< 0 pipelined, 1 iterative */
  uint8_t in_depth;
  uint8_t out_depth;
  uint16_t latency;  /**< core issue-to-result latency in cycles */
  uint16_t interval; /**< minimum cycles between accepted operations */
  /* Constants read once, in the working fixed-point format. */
  cordic_fx_t k_circ;
  cordic_fx_t ik_circ;
  cordic_fx_t k_hyp;
  cordic_fx_t ik_hyp;
  cordic_fx_t lim_circ;
  cordic_fx_t lim_hyp;
  cordic_fx_t lim_lin;
  cordic_fx_t tanh_lim_hyp;
} cordic_t;

/* ------------------------------------------------------------------------- */
/* Raw register access                                                       */
/* ------------------------------------------------------------------------- */
/*
 * On the target these are plain volatile loads and stores, which is all a
 * memory-mapped OBI peripheral needs.
 *
 * Building with CORDIC_HOST_SIM redirects them to two extern functions instead,
 * so the identical driver source can be linked against the register-accurate
 * peripheral model in sw/host/ and run on a workstation. That is what verifies the
 * driver's register sequencing, flag decoding and gain compensation, since this
 * repository has no Croc simulation to run an RV32 binary on. See sw/README.md.
 */

#if defined(CORDIC_HOST_SIM)

uint32_t cordic_mmio_read(const cordic_t *d, uint32_t off);
void cordic_mmio_write(const cordic_t *d, uint32_t off, uint32_t val);
void cordic_mmio_write_byte(const cordic_t *d, uint32_t off, uint8_t val);

static inline uint32_t cordic_rd(const cordic_t *d, uint32_t off) {
  return cordic_mmio_read(d, off);
}

static inline void cordic_wr(const cordic_t *d, uint32_t off, uint32_t val) {
  cordic_mmio_write(d, off, val);
}

static inline void cordic_wr_byte(const cordic_t *d, uint32_t off, uint8_t val) {
  cordic_mmio_write_byte(d, off, val);
}

#else

static inline uint32_t cordic_rd(const cordic_t *d, uint32_t off) {
  return d->base[off / 4u];
}

static inline void cordic_wr(const cordic_t *d, uint32_t off, uint32_t val) {
  d->base[off / 4u] = val;
}

/*
 * A byte store, which reaches the peripheral as a word write with one byte enable
 * set. CTRL keeps its write-1-to-trigger bits in byte 0 and its persistent
 * interrupt enables in byte 1 precisely so that these two groups can be written
 * independently: a full-word CTRL write to fire POP would otherwise clear the
 * interrupt enables as a side effect. CVE2 emits sb with the matching be, and
 * cordic_obi_regs honours it.
 */
static inline void cordic_wr_byte(const cordic_t *d, uint32_t off, uint8_t val) {
  ((volatile uint8_t *)d->base)[off] = val;
}

#endif

/* ------------------------------------------------------------------------- */
/* Fixed-point helpers, integer only                                         */
/* ------------------------------------------------------------------------- */

/** 1.0 in the working format. */
static inline cordic_fx_t cordic_one(const cordic_t *d) {
  return (cordic_fx_t)1 << d->frac_bits;
}

/** Integer part of a fixed-point value, rounding toward zero. */
static inline int32_t cordic_fx_to_int(const cordic_t *d, cordic_fx_t v) {
  return (int32_t)(v >> d->frac_bits);
}

/** Whole number to fixed point. Overflow is the caller's problem. */
static inline cordic_fx_t cordic_int_to_fx(const cordic_t *d, int32_t v) {
  return (cordic_fx_t)((uint32_t)v << d->frac_bits);
}

/**
 * Ratio to fixed point, computed without division where possible.
 * cordic_fx_from_ratio(d, 1, 2) is one half.
 */
static inline cordic_fx_t cordic_fx_from_ratio(const cordic_t *d, int32_t num,
                                               int32_t den) {
  if (den == 0) {
    return 0;
  }
  int64_t scaled = ((int64_t)num << d->frac_bits);
  return (cordic_fx_t)(scaled / den);
}

/**
 * Undo a CORDIC gain: returns v / k in the working format.
 * Use it on ROTATE outputs and on the magnitude from ATAN2 or ATANH, which are
 * scaled by K_CIRC and K_HYP respectively.
 */
static inline cordic_fx_t cordic_ungain(const cordic_t *d, cordic_fx_t v,
                                        cordic_fx_t k) {
  if (k == 0) {
    return 0;
  }
  int64_t scaled = ((int64_t)v << d->frac_bits);
  return (cordic_fx_t)(scaled / k);
}

/* ------------------------------------------------------------------------- */
/* Lifecycle                                                                 */
/* ------------------------------------------------------------------------- */

/**
 * Probe the accelerator at `base`, cache its configuration, and reset it.
 * Returns CORDIC_ERR_NO_DEVICE if the ID register does not read the magic.
 */
cordic_status_t cordic_init(cordic_t *d, uintptr_t base);

/** Abort everything in flight, flush both queues, clear the sticky errors. */
void cordic_reset(const cordic_t *d);

/** Sticky STATUS.ERR_* bits, as they stand. */
uint32_t cordic_errors(const cordic_t *d);

/** Clear the sticky STATUS.ERR_* bits. */
void cordic_clear_errors(const cordic_t *d);

/**
 * Enable or disable the interrupt sources.
 * Writes only CTRL byte 1, so it cannot disturb the trigger bits in byte 0.
 */
void cordic_irq_enable(const cordic_t *d, bool on_done, bool on_error);

/** Read IRQ, then clear the bits that were set. Returns what was read. */
uint32_t cordic_irq_claim(const cordic_t *d);

/* ------------------------------------------------------------------------- */
/* Non-blocking                                                              */
/* ------------------------------------------------------------------------- */

/**
 * Queue one operation. Does not wait.
 * Returns CORDIC_ERR_BUSY without issuing if the input queue is full, so a caller
 * can back off rather than lose the operation to STATUS.ERR_OVERFLOW.
 */
cordic_status_t cordic_submit(const cordic_t *d, uint8_t func, cordic_fx_t x,
                             cordic_fx_t y, cordic_fx_t z, uint8_t tag);

/** True if at least one result is waiting. */
bool cordic_result_ready(const cordic_t *d);

/** True if operations are queued or in flight. */
bool cordic_busy(const cordic_t *d);

/**
 * Take the result at the head of the queue, if there is one.
 * Returns CORDIC_OK, CORDIC_ERR_DOMAIN if the result carries a domain error, or
 * CORDIC_ERR_TIMEOUT if nothing is ready. `out` may be NULL to discard.
 */
cordic_status_t cordic_poll(const cordic_t *d, cordic_result_t *out);

/* ------------------------------------------------------------------------- */
/* Blocking                                                                  */
/* ------------------------------------------------------------------------- */

/**
 * Queue one operation and wait for its result.
 * `timeout_polls` bounds the wait in status reads; pass 0 for the driver's
 * default, which is derived from the advertised latency.
 */
cordic_status_t cordic_exec(const cordic_t *d, uint8_t func, cordic_fx_t x,
                            cordic_fx_t y, cordic_fx_t z, cordic_result_t *out,
                            uint32_t timeout_polls);

/**
 * Run `n` operations, keeping the input queue as full as it will go.
 * `in` and `out` are arrays of `n` entries; `in[i].tag` is ignored, the index is
 * used so results can be matched up. Returns the first error encountered, having
 * still filled in every result it managed to collect.
 */
typedef struct {
  uint8_t func;
  cordic_fx_t x;
  cordic_fx_t y;
  cordic_fx_t z;
} cordic_op_t;

cordic_status_t cordic_exec_batch(const cordic_t *d, const cordic_op_t *in,
                                  cordic_result_t *out, size_t n,
                                  uint32_t timeout_polls);

/* ------------------------------------------------------------------------- */
/* Convenience wrappers, one per mathematical function                       */
/* ------------------------------------------------------------------------- */

/** cos and sin of `angle` radians. Either pointer may be NULL. */
cordic_status_t cordic_sin_cos(const cordic_t *d, cordic_fx_t angle,
                              cordic_fx_t *sin_out, cordic_fx_t *cos_out);

/** atan2(y, x), all four quadrants. Never reports a domain error. */
cordic_status_t cordic_atan2(const cordic_t *d, cordic_fx_t y, cordic_fx_t x,
                            cordic_fx_t *angle_out);

/** hypot(x, y), gain-compensated by the driver. */
cordic_status_t cordic_hypot(const cordic_t *d, cordic_fx_t x, cordic_fx_t y,
                            cordic_fx_t *mag_out);

/** cosh and sinh of `arg`. Requires |arg| <= LIM_HYP. */
cordic_status_t cordic_sinh_cosh(const cordic_t *d, cordic_fx_t arg,
                                cordic_fx_t *sinh_out, cordic_fx_t *cosh_out);

/** exp(arg). Requires |arg| <= LIM_HYP. */
cordic_status_t cordic_exp(const cordic_t *d, cordic_fx_t arg,
                          cordic_fx_t *out);

/** ln(arg). Requires arg > 0 and (arg-1)/(arg+1) inside TANH_LIM_HYP. */
cordic_status_t cordic_ln(const cordic_t *d, cordic_fx_t arg, cordic_fx_t *out);

/** atanh(y/x). Requires x != 0 and |y/x| <= TANH_LIM_HYP. */
cordic_status_t cordic_atanh(const cordic_t *d, cordic_fx_t y, cordic_fx_t x,
                            cordic_fx_t *out);

/** a * b. Requires |b| <= LIM_LIN. */
cordic_status_t cordic_mul(const cordic_t *d, cordic_fx_t a, cordic_fx_t b,
                          cordic_fx_t *out);

/** num / den. Requires den != 0 and |num/den| <= LIM_LIN. */
cordic_status_t cordic_div(const cordic_t *d, cordic_fx_t num, cordic_fx_t den,
                          cordic_fx_t *out);

/** Rotate (x, y) by `angle`, gain-compensated by the driver. */
cordic_status_t cordic_rotate(const cordic_t *d, cordic_fx_t x, cordic_fx_t y,
                             cordic_fx_t angle, cordic_fx_t *x_out,
                             cordic_fx_t *y_out);

#ifdef __cplusplus
}
#endif

#endif /* CORDIC_H */
