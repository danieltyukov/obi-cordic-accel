// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// The CORDIC function unit: operand preparation, one of the two cores, result
// post-processing. Valid/ready in, valid/ready out, one function code per
// operation, no shared configuration state, so successive operations may use
// different coordinate systems and modes freely.
//
// Variant picks the microarchitecture. Both cores instantiate the same
// cordic_stage over the same shift and angle sequence, so switching between them
// changes area and throughput but not a single result bit; tb/test_equivalence.py
// asserts that.
//
// cordic_pre and cordic_post stay combinational, wrapped around the registered
// core. Their logic (a mux tree, one add for the pi fold, a magnitude compare, a
// rounding add) is comparable in depth to one micro-rotation, so they share a
// cycle with the first and last stage rather than adding two more of latency.

module cordic_unit #(
  /// Width of the interface fixed-point word.
  parameter int unsigned DataWidth = 32,
  /// Fractional bits of the interface word. DataWidth - FracBits >= 3.
  parameter int unsigned FracBits  = 29,
  /// Number of micro-rotations.
  parameter int unsigned NumStages = 28,
  /// 0 selects the fully pipelined core, 1 the iterative one.
  parameter int unsigned Variant   = 0,
  /// Integer guard bits of the internal datapath.
  parameter int unsigned GuardInt  = 2,
  /// Fractional guard bits of the internal datapath.
  parameter int unsigned GuardFrac = 4,
  /// Width of the attribute vector, pass CordicAttrWidth.
  parameter int unsigned AttrWidth = 21,
  /// Width of the flag vector, pass CordicFlagWidth.
  parameter int unsigned FlagWidth = 4,
  /// Derived internal datapath width. Do not override.
  parameter int unsigned IntWidth  = DataWidth + GuardInt + GuardFrac
) (
  input  logic clk_i,
  input  logic rst_ni,

  input  logic                        valid_i,
  output logic                        ready_o,
  input  logic [4:0]                  func_i,
  input  logic [7:0]                  tag_i,
  input  logic signed [DataWidth-1:0] x_i,
  input  logic signed [DataWidth-1:0] y_i,
  input  logic signed [DataWidth-1:0] z_i,

  output logic                        valid_o,
  input  logic                        ready_i,
  output logic signed [DataWidth-1:0] x_o,
  output logic signed [DataWidth-1:0] y_o,
  output logic signed [DataWidth-1:0] z_o,
  output logic [FlagWidth-1:0]        flags_o,
  output logic [4:0]                  func_o,
  output logic [7:0]                  tag_o,

  output logic                        busy_o,

  /// Per-stage occupancy, pipelined variant only, zero otherwise.
  output logic [NumStages:0]          dbg_stage_valid_o,
  /// Intermediate vector once per iteration, iterative variant only.
  output logic                        dbg_iter_valid_o,
  output logic [7:0]                  dbg_iter_idx_o,
  output logic signed [IntWidth-1:0]  dbg_iter_x_o,
  output logic signed [IntWidth-1:0]  dbg_iter_y_o,
  output logic signed [IntWidth-1:0]  dbg_iter_z_o
);

  logic signed [IntWidth-1:0] pre_x, pre_y, pre_z;
  logic [AttrWidth-1:0]       pre_attr;

  cordic_pre #(
    .DataWidth (DataWidth),
    .FracBits  (FracBits),
    .GuardInt  (GuardInt),
    .GuardFrac (GuardFrac),
    .NumStages (NumStages),
    .AttrWidth (AttrWidth)
  ) i_pre (
    .func_i,
    .tag_i,
    .x_i,
    .y_i,
    .z_i,
    .x_o    (pre_x),
    .y_o    (pre_y),
    .z_o    (pre_z),
    .attr_o (pre_attr)
  );

  logic signed [IntWidth-1:0] core_x, core_y, core_z;
  logic [AttrWidth-1:0]       core_attr;

  if (Variant == 0) begin : gen_pipelined
    cordic_core_pipe #(
      .Width     (IntWidth),
      .FracBits  (FracBits + GuardFrac),
      .NumStages (NumStages),
      .AttrWidth (AttrWidth)
    ) i_core (
      .clk_i,
      .rst_ni,
      .valid_i,
      .ready_o,
      .x_i               (pre_x),
      .y_i               (pre_y),
      .z_i               (pre_z),
      .attr_i            (pre_attr),
      .valid_o,
      .ready_i,
      .x_o               (core_x),
      .y_o               (core_y),
      .z_o               (core_z),
      .attr_o            (core_attr),
      .busy_o,
      .dbg_stage_valid_o (dbg_stage_valid_o)
    );

    assign dbg_iter_valid_o = 1'b0;
    assign dbg_iter_idx_o   = '0;
    assign dbg_iter_x_o     = '0;
    assign dbg_iter_y_o     = '0;
    assign dbg_iter_z_o     = '0;
  end else begin : gen_iterative
    cordic_core_iter #(
      .Width     (IntWidth),
      .FracBits  (FracBits + GuardFrac),
      .NumStages (NumStages),
      .AttrWidth (AttrWidth)
    ) i_core (
      .clk_i,
      .rst_ni,
      .valid_i,
      .ready_o,
      .x_i         (pre_x),
      .y_i         (pre_y),
      .z_i         (pre_z),
      .attr_i      (pre_attr),
      .valid_o,
      .ready_i,
      .x_o         (core_x),
      .y_o         (core_y),
      .z_o         (core_z),
      .attr_o      (core_attr),
      .busy_o,
      .dbg_valid_o (dbg_iter_valid_o),
      .dbg_idx_o   (dbg_iter_idx_o),
      .dbg_x_o     (dbg_iter_x_o),
      .dbg_y_o     (dbg_iter_y_o),
      .dbg_z_o     (dbg_iter_z_o)
    );

    assign dbg_stage_valid_o = '0;
  end

  cordic_post #(
    .DataWidth (DataWidth),
    .FracBits  (FracBits),
    .GuardInt  (GuardInt),
    .GuardFrac (GuardFrac),
    .NumStages (NumStages),
    .AttrWidth (AttrWidth),
    .FlagWidth (FlagWidth)
  ) i_post (
    .x_i     (core_x),
    .y_i     (core_y),
    .z_i     (core_z),
    .attr_i  (core_attr),
    .x_o,
    .y_o,
    .z_o,
    .flags_o,
    .func_o,
    .tag_o
  );

endmodule
