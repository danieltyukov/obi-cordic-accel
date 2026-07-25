// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// CORDIC accelerator top level: OBI subordinate register file, input and output
// FIFOs, the function unit, and a streaming side port.
//
// Why two ways in. A register-mapped issue costs a CVE2 store per operand plus
// one for the command, so five stores and four loads per operation, roughly 9 to
// 12 bus cycles. The pipelined core retires one operation per cycle, so the
// register path can only ever keep it about a tenth busy. The streaming port
// exists so a DMA engine or another accelerator can hand over one operation per
// cycle and actually saturate the pipeline. tb/test_throughput.py measures both.
//
// Both paths share the same input FIFO. A register issue wins a tie, and the
// streaming port simply sees ready low that cycle. Likewise the output FIFO head
// is shared: CTRL.POP wins, and the streaming output holds off for that cycle, so
// a result is never handed to two consumers.
//
// Issuing while busy queues rather than failing. An operation written to a full
// input FIFO is dropped and STATUS.ERR_OVERFLOW latches, which software can see
// beforehand through STATUS.IN_FULL.
//
// The ports are flat OBI signals rather than Croc's struct types, which keeps this
// module simulator-agnostic and directly drivable from cocotb.
// integration/croc/cordic_obi_wrap.sv adapts it to sbr_obi_req_t/sbr_obi_rsp_t.

