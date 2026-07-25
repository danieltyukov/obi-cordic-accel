// Copyright 2026 Daniel Tyukov
// SPDX-License-Identifier: Apache-2.0
//
// GENERATED FILE - DO NOT EDIT.
// Produced by scripts/gen_regmap.py from scripts/cordic_regmap.py.
// Regenerate with `make regmap`.
//
// Include this inside a module body, not at file scope. There is deliberately no
// include guard: each module that needs the offsets gets its own module-local
// copy, so no tool has to share $unit-scope declarations across files.
//
// No module uses every offset, so unused-parameter linting is switched off for the
// span of the file rather than case by case.

/* verilator lint_off UNUSEDPARAM */


  localparam int unsigned CordicWindowBytes = 'h1000;
  localparam int unsigned CordicMappedBytes = 'h64;
  localparam logic [31:0] CordicIdMagic     = 32'h434f5244;
  localparam logic [31:0] CordicVersionValue = 32'h01000000;
  localparam logic [31:0] CordicBadAccessData = 32'hbadacce5;
  localparam int unsigned CordicNumFuncs    = 10;

  // Word offsets, i.e. byte offset >> 2, used by the address decoder.
  localparam int unsigned CordicIdWord = 'h0; // byte 0x000  RO
  localparam int unsigned CordicVersionWord = 'h1; // byte 0x004  RO
  localparam int unsigned CordicCfg0Word = 'h2; // byte 0x008  RO
  localparam int unsigned CordicCfg1Word = 'h3; // byte 0x00c  RO
  localparam int unsigned CordicCtrlWord = 'h4; // byte 0x010  RW
  localparam int unsigned CordicStatusWord = 'h5; // byte 0x014  RO
  localparam int unsigned CordicIrqWord = 'h6; // byte 0x018  W1C
  localparam int unsigned CordicOpXWord = 'h8; // byte 0x020  RW
  localparam int unsigned CordicOpYWord = 'h9; // byte 0x024  RW
  localparam int unsigned CordicOpZWord = 'ha; // byte 0x028  RW
  localparam int unsigned CordicCmdWord = 'hb; // byte 0x02c  RW
  localparam int unsigned CordicResXWord = 'hc; // byte 0x030  RO
  localparam int unsigned CordicResYWord = 'hd; // byte 0x034  RO
  localparam int unsigned CordicResZWord = 'he; // byte 0x038  RO
  localparam int unsigned CordicResFlagsWord = 'hf; // byte 0x03c  RO
  localparam int unsigned CordicKCircWord = 'h10; // byte 0x040  RO
  localparam int unsigned CordicIkCircWord = 'h11; // byte 0x044  RO
  localparam int unsigned CordicKHypWord = 'h12; // byte 0x048  RO
  localparam int unsigned CordicIkHypWord = 'h13; // byte 0x04c  RO
  localparam int unsigned CordicLimCircWord = 'h14; // byte 0x050  RO
  localparam int unsigned CordicLimHypWord = 'h15; // byte 0x054  RO
  localparam int unsigned CordicLimLinWord = 'h16; // byte 0x058  RO
  localparam int unsigned CordicTanhLimHypWord = 'h17; // byte 0x05c  RO
  localparam int unsigned CordicScratchWord = 'h18; // byte 0x060  RW

  // Field positions.
  localparam int unsigned CordicIdMagicLsb = 0;
  localparam int unsigned CordicIdMagicMsb = 31;
  localparam int unsigned CordicVersionMajorLsb = 24;
  localparam int unsigned CordicVersionMajorMsb = 31;
  localparam int unsigned CordicVersionMinorLsb = 16;
  localparam int unsigned CordicVersionMinorMsb = 23;
  localparam int unsigned CordicVersionPatchLsb = 8;
  localparam int unsigned CordicVersionPatchMsb = 15;
  localparam int unsigned CordicCfg0DataWidthLsb = 0;
  localparam int unsigned CordicCfg0DataWidthMsb = 7;
  localparam int unsigned CordicCfg0FracBitsLsb = 8;
  localparam int unsigned CordicCfg0FracBitsMsb = 15;
  localparam int unsigned CordicCfg0NumStagesLsb = 16;
  localparam int unsigned CordicCfg0NumStagesMsb = 23;
  localparam int unsigned CordicCfg0GuardIntLsb = 24;
  localparam int unsigned CordicCfg0GuardIntMsb = 27;
  localparam int unsigned CordicCfg0GuardFracLsb = 28;
  localparam int unsigned CordicCfg0GuardFracMsb = 31;
  localparam int unsigned CordicCfg1VariantBit = 0;
  localparam int unsigned CordicCfg1UseRreadyBit = 1;
  localparam int unsigned CordicCfg1InDepthLsb = 4;
  localparam int unsigned CordicCfg1InDepthMsb = 7;
  localparam int unsigned CordicCfg1OutDepthLsb = 8;
  localparam int unsigned CordicCfg1OutDepthMsb = 11;
  localparam int unsigned CordicCfg1LatencyLsb = 12;
  localparam int unsigned CordicCfg1LatencyMsb = 19;
  localparam int unsigned CordicCfg1IntervalLsb = 20;
  localparam int unsigned CordicCfg1IntervalMsb = 27;
  localparam int unsigned CordicCtrlSoftRstBit = 0;
  localparam int unsigned CordicCtrlPopBit = 1;
  localparam int unsigned CordicCtrlFlushInBit = 2;
  localparam int unsigned CordicCtrlFlushOutBit = 3;
  localparam int unsigned CordicCtrlClrErrBit = 4;
  localparam int unsigned CordicCtrlIrqEnDoneBit = 8;
  localparam int unsigned CordicCtrlIrqEnErrBit = 9;
  localparam int unsigned CordicStatusBusyBit = 0;
  localparam int unsigned CordicStatusResValidBit = 1;
  localparam int unsigned CordicStatusInFullBit = 2;
  localparam int unsigned CordicStatusInEmptyBit = 3;
  localparam int unsigned CordicStatusOutFullBit = 4;
  localparam int unsigned CordicStatusOutEmptyBit = 5;
  localparam int unsigned CordicStatusInCountLsb = 8;
  localparam int unsigned CordicStatusInCountMsb = 11;
  localparam int unsigned CordicStatusOutCountLsb = 12;
  localparam int unsigned CordicStatusOutCountMsb = 15;
  localparam int unsigned CordicStatusErrDomainBit = 16;
  localparam int unsigned CordicStatusErrOverflowBit = 17;
  localparam int unsigned CordicStatusErrUnderflowBit = 18;
  localparam int unsigned CordicStatusErrAccessBit = 19;
  localparam int unsigned CordicIrqDoneBit = 0;
  localparam int unsigned CordicIrqErrBit = 1;
  localparam int unsigned CordicOpXValueLsb = 0;
  localparam int unsigned CordicOpXValueMsb = 31;
  localparam int unsigned CordicOpYValueLsb = 0;
  localparam int unsigned CordicOpYValueMsb = 31;
  localparam int unsigned CordicOpZValueLsb = 0;
  localparam int unsigned CordicOpZValueMsb = 31;
  localparam int unsigned CordicCmdFuncLsb = 0;
  localparam int unsigned CordicCmdFuncMsb = 4;
  localparam int unsigned CordicCmdTagLsb = 8;
  localparam int unsigned CordicCmdTagMsb = 15;
  localparam int unsigned CordicCmdGoBit = 31;
  localparam int unsigned CordicResXValueLsb = 0;
  localparam int unsigned CordicResXValueMsb = 31;
  localparam int unsigned CordicResYValueLsb = 0;
  localparam int unsigned CordicResYValueMsb = 31;
  localparam int unsigned CordicResZValueLsb = 0;
  localparam int unsigned CordicResZValueMsb = 31;
  localparam int unsigned CordicResFlagsDomainErrBit = 0;
  localparam int unsigned CordicResFlagsSatXBit = 1;
  localparam int unsigned CordicResFlagsSatYBit = 2;
  localparam int unsigned CordicResFlagsSatZBit = 3;
  localparam int unsigned CordicResFlagsFuncLsb = 8;
  localparam int unsigned CordicResFlagsFuncMsb = 12;
  localparam int unsigned CordicResFlagsTagLsb = 16;
  localparam int unsigned CordicResFlagsTagMsb = 23;
  localparam int unsigned CordicKCircValueLsb = 0;
  localparam int unsigned CordicKCircValueMsb = 31;
  localparam int unsigned CordicIkCircValueLsb = 0;
  localparam int unsigned CordicIkCircValueMsb = 31;
  localparam int unsigned CordicKHypValueLsb = 0;
  localparam int unsigned CordicKHypValueMsb = 31;
  localparam int unsigned CordicIkHypValueLsb = 0;
  localparam int unsigned CordicIkHypValueMsb = 31;
  localparam int unsigned CordicLimCircValueLsb = 0;
  localparam int unsigned CordicLimCircValueMsb = 31;
  localparam int unsigned CordicLimHypValueLsb = 0;
  localparam int unsigned CordicLimHypValueMsb = 31;
  localparam int unsigned CordicLimLinValueLsb = 0;
  localparam int unsigned CordicLimLinValueMsb = 31;
  localparam int unsigned CordicTanhLimHypValueLsb = 0;
  localparam int unsigned CordicTanhLimHypValueMsb = 31;
  localparam int unsigned CordicScratchValueLsb = 0;
  localparam int unsigned CordicScratchValueMsb = 31;

  // Writable-bit masks. A write only affects these bits; the rest are
  // reserved, ignore writes and read back zero.
  localparam logic [31:0] CordicIdWrMask = 32'h00000000;
  localparam logic [31:0] CordicVersionWrMask = 32'h00000000;
  localparam logic [31:0] CordicCfg0WrMask = 32'h00000000;
  localparam logic [31:0] CordicCfg1WrMask = 32'h00000000;
  localparam logic [31:0] CordicCtrlWrMask = 32'h0000031f;
  localparam logic [31:0] CordicStatusWrMask = 32'h00000000;
  localparam logic [31:0] CordicIrqWrMask = 32'h00000003;
  localparam logic [31:0] CordicOpXWrMask = 32'hffffffff;
  localparam logic [31:0] CordicOpYWrMask = 32'hffffffff;
  localparam logic [31:0] CordicOpZWrMask = 32'hffffffff;
  localparam logic [31:0] CordicCmdWrMask = 32'h8000ff1f;
  localparam logic [31:0] CordicResXWrMask = 32'h00000000;
  localparam logic [31:0] CordicResYWrMask = 32'h00000000;
  localparam logic [31:0] CordicResZWrMask = 32'h00000000;
  localparam logic [31:0] CordicResFlagsWrMask = 32'h00000000;
  localparam logic [31:0] CordicKCircWrMask = 32'h00000000;
  localparam logic [31:0] CordicIkCircWrMask = 32'h00000000;
  localparam logic [31:0] CordicKHypWrMask = 32'h00000000;
  localparam logic [31:0] CordicIkHypWrMask = 32'h00000000;
  localparam logic [31:0] CordicLimCircWrMask = 32'h00000000;
  localparam logic [31:0] CordicLimHypWrMask = 32'h00000000;
  localparam logic [31:0] CordicLimLinWrMask = 32'h00000000;
  localparam logic [31:0] CordicTanhLimHypWrMask = 32'h00000000;
  localparam logic [31:0] CordicScratchWrMask = 32'hffffffff;

  // Bits that self-clear after one cycle (write-1-to-trigger).
  localparam logic [31:0] CordicCtrlTrigMask = 32'h0000001f;
  localparam logic [31:0] CordicCmdTrigMask = 32'h80000000;

  // Function codes for CMD.FUNC.
  localparam logic [4:0] CordicFuncSinCos = 5'd0; // circular rotation
  localparam logic [4:0] CordicFuncRotate = 5'd1; // circular rotation
  localparam logic [4:0] CordicFuncAtan2 = 5'd2; // circular vectoring
  localparam logic [4:0] CordicFuncSinhCosh = 5'd3; // hyperbolic rotation
  localparam logic [4:0] CordicFuncHrotate = 5'd4; // hyperbolic rotation
  localparam logic [4:0] CordicFuncAtanh = 5'd5; // hyperbolic vectoring
  localparam logic [4:0] CordicFuncExp = 5'd6; // hyperbolic rotation
  localparam logic [4:0] CordicFuncLn = 5'd7; // hyperbolic vectoring
  localparam logic [4:0] CordicFuncMul = 5'd8; // linear rotation
  localparam logic [4:0] CordicFuncDiv = 5'd9; // linear vectoring

/* verilator lint_on UNUSEDPARAM */
