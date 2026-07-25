// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Constant functions that read the generated tables in cordic_rom.svh.
//
// Include order inside a module body:
//   `include "cordic_rom.svh"
//   `include "cordic_defs.svh"
//   `include "cordic_rom_fx.svh"
//
// No include guard, by the same reasoning as cordic_defs.svh. Nothing here infers
// hardware: every call site passes constants, so the results fold away.

// The lint_off below is deliberate: these headers are catalogues of constants
// and no single module uses every entry. Suppressing it here keeps `make lint`
// at zero warnings without hiding unused parameters in the modules themselves.
/* verilator lint_off UNUSEDPARAM */

  /// Re-round a Q3.61 ROM entry to `frac` fractional bits, round half up.
  /// Mirrors cordic_tables.rom_to_fx() in the Python model exactly.
  function automatic logic signed [63:0] cordic_rom_to_fx(input logic [63:0] rom_val,
                                                          input int unsigned frac);
    logic signed [63:0] v;
    int unsigned        sh;
    begin
      v  = $signed(rom_val);
      sh = CordicRomFrac - frac;
      cordic_rom_to_fx = (sh == 0) ? v : ((v + (64'sd1 <<< (sh - 1))) >>> sh);
    end
  endfunction

  /// Shift amount used by stage `stage` of coordinate system `coord`.
  /// Circular and linear walk 0, 1, 2, ...; hyperbolic follows the repeat
  /// sequence 1, 2, 3, 4, 4, 5, ..., 13, 13, 14, ... taken from the ROM.
  function automatic int unsigned cordic_stage_shift(input logic [1:0] coord,
                                                     input int unsigned stage);
    begin
      if (coord == CordicCoordHyp) cordic_stage_shift = 32'(CordicHypShiftRom[stage]);
      else                         cordic_stage_shift = stage;
    end
  endfunction

  /// Micro-rotation angle of stage `stage`, quantised to `frac` fractional bits.
  function automatic logic signed [63:0] cordic_stage_angle(input logic [1:0] coord,
                                                            input int unsigned stage,
                                                            input int unsigned frac);
    int unsigned sh;
    begin
      sh = cordic_stage_shift(coord, stage);
      case (coord)
        CordicCoordCirc: cordic_stage_angle = cordic_rom_to_fx(CordicAtanRom[sh], frac);
        // 2**-s is exact in any binary format, so no ROM lookup is needed.
        CordicCoordLin:  cordic_stage_angle = (sh > frac) ? 64'sd0
                                                         : (64'sd1 <<< (frac - sh));
        default:         cordic_stage_angle = cordic_rom_to_fx(CordicAtanhRom[sh], frac);
      endcase
    end
  endfunction

/* verilator lint_on UNUSEDPARAM */
