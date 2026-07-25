// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Fully pipelined CORDIC core: NumStages micro-rotations, one register bank per
// stage, one result per clock cycle once the pipeline is full.
//
// Flow control is a single global enable rather than per-stage skid buffers. The
// pipeline freezes as a whole whenever the final stage holds a result the
// consumer will not take. That costs one high-fanout enable net instead of a
// ready chain running back through every stage, and no operation is ever lost.
//
// Every stage's shift amount is a compile-time constant, so `x >>> s` is wiring.
// Circular and linear share shift s while hyperbolic uses the repeat sequence, so
// a stage needs at most a two-way mux ahead of its adders.

module cordic_core_pipe #(
  /// Width of the internal (guarded) datapath.
  parameter int unsigned Width     = 38,
  /// Fractional bits of the internal datapath.
  parameter int unsigned FracBits  = 33,
  /// Number of micro-rotations.
  parameter int unsigned NumStages = 28,
  /// Width of the attribute vector, pass CordicAttrWidth.
  parameter int unsigned AttrWidth = 22
) (
  input  logic clk_i,
  input  logic rst_ni,
  /// Synchronously drop every operation in flight.
  input  logic                     flush_i,

  input  logic                     valid_i,
  output logic                     ready_o,
  input  logic signed [Width-1:0]  x_i,
  input  logic signed [Width-1:0]  y_i,
  input  logic signed [Width-1:0]  z_i,
  input  logic [AttrWidth-1:0]     attr_i,

  output logic                     valid_o,
  input  logic                     ready_i,
  output logic signed [Width-1:0]  x_o,
  output logic signed [Width-1:0]  y_o,
  output logic signed [Width-1:0]  z_o,
  output logic [AttrWidth-1:0]     attr_o,

  /// High while any stage holds a live operation.
  output logic                     busy_o,
  /// Bit 0 is the operation accepted this cycle, bit s+1 the output of stage s.
  output logic [NumStages:0]       dbg_stage_valid_o
);

  `include "cordic_rom.svh"
  `include "cordic_defs.svh"
  `include "cordic_rom_fx.svh"

  // Stage storage as flat vectors rather than packed 2D arrays: Yosys 0.33
  // rejects `logic [N-1:0][W-1:0]` declarations outright. Stage s owns bits
  // [s*Width + Width-1 : s*Width], and every access below uses a genvar, so the
  // offsets are elaboration-time constants and no shifter is inferred.
  logic signed [NumStages*Width-1:0]     xq, yq, zq;
  logic        [NumStages*AttrWidth-1:0] aq;
  logic        [NumStages-1:0]           vq;

  // Freeze everything when the tail holds a result nobody is taking.
  logic pipe_en;
  assign pipe_en = !(vq[NumStages-1] && !ready_i);
  assign ready_o = pipe_en;

  for (genvar s = 0; s < NumStages; s++) begin : gen_stage
    // Circular and linear both walk 0, 1, 2, ...; hyperbolic follows
    // 1, 2, 3, 4, 4, 5, ... with 4 and 13 repeated.
    localparam int unsigned ShiftCircLin = cordic_stage_shift(CordicCoordCirc, s);
    localparam int unsigned ShiftHyp     = cordic_stage_shift(CordicCoordHyp, s);

    localparam logic signed [Width-1:0] AngleCirc =
        Width'(cordic_stage_angle(CordicCoordCirc, s, FracBits));
    localparam logic signed [Width-1:0] AngleLin =
        Width'(cordic_stage_angle(CordicCoordLin, s, FracBits));
    localparam logic signed [Width-1:0] AngleHyp =
        Width'(cordic_stage_angle(CordicCoordHyp, s, FracBits));

    logic signed [Width-1:0] x_in, y_in, z_in;
    logic [AttrWidth-1:0]    a_in;
    logic                    v_in;

    if (s == 0) begin : gen_head
      assign x_in = x_i;
      assign y_in = y_i;
      assign z_in = z_i;
      assign a_in = attr_i;
      assign v_in = valid_i;
    end else begin : gen_body
      assign x_in = xq[(s-1)*Width +: Width];
      assign y_in = yq[(s-1)*Width +: Width];
      assign z_in = zq[(s-1)*Width +: Width];
      assign a_in = aq[(s-1)*AttrWidth +: AttrWidth];
      assign v_in = vq[s-1];
    end

    logic [1:0]              coord;
    logic                    mode;
    logic signed [Width-1:0] x_sh, y_sh, angle;

    assign coord = a_in[CordicAttrCoordLsb+1:CordicAttrCoordLsb];
    assign mode  = a_in[CordicAttrModeBit];

    always_comb begin
      case (coord)
        CordicCoordHyp: begin
          x_sh  = x_in >>> ShiftHyp;
          y_sh  = y_in >>> ShiftHyp;
          angle = AngleHyp;
        end
        CordicCoordLin: begin
          x_sh  = x_in >>> ShiftCircLin;
          y_sh  = y_in >>> ShiftCircLin;
          angle = AngleLin;
        end
        default: begin
          x_sh  = x_in >>> ShiftCircLin;
          y_sh  = y_in >>> ShiftCircLin;
          angle = AngleCirc;
        end
      endcase
    end

    logic signed [Width-1:0] x_st, y_st, z_st;

    cordic_stage #(
      .Width (Width)
    ) i_stage (
      .coord_i     (coord),
      .mode_i      (mode),
      .x_i         (x_in),
      .y_i         (y_in),
      .z_i         (z_in),
      .x_shifted_i (x_sh),
      .y_shifted_i (y_sh),
      .angle_i     (angle),
      .x_o         (x_st),
      .y_o         (y_st),
      .z_o         (z_st)
    );

    // The flush wins over the stall, so a flush lands even while the tail is
    // blocked on a full consumer.
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        vq[s] <= 1'b0;
      end else if (flush_i) begin
        vq[s] <= 1'b0;
      end else if (pipe_en) begin
        vq[s] <= v_in;
      end
    end

    // The datapath registers take no reset: they are only ever read behind a
    // valid bit, and leaving the reset out keeps the reset tree off 3*NumStages
    // wide words.
    always_ff @(posedge clk_i) begin
      if (pipe_en && v_in) begin
        xq[s*Width +: Width]         <= x_st;
        yq[s*Width +: Width]         <= y_st;
        zq[s*Width +: Width]         <= z_st;
        aq[s*AttrWidth +: AttrWidth] <= a_in;
      end
    end
  end

  assign valid_o = vq[NumStages-1];
  assign x_o     = xq[(NumStages-1)*Width +: Width];
  assign y_o     = yq[(NumStages-1)*Width +: Width];
  assign z_o     = zq[(NumStages-1)*Width +: Width];
  assign attr_o  = aq[(NumStages-1)*AttrWidth +: AttrWidth];
  assign busy_o  = |vq;

  assign dbg_stage_valid_o = {vq, valid_i && ready_o};

`ifndef SYNTHESIS
  // The whole point of the global-enable scheme is that a stalled consumer costs
  // throughput and nothing else. If the tail is holding a result the consumer will
  // not take, that result must still be there, unchanged, next cycle.
  a_tail_holds_on_stall: assert property (@(posedge clk_i) disable iff (!rst_ni)
      (valid_o && !ready_i && !flush_i)
      |=> valid_o && $stable({x_o, y_o, z_o, attr_o}))
    else $error("a stalled result was dropped or changed");

  // ready_o low means the pipeline is frozen, so nothing may advance.
  a_frozen_when_not_ready: assert property (@(posedge clk_i) disable iff (!rst_ni)
      (!ready_o && !flush_i) |=> $stable(vq))
    else $error("the pipeline advanced while frozen");
`endif

endmodule
