// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// OBI subordinate register file for the CORDIC accelerator.
//
// Targets OBI v1.6 (pulp-platform/obi, doc/OBI-v1.6.0.pdf) as Croc configures it:
// 32-bit address and data, IdWidth from croc_pkg::SbrObiCfg, BeFull = 1,
// Integrity = 0, CombGnt = 0, and no optional A- or R-channel fields. The signals
// implemented are req, gnt, addr, we, be, wdata, aid on the A channel and rvalid,
// rdata, rid, err on the R channel.
//
// UseRReady covers both variants of the R-channel handshake. Croc sets
// UseRReady = 0, where a response has to be taken the cycle it is offered, so gnt
// can stay high forever and a request is accepted every cycle. Setting it to 1
// makes the response wait for rready, which in turn makes gnt drop while a
// response is held: the same code path, exercised by tb/test_obi.py in both
// configurations.
//
// Protocol rules honoured:
//   - A request is accepted only on req && gnt; wdata, be, we and aid are sampled
//     then and nowhere else, so a manager may change them freely afterwards.
//   - Exactly one R beat per accepted A beat, in order, with rid echoing aid.
//   - At most one transaction is outstanding, so ordering is structural.
//   - gnt never depends on rvalid being consumed when UseRReady = 0, so a manager
//     that ignores rready cannot deadlock the bus.
//
// Error responses (r.err with rdata = CordicBadAccessData) are given for an
// unaligned address, an offset above the implemented range, and a write to a
// read-only register. Each also sets STATUS.ERR_ACCESS.
//
// Only addr_i[11:0] is decoded: the window is 4 KB and keeping the peripheral
// blind to the bits above that is what lets it be placed at any 4 KB-aligned base
// address without reparameterisation.

