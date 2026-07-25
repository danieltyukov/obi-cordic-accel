// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Miter for proving the two microarchitectures equivalent.
//
// tb/test_equivalence.py already shows they agree over 900 directed and random
// operations, and that is real evidence. This is a different kind of claim: a bounded
// proof that no input sequence at all, within the bound, can make them disagree.
//
// The two cores have different latencies and different issue intervals, so a miter
// cannot simply compare their outputs cycle by cycle. Instead:
//
//   - both cores are handed the same operands whenever both are ready, so neither
//     can drift onto a different operation from the other;
//   - each core's result is captured into its own holding register when it retires;
//   - the assertion fires only once both have captured a result for the same
//     operation index, and then compares the captured words.
//
// The operation index is what makes that sound. Each side counts the operations it
// has retired, and the comparison is gated on the counts being equal, so a proof
// failure means two cores genuinely disagreed on the same operation rather than that
// they were merely out of step.

module cordic_equiv_miter #(
  parameter int unsigned DataWidth = 32,
  parameter int unsigned FracBits  = 29,
  parameter int unsigned NumStages = 28,
  parameter int unsigned GuardInt  = 2,
  parameter int unsigned GuardFrac = 4,
  // Cap on how many operations the solver may issue. Zero means no cap.
  //
  // This is the knob that decides whether the proof is tractable. With no cap the
  // solver may fill the pipelined core with a different operation in every stage,
  // and the unrolled state it has to track is the product of the pipeline depth and
  // the word width. Capping it at one leaves a single operation in flight on each
  // side, which is a smaller problem and still a real claim: for any operands, any
  // function, any stall pattern, the two cores agree on that operation.
  parameter int unsigned MaxIssue  = 0
) (
  input  logic                        clk_i,
  input  logic                        rst_ni,
  // Free inputs: the solver picks these.
  input  logic                        valid_i,
  input  logic [4:0]                  func_i,
  input  logic [7:0]                  tag_i,
  input  logic signed [DataWidth-1:0] x_i,
  input  logic signed [DataWidth-1:0] y_i,
  input  logic signed [DataWidth-1:0] z_i,
  input  logic                        ready_i
);

  localparam int unsigned AttrWidth = 22;   // CordicAttrWidth
  localparam int unsigned FlagWidth = 4;    // CordicFlagWidth
  localparam int unsigned IntWidth  = DataWidth + GuardInt + GuardFrac;
  // Enough to count every operation the bound can retire without wrapping.
  localparam int unsigned CntWidth  = 8;

  // --- the two units under comparison ---------------------------------------
  logic                        p_ready, p_valid, i_ready, i_valid;
  logic signed [DataWidth-1:0] p_x, p_y, p_z, i_x, i_y, i_z;
  logic [FlagWidth-1:0]        p_flags, i_flags;
  logic [4:0]                  p_func, i_func;
  logic [7:0]                  p_tag, i_tag;
  logic                        p_busy, i_busy;

  // Issue only when both can take it, so the two never diverge onto different
  // operations. This is the constraint that makes the comparison meaningful rather
  // than a race between two different schedules.
  logic issue;
  assign issue = valid_i && p_ready && i_ready && !issue_blocked;

  // Count what has been issued, so MaxIssue can be enforced structurally rather than
  // as an assumption on a free input. Blocking `issue` directly is stronger than
  // assuming `!valid_i`: the solver cannot satisfy it by driving valid_i high in a
  // cycle where a core happens not to be ready.
  logic [CntWidth-1:0] issued_q;
  logic                issue_blocked;

  assign issue_blocked = (MaxIssue != 0) && (issued_q >= CntWidth'(MaxIssue));

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) issued_q <= '0;
    else if (issue) issued_q <= issued_q + 1'b1;
  end

  logic [NumStages:0]         p_dbg_stage;
  logic                       p_dbg_iv, i_dbg_iv;
  logic [7:0]                 p_dbg_idx, i_dbg_idx;
  logic signed [IntWidth-1:0] p_dbg_x, p_dbg_y, p_dbg_z;
  logic signed [IntWidth-1:0] i_dbg_x, i_dbg_y, i_dbg_z;
  logic [NumStages:0]         i_dbg_stage;

  cordic_unit #(
    .DataWidth (DataWidth), .FracBits (FracBits), .NumStages (NumStages),
    .Variant (0), .GuardInt (GuardInt), .GuardFrac (GuardFrac),
    .AttrWidth (AttrWidth), .FlagWidth (FlagWidth)
  ) i_pipe (
    .clk_i, .rst_ni, .flush_i (1'b0),
    .valid_i (issue), .ready_o (p_ready),
    .func_i, .tag_i, .x_i, .y_i, .z_i,
    .valid_o (p_valid), .ready_i (ready_i),
    .x_o (p_x), .y_o (p_y), .z_o (p_z), .flags_o (p_flags),
    .func_o (p_func), .tag_o (p_tag), .busy_o (p_busy),
    .dbg_stage_valid_o (p_dbg_stage), .dbg_iter_valid_o (p_dbg_iv),
    .dbg_iter_idx_o (p_dbg_idx), .dbg_iter_x_o (p_dbg_x),
    .dbg_iter_y_o (p_dbg_y), .dbg_iter_z_o (p_dbg_z)
  );

  cordic_unit #(
    .DataWidth (DataWidth), .FracBits (FracBits), .NumStages (NumStages),
    .Variant (1), .GuardInt (GuardInt), .GuardFrac (GuardFrac),
    .AttrWidth (AttrWidth), .FlagWidth (FlagWidth)
  ) i_iter (
    .clk_i, .rst_ni, .flush_i (1'b0),
    .valid_i (issue), .ready_o (i_ready),
    .func_i, .tag_i, .x_i, .y_i, .z_i,
    .valid_o (i_valid), .ready_i (ready_i),
    .x_o (i_x), .y_o (i_y), .z_o (i_z), .flags_o (i_flags),
    .func_o (i_func), .tag_o (i_tag), .busy_o (i_busy),
    .dbg_stage_valid_o (i_dbg_stage), .dbg_iter_valid_o (i_dbg_iv),
    .dbg_iter_idx_o (i_dbg_idx), .dbg_iter_x_o (i_dbg_x),
    .dbg_iter_y_o (i_dbg_y), .dbg_iter_z_o (i_dbg_z)
  );

  // --- capture each side's result, per operation index ----------------------
  logic [CntWidth-1:0]         p_cnt, i_cnt;
  logic signed [DataWidth-1:0] p_cx, p_cy, p_cz, i_cx, i_cy, i_cz;
  logic [FlagWidth-1:0]        p_cf, i_cf;
  logic [4:0]                  p_cfn, i_cfn;
  logic [7:0]                  p_ct, i_ct;

  logic p_take, i_take;
  assign p_take = p_valid && ready_i;
  assign i_take = i_valid && ready_i;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      p_cnt <= '0;
      i_cnt <= '0;
    end else begin
      if (p_take) p_cnt <= p_cnt + 1'b1;
      if (i_take) i_cnt <= i_cnt + 1'b1;
    end
  end

  always_ff @(posedge clk_i) begin
    if (p_take) begin
      p_cx <= p_x; p_cy <= p_y; p_cz <= p_z;
      p_cf <= p_flags; p_cfn <= p_func; p_ct <= p_tag;
    end
    if (i_take) begin
      i_cx <= i_x; i_cy <= i_y; i_cz <= i_z;
      i_cf <= i_flags; i_cfn <= i_func; i_ct <= i_tag;
    end
  end

  // --- the property ---------------------------------------------------------
  // Compare only when both sides have retired the same number of operations and at
  // least one, so the captured words belong to the same operation. `matched` is
  // exposed as a cover so the proof cannot pass by never reaching the comparison.
  logic matched;
  assign matched = (p_cnt == i_cnt) && (p_cnt != 0);

  // Immediate assertions in a clocked block, not concurrent SVA.
  //
  // Yosys's native Verilog front end has no SVA support at all: `assert property` with
  // a clocking event is a syntax error, which is why every Yosys path in this repo
  // defines SYNTHESIS to skip the concurrent assertions in the RTL. Sampling the same
  // expressions inside `always @(posedge clk_i)` is equivalent here because every
  // property below is a same-cycle implication, so there is no temporal operator to
  // lose. `disable iff (!rst_ni)` becomes the `if (rst_ni)` guard.
  always @(posedge clk_i) begin
    if (rst_ni && matched) begin
      a_equiv_x:     assert (p_cx  == i_cx);
      a_equiv_y:     assert (p_cy  == i_cy);
      a_equiv_z:     assert (p_cz  == i_cz);
      a_equiv_flags: assert (p_cf  == i_cf);
      a_equiv_func:  assert (p_cfn == i_cfn);
      a_equiv_tag:   assert (p_ct  == i_ct);
    end
  end

  // Liveness of the check itself: unless the bound is deep enough for both sides to
  // retire, every assertion above is vacuously true. A reachable cover is what proves
  // the comparison actually happens rather than being skipped for the whole trace.
  always @(posedge clk_i) begin
    if (rst_ni) begin
      c_reached_one: cover (matched);
      c_reached_two: cover (matched && (p_cnt == 2));
    end
  end

  // The observation ports exist for the testbench; sink them so nothing is undriven.
  logic unused;
  assign unused = ^{p_dbg_stage, p_dbg_iv, p_dbg_idx, p_dbg_x, p_dbg_y, p_dbg_z,
                    i_dbg_stage, i_dbg_iv, i_dbg_idx, i_dbg_x, i_dbg_y, i_dbg_z,
                    p_busy, i_busy};

endmodule
