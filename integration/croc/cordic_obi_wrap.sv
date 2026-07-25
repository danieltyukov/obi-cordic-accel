// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Croc adapter for cordic_accel.
//
// cordic_accel takes flat OBI signals so it stays simulator-agnostic and can be
// driven straight from cocotb. Croc's interconnect speaks struct types
// (croc_pkg::sbr_obi_req_t and sbr_obi_rsp_t). This module is the only place the
// two meet, and it is deliberately nothing but wiring: no logic, no registers, so
// it adds no cycles and nothing to verify beyond the connection itself.
//
// Instantiate it from rtl/user_domain.sv in place of a subordinate. See
// docs/CROC_INTEGRATION.md for the address map entry, the Bender fragment and the
// sources list.
//
// Croc's SbrObiCfg has UseRReady = 0, so sbr_obi_req_t carries no rready field and
// the tie-off below is correct. If you reconfigure Croc for UseRReady = 1, change
// the parameter to match and connect req_i.rready instead.

module cordic_obi_wrap #(
  /// Croc's OBI subordinate configuration, normally croc_pkg::SbrObiCfg.
  parameter obi_pkg::obi_cfg_t ObiCfg     = obi_pkg::ObiDefaultConfig,
  /// Croc's request and response struct types.
  parameter type               obi_req_t  = logic,
  parameter type               obi_rsp_t  = logic,

  /// Fixed-point word width, at most 32.
  parameter int unsigned       DataWidth  = 32,
  /// Fractional bits. DataWidth - FracBits must be at least 3.
  parameter int unsigned       FracBits   = 29,
  /// Micro-rotations. Use 5, or 15 and above, for hyperbolic support.
  parameter int unsigned       NumStages  = 28,
  /// 0 fully pipelined, 1 iterative. See the area table in the README.
  parameter int unsigned       Variant    = 0,
  parameter int unsigned       GuardInt   = 2,
  parameter int unsigned       GuardFrac  = 4,
  parameter int unsigned       InDepth    = 4,
  parameter int unsigned       OutDepth   = 4,
  /// Expose the streaming ports. Leave 0 for a register-only integration; the
  /// ports are still present and are tied off internally.
  parameter bit                EnableStream = 1'b0
) (
  input  logic     clk_i,
  input  logic     rst_ni,

  input  obi_req_t obi_req_i,
  output obi_rsp_t obi_rsp_o,

  /// Level-sensitive, wire to one bit of user_domain's interrupts_o.
  output logic     irq_o,

  // Streaming ports. Ignore them entirely for a register-only integration.
  input  logic                        str_in_valid_i,
  output logic                        str_in_ready_o,
  input  logic [4:0]                  str_in_func_i,
  input  logic [7:0]                  str_in_tag_i,
  input  logic signed [DataWidth-1:0] str_in_x_i,
  input  logic signed [DataWidth-1:0] str_in_y_i,
  input  logic signed [DataWidth-1:0] str_in_z_i,

  output logic                        str_out_valid_o,
  input  logic                        str_out_ready_i,
  output logic signed [DataWidth-1:0] str_out_x_o,
  output logic signed [DataWidth-1:0] str_out_y_o,
  output logic signed [DataWidth-1:0] str_out_z_o,
  output logic [3:0]                  str_out_flags_o,
  output logic [4:0]                  str_out_func_o,
  output logic [7:0]                  str_out_tag_o
);

  localparam int unsigned IntWidth = DataWidth + GuardInt + GuardFrac;

  logic                        gnt, rvalid, err;
  logic [31:0]                 rdata;
  logic [ObiCfg.IdWidth-1:0]   rid;

  logic                        s_in_valid, s_in_ready;
  logic [4:0]                  s_in_func;
  logic [7:0]                  s_in_tag;
  logic signed [DataWidth-1:0] s_in_x, s_in_y, s_in_z;
  logic                        s_out_ready;

  if (EnableStream) begin : gen_stream
    assign s_in_valid     = str_in_valid_i;
    assign s_in_func      = str_in_func_i;
    assign s_in_tag       = str_in_tag_i;
    assign s_in_x         = str_in_x_i;
    assign s_in_y         = str_in_y_i;
    assign s_in_z         = str_in_z_i;
    assign s_out_ready    = str_out_ready_i;
    assign str_in_ready_o = s_in_ready;
  end else begin : gen_no_stream
    assign s_in_valid     = 1'b0;
    assign s_in_func      = '0;
    assign s_in_tag       = '0;
    assign s_in_x         = '0;
    assign s_in_y         = '0;
    assign s_in_z         = '0;
    assign s_out_ready    = 1'b0;
    assign str_in_ready_o = 1'b0;
    // The ports stay in the port list either way, so that user_domain.sv does not
    // have to change when EnableStream is flipped. Sink them explicitly.
    logic unused_stream_in;
    assign unused_stream_in = ^{str_in_valid_i, str_in_func_i, str_in_tag_i,
                                str_in_x_i, str_in_y_i, str_in_z_i,
                                str_out_ready_i, s_in_ready};
  end

  // The observation ports exist for tb/ and the documentation figures; a real
  // integration leaves them unread.
  logic [NumStages:0]           unused_stage_valid;
  logic                         unused_iter_valid;
  logic [7:0]                   unused_iter_idx;
  logic signed [IntWidth-1:0]   unused_iter_x, unused_iter_y, unused_iter_z;

  cordic_accel #(
    .DataWidth (DataWidth),
    .FracBits  (FracBits),
    .NumStages (NumStages),
    .Variant   (Variant),
    .GuardInt  (GuardInt),
    .GuardFrac (GuardFrac),
    .InDepth   (InDepth),
    .OutDepth  (OutDepth),
    .AddrWidth (ObiCfg.AddrWidth),
    .IdWidth   (ObiCfg.IdWidth),
    // Croc's SbrObiCfg sets UseRReady = 0, so the R beat is taken the cycle it is
    // offered and gnt can stay high for ever.
    .UseRReady (0)
  ) i_cordic (
    .clk_i,
    .rst_ni,

    .obi_req_i    (obi_req_i.req),
    .obi_gnt_o    (gnt),
    .obi_addr_i   (obi_req_i.a.addr),
    .obi_we_i     (obi_req_i.a.we),
    .obi_be_i     (obi_req_i.a.be),
    .obi_wdata_i  (obi_req_i.a.wdata),
    .obi_aid_i    (obi_req_i.a.aid),
    .obi_rvalid_o (rvalid),
    .obi_rready_i (1'b1),
    .obi_rdata_o  (rdata),
    .obi_rid_o    (rid),
    .obi_err_o    (err),

    .irq_o,

    .str_in_valid_i  (s_in_valid),
    .str_in_ready_o  (s_in_ready),
    .str_in_func_i   (s_in_func),
    .str_in_tag_i    (s_in_tag),
    .str_in_x_i      (s_in_x),
    .str_in_y_i      (s_in_y),
    .str_in_z_i      (s_in_z),

    .str_out_valid_o (str_out_valid_o),
    .str_out_ready_i (s_out_ready),
    .str_out_x_o     (str_out_x_o),
    .str_out_y_o     (str_out_y_o),
    .str_out_z_o     (str_out_z_o),
    .str_out_flags_o (str_out_flags_o),
    .str_out_func_o  (str_out_func_o),
    .str_out_tag_o   (str_out_tag_o),

    .dbg_stage_valid_o (unused_stage_valid),
    .dbg_iter_valid_o  (unused_iter_valid),
    .dbg_iter_idx_o    (unused_iter_idx),
    .dbg_iter_x_o      (unused_iter_x),
    .dbg_iter_y_o      (unused_iter_y),
    .dbg_iter_z_o      (unused_iter_z)
  );

  // A channel
  assign obi_rsp_o.gnt          = gnt;
  // R channel
  assign obi_rsp_o.rvalid       = rvalid;
  assign obi_rsp_o.r.rdata      = rdata;
  assign obi_rsp_o.r.rid        = rid;
  assign obi_rsp_o.r.err        = err;
  assign obi_rsp_o.r.r_optional = '0;

  // Croc's SbrObiCfg uses a 32-bit data word and no optional A-channel fields.
  // Anything else needs this wrapper revisited, so say so at elaboration rather
  // than let it mis-wire silently.
`ifndef SYNTHESIS
  initial begin
    if (ObiCfg.DataWidth != 32) begin
      $fatal(1, "cordic_obi_wrap: expects a 32-bit OBI data word, got %0d",
             ObiCfg.DataWidth);
    end
    if (ObiCfg.UseRReady != 1'b0) begin
      $fatal(1, "cordic_obi_wrap: this wrapper ties rready high; set UseRReady on cordic_accel and connect obi_req_i.rready instead");
    end
    if (ObiCfg.Integrity != 1'b0) begin
      $fatal(1, "cordic_obi_wrap: OBI integrity fields are not implemented");
    end
  end
`endif

  // Silence unused-signal linting on the observation ports, which is deliberate.
  logic unused_dbg;
  assign unused_dbg = ^{unused_stage_valid, unused_iter_valid, unused_iter_idx,
                        unused_iter_x, unused_iter_y, unused_iter_z};

endmodule