module cordic_accel #(
  /// Width of the interface fixed-point word. Must be at most 32.
  parameter int unsigned DataWidth = 32,
  /// Fractional bits. DataWidth - FracBits must be at least 3 so that pi fits.
  parameter int unsigned FracBits  = 29,
  /// Micro-rotations per operation. 5, or 15 and above, for hyperbolic support.
  parameter int unsigned NumStages = 28,
  /// 0 selects the fully pipelined core, 1 the iterative one.
  parameter bit          Variant   = 1'b0,
  /// Integer guard bits of the internal datapath, at least 1.
  parameter int unsigned GuardInt  = 2,
  /// Fractional guard bits of the internal datapath, at least 1.
  parameter int unsigned GuardFrac = 4,
  /// Input FIFO depth, a power of two from 2 to 8.
  parameter int unsigned InDepth   = 4,
  /// Output FIFO depth, a power of two from 2 to 8.
  parameter int unsigned OutDepth  = 4,

  parameter int unsigned AddrWidth = 32,
  parameter int unsigned IdWidth   = 3,
  /// 1 makes the OBI R channel wait for rready. Croc uses 0.
  parameter bit          UseRReady = 1'b0
) (
  input  logic clk_i,
  input  logic rst_ni,

  // OBI subordinate, A channel
  input  logic                 obi_req_i,
  output logic                 obi_gnt_o,
  input  logic [AddrWidth-1:0] obi_addr_i,
  input  logic                 obi_we_i,
  input  logic [3:0]           obi_be_i,
  input  logic [31:0]          obi_wdata_i,
  input  logic [IdWidth-1:0]   obi_aid_i,
  // OBI subordinate, R channel
  output logic                 obi_rvalid_o,
  input  logic                 obi_rready_i,
  output logic [31:0]          obi_rdata_o,
  output logic [IdWidth-1:0]   obi_rid_o,
  output logic                 obi_err_o,

  /// Level-sensitive interrupt, masked by CTRL.IRQ_EN_*.
  output logic                 irq_o,

  // Streaming input
  input  logic                        str_in_valid_i,
  output logic                        str_in_ready_o,
  input  logic [4:0]                  str_in_func_i,
  input  logic [7:0]                  str_in_tag_i,
  input  logic signed [DataWidth-1:0] str_in_x_i,
  input  logic signed [DataWidth-1:0] str_in_y_i,
  input  logic signed [DataWidth-1:0] str_in_z_i,

  // Streaming output
  output logic                        str_out_valid_o,
  input  logic                        str_out_ready_i,
  output logic signed [DataWidth-1:0] str_out_x_o,
  output logic signed [DataWidth-1:0] str_out_y_o,
  output logic signed [DataWidth-1:0] str_out_z_o,
  output logic [3:0]                  str_out_flags_o,
  output logic [4:0]                  str_out_func_o,
  output logic [7:0]                  str_out_tag_o,

  // Observation ports for the testbench and the documentation figures. Leave
  // unconnected in a real integration.
  output logic [NumStages:0]                                    dbg_stage_valid_o,
  output logic                                                  dbg_iter_valid_o,
  output logic [7:0]                                            dbg_iter_idx_o,
  output logic signed [DataWidth+GuardInt+GuardFrac-1:0]         dbg_iter_x_o,
  output logic signed [DataWidth+GuardInt+GuardFrac-1:0]         dbg_iter_y_o,
  output logic signed [DataWidth+GuardInt+GuardFrac-1:0]         dbg_iter_z_o
);

  `include "cordic_defs.svh"
  `include "cordic_regmap.svh"

  localparam int unsigned FlagWidth = CordicFlagWidth;

  // Latency and issue interval, reported through CFG1 so software need not guess.
  // Pipelined: NumStages cycles from an accepted operation to a result, one
  // operation per cycle. Iterative: NumStages+1 cycles, and the next operation
  // may be accepted in the cycle the result is taken.
  localparam int unsigned CoreLatency  = Variant ? (NumStages + 1) : NumStages;
  localparam int unsigned CoreInterval = Variant ? (NumStages + 1) : 1;

  // Payload layouts. Concatenation order is fixed here so that the FIFO stays a
  // plain vector-width parameter.
  localparam int unsigned ReqWidth = 5 + 8 + 3 * DataWidth;
  localparam int unsigned RspWidth = FlagWidth + 5 + 8 + 3 * DataWidth;

  localparam int unsigned InCntWidth  = $clog2(InDepth) + 1;
  localparam int unsigned OutCntWidth = $clog2(OutDepth) + 1;

  // ---------------------------------------------------------------------------
  // Register file
  // ---------------------------------------------------------------------------
  logic                        iss_valid, iss_ready;
  logic [4:0]                  iss_func;
  logic [7:0]                  iss_tag;
  logic signed [DataWidth-1:0] iss_x, iss_y, iss_z;

  logic                        res_valid, res_pop;
  logic signed [DataWidth-1:0] res_x, res_y, res_z;
  logic [FlagWidth-1:0]        res_flags;
  logic [4:0]                  res_func;
  logic [7:0]                  res_tag;

  logic                    unit_busy;
  logic                    in_full, in_empty, out_full, out_empty;
  logic [InCntWidth-1:0]   in_count;
  logic [OutCntWidth-1:0]  out_count;
  logic                    res_push, res_push_dom;
  logic                    flush_in, flush_out;

  cordic_obi_regs #(
    .AddrWidth (AddrWidth),
    .IdWidth   (IdWidth),
    .UseRReady (UseRReady),
    .DataWidth (DataWidth),
    .FracBits  (FracBits),
    .NumStages (NumStages),
    .GuardInt  (GuardInt),
    .GuardFrac (GuardFrac),
    .Variant   (Variant),
    .InDepth   (InDepth),
    .OutDepth  (OutDepth),
    .Latency   (CoreLatency),
    .Interval  (CoreInterval),
    .FlagWidth (FlagWidth),
    .CntWidth  (InCntWidth)
  ) i_regs (
    .clk_i,
    .rst_ni,
    .obi_req_i,
    .obi_gnt_o,
    .obi_addr_i,
    .obi_we_i,
    .obi_be_i,
    .obi_wdata_i,
    .obi_aid_i,
    .obi_rvalid_o,
    .obi_rready_i,
    .obi_rdata_o,
    .obi_rid_o,
    .obi_err_o,

    .iss_valid_o (iss_valid),
    .iss_ready_i (iss_ready),
    .iss_func_o  (iss_func),
    .iss_tag_o   (iss_tag),
    .iss_x_o     (iss_x),
    .iss_y_o     (iss_y),
    .iss_z_o     (iss_z),

    .res_valid_i (res_valid),
    .res_pop_o   (res_pop),
    .res_x_i     (res_x),
    .res_y_i     (res_y),
    .res_z_i     (res_z),
    .res_flags_i (res_flags),
    .res_func_i  (res_func),
    .res_tag_i   (res_tag),

    .unit_busy_i (unit_busy),
    .in_full_i   (in_full),
    .in_empty_i  (in_empty),
    .out_full_i  (out_full),
    .out_empty_i (out_empty),
    .in_count_i  (in_count),
    .out_count_i (InCntWidth'(out_count)),
    .res_push_i     (res_push),
    .res_push_dom_i (res_push_dom),

    .flush_in_o  (flush_in),
    .flush_out_o (flush_out),
    .irq_o       (irq_o)
  );

  // ---------------------------------------------------------------------------
  // Input FIFO, shared by the register and streaming issue paths
  // ---------------------------------------------------------------------------
  logic                in_valid, in_ready;
  logic [ReqWidth-1:0] in_data;

  // A register issue wins a tie: the streaming port simply sees ready low.
  assign in_valid       = iss_valid || str_in_valid_i;
  assign in_data        = iss_valid ? {iss_func, iss_tag, iss_x, iss_y, iss_z}
                                    : {str_in_func_i, str_in_tag_i,
                                       str_in_x_i, str_in_y_i, str_in_z_i};
  assign iss_ready      = in_ready;
  assign str_in_ready_o = in_ready && !iss_valid;

  logic                fifo_out_valid, fifo_out_ready;
  logic [ReqWidth-1:0] fifo_out_data;

  cordic_fifo #(
    .Width (ReqWidth),
    .Depth (InDepth)
  ) i_in_fifo (
    .clk_i,
    .rst_ni,
    .flush_i (flush_in),
    .valid_i (in_valid),
    .ready_o (in_ready),
    .data_i  (in_data),
    .valid_o (fifo_out_valid),
    .ready_i (fifo_out_ready),
    .data_o  (fifo_out_data),
    .count_o (in_count),
    .full_o  (in_full),
    .empty_o (in_empty)
  );

  logic [4:0]                  unit_func;
  logic [7:0]                  unit_tag;
  logic signed [DataWidth-1:0] unit_x, unit_y, unit_z;

  assign {unit_func, unit_tag, unit_x, unit_y, unit_z} = fifo_out_data;

  // ---------------------------------------------------------------------------
  // Function unit
  // ---------------------------------------------------------------------------
  logic                        unit_valid, unit_ready;
  logic signed [DataWidth-1:0] unit_rx, unit_ry, unit_rz;
  logic [FlagWidth-1:0]        unit_flags;
  logic [4:0]                  unit_rfunc;
  logic [7:0]                  unit_rtag;

  cordic_unit #(
    .DataWidth (DataWidth),
    .FracBits  (FracBits),
    .NumStages (NumStages),
    .Variant   (Variant),
    .GuardInt  (GuardInt),
    .GuardFrac (GuardFrac),
    .AttrWidth (CordicAttrWidth),
    .FlagWidth (FlagWidth)
  ) i_unit (
    .clk_i,
    .rst_ni,
    .valid_i (fifo_out_valid),
    .ready_o (fifo_out_ready),
    .func_i  (unit_func),
    .tag_i   (unit_tag),
    .x_i     (unit_x),
    .y_i     (unit_y),
    .z_i     (unit_z),

    .valid_o (unit_valid),
    .ready_i (unit_ready),
    .x_o     (unit_rx),
    .y_o     (unit_ry),
    .z_o     (unit_rz),
    .flags_o (unit_flags),
    .func_o  (unit_rfunc),
    .tag_o   (unit_rtag),

    .busy_o  (unit_busy),

    .dbg_stage_valid_o (dbg_stage_valid_o),
    .dbg_iter_valid_o  (dbg_iter_valid_o),
    .dbg_iter_idx_o    (dbg_iter_idx_o),
    .dbg_iter_x_o      (dbg_iter_x_o),
    .dbg_iter_y_o      (dbg_iter_y_o),
    .dbg_iter_z_o      (dbg_iter_z_o)
  );

  // ---------------------------------------------------------------------------
  // Output FIFO, drained by the register or the streaming path
  // ---------------------------------------------------------------------------
  logic                out_valid, out_drain;
  logic [RspWidth-1:0] out_data;

  cordic_fifo #(
    .Width (RspWidth),
    .Depth (OutDepth)
  ) i_out_fifo (
    .clk_i,
    .rst_ni,
    .flush_i (flush_out),
    .valid_i (unit_valid),
    .ready_o (unit_ready),
    .data_i  ({unit_flags, unit_rfunc, unit_rtag, unit_rx, unit_ry, unit_rz}),
    .valid_o (out_valid),
    .ready_i (out_drain),
    .data_o  (out_data),
    .count_o (out_count),
    .full_o  (out_full),
    .empty_o (out_empty)
  );

  assign {res_flags, res_func, res_tag, res_x, res_y, res_z} = out_data;
  assign res_valid = out_valid;

  // CTRL.POP wins, so the streaming output stands down for that cycle and a
  // result can never be handed to two consumers.
  assign str_out_valid_o = out_valid && !res_pop;
  assign out_drain       = res_pop || (str_out_valid_o && str_out_ready_i);

  assign str_out_x_o     = res_x;
  assign str_out_y_o     = res_y;
  assign str_out_z_o     = res_z;
  assign str_out_flags_o = 4'(res_flags);
  assign str_out_func_o  = res_func;
  assign str_out_tag_o   = res_tag;

  // Fed back to the register file for IRQ.DONE and STATUS.ERR_DOMAIN.
  assign res_push     = unit_valid && unit_ready;
  assign res_push_dom = unit_flags[CordicFlagDomBit];

  // ---------------------------------------------------------------------------
  // Elaboration-time parameter checks
  // ---------------------------------------------------------------------------
