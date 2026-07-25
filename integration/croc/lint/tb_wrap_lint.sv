// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Elaboration harness for cordic_obi_wrap: instantiates it exactly the way
// user_domain.sv.example does, with Croc's struct types, so `make lint` proves the
// integration wrapper connects rather than merely looks plausible.
//
// Both variants and both stream settings are elaborated, because the wrapper's
// generate blocks differ between them.

module tb_wrap_lint import croc_pkg::*; (
  input  logic         clk_i,
  input  logic         rst_ni,
  input  sbr_obi_req_t req_i,
  output sbr_obi_rsp_t rsp_pipe_o,
  output sbr_obi_rsp_t rsp_iter_o,
  output logic         irq_pipe_o,
  output logic         irq_iter_o,

  input  logic         str_in_valid_i,
  output logic         str_in_ready_o,
  input  logic [4:0]   str_in_func_i,
  input  logic [7:0]   str_in_tag_i,
  input  logic signed [31:0] str_in_x_i,
  input  logic signed [31:0] str_in_y_i,
  input  logic signed [31:0] str_in_z_i,
  output logic         str_out_valid_o,
  input  logic         str_out_ready_i,
  output logic signed [31:0] str_out_x_o,
  output logic signed [31:0] str_out_y_o,
  output logic signed [31:0] str_out_z_o,
  output logic [3:0]   str_out_flags_o,
  output logic [4:0]   str_out_func_o,
  output logic [7:0]   str_out_tag_o
);

  // Pipelined, streaming enabled: the configuration a DMA-fed system would use.
  cordic_obi_wrap #(
    .ObiCfg       ( SbrObiCfg     ),
    .obi_req_t    ( sbr_obi_req_t ),
    .obi_rsp_t    ( sbr_obi_rsp_t ),
    .Variant      ( 0             ),
    .EnableStream ( 1'b1          )
  ) i_pipe (
    .clk_i,
    .rst_ni,
    .obi_req_i (req_i),
    .obi_rsp_o (rsp_pipe_o),
    .irq_o     (irq_pipe_o),
    .str_in_valid_i,
    .str_in_ready_o,
    .str_in_func_i,
    .str_in_tag_i,
    .str_in_x_i,
    .str_in_y_i,
    .str_in_z_i,
    .str_out_valid_o,
    .str_out_ready_i,
    .str_out_x_o,
    .str_out_y_o,
    .str_out_z_o,
    .str_out_flags_o,
    .str_out_func_o,
    .str_out_tag_o
  );

  // Iterative, register only: the small configuration, wired as
  // user_domain.sv.example wires it. The unused stream outputs get named sinks
  // rather than empty connections, so lint stays clean at -Wall.
  logic        iter_in_ready, iter_out_valid;
  logic signed [15:0] iter_out_x, iter_out_y, iter_out_z;
  logic [3:0]  iter_out_flags;
  logic [4:0]  iter_out_func;
  logic [7:0]  iter_out_tag;
  logic        unused_iter;

  cordic_obi_wrap #(
    .ObiCfg       ( SbrObiCfg     ),
    .obi_req_t    ( sbr_obi_req_t ),
    .obi_rsp_t    ( sbr_obi_rsp_t ),
    .DataWidth    ( 16            ),
    .FracBits     ( 13            ),
    .NumStages    ( 15            ),
    .Variant      ( 1             ),
    .EnableStream ( 1'b0          )
  ) i_iter (
    .clk_i,
    .rst_ni,
    .obi_req_i (req_i),
    .obi_rsp_o (rsp_iter_o),
    .irq_o     (irq_iter_o),
    .str_in_valid_i  (1'b0),
    .str_in_ready_o  (iter_in_ready),
    .str_in_func_i   (5'd0),
    .str_in_tag_i    (8'd0),
    .str_in_x_i      ('0),
    .str_in_y_i      ('0),
    .str_in_z_i      ('0),
    .str_out_valid_o (iter_out_valid),
    .str_out_ready_i (1'b0),
    .str_out_x_o     (iter_out_x),
    .str_out_y_o     (iter_out_y),
    .str_out_z_o     (iter_out_z),
    .str_out_flags_o (iter_out_flags),
    .str_out_func_o  (iter_out_func),
    .str_out_tag_o   (iter_out_tag)
  );

  assign unused_iter = ^{iter_in_ready, iter_out_valid, iter_out_x, iter_out_y,
                         iter_out_z, iter_out_flags, iter_out_func, iter_out_tag};

endmodule
