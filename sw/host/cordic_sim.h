/* Copyright 2026 Daniel Tyukov
 * SPDX-License-Identifier: Apache-2.0
 *
 * Host-side peripheral model, used only by the CORDIC_HOST_SIM build.
 */

#ifndef CORDIC_SIM_H
#define CORDIC_SIM_H

#include <stdint.h>

#include "cordic.h"

/** Access counters the test inspects to confirm the driver's bus behaviour. */
typedef struct {
  uint32_t reads;
  uint32_t writes;
  uint32_t issued;
  uint32_t completed;
  uint32_t dropped;          /**< issues refused because the queue was full */
  uint32_t missing_vectors;  /**< operations with no entry in cordic_vectors.h */
} cordic_sim_stats_t;

/** Any base address will do; the model ignores it. */
#define CORDIC_SIM_BASE 0x20001000u

void cordic_sim_reset(void);
cordic_sim_stats_t cordic_sim_stats(void);
int cordic_sim_irq_pending(void);

#endif /* CORDIC_SIM_H */
