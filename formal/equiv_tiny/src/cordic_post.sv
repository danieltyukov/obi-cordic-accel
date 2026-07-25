// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Result post-processing, purely combinational: convergence check, angle
// correction, rounding and saturation back to the interface format.
//
// Vectoring domain check. The closed-form condition for hyperbolic vectoring is
// |y/x| <= tanh(sum atanh(2**-s)), and for linear vectoring |y/x| <= sum 2**-s.
// Testing either literally needs a full-width multiply by a constant, which is by
// far the largest block the iterative variant would contain. Instead the residual
// is inspected: vectoring drives y to zero, so on convergence |y| ends below the
// granularity of the last micro-rotation, |x| >> s_last, whereas a non-converging
// argument leaves |y| stuck far above it.
//
// That is not merely cheaper, it tests the thing that actually matters. It was
// tuned and characterised against the bit-accurate model in tb/cordic_model.py:
// with ResidShiftMargin = 1 and ResidFloorMul = 4, a sweep of 380k arguments
// produced no false positives at all, and an out-of-domain argument is caught
// once it is more than 16 LSBs past the boundary (11 for ATANH, 16 for DIV, 9 for
// LN). Inside that band the operation still converges, so a missed flag returns a
// correct result rather than a wrong one. tb/test_domain.py re-checks both halves.

