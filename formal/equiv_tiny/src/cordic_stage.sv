// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// One generalised CORDIC micro-rotation, purely combinational.
//
// Both the fully pipelined and the iterative core instantiate this module, which
// is what makes them bit-identical: the arithmetic exists in exactly one place.
//
// The shift network lives outside. A pipelined stage knows its shift amount at
// elaboration time, so `x >>> s` is wiring there, while the iterative core needs
// a real barrel shifter. Taking the shifted operands as inputs keeps that cost
// where it belongs instead of forcing a barrel shifter into every stage.

module cordic_stage #(
  /// Width of the internal (guarded) datapath.
  parameter int unsigned Width = 38
) (
  /// Coordinate system: CordicCoordCirc, CordicCoordLin or CordicCoordHyp.
  input  logic [1:0]              coord_i,
  /// CordicModeRot drives z to zero, CordicModeVec drives y to zero.
  input  logic                    mode_i,

  input  logic signed [Width-1:0] x_i,
  input  logic signed [Width-1:0] y_i,
  input  logic signed [Width-1:0] z_i,
  /// x_i arithmetic-shifted right by this stage's shift amount.
  input  logic signed [Width-1:0] x_shifted_i,
  /// y_i arithmetic-shifted right by this stage's shift amount.
  input  logic signed [Width-1:0] y_shifted_i,
  /// This stage's micro-rotation angle in the internal format.
  input  logic signed [Width-1:0] angle_i,

  output logic signed [Width-1:0] x_o,
  output logic signed [Width-1:0] y_o,
  output logic signed [Width-1:0] z_o
);

  `include "cordic_defs.svh"

  // Rotation direction. `dir` high means d = +1.
  //   rotation:  d = sign(z), so d = +1 while z is non-negative
  //   vectoring: d = -sign(y), so d = +1 while y is negative
  logic dir;
  assign dir = (mode_i == CordicModeVec) ? y_i[Width-1] : ~z_i[Width-1];

  // x' = x - m*d*(y >> s). m is +1 circular, 0 linear and -1 hyperbolic, so the
  // hyperbolic case is the circular one with the addend's sign flipped, and the
  // linear case leaves x alone.
  always_comb begin
    case (coord_i)
      CordicCoordCirc: x_o = dir ? (x_i - y_shifted_i) : (x_i + y_shifted_i);
      CordicCoordHyp:  x_o = dir ? (x_i + y_shifted_i) : (x_i - y_shifted_i);
      default:         x_o = x_i;
    endcase
  end

  // y' = y + d*(x >> s)
  assign y_o = dir ? (y_i + x_shifted_i) : (y_i - x_shifted_i);

  // z' = z - d*a_s
  assign z_o = dir ? (z_i - angle_i) : (z_i + angle_i);

endmodule
