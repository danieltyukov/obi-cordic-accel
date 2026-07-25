// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Formal wrapper for the OBI subordinate protocol rules.
//
// tb/test_obi.py drives 14 tests in each of the two R-channel handshake
// configurations, and the manager doubles as a checker. This asks the stronger
// question: do the protocol rules hold for *every* sequence of bus activity up to a
// bound, including sequences a testbench would not think to drive.
//
// cordic_obi_regs is the right unit to ask that of. The CORDIC datapath sits entirely
// outside it: the issue port, the result port and the status inputs are all ports, so
// the solver drives them freely and the state left to reason about is the register file
// and the response-holding registers. That is a few hundred bits of control, which a
// bounded solver handles in seconds. The same question asked of cordic_accel would drag
// the whole 28-stage datapath in and not converge; see formal/README.md.
//
// Every property below is written in terms of ports only, even where the RTL states it
// over an internal signal. That is deliberate, and it is sound because
// obi_rvalid_o is rsp_hold_q, obi_gnt_o is !rsp_hold_q || rsp_taken, and a_ack is
// obi_req_i && obi_gnt_o. Restating them at the port boundary checks the contract a
// bus manager can actually observe, which is the contract that matters.
//
// The SVA in the RTL uses |=>, $past, $rose and $stable. Yosys's native Verilog front
// end has no SVA at all, so the one cycle of history those need is registered
// explicitly here and the properties become immediate assertions.

