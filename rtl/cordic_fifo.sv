// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Synchronous FIFO with a synchronous flush.
//
// Written locally rather than pulled from pulp-platform/common_cells so that this
// repository stands alone: it lints, simulates and synthesises with nothing but
// the files in rtl/. Croc already carries common_cells, so an integrator who
// prefers fifo_v3 can swap it in, the handshake is the same.
//
// Depth must be a power of two. The pointers carry one extra bit, so full and
// empty are told apart without wasting an entry.

module cordic_fifo #(
  parameter int unsigned Width = 32,
  parameter int unsigned Depth = 4,
  /// Derived. Do not override.
  parameter int unsigned CntWidth = $clog2(Depth) + 1
) (
  input  logic clk_i,
  input  logic rst_ni,
  /// Drop every entry at the next clock edge.
  input  logic flush_i,

  input  logic             valid_i,
  output logic             ready_o,
  input  logic [Width-1:0] data_i,

  output logic             valid_o,
  input  logic             ready_i,
  output logic [Width-1:0] data_o,

  output logic [CntWidth-1:0] count_o,
  output logic                full_o,
  output logic                empty_o
);

  localparam int unsigned PtrWidth = $clog2(Depth);

  logic [Width-1:0]    mem [Depth];
  logic [PtrWidth:0]   wptr_q, rptr_q;
  logic                push, pop;

  assign empty_o = (wptr_q == rptr_q);
  // Same index, different wrap bit.
  assign full_o  = (wptr_q[PtrWidth-1:0] == rptr_q[PtrWidth-1:0]) &&
                   (wptr_q[PtrWidth] != rptr_q[PtrWidth]);

  assign ready_o = !full_o;
  assign valid_o = !empty_o;
  assign push    = valid_i && ready_o;
  assign pop     = valid_o && ready_i;

  assign count_o = CntWidth'(wptr_q - rptr_q);
  assign data_o  = mem[rptr_q[PtrWidth-1:0]];

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      wptr_q <= '0;
      rptr_q <= '0;
    end else if (flush_i) begin
      wptr_q <= '0;
      rptr_q <= '0;
    end else begin
      if (push) wptr_q <= wptr_q + 1'b1;
      if (pop)  rptr_q <= rptr_q + 1'b1;
    end
  end

  // No reset on the storage: an entry is only ever read back after being written.
  always_ff @(posedge clk_i) begin
    if (push) mem[wptr_q[PtrWidth-1:0]] <= data_i;
  end

`ifndef SYNTHESIS
  initial begin
    if (Depth < 2 || (Depth & (Depth - 1)) != 0) begin
      $fatal(1, "cordic_fifo: Depth must be a power of two and at least 2, got %0d", Depth);
    end
  end
`endif

endmodule
