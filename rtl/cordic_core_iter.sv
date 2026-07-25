// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Iterative (folded) CORDIC core: one micro-rotation reused NumStages times.
//
// The same cordic_stage the pipelined core uses walks the same shift and angle
// sequence, so both cores produce bit-identical results. What changes is the
// cost: three registers instead of 3*NumStages, one adder set instead of
// NumStages of them, but now two barrel shifters and a mux over the angle table,
// and one result every NumStages+1 cycles instead of every cycle.
//
// The debug port streams the intermediate vector out once per iteration, which is
// what the convergence-trajectory figure in docs/img is plotted from.

module cordic_core_iter #(
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

  input  logic                    valid_i,
  output logic                    ready_o,
  input  logic signed [Width-1:0] x_i,
  input  logic signed [Width-1:0] y_i,
  input  logic signed [Width-1:0] z_i,
  input  logic [AttrWidth-1:0]    attr_i,

  output logic                    valid_o,
  input  logic                    ready_i,
  output logic signed [Width-1:0] x_o,
  output logic signed [Width-1:0] y_o,
  output logic signed [Width-1:0] z_o,
  output logic [AttrWidth-1:0]    attr_o,

  /// High while an operation is loaded or in flight.
  output logic                    busy_o,

  /// Intermediate vector after dbg_idx_o micro-rotations, valid while busy.
  output logic                    dbg_valid_o,
  output logic [7:0]              dbg_idx_o,
  output logic signed [Width-1:0] dbg_x_o,
  output logic signed [Width-1:0] dbg_y_o,
  output logic signed [Width-1:0] dbg_z_o
);

  `include "cordic_rom.svh"
  `include "cordic_defs.svh"
  `include "cordic_rom_fx.svh"

  // Wide enough to hold NumStages itself, which is the terminal count.
  localparam int unsigned IdxWidth   = cordic_clog2(NumStages + 1);
  localparam int unsigned ShiftWidth = 6;

  localparam logic [1:0] StIdle = 2'd0;
  localparam logic [1:0] StRun  = 2'd1;
  localparam logic [1:0] StDone = 2'd2;

  logic [1:0]              state_q, state_d;
  logic [IdxWidth-1:0]     cnt_q, cnt_d;
  logic signed [Width-1:0] xr_q, yr_q, zr_q;
  logic signed [Width-1:0] xr_d, yr_d, zr_d;
  logic [AttrWidth-1:0]    ar_q, ar_d;

  // ---------------------------------------------------------------------------
  // Constant angle tables, one entry per stage per coordinate system. The
  // synthesiser folds them into a mux over literals.
  // ---------------------------------------------------------------------------
  logic signed [NumStages-1:0][Width-1:0]      angle_circ, angle_lin, angle_hyp;
  logic        [NumStages-1:0][ShiftWidth-1:0] shift_hyp;

  for (genvar s = 0; s < NumStages; s++) begin : gen_tables
    assign angle_circ[s] = Width'(cordic_stage_angle(CordicCoordCirc, s, FracBits));
    assign angle_lin[s]  = Width'(cordic_stage_angle(CordicCoordLin, s, FracBits));
    assign angle_hyp[s]  = Width'(cordic_stage_angle(CordicCoordHyp, s, FracBits));
    assign shift_hyp[s]  = ShiftWidth'(cordic_stage_shift(CordicCoordHyp, s));
  end

  logic [1:0] coord;
  logic       mode;
  assign coord = ar_q[CordicAttrCoordLsb+1:CordicAttrCoordLsb];
  assign mode  = ar_q[CordicAttrModeBit];

  // Angle and shift for the iteration about to be applied. The index saturates
  // so the StDone cycle, where cnt_q equals NumStages, cannot read off the end.
  logic [ShiftWidth-1:0]   shift_sel;
  logic signed [Width-1:0] angle_sel;
  logic [IdxWidth-1:0]     idx;

  assign idx = (cnt_q < IdxWidth'(NumStages)) ? cnt_q : IdxWidth'(NumStages - 1);

  always_comb begin
    case (coord)
      CordicCoordHyp: begin
        shift_sel = shift_hyp[idx];
        angle_sel = angle_hyp[idx];
      end
      CordicCoordLin: begin
        shift_sel = ShiftWidth'(idx);
        angle_sel = angle_lin[idx];
      end
      default: begin
        shift_sel = ShiftWidth'(idx);
        angle_sel = angle_circ[idx];
      end
    endcase
  end

  logic signed [Width-1:0] x_sh, y_sh;
  assign x_sh = xr_q >>> shift_sel;
  assign y_sh = yr_q >>> shift_sel;

  logic signed [Width-1:0] x_st, y_st, z_st;

  cordic_stage #(
    .Width (Width)
  ) i_stage (
    .coord_i     (coord),
    .mode_i      (mode),
    .x_i         (xr_q),
    .y_i         (yr_q),
    .z_i         (zr_q),
    .x_shifted_i (x_sh),
    .y_shifted_i (y_sh),
    .angle_i     (angle_sel),
    .x_o         (x_st),
    .y_o         (y_st),
    .z_o         (z_st)
  );

  // ---------------------------------------------------------------------------
  // Control
  // ---------------------------------------------------------------------------
  // Accepting in StDone as well as StIdle saves a cycle per operation. The
  // consumer's ready reaches ready_o combinationally, which is safe here because
  // both sides of this core face FIFOs whose handshake comes out of registers.
  logic load;
  assign ready_o = (state_q == StIdle) || ((state_q == StDone) && ready_i);
  assign load    = valid_i && ready_o;

  always_comb begin
    state_d = state_q;
    cnt_d   = cnt_q;
    xr_d    = xr_q;
    yr_d    = yr_q;
    zr_d    = zr_q;
    ar_d    = ar_q;

    case (state_q)
      StRun: begin
        xr_d  = x_st;
        yr_d  = y_st;
        zr_d  = z_st;
        cnt_d = cnt_q + 1'b1;
        if (cnt_q == IdxWidth'(NumStages - 1)) state_d = StDone;
      end
      StDone: begin
        if (ready_i) state_d = StIdle;
      end
      default: ;  // StIdle waits for `load` below
    endcase

    // A load overrides the sequencing above, which is what lets an operation be
    // accepted in the same cycle the previous result is taken.
    if (load) begin
      xr_d    = x_i;
      yr_d    = y_i;
      zr_d    = z_i;
      ar_d    = attr_i;
      cnt_d   = '0;
      state_d = StRun;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= StIdle;
      cnt_q   <= '0;
    end else begin
      state_q <= state_d;
      cnt_q   <= cnt_d;
    end
  end

  always_ff @(posedge clk_i) begin
    xr_q <= xr_d;
    yr_q <= yr_d;
    zr_q <= zr_d;
    ar_q <= ar_d;
  end

  assign valid_o = (state_q == StDone);
  assign x_o     = xr_q;
  assign y_o     = yr_q;
  assign z_o     = zr_q;
  assign attr_o  = ar_q;
  assign busy_o  = (state_q != StIdle);

  assign dbg_valid_o = (state_q != StIdle);
  assign dbg_idx_o   = 8'(cnt_q);
  assign dbg_x_o     = xr_q;
  assign dbg_y_o     = yr_q;
  assign dbg_z_o     = zr_q;

endmodule
