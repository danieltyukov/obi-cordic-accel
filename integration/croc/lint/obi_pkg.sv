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

package obi_pkg;

  typedef struct packed {
    bit          UseAtop;
    bit          UseMemtype;
    bit          UseProt;
    bit          UseDbg;
    int unsigned AUserWidth;
    int unsigned WUserWidth;
    int unsigned RUserWidth;
    int unsigned MidWidth;
    int unsigned AChkWidth;
    int unsigned RChkWidth;
  } obi_optional_cfg_t;

  localparam obi_optional_cfg_t ObiMinimalOptionalConfig = '{
    UseAtop:    1'b0,
    UseMemtype: 1'b0,
    UseProt:    1'b0,
    UseDbg:     1'b0,
    AUserWidth:    0,
    WUserWidth:    0,
    RUserWidth:    0,
    MidWidth:      0,
    AChkWidth:     0,
    RChkWidth:     0
  };

  typedef struct packed {
    bit          UseRReady;
    bit          CombGnt;
    int unsigned AddrWidth;
    int unsigned DataWidth;
    int unsigned IdWidth;
    bit          Integrity;
    bit          BeFull;
    obi_optional_cfg_t OptionalCfg;
  } obi_cfg_t;

  localparam obi_cfg_t ObiDefaultConfig = '{
    UseRReady:   1'b0,
    CombGnt:     1'b0,
    AddrWidth:     32,
    DataWidth:     32,
    IdWidth:        1,
    Integrity:   1'b0,
    BeFull:      1'b1,
    OptionalCfg: ObiMinimalOptionalConfig
  };

endpackage