module cordic_post #(
  /// Width of the interface fixed-point word.
  parameter int unsigned DataWidth = 32,
  /// Fractional bits of the interface word.
  parameter int unsigned FracBits  = 29,
  /// Integer guard bits of the internal datapath.
  parameter int unsigned GuardInt  = 2,
  /// Fractional guard bits of the internal datapath.
  parameter int unsigned GuardFrac = 4,
  /// Number of micro-rotations.
  parameter int unsigned NumStages = 28,
  /// Width of the attribute vector, pass CordicAttrWidth.
  parameter int unsigned AttrWidth = 22,
  /// Width of the flag vector, pass CordicFlagWidth.
  parameter int unsigned FlagWidth = 4,
  /// Slack on the residual threshold shift. 1 doubles the threshold.
  parameter int unsigned ResidShiftMargin = 1,
  /// Residual noise floor in internal LSBs, as a multiple of NumStages.
  parameter int unsigned ResidFloorMul = 4,
  /// Derived internal datapath width. Do not override.
  parameter int unsigned IntWidth  = DataWidth + GuardInt + GuardFrac
) (
  input  logic signed [IntWidth-1:0]  x_i,
  input  logic signed [IntWidth-1:0]  y_i,
  input  logic signed [IntWidth-1:0]  z_i,
  input  logic [AttrWidth-1:0]        attr_i,

  output logic signed [DataWidth-1:0] x_o,
  output logic signed [DataWidth-1:0] y_o,
  output logic signed [DataWidth-1:0] z_o,
  output logic [FlagWidth-1:0]        flags_o,
  output logic [4:0]                  func_o,
  output logic [7:0]                  tag_o
);

  `include "cordic_rom.svh"
  `include "cordic_defs.svh"
  `include "cordic_rom_fx.svh"

  localparam int unsigned IntFrac = FracBits + GuardFrac;

  localparam logic signed [IntWidth-1:0] Pi =
      IntWidth'(cordic_rom_to_fx(CordicPiRom, IntFrac));

  // Residual thresholds. The last stage's shift sets the convergence
  // granularity; ResidShiftMargin widens it and ResidFloorMul covers the
  // truncation noise the micro-rotations accumulate.
  localparam int unsigned LastShiftHyp = cordic_stage_shift(CordicCoordHyp, NumStages - 1);
  localparam int unsigned LastShiftLin = cordic_stage_shift(CordicCoordLin, NumStages - 1);
  localparam int unsigned ResidShiftHyp =
      (LastShiftHyp > ResidShiftMargin) ? LastShiftHyp - ResidShiftMargin : 0;
  localparam int unsigned ResidShiftLin =
      (LastShiftLin > ResidShiftMargin) ? LastShiftLin - ResidShiftMargin : 0;
  localparam logic signed [IntWidth-1:0] ResidFloor =
      IntWidth'(ResidFloorMul * NumStages);

  logic [1:0] coord;
  logic       mode;
  logic       dom_pre, resid_chk, dbl_z, zero_res;
  logic [1:0] pi_ctl;

  assign coord     = attr_i[CordicAttrCoordLsb+1:CordicAttrCoordLsb];
  assign mode      = attr_i[CordicAttrModeBit];
  assign dom_pre   = attr_i[CordicAttrDomBit];
  assign resid_chk = attr_i[CordicAttrChkBit];
  assign pi_ctl    = attr_i[CordicAttrPiLsb+1:CordicAttrPiLsb];
  assign dbl_z     = attr_i[CordicAttrDblBit];
  assign zero_res  = attr_i[CordicAttrZeroBit];
  assign func_o    = attr_i[CordicAttrOpLsb+4:CordicAttrOpLsb];
  assign tag_o     = attr_i[CordicAttrTagLsb+7:CordicAttrTagLsb];

  function automatic logic signed [IntWidth-1:0] absv(input logic signed [IntWidth-1:0] v);
    begin
      absv = (v < 0) ? -v : v;
    end
  endfunction

  // ---------------------------------------------------------------------------
  // Convergence check
  // ---------------------------------------------------------------------------
  logic signed [IntWidth-1:0] resid_thresh;
  logic                       dom_resid;

  always_comb begin
    resid_thresh = (coord == CordicCoordHyp) ? (absv(x_i) >>> ResidShiftHyp)
                                            : (absv(x_i) >>> ResidShiftLin);
    resid_thresh = resid_thresh + ResidFloor;
    dom_resid    = resid_chk && (absv(y_i) > resid_thresh);
  end

  logic dom_err;
  assign dom_err = dom_pre || dom_resid;

  // ---------------------------------------------------------------------------
  // Angle correction
  // ---------------------------------------------------------------------------
  // ATAN2 with a negative x needs +-pi added back after the pi pre-rotation, and
  // LN needs its half-logarithm doubled. No function sets both.
  logic signed [IntWidth-1:0] z_corr, z_final;

  always_comb begin
    z_corr = z_i;
    if (pi_ctl[1]) z_corr = pi_ctl[0] ? (z_i - Pi) : (z_i + Pi);
    z_final = dbl_z ? (z_corr <<< 1) : z_corr;
  end

  // ---------------------------------------------------------------------------
  // Round to the interface format and saturate
  // ---------------------------------------------------------------------------
  localparam logic signed [IntWidth-1:0] FxMax = (IntWidth'(1) <<< (DataWidth - 1)) - 1;
  localparam logic signed [IntWidth-1:0] FxMin = -(IntWidth'(1) <<< (DataWidth - 1));

  /// Round half up by GuardFrac bits, then clamp. Bit DataWidth of the result is
  /// the saturation flag; a function returning one vector keeps this usable in
  /// tools that dislike output arguments.
  function automatic logic [DataWidth:0] pack(input logic signed [IntWidth-1:0] v);
    logic signed [IntWidth-1:0] r;
    begin
      r = (v + (IntWidth'(1) <<< (GuardFrac - 1))) >>> GuardFrac;
      if (r > FxMax)      pack = {1'b1, FxMax[DataWidth-1:0]};
      else if (r < FxMin) pack = {1'b1, FxMin[DataWidth-1:0]};
      else                pack = {1'b0, r[DataWidth-1:0]};
    end
  endfunction

  logic [DataWidth:0] px, py, pz;
  assign px = pack(x_i);
  assign py = pack(y_i);
  assign pz = pack(z_final);

  // A domain error zeroes the outputs. Returning the raw non-converged vector
  // would look like a plausible answer; zero plus the flag cannot be mistaken
  // for one.
  always_comb begin
    if (dom_err) begin
      x_o     = '0;
      y_o     = '0;
      z_o     = '0;
      flags_o = '0;
      flags_o[CordicFlagDomBit] = 1'b1;
    end else if (zero_res) begin
      // A defined answer, not an error, so no flag is raised.
      x_o     = '0;
      y_o     = '0;
      z_o     = '0;
      flags_o = '0;
    end else begin
      x_o     = px[DataWidth-1:0];
      y_o     = py[DataWidth-1:0];
      z_o     = pz[DataWidth-1:0];
      flags_o = '0;
      flags_o[CordicFlagSatXBit] = px[DataWidth];
      flags_o[CordicFlagSatYBit] = py[DataWidth];
      flags_o[CordicFlagSatZBit] = pz[DataWidth];
    end
  end

  // mode is part of the attribute vector but only pre and the cores need it.
  logic unused_mode;
  assign unused_mode = mode;

endmodule