`ifndef SYNTHESIS
  initial begin
    if (DataWidth < 8 || DataWidth > 32) begin
      $fatal(1, "cordic_accel: DataWidth must be 8 to 32, got %0d", DataWidth);
    end
    if (FracBits >= DataWidth) begin
      $fatal(1, "cordic_accel: FracBits %0d must be below DataWidth %0d",
             FracBits, DataWidth);
    end
    if (DataWidth - FracBits < 3) begin
      $fatal(1, "cordic_accel: need DataWidth - FracBits >= 3 (sign plus two integer bits) so pi is representable, got %0d",
             DataWidth - FracBits);
    end
    if (GuardInt < 1 || GuardFrac < 1) begin
      $fatal(1, "cordic_accel: GuardInt and GuardFrac must be at least 1, got %0d and %0d",
             GuardInt, GuardFrac);
    end
    if (FracBits + GuardFrac > 56) begin
      $fatal(1, "cordic_accel: FracBits + GuardFrac %0d exceeds the ROM's usable precision of 56",
             FracBits + GuardFrac);
    end
    if (NumStages < 4 || NumStages > 48) begin
      $fatal(1, "cordic_accel: NumStages must be 4 to 48, got %0d", NumStages);
    end
    // The hyperbolic sequence only satisfies the convergence condition once each
    // repeated index (4, then 13) is complete. See docs/DESIGN.md.
    if (NumStages != 5 && NumStages < 15) begin
      $fatal(1, "cordic_accel: NumStages %0d truncates the hyperbolic repeat sequence; use 5, or 15 or more",
             NumStages);
    end
    if (InDepth < 2 || InDepth > 8 || (InDepth & (InDepth - 1)) != 0) begin
      $fatal(1, "cordic_accel: InDepth must be 2, 4 or 8, got %0d", InDepth);
    end
    if (OutDepth < 2 || OutDepth > 8 || (OutDepth & (OutDepth - 1)) != 0) begin
      $fatal(1, "cordic_accel: OutDepth must be 2, 4 or 8, got %0d", OutDepth);
    end
    if (IdWidth < 1) $fatal(1, "cordic_accel: IdWidth must be at least 1");
    if (AddrWidth < 12) $fatal(1, "cordic_accel: AddrWidth must be at least 12");
  end
`endif

endmodule
