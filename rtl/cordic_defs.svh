// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Shared definitions for the CORDIC accelerator.
//
// Deliberately an include file rather than a SystemVerilog package, and
// deliberately without an include guard: `include this inside a module body, so
// the localparams and constant functions stay module-local. The design has to
// elaborate in Verilator, Yosys and vendor tools alike, and module-local
// localparams work everywhere, whereas package and $unit-scope support in older
// Yosys releases is patchy and depends on file ordering.
//
// This file holds only constants that stand on their own. The functions that
// read the generated constant tables live in cordic_rom_fx.svh, which must be
// included after both cordic_rom.svh and this file. Nothing here infers hardware.

// The lint_off below is deliberate: these headers are catalogues of constants
// and no single module uses every entry. Suppressing it here keeps `make lint`
// at zero warnings without hiding unused parameters in the modules themselves.
/* verilator lint_off UNUSEDPARAM */

  // ---------------------------------------------------------------------------
  // Coordinate systems and micro-rotation modes
  // ---------------------------------------------------------------------------
  // The generalised CORDIC recurrence, for a stage with shift s and angle a_s:
  //   x' = x - m*d*(y >>> s)
  //   y' = y +   d*(x >>> s)
  //   z' = z -   d*a_s
  // m selects the coordinate system and a_s the matching micro-rotation angle.
  localparam logic [1:0] CordicCoordCirc = 2'd0;  // m = +1, a_s = atan(2**-s)
  localparam logic [1:0] CordicCoordLin  = 2'd1;  // m =  0, a_s = 2**-s
  localparam logic [1:0] CordicCoordHyp  = 2'd2;  // m = -1, a_s = atanh(2**-s)

  localparam logic CordicModeRot = 1'b0;  // d = sign(z), drives z to zero
  localparam logic CordicModeVec = 1'b1;  // d = -sign(y), drives y to zero

  // ---------------------------------------------------------------------------
  // Attribute vector
  // ---------------------------------------------------------------------------
  // Travels beside x, y and z through the datapath so a pipelined core can hold
  // operations of different functions in flight at the same time.
  localparam int unsigned CordicAttrCoordLsb = 0;   // [1:0] coordinate system
  localparam int unsigned CordicAttrModeBit  = 2;   // rotation or vectoring
  localparam int unsigned CordicAttrDomBit   = 3;   // domain error found in pre
  localparam int unsigned CordicAttrChkBit   = 4;   // post must run the residual check
  localparam int unsigned CordicAttrPiLsb    = 5;   // [6:5] see CordicPi* below
  localparam int unsigned CordicAttrDblBit   = 7;   // double z on the way out (LN)
  localparam int unsigned CordicAttrOpLsb    = 8;   // [12:8] function code
  localparam int unsigned CordicAttrTagLsb   = 13;  // [20:13] software tag
  localparam int unsigned CordicAttrWidth    = 21;

  localparam logic [1:0] CordicPiNone = 2'b00;  // leave z alone
  localparam logic [1:0] CordicPiAdd  = 2'b10;  // z += pi
  localparam logic [1:0] CordicPiSub  = 2'b11;  // z -= pi

  // ---------------------------------------------------------------------------
  // Result flag vector
  // ---------------------------------------------------------------------------
  localparam int unsigned CordicFlagDomBit  = 0;
  localparam int unsigned CordicFlagSatXBit = 1;
  localparam int unsigned CordicFlagSatYBit = 2;
  localparam int unsigned CordicFlagSatZBit = 3;
  localparam int unsigned CordicFlagWidth   = 4;

  // Width of the debug iteration index port. Eight bits covers every stage count
  // the ROM tabulates, so the port width never depends on a parameter.
  localparam int unsigned CordicDbgIdxWidth = 8;

  // ---------------------------------------------------------------------------
  // Constant helpers
  // ---------------------------------------------------------------------------

  /// Bits needed to index 0 .. n-1, at least 1.
  function automatic int unsigned cordic_clog2(input int unsigned n);
    int unsigned r;
    int unsigned v;
    begin
      r = 0;
      v = (n > 0) ? n - 1 : 0;
      while (v > 0) begin
        r = r + 1;
        v = v >> 1;
      end
      cordic_clog2 = (r == 0) ? 1 : r;
    end
  endfunction

/* verilator lint_on UNUSEDPARAM */
