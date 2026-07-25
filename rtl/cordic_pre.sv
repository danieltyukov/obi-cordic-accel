// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Operand preparation, purely combinational.
//
// Maps a function code onto the initial vector (x0, y0, z0), a coordinate system
// and a micro-rotation mode, and folds arguments the raw recurrence cannot reach
// back into its convergence domain.
//
// Circular rotation. The bare recurrence converges only for |z| <= sum
// atan(2**-s), about 1.7433 rad or 99.9 degrees, so quadrants two and three are
// out of reach. Subtracting pi and negating the initial vector fixes that,
// because R(z) = R(z - pi) * R(pi) and R(pi) = -I. After the fold the residual
// angle is at most max(pi/2, |z_max| - pi). With the recommended three integer
// bits, z_max is just under 4, so the residual never exceeds 1.5708 rad and every
// representable angle converges: full four-quadrant sin and cos, no error case.
//
// Circular vectoring. atan2 needs x > 0. Negating both components rotates by pi
// and leaves the ratio alone, so the post stage only has to add or subtract pi
// afterwards, with the sign taken from the original y. Every quadrant converges.
//
// Hyperbolic and linear. There is no equivalent fold, so out-of-domain arguments
// are reported. Rotation compares |z| against the radius directly here;
// vectoring cannot be checked without a multiplier, so cordic_post watches the
// residual instead.

