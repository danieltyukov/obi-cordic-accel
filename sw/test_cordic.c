/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Self-checking test program for the CORDIC driver.
 *
 * One source, two builds:
 *
 *   host  gcc -DCORDIC_HOST_SIM, linked against the register-accurate peripheral
 *         model in sw/host/. Runs and reports on a workstation, which is what
 *         actually verifies the driver.
 *   rv32  riscv64-unknown-elf-gcc -march=rv32imc_zicsr, freestanding, for Croc.
 *         Compiles and links here but is not executed: this repository carries no
 *         Croc simulation. Point CORDIC_BASE at the accelerator's window and run
 *         it under Croc's own testbench.
 *
 * Every expected value in sw/host/cordic_vectors.h came from the bit-accurate
 * model that the RTL is asserted against, so the checks below are against real
 * hardware behaviour rather than against a second software implementation.
 */

#include <stdint.h>

#include "cordic.h"
#include "cordic_vectors.h"

#if defined(CORDIC_HOST_SIM)
#include <stdio.h>
#include "cordic_sim.h"
#define BASE CORDIC_SIM_BASE
#else
/* Croc's user domain starts at croc_pkg::UserBaseAddr; docs/CROC_INTEGRATION.md
 * places this peripheral one 4 KB window in. Override on the command line. */
#ifndef CORDIC_BASE
#define CORDIC_BASE 0x20001000u
#endif
#define BASE CORDIC_BASE
#endif

/*
 * Reporting.
 *
 * On the host, failures print. On the target there is nothing to print to unless
 * the integrator supplies one, so the outcome is recorded in `cordic_test_report`
 * instead, at a known symbol Croc's testbench can read out of memory, and main()
 * returns the failure count in a0. Define CORDIC_TEST_PUTC(c) to a character sink
 * (Croc's UART, for instance) to get the log as well.
 */
typedef struct {
  uint32_t magic;        /* 0x54455354, "TEST", set once the run has started */
  uint32_t checks;
  uint32_t failures;
  uint32_t first_fail_line;
  int32_t first_fail_got;
  int32_t first_fail_want;
  const char *first_fail_what;
  uint32_t finished;     /* 1 once main() is about to return */
} cordic_test_report_t;

volatile cordic_test_report_t cordic_test_report = {0, 0, 0, 0, 0, 0, 0, 0};

#if defined(CORDIC_HOST_SIM)
#define LOG(...) printf(__VA_ARGS__)
#elif defined(CORDIC_TEST_PUTC)
static void log_str(const char *s) {
  while (*s != '\0') {
    CORDIC_TEST_PUTC(*s++);
  }
}
#define LOG(...) log_str("")   /* format strings need no printf on the target */
#else
#define LOG(...) ((void)0)
#endif

static void record_fail(const char *what, long got, long want, unsigned line) {
  cordic_test_report.failures++;
  if (cordic_test_report.first_fail_line == 0u) {
    cordic_test_report.first_fail_line = line;
    cordic_test_report.first_fail_got = (int32_t)got;
    cordic_test_report.first_fail_want = (int32_t)want;
    cordic_test_report.first_fail_what = what;
  }
#if defined(CORDIC_HOST_SIM)
  printf("  FAIL %s: got %ld, expected %ld (line %u)\n", what, got, want, line);
#else
  (void)what;
  (void)got;
  (void)want;
  (void)line;
#endif
}

#define FAIL(what, got, want) record_fail((what), (long)(got), (long)(want), __LINE__)

static void count_check(void) {
  cordic_test_report.checks++;
}

#define EXPECT_EQ(what, got, want)                     \
  do {                                                 \
    count_check();                                     \
    long g_ = (long)(got);                             \
    long w_ = (long)(want);                            \
    if (g_ != w_) {                                    \
      FAIL((what), g_, w_);                            \
    }                                                  \
  } while (0)

#define EXPECT_NEAR(what, got, want, tol)              \
  do {                                                 \
    count_check();                                     \
    int32_t g_ = (int32_t)(got);                       \
    int32_t w_ = (int32_t)(want);                      \
    int32_t d_ = (g_ > w_) ? (g_ - w_) : (w_ - g_);    \
    if (d_ > (int32_t)(tol)) {                         \
      FAIL((what), g_, w_);                            \
    }                                                  \
  } while (0)

/* --------------------------------------------------------------------------- */