module cordic_obi_props #(
  parameter int unsigned AddrWidth = 32,
  parameter int unsigned IdWidth   = 3,
  parameter int unsigned UseRReady = 0,
  parameter int unsigned DataWidth = 32,
  parameter int unsigned FracBits  = 29,
  parameter int unsigned NumStages = 28,
  parameter int unsigned Variant   = 0,
  parameter int unsigned FlagWidth = 4,
  parameter int unsigned CntWidth  = 4
) (
  input  logic clk_i,
  input  logic rst_ni,

  // Every one of these is free: the solver picks the bus traffic, the datapath's
  // responses and the status flags.
  input  logic                 obi_req_i,
  input  logic [AddrWidth-1:0] obi_addr_i,
  input  logic                 obi_we_i,
  input  logic [3:0]           obi_be_i,
  input  logic [31:0]          obi_wdata_i,
  input  logic [IdWidth-1:0]   obi_aid_i,
  input  logic                 obi_rready_i,

  input  logic                        iss_ready_i,
  input  logic                        res_valid_i,
  input  logic signed [DataWidth-1:0] res_x_i,
  input  logic signed [DataWidth-1:0] res_y_i,
  input  logic signed [DataWidth-1:0] res_z_i,
  input  logic [FlagWidth-1:0]        res_flags_i,
  input  logic [4:0]                  res_func_i,
  input  logic [7:0]                  res_tag_i,

  input  logic                 unit_busy_i,
  input  logic                 in_full_i,
  input  logic                 in_empty_i,
  input  logic                 out_full_i,
  input  logic                 out_empty_i,
  input  logic [CntWidth-1:0]  in_count_i,
  input  logic [CntWidth-1:0]  out_count_i,
  input  logic                 res_push_i,
  input  logic                 res_push_dom_i
);

  logic                 obi_gnt_o, obi_rvalid_o, obi_err_o;
  logic [31:0]          obi_rdata_o;
  logic [IdWidth-1:0]   obi_rid_o;

  logic                        iss_valid_o, res_pop_o, soft_rst_o, irq_o;
  logic                        flush_in_o, flush_out_o;
  logic [4:0]                  iss_func_o;
  logic [7:0]                  iss_tag_o;
  logic signed [DataWidth-1:0] iss_x_o, iss_y_o, iss_z_o;

  cordic_obi_regs #(
    .AddrWidth (AddrWidth), .IdWidth (IdWidth), .UseRReady (UseRReady),
    .DataWidth (DataWidth), .FracBits (FracBits), .NumStages (NumStages),
    .Variant (Variant), .FlagWidth (FlagWidth), .CntWidth (CntWidth)
  ) i_regs (
    .clk_i, .rst_ni,
    .obi_req_i, .obi_gnt_o, .obi_addr_i, .obi_we_i, .obi_be_i, .obi_wdata_i,
    .obi_aid_i, .obi_rvalid_o, .obi_rready_i, .obi_rdata_o, .obi_rid_o, .obi_err_o,
    .iss_valid_o, .iss_ready_i, .iss_func_o, .iss_tag_o,
    .iss_x_o, .iss_y_o, .iss_z_o,
    .res_valid_i, .res_pop_o, .res_x_i, .res_y_i, .res_z_i,
    .res_flags_i, .res_func_i, .res_tag_i,
    .unit_busy_i, .in_full_i, .in_empty_i, .out_full_i, .out_empty_i,
    .in_count_i, .out_count_i, .res_push_i, .res_push_dom_i,
    .flush_in_o, .flush_out_o, .soft_rst_o, .irq_o
  );

  // --- observable reconstruction of the handshake state ----------------------
  logic a_ack, rsp_taken;
  assign rsp_taken = (UseRReady != 0) ? (obi_rvalid_o && obi_rready_i) : obi_rvalid_o;
  assign a_ack     = obi_req_i && obi_gnt_o;

  // --- one cycle of history, since the front end has no $past ----------------
  logic                a_ack_q, rvalid_q, rready_q, iss_valid_q;
  logic [IdWidth-1:0]  aid_q;
  logic [31:0]         rdata_q;
  logic [IdWidth-1:0]  rid_q;
  logic                err_q;
  logic                past_valid_q;   // low in the first cycle after reset

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      a_ack_q      <= 1'b0;
      rvalid_q     <= 1'b0;
      rready_q     <= 1'b0;
      iss_valid_q  <= 1'b0;
      past_valid_q <= 1'b0;
    end else begin
      a_ack_q      <= a_ack;
      rvalid_q     <= obi_rvalid_o;
      rready_q     <= obi_rready_i;
      iss_valid_q  <= iss_valid_o;
      past_valid_q <= 1'b1;
    end
  end

  always_ff @(posedge clk_i) begin
    aid_q   <= obi_aid_i;
    rdata_q <= obi_rdata_o;
    rid_q   <= obi_rid_o;
    err_q   <= obi_err_o;
  end

  // --- the rules ------------------------------------------------------------
  always @(posedge clk_i) begin
    if (rst_ni) begin
      // A request may only be taken when a response slot is free. Violating this is
      // how a subordinate silently loses a transaction.
      a_no_accept_while_held: assert (!(a_ack && obi_rvalid_o && !rsp_taken));

      // Popping a result the hardware does not have would corrupt the queue.
      a_pop_only_when_valid: assert (!res_pop_o || res_valid_i);

      // Without rready, gnt must never fall. A manager that ignores rready depends
      // on that, and Croc's SbrObiCfg is exactly that configuration.
      if (UseRReady == 0) begin
        a_gnt_always: assert (obi_gnt_o);
      end

      if (past_valid_q) begin
        // A response only ever appears because a request was accepted the cycle
        // before. This is $rose(rvalid) |-> $past(a_ack).
        a_rsp_follows_req: assert (!(obi_rvalid_o && !rvalid_q) || a_ack_q);

        // rid echoes the aid of the request being answered.
        a_rid_echo: assert (!a_ack_q || (obi_rid_o == aid_q));

        // An issue is only ever offered for one cycle.
        a_issue_pulse: assert (!iss_valid_q || !iss_valid_o);

        // With rready in play, a held response must neither change nor withdraw.
        if (UseRReady != 0 && rvalid_q && !rready_q) begin
          a_rsp_stable: assert (obi_rvalid_o &&
                                (obi_rdata_o == rdata_q) &&
                                (obi_rid_o   == rid_q) &&
                                (obi_err_o   == err_q));
        end
      end
    end
  end

  // --- reachability, so none of the above can pass vacuously -----------------
  always @(posedge clk_i) begin
    if (rst_ni) begin
      c_read_answered:  cover (obi_rvalid_o && !obi_err_o);
      c_error_answered: cover (obi_rvalid_o && obi_err_o);
      c_issue:          cover (iss_valid_o);
      c_pop:            cover (res_pop_o);
      c_back_to_back:   cover (a_ack && obi_rvalid_o);
    end
  end

  logic unused;
  assign unused = ^{soft_rst_o, irq_o, flush_in_o, flush_out_o,
                    iss_func_o, iss_tag_o, iss_x_o, iss_y_o, iss_z_o};

endmodule