module cordic_pre #(
  /// Width of the interface fixed-point word.
  parameter int unsigned DataWidth = 32,
  /// Fractional bits of the interface word.
  parameter int unsigned FracBits  = 29,
  /// Integer guard bits added to the internal datapath.
  parameter int unsigned GuardInt  = 2,
  /// Fractional guard bits added to the internal datapath.
  parameter int unsigned GuardFrac = 4,
  /// Number of micro-rotations, selects which gain and radius constants apply.
  parameter int unsigned NumStages = 28,
  /// Width of the attribute vector, pass CordicAttrWidth.
  parameter int unsigned AttrWidth = 21,
  /// Derived internal datapath width. Do not override.
  parameter int unsigned IntWidth  = DataWidth + GuardInt + GuardFrac
) (
  input  logic [4:0]                  func_i,
  input  logic [7:0]                  tag_i,
  input  logic signed [DataWidth-1:0] x_i,
  input  logic signed [DataWidth-1:0] y_i,
  input  logic signed [DataWidth-1:0] z_i,

  output logic signed [IntWidth-1:0]  x_o,
  output logic signed [IntWidth-1:0]  y_o,
  output logic signed [IntWidth-1:0]  z_o,
  output logic [AttrWidth-1:0]        attr_o
);

  `include "cordic_rom.svh"
  `include "cordic_defs.svh"
  `include "cordic_rom_fx.svh"
  `include "cordic_regmap.svh"

  localparam int unsigned IntFrac = FracBits + GuardFrac;

  // Constants in the internal format.
  localparam logic signed [IntWidth-1:0] Pi =
      IntWidth'(cordic_rom_to_fx(CordicPiRom, IntFrac));
  localparam logic signed [IntWidth-1:0] HalfPi =
      IntWidth'(cordic_rom_to_fx(CordicHalfPiRom, IntFrac));
  localparam logic signed [IntWidth-1:0] InvKCirc =
      IntWidth'(cordic_rom_to_fx(CordicInvKCircRom[NumStages], IntFrac));
  localparam logic signed [IntWidth-1:0] InvKHyp =
      IntWidth'(cordic_rom_to_fx(CordicInvKHypRom[NumStages], IntFrac));
  localparam logic signed [IntWidth-1:0] LimCirc =
      IntWidth'(cordic_rom_to_fx(CordicLimCircRom[NumStages], IntFrac));
  localparam logic signed [IntWidth-1:0] LimHyp =
      IntWidth'(cordic_rom_to_fx(CordicLimHypRom[NumStages], IntFrac));
  localparam logic signed [IntWidth-1:0] LimLin =
      IntWidth'(cordic_rom_to_fx(CordicLimLinRom[NumStages], IntFrac));
  /// One half in the internal format, used to build the LN operand pair.
  localparam logic signed [IntWidth-1:0] Half = IntWidth'(1) <<< (IntFrac - 1);

  /// Widen an interface word into the internal format: sign-extend by GuardInt
  /// and shift left by GuardFrac.
  function automatic logic signed [IntWidth-1:0] widen(input logic signed [DataWidth-1:0] v);
    begin
      widen = {{GuardInt{v[DataWidth-1]}}, v, {GuardFrac{1'b0}}};
    end
  endfunction

  logic signed [IntWidth-1:0] xw, yw, zw;
  assign xw = widen(x_i);
  assign yw = widen(y_i);
  assign zw = widen(z_i);

  logic signed [IntWidth-1:0] x0, y0, z0;
  logic [1:0]                 coord;
  logic                       mode;
  logic                       dom_err;
  logic                       resid_chk;
  logic [1:0]                 pi_ctl;
  logic                       dbl_z;

  /// Magnitude of an internal-format value.
  function automatic logic signed [IntWidth-1:0] absv(input logic signed [IntWidth-1:0] v);
    begin
      absv = (v < 0) ? -v : v;
    end
  endfunction

  always_comb begin
    // Defaults: a generic circular rotation of the supplied vector.
    coord     = CordicCoordCirc;
    mode      = CordicModeRot;
    x0        = xw;
    y0        = yw;
    z0        = zw;
    dom_err   = 1'b0;
    resid_chk = 1'b0;
    pi_ctl    = CordicPiNone;
    dbl_z     = 1'b0;

    case (func_i)
      // Circular rotation from the reciprocal gain, so cos and sin come out
      // already gain-compensated.
      CordicFuncSinCos: begin
        x0 = InvKCirc;
        y0 = '0;
      end

      // Generic circular rotation. Outputs carry the gain K_CIRC.
      CordicFuncRotate: ;

      // Circular vectoring: z accumulates atan2(y, x), x ends at K*hypot(x,y).
      CordicFuncAtan2: begin
        mode = CordicModeVec;
        z0   = '0;
        if (xw < 0) begin
          x0     = -xw;
          y0     = -yw;
          pi_ctl = (yw < 0) ? CordicPiSub : CordicPiAdd;
        end
      end

      // Hyperbolic rotation from the reciprocal hyperbolic gain: cosh and sinh.
      CordicFuncSinhCosh: begin
        coord = CordicCoordHyp;
        x0    = InvKHyp;
        y0    = '0;
      end

      // Generic hyperbolic rotation. Outputs carry the gain K_HYP.
      CordicFuncHrotate: begin
        coord = CordicCoordHyp;
      end

      // Hyperbolic vectoring: z accumulates atanh(y/x).
      CordicFuncAtanh: begin
        coord     = CordicCoordHyp;
        mode      = CordicModeVec;
        z0        = '0;
        resid_chk = 1'b1;
        // atanh((-y)/(-x)) equals atanh(y/x) and sqrt(x^2 - y^2) is unchanged,
        // so a negative x only needs both components flipped.
        if (xw < 0) begin
          x0 = -xw;
          y0 = -yw;
        end
        if (x0 == 0) dom_err = 1'b1;
      end

      // exp(z) = cosh(z) + sinh(z), so starting from x0 = y0 = 1/Kh leaves
      // exp(z) in both x and y.
      CordicFuncExp: begin
        coord = CordicCoordHyp;
        x0    = InvKHyp;
        y0    = InvKHyp;
      end

      // ln(w) = 2*atanh((w-1)/(w+1)). Halving both components keeps the ratio
      // and keeps x0 inside the format for every representable w.
      CordicFuncLn: begin
        coord     = CordicCoordHyp;
        mode      = CordicModeVec;
        x0        = (xw >>> 1) + Half;
        y0        = (xw >>> 1) - Half;
        z0        = '0;
        resid_chk = 1'b1;
        dbl_z     = 1'b1;
        if (xw <= 0) dom_err = 1'b1;
      end

      // Linear rotation: y ends at x*z, gain is exactly one.
      CordicFuncMul: begin
        coord = CordicCoordLin;
        y0    = '0;
      end

      // Linear vectoring: z accumulates y/x by binary long division.
      CordicFuncDiv: begin
        coord     = CordicCoordLin;
        mode      = CordicModeVec;
        z0        = '0;
        resid_chk = 1'b1;
        if (xw < 0) begin
          x0 = -xw;
          y0 = -yw;
        end
        if (x0 == 0) dom_err = 1'b1;
      end

      // Unassigned function codes are reported rather than silently computed.
      default: dom_err = 1'b1;
    endcase

    // Rotation-mode argument folding and range checks.
    if (mode == CordicModeRot) begin
      case (coord)
        CordicCoordCirc: begin
          // R(z) = R(z -+ pi) * R(-+pi) and R(pi) = -I.
          if (z0 > HalfPi) begin
            z0 = z0 - Pi;
            x0 = -x0;
            y0 = -y0;
          end else if (z0 < -HalfPi) begin
            z0 = z0 + Pi;
            x0 = -x0;
            y0 = -y0;
          end
          // Unreachable while DataWidth - FracBits is 3, kept so that wider
          // integer parts, where |z| can exceed pi/2 + LimCirc, stay honest.
          if (absv(z0) > LimCirc) dom_err = 1'b1;
        end
        CordicCoordLin: if (absv(z0) > LimLin) dom_err = 1'b1;
        default:        if (absv(z0) > LimHyp) dom_err = 1'b1;
      endcase
    end
  end

  assign x_o = x0;
  assign y_o = y0;
  assign z_o = z0;

  always_comb begin
    attr_o                                                = '0;
    attr_o[CordicAttrCoordLsb+1:CordicAttrCoordLsb]       = coord;
    attr_o[CordicAttrModeBit]                             = mode;
    attr_o[CordicAttrDomBit]                              = dom_err;
    attr_o[CordicAttrChkBit]                              = resid_chk;
    attr_o[CordicAttrPiLsb+1:CordicAttrPiLsb]             = pi_ctl;
    attr_o[CordicAttrDblBit]                              = dbl_z;
    attr_o[CordicAttrOpLsb+4:CordicAttrOpLsb]             = func_i;
    attr_o[CordicAttrTagLsb+7:CordicAttrTagLsb]           = tag_i;
  end

endmodule