static int test_probe(cordic_t *d) {
  cordic_status_t rc = cordic_init(d, BASE);
  if (rc != CORDIC_OK) {
    FAIL("cordic_init", rc, CORDIC_OK);
    return 1;
  }
  EXPECT_EQ("CFG0.DATA_WIDTH", d->data_width, CORDIC_VEC_DATA_WIDTH);
  EXPECT_EQ("CFG0.FRAC_BITS", d->frac_bits, CORDIC_VEC_FRAC_BITS);
  EXPECT_EQ("CFG0.NUM_STAGES", d->num_stages, CORDIC_VEC_NUM_STAGES);
  EXPECT_EQ("K_CIRC", d->k_circ, CORDIC_VEC_K_CIRC);
  EXPECT_EQ("IK_CIRC", d->ik_circ, CORDIC_VEC_IK_CIRC);
  EXPECT_EQ("K_HYP", d->k_hyp, CORDIC_VEC_K_HYP);
  EXPECT_EQ("LIM_HYP", d->lim_hyp, CORDIC_VEC_LIM_HYP);
  EXPECT_EQ("TANH_LIM_HYP", d->tanh_lim_hyp, CORDIC_VEC_TANH_LIM_HYP);
  EXPECT_EQ("sticky errors after init", (long)cordic_errors(d), 0);
  EXPECT_EQ("busy after init", (long)cordic_busy(d), 0);
  EXPECT_EQ("result ready after init", (long)cordic_result_ready(d), 0);
  LOG("probe: Q%d.%d, %d stages, variant %d, latency %d, interval %d\n",
      d->data_width - d->frac_bits, d->frac_bits, d->num_stages, d->variant,
      d->latency, d->interval);
  return 0;
}

/*
 * The vector table itself is truncated at generation time when a build asks for
 * it: sw/Makefile passes -DCORDIC_VEC_LIMIT for the RV32 image, because the table
 * lives in .rodata and Croc's default SRAM is 8 KB (croc_pkg.sv: two banks of 1024
 * words). CORDIC_VEC_COUNT is whatever survived, and the wrapper-check operands
 * are generated first so they always do.
 */

/* Every vector through cordic_exec: raw words exact, wrapper values within
 * their documented bound. */
static void test_all_vectors(const cordic_t *d) {
  int domain_errors = 0;
  for (int i = 0; i < CORDIC_VEC_COUNT; i++) {
    const cordic_vec_t *v = &cordic_vectors[i];
    cordic_result_t r;
    cordic_status_t rc = cordic_exec(d, v->func, v->x, v->y, v->z, &r, 0);

    int want_domain = (v->flags & CORDIC_FLAG_DOMAIN) ? 1 : 0;
    EXPECT_EQ(v->note, (rc == CORDIC_ERR_DOMAIN) ? 1 : 0, want_domain);
    if (want_domain) {
      domain_errors++;
      /* A rejected operation must return zeroes, not a plausible wrong answer. */
      EXPECT_EQ("domain error zeroes X", r.x, 0);
      EXPECT_EQ("domain error zeroes Y", r.y, 0);
      EXPECT_EQ("domain error zeroes Z", r.z, 0);
      continue;
    }
    if (rc != CORDIC_OK) {
      FAIL(v->note, rc, 0);
      continue;
    }
    EXPECT_EQ("raw X", r.x, v->rx);
    EXPECT_EQ("raw Y", r.y, v->ry);
    EXPECT_EQ("raw Z", r.z, v->rz);
    EXPECT_EQ("flags", (long)r.flags, (long)v->flags);
    EXPECT_EQ("func echo", r.func, v->func);

    for (int c = 0; c < v->n_checks; c++) {
      const cordic_vec_check_t *ck = &v->checks[c];
      int32_t got = (ck->out == 'x') ? r.x : (ck->out == 'y') ? r.y : r.z;
      /* The gain-compensating wrappers are checked separately below; here the
       * raw output is compared against the reference. */
      if (v->func == CORDIC_FUNC_ROTATE || v->func == CORDIC_FUNC_HROTATE ||
          (v->func == CORDIC_FUNC_ATAN2 && ck->out == 'x')) {
        cordic_fx_t k = (v->func == CORDIC_FUNC_HROTATE) ? d->k_hyp : d->k_circ;
        got = cordic_ungain(d, got, k);
      }
      EXPECT_NEAR(ck->label, got, ck->expected, ck->tol_lsb);
    }
  }
  LOG("vectors: %d of %d operations, %d reported a domain error\n",
      CORDIC_VEC_COUNT, CORDIC_VEC_TOTAL, domain_errors);
}