module cordic_obi_regs #(
  parameter int unsigned AddrWidth = 32,
  parameter int unsigned IdWidth   = 3,
  /// 1 makes the R channel wait for rready. Croc uses 0.
  parameter int unsigned UseRReady = 0,

  /// Width of the interface fixed-point word, at most 32.
  parameter int unsigned DataWidth = 32,
  parameter int unsigned FracBits  = 29,
  parameter int unsigned NumStages = 28,
  parameter int unsigned GuardInt  = 2,
  parameter int unsigned GuardFrac = 4,
  parameter int unsigned Variant   = 0,
  parameter int unsigned InDepth   = 4,
  parameter int unsigned OutDepth  = 4,
  /// Issue-to-result latency in cycles, reported through CFG1.
  parameter int unsigned Latency   = 28,
  /// Minimum cycles between accepted operations, reported through CFG1.
  parameter int unsigned Interval  = 1,
  parameter int unsigned FlagWidth = 4,
  parameter int unsigned CntWidth  = 4
) (
  input  logic clk_i,
  input  logic rst_ni,

  // OBI A channel
  input  logic                 obi_req_i,
  output logic                 obi_gnt_o,
  input  logic [AddrWidth-1:0] obi_addr_i,
  input  logic                 obi_we_i,
  input  logic [3:0]           obi_be_i,
  input  logic [31:0]          obi_wdata_i,
  input  logic [IdWidth-1:0]   obi_aid_i,
  // OBI R channel
  output logic                 obi_rvalid_o,
  input  logic                 obi_rready_i,
  output logic [31:0]          obi_rdata_o,
  output logic [IdWidth-1:0]   obi_rid_o,
  output logic                 obi_err_o,

  // Issue port towards the input FIFO
  output logic                        iss_valid_o,
  input  logic                        iss_ready_i,
  output logic [4:0]                  iss_func_o,
  output logic [7:0]                  iss_tag_o,
  output logic signed [DataWidth-1:0] iss_x_o,
  output logic signed [DataWidth-1:0] iss_y_o,
  output logic signed [DataWidth-1:0] iss_z_o,

  // Result port from the output FIFO. Reads are non-destructive; res_pop_o
  // discards the head.
  input  logic                        res_valid_i,
  output logic                        res_pop_o,
  input  logic signed [DataWidth-1:0] res_x_i,
  input  logic signed [DataWidth-1:0] res_y_i,
  input  logic signed [DataWidth-1:0] res_z_i,
  input  logic [FlagWidth-1:0]        res_flags_i,
  input  logic [4:0]                  res_func_i,
  input  logic [7:0]                  res_tag_i,

  // Status inputs
  input  logic                 unit_busy_i,
  input  logic                 in_full_i,
  input  logic                 in_empty_i,
  input  logic                 out_full_i,
  input  logic                 out_empty_i,
  input  logic [CntWidth-1:0]  in_count_i,
  input  logic [CntWidth-1:0]  out_count_i,
  /// A result entered the output FIFO this cycle.
  input  logic                 res_push_i,
  /// That result carried a domain error.
  input  logic                 res_push_dom_i,
  // Control outputs
  output logic                 flush_in_o,
  output logic                 flush_out_o,
  /// CTRL.SOFT_RST: abort every operation in flight as well as flushing.
  output logic                 soft_rst_o,
  output logic                 irq_o
);

  `include "cordic_rom.svh"
  `include "cordic_defs.svh"
  `include "cordic_rom_fx.svh"
  `include "cordic_regmap.svh"

  localparam int unsigned WordSelBits = 10;  // addr[11:2] inside a 4 KB window
  localparam int unsigned IntFrac     = FracBits + GuardFrac;

  // ---------------------------------------------------------------------------
  // A-channel handshake. One transaction outstanding, one R beat per A beat.
  // ---------------------------------------------------------------------------
  logic rsp_hold_q;   // a response is waiting to be taken
  logic rsp_taken;    // it is being taken this cycle
  logic a_ack;        // an A beat is accepted this cycle

  assign rsp_taken   = (UseRReady != 0) ? (rsp_hold_q && obi_rready_i) : rsp_hold_q;
  assign obi_gnt_o   = !rsp_hold_q || rsp_taken;
  assign a_ack       = obi_req_i && obi_gnt_o;
  assign obi_rvalid_o = rsp_hold_q;

  // ---------------------------------------------------------------------------
  // Address decode
  // ---------------------------------------------------------------------------
  // Zero-extended to 32 bits so that comparisons against the `int unsigned`
  // offsets in cordic_regmap.svh need no per-site casts.
  logic [31:0] word_sel;
  logic        aligned, in_range;

  assign word_sel = 32'(obi_addr_i[WordSelBits+1:2]);
  assign aligned  = (obi_addr_i[1:0] == 2'b00);
  assign in_range = (obi_addr_i[11:0] < 12'(CordicMappedBytes));

  // ---------------------------------------------------------------------------
  // Byte-enable expansion and masked write value
  // ---------------------------------------------------------------------------
  logic [31:0] be_mask;
  always_comb begin
    for (int unsigned b = 0; b < 4; b++) be_mask[8*b+:8] = {8{obi_be_i[b]}};
  end

  /// Merge wdata into `old` under the byte enables, then keep only `wmask`.
  function automatic logic [31:0] merge(input logic [31:0] old, input logic [31:0] wmask);
    logic [31:0] m;
    begin
      m      = be_mask & wmask;
      merge  = (old & ~m) | (obi_wdata_i & m);
    end
  endfunction

  // ---------------------------------------------------------------------------
  // Registers
  // ---------------------------------------------------------------------------
  logic                        irq_en_done_q, irq_en_err_q;
  logic signed [DataWidth-1:0] op_x_q, op_y_q, op_z_q;
  logic [4:0]                  cmd_func_q;
  logic [7:0]                  cmd_tag_q;
  logic [31:0]                 scratch_q;
  logic                        irq_done_q, irq_err_q;
  logic                        err_dom_q, err_ovf_q, err_unf_q, err_acc_q;

  logic                        irq_en_done_d, irq_en_err_d;
  logic signed [DataWidth-1:0] op_x_d, op_y_d, op_z_d;
  logic [4:0]                  cmd_func_d;
  logic [7:0]                  cmd_tag_d;
  logic [31:0]                 scratch_d;
  logic                        irq_done_d, irq_err_d;
  logic                        err_dom_d, err_ovf_d, err_unf_d, err_acc_d;

  // Write-1-to-trigger pulses, all one cycle wide.
  logic trig_soft_rst, trig_pop, trig_flush_in, trig_flush_out, trig_clr_err;
  logic cmd_go;
  logic err_access, err_underflow;

  logic is_write, is_read, reg_ro, access_fault;

  // ---------------------------------------------------------------------------
  // Read data, formed in the A phase and registered for the R phase.
  // ---------------------------------------------------------------------------
  logic [31:0] rdata_sel;
  logic        rerr_sel;

  /// Sign-extend a DataWidth fixed-point word into a 32-bit read value, so that
  /// software sees a correctly signed integer for formats narrower than 32 bits.
  function automatic logic [31:0] sext(input logic signed [DataWidth-1:0] v);
    begin
      sext = 32'(signed'(v));
    end
  endfunction

  function automatic logic [31:0] rom_word(input logic [63:0] rom_val);
    begin
      rom_word = 32'(cordic_rom_to_fx(rom_val, FracBits));
    end
  endfunction

  /// Convergence radii read back truncated, matching what cordic_pre compares
  /// against, so writing a limit register's value straight back as an operand is
  /// always accepted.
  function automatic logic [31:0] limit_word(input logic [63:0] rom_val);
    begin
      limit_word = 32'(cordic_rom_to_fx_floor(rom_val, FracBits));
    end
  endfunction

  logic [31:0] status_word, ctrl_word, cfg0_word, cfg1_word, cmd_word, flags_word;

  always_comb begin
    status_word = '0;
    status_word[CordicStatusBusyBit]        = unit_busy_i || !in_empty_i;
    status_word[CordicStatusResValidBit]    = res_valid_i;
    status_word[CordicStatusInFullBit]      = in_full_i;
    status_word[CordicStatusInEmptyBit]     = in_empty_i;
    status_word[CordicStatusOutFullBit]     = out_full_i;
    status_word[CordicStatusOutEmptyBit]    = out_empty_i;
    status_word[CordicStatusInCountMsb:CordicStatusInCountLsb]   = 4'(in_count_i);
    status_word[CordicStatusOutCountMsb:CordicStatusOutCountLsb] = 4'(out_count_i);
    status_word[CordicStatusErrDomainBit]    = err_dom_q;
    status_word[CordicStatusErrOverflowBit]  = err_ovf_q;
    status_word[CordicStatusErrUnderflowBit] = err_unf_q;
    status_word[CordicStatusErrAccessBit]    = err_acc_q;

    // The five trigger bits always read back zero.
    ctrl_word = '0;
    ctrl_word[CordicCtrlIrqEnDoneBit] = irq_en_done_q;
    ctrl_word[CordicCtrlIrqEnErrBit]  = irq_en_err_q;

    cfg0_word = '0;
    cfg0_word[CordicCfg0DataWidthMsb:CordicCfg0DataWidthLsb] = 8'(DataWidth);
    cfg0_word[CordicCfg0FracBitsMsb:CordicCfg0FracBitsLsb]   = 8'(FracBits);
    cfg0_word[CordicCfg0NumStagesMsb:CordicCfg0NumStagesLsb] = 8'(NumStages);
    cfg0_word[CordicCfg0GuardIntMsb:CordicCfg0GuardIntLsb]   = 4'(GuardInt);
    cfg0_word[CordicCfg0GuardFracMsb:CordicCfg0GuardFracLsb] = 4'(GuardFrac);

    cfg1_word = '0;
    cfg1_word[CordicCfg1VariantBit]   = (Variant != 0);
    cfg1_word[CordicCfg1UseRreadyBit] = (UseRReady != 0);
    cfg1_word[CordicCfg1InDepthMsb:CordicCfg1InDepthLsb]   = 4'(InDepth);
    cfg1_word[CordicCfg1OutDepthMsb:CordicCfg1OutDepthLsb] = 4'(OutDepth);
    cfg1_word[CordicCfg1LatencyMsb:CordicCfg1LatencyLsb]   = 8'(Latency);
    cfg1_word[CordicCfg1IntervalMsb:CordicCfg1IntervalLsb] = 8'(Interval);

    cmd_word = '0;
    cmd_word[CordicCmdFuncMsb:CordicCmdFuncLsb] = cmd_func_q;
    cmd_word[CordicCmdTagMsb:CordicCmdTagLsb]   = cmd_tag_q;

    flags_word = '0;
    if (res_valid_i) begin
      flags_word[CordicResFlagsDomainErrBit] = res_flags_i[CordicFlagDomBit];
      flags_word[CordicResFlagsSatXBit]      = res_flags_i[CordicFlagSatXBit];
      flags_word[CordicResFlagsSatYBit]      = res_flags_i[CordicFlagSatYBit];
      flags_word[CordicResFlagsSatZBit]      = res_flags_i[CordicFlagSatZBit];
      flags_word[CordicResFlagsFuncMsb:CordicResFlagsFuncLsb] = res_func_i;
      flags_word[CordicResFlagsTagMsb:CordicResFlagsTagLsb]   = res_tag_i;
    end
  end

  always_comb begin
    rdata_sel = '0;
    rerr_sel  = 1'b0;
    reg_ro    = 1'b0;

    case (word_sel)
      CordicIdWord:      rdata_sel = CordicIdMagic;
      CordicVersionWord: rdata_sel = CordicVersionValue;
      CordicCfg0Word:    rdata_sel = cfg0_word;
      CordicCfg1Word:    rdata_sel = cfg1_word;
      CordicCtrlWord:    rdata_sel = ctrl_word;
      CordicStatusWord:  rdata_sel = status_word;
      CordicIrqWord:     rdata_sel = {30'b0, irq_err_q, irq_done_q};
      CordicOpXWord:     rdata_sel = sext(op_x_q);
      CordicOpYWord:     rdata_sel = sext(op_y_q);
      CordicOpZWord:     rdata_sel = sext(op_z_q);
      CordicCmdWord:     rdata_sel = cmd_word;
      CordicResXWord:    rdata_sel = res_valid_i ? sext(res_x_i) : 32'b0;
      CordicResYWord:    rdata_sel = res_valid_i ? sext(res_y_i) : 32'b0;
      CordicResZWord:    rdata_sel = res_valid_i ? sext(res_z_i) : 32'b0;
      CordicResFlagsWord: rdata_sel = flags_word;
      CordicKCircWord:   rdata_sel = rom_word(cordic_k_circ_rom(NumStages));
      CordicIkCircWord:  rdata_sel = rom_word(cordic_inv_k_circ_rom(NumStages));
      CordicKHypWord:    rdata_sel = rom_word(cordic_k_hyp_rom(NumStages));
      CordicIkHypWord:   rdata_sel = rom_word(cordic_inv_k_hyp_rom(NumStages));
      CordicLimCircWord: rdata_sel = limit_word(cordic_lim_circ_rom(NumStages));
      CordicLimHypWord:  rdata_sel = limit_word(cordic_lim_hyp_rom(NumStages));
      CordicLimLinWord:  rdata_sel = limit_word(cordic_lim_lin_rom(NumStages));
      CordicTanhLimHypWord: rdata_sel = limit_word(cordic_tanh_lim_hyp_rom(NumStages));
      CordicScratchWord: rdata_sel = scratch_q;
      default: begin
        rdata_sel = CordicBadAccessData;
        rerr_sel  = 1'b1;
      end
    endcase

    // Read-only registers reject writes.
    case (word_sel)
      CordicCtrlWord, CordicIrqWord, CordicOpXWord, CordicOpYWord, CordicOpZWord,
      CordicCmdWord, CordicScratchWord: reg_ro = 1'b0;
      default: reg_ro = 1'b1;
    endcase

    if (!aligned || !in_range) begin
      rdata_sel = CordicBadAccessData;
      rerr_sel  = 1'b1;
    end
  end

  assign is_write = a_ack && obi_we_i && aligned && in_range && !rerr_sel;
  assign is_read  = a_ack && !obi_we_i && aligned && in_range && !rerr_sel;

  // An access is faulted when misaligned, out of range, or a write to a
  // read-only register. The R beat carries r.err and CordicBadAccessData.
  assign access_fault = rerr_sel || (obi_we_i && reg_ro);
  assign err_access   = a_ack && access_fault;

  // ---------------------------------------------------------------------------
  // Write decode
  // ---------------------------------------------------------------------------
  always_comb begin
    irq_en_done_d = irq_en_done_q;
    irq_en_err_d  = irq_en_err_q;
    op_x_d        = op_x_q;
    op_y_d        = op_y_q;
    op_z_d        = op_z_q;
    cmd_func_d    = cmd_func_q;
    cmd_tag_d     = cmd_tag_q;
    scratch_d     = scratch_q;

    trig_soft_rst  = 1'b0;
    trig_pop       = 1'b0;
    trig_flush_in  = 1'b0;
    trig_flush_out = 1'b0;
    trig_clr_err   = 1'b0;
    cmd_go         = 1'b0;

    if (is_write && !reg_ro) begin
      case (word_sel)
        CordicCtrlWord: begin
          if (obi_be_i[0]) begin
            trig_soft_rst  = obi_wdata_i[CordicCtrlSoftRstBit];
            trig_pop       = obi_wdata_i[CordicCtrlPopBit];
            trig_flush_in  = obi_wdata_i[CordicCtrlFlushInBit];
            trig_flush_out = obi_wdata_i[CordicCtrlFlushOutBit];
            trig_clr_err   = obi_wdata_i[CordicCtrlClrErrBit];
          end
          if (obi_be_i[1]) begin
            irq_en_done_d = obi_wdata_i[CordicCtrlIrqEnDoneBit];
            irq_en_err_d  = obi_wdata_i[CordicCtrlIrqEnErrBit];
          end
        end
        CordicOpXWord: op_x_d = DataWidth'(merge(sext(op_x_q), CordicOpXWrMask));
        CordicOpYWord: op_y_d = DataWidth'(merge(sext(op_y_q), CordicOpYWrMask));
        CordicOpZWord: op_z_d = DataWidth'(merge(sext(op_z_q), CordicOpZWrMask));
        CordicCmdWord: begin
          cmd_func_d = 5'(merge(cmd_word, CordicCmdWrMask) >> CordicCmdFuncLsb);
          cmd_tag_d  = 8'(merge(cmd_word, CordicCmdWrMask) >> CordicCmdTagLsb);
          // GO lives in byte 3, so a partial write that leaves byte 3 out
          // updates FUNC and TAG without issuing.
          cmd_go     = obi_be_i[3] && obi_wdata_i[CordicCmdGoBit];
        end
        CordicScratchWord: scratch_d = merge(scratch_q, CordicScratchWrMask);
        default: ;  // IRQ is handled with the interrupt state below
      endcase
    end

    if (trig_soft_rst) begin
      trig_flush_in  = 1'b1;
      trig_flush_out = 1'b1;
      trig_clr_err   = 1'b1;
    end
  end

  // The operands issued are the ones registered when GO was written, so writing
  // GO in the same access as FUNC works and the operand registers may be reused
  // for the next operation immediately.
  assign iss_valid_o = cmd_go;
  assign iss_func_o  = cmd_func_d;
  assign iss_tag_o   = cmd_tag_d;
  assign iss_x_o     = op_x_q;
  assign iss_y_o     = op_y_q;
  assign iss_z_o     = op_z_q;

  // Reading or popping an empty result queue is reported rather than silently
  // returning stale data.
  logic res_read_empty;
  assign res_read_empty = is_read && !res_valid_i &&
                          ((word_sel == CordicResXWord) || (word_sel == CordicResYWord) ||
                           (word_sel == CordicResZWord) || (word_sel == CordicResFlagsWord));
  assign res_pop_o      = trig_pop && res_valid_i;
  assign err_underflow  = res_read_empty || (trig_pop && !res_valid_i);

  assign flush_in_o  = trig_flush_in;
  assign flush_out_o = trig_flush_out;
  assign soft_rst_o  = trig_soft_rst;

  // ---------------------------------------------------------------------------
  // Sticky errors and interrupt state
  // ---------------------------------------------------------------------------
  logic err_any_set;

  always_comb begin
    err_dom_d = err_dom_q || (res_push_i && res_push_dom_i);
    err_ovf_d = err_ovf_q || (cmd_go && !iss_ready_i);
    err_unf_d = err_unf_q || err_underflow;
    err_acc_d = err_acc_q || err_access;

    err_any_set = (!err_dom_q && err_dom_d) || (!err_ovf_q && err_ovf_d) ||
                  (!err_unf_q && err_unf_d) || (!err_acc_q && err_acc_d);

    if (trig_clr_err) begin
      err_dom_d = 1'b0;
      err_ovf_d = 1'b0;
      err_unf_d = 1'b0;
      err_acc_d = 1'b0;
    end

    irq_done_d = irq_done_q || res_push_i;
    irq_err_d  = irq_err_q  || err_any_set;

    if (is_write && (word_sel == CordicIrqWord) && obi_be_i[0]) begin
      if (obi_wdata_i[CordicIrqDoneBit]) irq_done_d = 1'b0;
      if (obi_wdata_i[CordicIrqErrBit])  irq_err_d  = 1'b0;
    end
    if (trig_soft_rst) begin
      irq_done_d = 1'b0;
      irq_err_d  = 1'b0;
    end
  end

  assign irq_o = (irq_done_q && irq_en_done_q) || (irq_err_q && irq_en_err_q);

  // ---------------------------------------------------------------------------
  // Sequential state
  // ---------------------------------------------------------------------------
  logic [31:0]           rdata_q;
  logic                  rerr_q;
  logic [IdWidth-1:0]    rid_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      rsp_hold_q    <= 1'b0;
      rerr_q        <= 1'b0;
      rid_q         <= '0;
      rdata_q       <= '0;
      irq_en_done_q <= 1'b0;
      irq_en_err_q  <= 1'b0;
      op_x_q        <= '0;
      op_y_q        <= '0;
      op_z_q        <= '0;
      cmd_func_q    <= '0;
      cmd_tag_q     <= '0;
      scratch_q     <= '0;
      irq_done_q    <= 1'b0;
      irq_err_q     <= 1'b0;
      err_dom_q     <= 1'b0;
      err_ovf_q     <= 1'b0;
      err_unf_q     <= 1'b0;
      err_acc_q     <= 1'b0;
    end else begin
      rsp_hold_q <= a_ack || (rsp_hold_q && !rsp_taken);
      if (a_ack) begin
        rid_q   <= obi_aid_i;
        rdata_q <= access_fault ? CordicBadAccessData
                                : (obi_we_i ? 32'b0 : rdata_sel);
        rerr_q  <= access_fault;
      end

      irq_en_done_q <= irq_en_done_d;
      irq_en_err_q  <= irq_en_err_d;
      op_x_q        <= op_x_d;
      op_y_q        <= op_y_d;
      op_z_q        <= op_z_d;
      cmd_func_q    <= cmd_func_d;
      cmd_tag_q     <= cmd_tag_d;
      scratch_q     <= scratch_d;
      irq_done_q    <= irq_done_d;
      irq_err_q     <= irq_err_d;
      err_dom_q     <= err_dom_d;
      err_ovf_q     <= err_ovf_d;
      err_unf_q     <= err_unf_d;
      err_acc_q     <= err_acc_d;
    end
  end

  assign obi_rdata_o = rdata_q;
  assign obi_rid_o   = rid_q;
  assign obi_err_o   = rerr_q;

  // Bits above the 4 KB window are the interconnect's business: ignoring them is
  // what lets this peripheral sit at any 4 KB-aligned base address unchanged.
  logic unused_addr_msbs;
  assign unused_addr_msbs = ^{obi_addr_i[AddrWidth-1:12]};

`ifndef SYNTHESIS
  initial begin
    if (DataWidth > 32) $fatal(1, "cordic_obi_regs: DataWidth %0d exceeds the 32-bit OBI word",
                               DataWidth);
    if (IntFrac > 56)   $fatal(1, "cordic_obi_regs: FracBits + GuardFrac %0d exceeds ROM precision",
                               IntFrac);
  end
`endif

endmodule
