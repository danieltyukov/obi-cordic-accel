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

  // ---------------------------------------------------------------------------
  // Table accessors
  // ---------------------------------------------------------------------------
  // The generated tables in cordic_rom.svh are flat vectors, because Yosys 0.33
  // cannot parse a packed 2D localparam. Entry i of a table with W-bit entries
  // sits at bits [i*W + W-1 : i*W]; these accessors are the only place that
  // layout is spelled out. Every call site passes a constant, so they fold away.

  function automatic logic [63:0] cordic_atan_rom(input int unsigned idx);
    begin
      cordic_atan_rom = CordicAtanRom[idx*64 +: 64];
    end
  endfunction

  function automatic logic [63:0] cordic_atanh_rom(input int unsigned idx);
    begin
      cordic_atanh_rom = CordicAtanhRom[idx*64 +: 64];
    end
  endfunction

  function automatic logic [63:0] cordic_k_circ_rom(input int unsigned n);
    begin
      cordic_k_circ_rom = CordicKCircRom[n*64 +: 64];
    end
  endfunction

  function automatic logic [63:0] cordic_inv_k_circ_rom(input int unsigned n);
    begin
      cordic_inv_k_circ_rom = CordicInvKCircRom[n*64 +: 64];
    end
  endfunction

  function automatic logic [63:0] cordic_k_hyp_rom(input int unsigned n);
    begin
      cordic_k_hyp_rom = CordicKHypRom[n*64 +: 64];
    end
  endfunction

  function automatic logic [63:0] cordic_inv_k_hyp_rom(input int unsigned n);
    begin
      cordic_inv_k_hyp_rom = CordicInvKHypRom[n*64 +: 64];
    end
  endfunction

  function automatic logic [63:0] cordic_lim_circ_rom(input int unsigned n);
    begin
      cordic_lim_circ_rom = CordicLimCircRom[n*64 +: 64];
    end
  endfunction

  function automatic logic [63:0] cordic_lim_hyp_rom(input int unsigned n);
    begin
      cordic_lim_hyp_rom = CordicLimHypRom[n*64 +: 64];
    end
  endfunction

  function automatic logic [63:0] cordic_lim_lin_rom(input int unsigned n);
    begin
      cordic_lim_lin_rom = CordicLimLinRom[n*64 +: 64];
    end
  endfunction

  function automatic logic [63:0] cordic_tanh_lim_hyp_rom(input int unsigned n);
    begin
      cordic_tanh_lim_hyp_rom = CordicTanhLimHypRom[n*64 +: 64];
    end
  endfunction

  function automatic logic [7:0] cordic_hyp_shift_rom(input int unsigned k);
    begin
      cordic_hyp_shift_rom = CordicHypShiftRom[k*8 +: 8];
    end
  endfunction

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

  /// Convert a Q3.61 ROM entry to `frac` fractional bits, truncating rather than
  /// rounding. Used only for the convergence radii, where rounding up could put
  /// the advertised limit a hair outside the radius the datapath can actually
  /// reach. Truncating keeps the limit inside it.
  function automatic logic signed [63:0] cordic_rom_to_fx_floor(input logic [63:0] rom_val,
                                                                input int unsigned frac);
    int unsigned sh;
    begin
      sh = CordicRomFrac - frac;
      cordic_rom_to_fx_floor = $signed(rom_val) >>> sh;
    end
  endfunction

  /// A convergence radius in the internal format, quantised so that the value
  /// software reads from LIM_CIRC, LIM_HYP or LIM_LIN is exactly the largest
  /// argument the hardware accepts. Rounding straight to the internal format
  /// instead would leave the interface-format value one LSB out of range, and an
  /// argument written back from the register would be rejected.
  function automatic logic signed [63:0] cordic_limit_to_int(input logic [63:0] rom_val,
                                                             input int unsigned frac_bits,
                                                             input int unsigned guard_frac);
    begin
      cordic_limit_to_int = cordic_rom_to_fx_floor(rom_val, frac_bits) <<< guard_frac;
    end
  endfunction

  /// Shift amount used by stage `stage` of coordinate system `coord`.
  /// Circular and linear walk 0, 1, 2, ...; hyperbolic follows the repeat
  /// sequence 1, 2, 3, 4, 4, 5, ..., 13, 13, 14, ... taken from the ROM.
  function automatic int unsigned cordic_stage_shift(input logic [1:0] coord,
                                                     input int unsigned stage);
    begin
      if (coord == CordicCoordHyp) cordic_stage_shift = 32'(cordic_hyp_shift_rom(stage));
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
        CordicCoordCirc: cordic_stage_angle = cordic_rom_to_fx(cordic_atan_rom(sh), frac);
        // 2**-s is exact in any binary format, so no ROM lookup is needed.
        CordicCoordLin:  cordic_stage_angle = (sh > frac) ? 64'sd0
                                                         : (64'sd1 <<< (frac - sh));
        default:         cordic_stage_angle = cordic_rom_to_fx(cordic_atanh_rom(sh), frac);
      endcase
    end
  endfunction

/* verilator lint_on UNUSEDPARAM */