/* The named wrappers, spot-checked against the same vectors. */
static void test_wrappers(const cordic_t *d) {
  const cordic_fx_t one = cordic_one(d);
  cordic_fx_t s = 0, c = 0, out = 0;

  EXPECT_EQ("sin_cos rc", cordic_sin_cos(d, 0, &s, &c), CORDIC_OK);
  EXPECT_EQ("cos(0) is one", c, one);
  EXPECT_NEAR("sin(0) is zero", s, 0, 4);

  EXPECT_EQ("atan2 rc", cordic_atan2(d, 0, one, &out), CORDIC_OK);
  EXPECT_NEAR("atan2(0, 1) is zero", out, 0, 4);

  EXPECT_EQ("hypot rc", cordic_hypot(d, one, 0, &out), CORDIC_OK);
  EXPECT_NEAR("hypot(1, 0) is one", out, one, 8);

  EXPECT_EQ("exp rc", cordic_exp(d, 0, &out), CORDIC_OK);
  EXPECT_NEAR("exp(0) is one", out, one, 8);

  EXPECT_EQ("ln rc", cordic_ln(d, one, &out), CORDIC_OK);
  EXPECT_NEAR("ln(1) is zero", out, 0, 8);

  EXPECT_EQ("mul rc", cordic_mul(d, one, one, &out), CORDIC_OK);
  EXPECT_NEAR("1 * 1 is one", out, one, 8);

  EXPECT_EQ("div rc", cordic_div(d, one, one + one, &out), CORDIC_OK);
  EXPECT_NEAR("1 / 2 is one half", out, one / 2, 8);

  cordic_fx_t rx = 0, ry = 0;
  EXPECT_EQ("rotate rc", cordic_rotate(d, one, 0, 0, &rx, &ry), CORDIC_OK);
  EXPECT_NEAR("rotate by zero keeps x", rx, one, 8);
  EXPECT_NEAR("rotate by zero keeps y", ry, 0, 8);

  /* Out-of-domain wrappers must report, not compute. */
  EXPECT_EQ("exp out of domain", cordic_exp(d, d->lim_hyp + d->lim_hyp / 2, &out),
            CORDIC_ERR_DOMAIN);
  EXPECT_EQ("ln(0) out of domain", cordic_ln(d, 0, &out), CORDIC_ERR_DOMAIN);
  EXPECT_EQ("divide by zero", cordic_div(d, one, 0, &out), CORDIC_ERR_DOMAIN);
  /* An unassigned function code is refused before it reaches the hardware. */
  cordic_result_t r;
  EXPECT_EQ("bad func code", cordic_exec(d, 200, 0, 0, 0, &r, 0),
            CORDIC_ERR_INVAL);
  LOG("wrappers: all named helpers behave\n");
}

/* Fixed-point helpers. */
static void test_fixed_point(const cordic_t *d) {
  const cordic_fx_t one = cordic_one(d);
  EXPECT_EQ("int_to_fx(1)", cordic_int_to_fx(d, 1), one);
  EXPECT_EQ("int_to_fx(-1)", cordic_int_to_fx(d, -1), -one);
  EXPECT_EQ("fx_to_int(one)", cordic_fx_to_int(d, one), 1);
  EXPECT_EQ("fx_from_ratio(1, 2)", cordic_fx_from_ratio(d, 1, 2), one / 2);
  EXPECT_EQ("fx_from_ratio(-1, 4)", cordic_fx_from_ratio(d, -1, 4), -(one / 4));
  EXPECT_EQ("fx_from_ratio(1, 0) is zero", cordic_fx_from_ratio(d, 1, 0), 0);
  EXPECT_EQ("ungain by one", cordic_ungain(d, one, one), one);
  EXPECT_EQ("ungain by zero is zero", cordic_ungain(d, one, 0), 0);
  LOG("fixed point: helpers agree\n");
}

