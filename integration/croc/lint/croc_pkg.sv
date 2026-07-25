// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// Minimal stand-in for one of the two Croc packages cordic_obi_wrap depends on,
// so that
// `make lint` can actually elaborate the integration wrapper instead of taking it
// on trust. Written from the field lists in pulp-platform/croc's rtl/obi/obi_pkg.sv
// and rtl/croc_pkg.sv (Solderpad SHL-0.51), matching them field for field and in
// order so a struct assignment behaves identically.
//
// FOR LINTING ONLY. Never compile this into a Croc build: Croc brings its own
// packages and two definitions of obi_pkg would collide.

package croc_pkg;

  // Croc grows the subordinate id width by idx_width(NumXbarManagers); with the
  // four default managers that is 1 + 2 = 3.
  localparam obi_pkg::obi_cfg_t SbrObiCfg = '{
    UseRReady:   1'b0,
    CombGnt:     1'b0,
    AddrWidth:     32,
    DataWidth:     32,
    IdWidth:        3,
    Integrity:   1'b0,
    BeFull:      1'b1,
    OptionalCfg: obi_pkg::ObiMinimalOptionalConfig
  };

  typedef struct packed {
    logic [  SbrObiCfg.AddrWidth-1:0] addr;
    logic                             we;
    logic [SbrObiCfg.DataWidth/8-1:0] be;
    logic [  SbrObiCfg.DataWidth-1:0] wdata;
    logic [    SbrObiCfg.IdWidth-1:0] aid;
    logic                             a_optional;
  } sbr_obi_a_chan_t;

  typedef struct packed {
    sbr_obi_a_chan_t a;
    logic            req;
  } sbr_obi_req_t;

  typedef struct packed {
    logic [SbrObiCfg.DataWidth-1:0] rdata;
    logic [  SbrObiCfg.IdWidth-1:0] rid;
    logic                           err;
    logic                           r_optional;
  } sbr_obi_r_chan_t;

  typedef struct packed {
    sbr_obi_r_chan_t r;
    logic            gnt;
    logic            rvalid;
  } sbr_obi_rsp_t;

endpackage