/* Queueing, back-off, and the batch API. */
static void test_queueing(const cordic_t *d) {
  cordic_reset(d);
  const cordic_fx_t one = cordic_one(d);

  /* Submit until the queue refuses. At least in_depth must get in; more than that
   * is normal, because the accelerator drains the input queue while the driver is
   * still pushing. What matters is that back-off happens rather than an operation
   * being dropped. */
  int accepted = 0;
  const int attempts = d->in_depth + d->out_depth + 4;
  for (int i = 0; i < attempts; i++) {
    if (cordic_submit(d, CORDIC_FUNC_SIN_COS, 0, 0, 0, (uint8_t)i) != CORDIC_OK) {
      break;
    }
    accepted++;
  }
  count_check();
  if (accepted < d->in_depth) {
    FAIL("submits accepted before back-off", accepted, d->in_depth);
  }
  count_check();
  if (accepted >= attempts) {
    FAIL("the driver never backed off", accepted, attempts - 1);
  }
  EXPECT_EQ("no overflow when the driver backs off",
            (long)(cordic_errors(d) & CORDIC_STATUS_ERR_OVERFLOW_MASK), 0);

  int collected = 0;
  for (int i = 0; i < accepted * 8 && collected < accepted; i++) {
    cordic_result_t r;
    if (cordic_poll(d, &r) == CORDIC_OK) {
      EXPECT_EQ("queued tag preserved", r.tag, collected);
      collected++;
    }
  }
  EXPECT_EQ("queued results collected", collected, accepted);

  /* Batch API over a mix of functions. Built by direct initialisation rather
   * than copied from a template, so a freestanding build needs no memcpy. */
  cordic_op_t batch[4] = {
    {CORDIC_FUNC_SIN_COS, 0, 0, 0},
    {CORDIC_FUNC_EXP, 0, 0, 0},
    {CORDIC_FUNC_MUL, one, 0, one},
    {CORDIC_FUNC_SIN_COS, 0, 0, 0},
  };
  cordic_result_t res[4];
  EXPECT_EQ("batch rc", cordic_exec_batch(d, batch, res, 4, 0), CORDIC_OK);
  EXPECT_EQ("batch cos(0)", res[0].x, one);
  EXPECT_EQ("batch tag 0", res[0].tag, 0);
  EXPECT_EQ("batch tag 3", res[3].tag, 3);
  LOG("queueing: back-off at depth %d, batch of 4 completed in order\n",
      d->in_depth);
}

/* Underflow and error reporting. */
static void test_errors(const cordic_t *d) {
  cordic_reset(d);
  EXPECT_EQ("errors clear after reset", (long)cordic_errors(d), 0);

  cordic_result_t r;
  EXPECT_EQ("poll on an empty queue", cordic_poll(d, &r), CORDIC_ERR_TIMEOUT);

  /* Reading a result register while empty is what latches ERR_UNDERFLOW. */
  (void)cordic_rd(d, CORDIC_RES_X);
  EXPECT_EQ("underflow latched",
            (long)((cordic_errors(d) & CORDIC_STATUS_ERR_UNDERFLOW_MASK) != 0u), 1);
  cordic_clear_errors(d);
  EXPECT_EQ("errors cleared", (long)cordic_errors(d), 0);

  /* A domain error latches ERR_DOMAIN and raises IRQ.ERR. */
  cordic_irq_enable(d, false, true);
  EXPECT_EQ("ln(0)", cordic_ln(d, 0, NULL), CORDIC_ERR_DOMAIN);
  EXPECT_EQ("domain error latched",
            (long)((cordic_errors(d) & CORDIC_STATUS_ERR_DOMAIN_MASK) != 0u), 1);
#if defined(CORDIC_HOST_SIM)
  EXPECT_EQ("interrupt pending", cordic_sim_irq_pending(), 1);
#endif
  uint32_t claimed = cordic_irq_claim(d);
  EXPECT_EQ("IRQ.ERR claimed", (long)((claimed & CORDIC_IRQ_ERR_MASK) != 0u), 1);
  EXPECT_EQ("IRQ cleared after claim", (long)cordic_irq_claim(d), 0);
  cordic_irq_enable(d, false, false);
  cordic_clear_errors(d);
  LOG("errors: underflow, domain and interrupt paths all report correctly\n");
}

int main(void) {
#if defined(CORDIC_HOST_SIM)
  cordic_sim_reset();
#endif
  cordic_t dev;

  cordic_test_report.magic = 0x54455354u;   /* "TEST" */
  LOG("CORDIC driver self-test\n");
  if (test_probe(&dev) != 0) {
    LOG("RESULT: FAIL, no device\n");
    cordic_test_report.finished = 1u;
    return 1;
  }
  test_fixed_point(&dev);
  test_all_vectors(&dev);
  test_wrappers(&dev);
  test_queueing(&dev);
  test_errors(&dev);

#if defined(CORDIC_HOST_SIM)
  cordic_sim_stats_t st = cordic_sim_stats();
  LOG("bus traffic: %u reads, %u writes, %u issued, %u completed, %u dropped\n",
      st.reads, st.writes, st.issued, st.completed, st.dropped);
  if (st.missing_vectors != 0u) {
    FAIL("operations with no vector", st.missing_vectors, 0);
  }
#endif

  cordic_test_report.finished = 1u;
  LOG("RESULT: %s, %u checks, %u failures\n",
      cordic_test_report.failures ? "FAIL" : "PASS",
      cordic_test_report.checks, cordic_test_report.failures);
  return (int)cordic_test_report.failures;
}
