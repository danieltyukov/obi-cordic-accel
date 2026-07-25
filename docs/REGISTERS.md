# Register map

Generated from `scripts/cordic_regmap.py` by `scripts/gen_regmap.py`.
Do not edit by hand.

The peripheral occupies a 4 KB window. Offsets `0x000` to `0x060` are implemented; everything above is unmapped.

### Register summary

| Offset | Name | Access | Description |
|--------|------|--------|-------------|
| `0x000` | `ID` | RO | Identification magic, reads 0x434F5244 ("CORD") |
| `0x004` | `VERSION` | RO | Semantic version of the register interface |
| `0x008` | `CFG0` | RO | Elaborated fixed-point format |
| `0x00C` | `CFG1` | RO | Elaborated microarchitecture and timing |
| `0x010` | `CTRL` | RW | Control. Bits 0 to 4 are write-1-to-trigger and read 0 |
| `0x014` | `STATUS` | RO | Live and sticky status |
| `0x018` | `IRQ` | W1C | Interrupt status, write 1 to clear |
| `0x020` | `OP_X` | RW | Operand X in the working fixed-point format |
| `0x024` | `OP_Y` | RW | Operand Y in the working fixed-point format |
| `0x028` | `OP_Z` | RW | Operand Z in the working fixed-point format |
| `0x02C` | `CMD` | RW | Function select and issue trigger |
| `0x030` | `RES_X` | RO | Result X at the head of the output FIFO |
| `0x034` | `RES_Y` | RO | Result Y at the head of the output FIFO |
| `0x038` | `RES_Z` | RO | Result Z at the head of the output FIFO |
| `0x03C` | `RES_FLAGS` | RO | Per-result flags at the head of the output FIFO |
| `0x040` | `K_CIRC` | RO | Circular CORDIC gain K, working format |
| `0x044` | `IK_CIRC` | RO | Reciprocal circular gain 1/K, working format |
| `0x048` | `K_HYP` | RO | Hyperbolic CORDIC gain Kh, working format |
| `0x04C` | `IK_HYP` | RO | Reciprocal hyperbolic gain 1/Kh, working format |
| `0x050` | `LIM_CIRC` | RO | Circular convergence radius, working format |
| `0x054` | `LIM_HYP` | RO | Hyperbolic convergence radius, working format |
| `0x058` | `LIM_LIN` | RO | Linear convergence radius, working format |
| `0x05C` | `TANH_LIM_HYP` | RO | Largest |Y/X| the hyperbolic vectoring mode resolves |
| `0x060` | `SCRATCH` | RW | Read-write scratch word, no hardware effect |
| `0x064` .. `0xFFC` | unmapped | - | Reads return `0xBADACCE5` with `r.err`, writes take `r.err` |

### Bit fields

#### `VERSION` at `0x004` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `31:24` | `MAJOR` | RO | Major version |
| `23:16` | `MINOR` | RO | Minor version |
| `15:8` | `PATCH` | RO | Patch version |
| others | reserved | RO | Read 0, writes ignored |

#### `CFG0` at `0x008` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `31:28` | `GUARD_FRAC` | RO | Fractional guard bits of the internal datapath |
| `27:24` | `GUARD_INT` | RO | Integer guard bits of the internal datapath |
| `23:16` | `NUM_STAGES` | RO | CORDIC micro-rotations per operation |
| `15:8` | `FRAC_BITS` | RO | Fractional bits of the fixed-point word |
| `7:0` | `DATA_WIDTH` | RO | Fixed-point word width in bits |

#### `CFG1` at `0x00C` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `27:20` | `INTERVAL` | RO | Minimum cycles between accepted operations |
| `19:12` | `LATENCY` | RO | Issue-to-result latency in clock cycles |
| `11:8` | `OUT_DEPTH` | RO | Output FIFO depth in entries |
| `7:4` | `IN_DEPTH` | RO | Input FIFO depth in entries |
| `1` | `USE_RREADY` | RO | 1 if the OBI R channel implements rready |
| `0` | `VARIANT` | RO | 0 = fully pipelined, 1 = iterative |
| others | reserved | RO | Read 0, writes ignored |

#### `CTRL` at `0x010` (RW)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `9` | `IRQ_EN_ERR` | RW | Route IRQ.ERR to the interrupt output |
| `8` | `IRQ_EN_DONE` | RW | Route IRQ.DONE to the interrupt output |
| `4` | `CLR_ERR` | W1S | Clear the sticky STATUS.ERR_* bits |
| `3` | `FLUSH_OUT` | W1S | Drop every completed but unread result |
| `2` | `FLUSH_IN` | W1S | Drop every queued but unstarted operation |
| `1` | `POP` | W1S | Discard the result at the head of the output FIFO |
| `0` | `SOFT_RST` | W1S | Flush both FIFOs, clear sticky errors and IRQ state |
| others | reserved | RO | Read 0, writes ignored |

#### `STATUS` at `0x014` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `19` | `ERR_ACCESS` | RO | Sticky: an unmapped, unaligned or illegal access occurred |
| `18` | `ERR_UNDERFLOW` | RO | Sticky: a result was read or popped while empty |
| `17` | `ERR_OVERFLOW` | RO | Sticky: an issue was dropped, input FIFO was full |
| `16` | `ERR_DOMAIN` | RO | Sticky: an operand was outside the convergence domain |
| `15:12` | `OUT_COUNT` | RO | Results waiting in the output FIFO |
| `11:8` | `IN_COUNT` | RO | Operations queued in the input FIFO |
| `5` | `OUT_EMPTY` | RO | Output FIFO holds no result |
| `4` | `OUT_FULL` | RO | Output FIFO cannot accept another result |
| `3` | `IN_EMPTY` | RO | Input FIFO holds no operation |
| `2` | `IN_FULL` | RO | Input FIFO cannot accept another operation |
| `1` | `RES_VALID` | RO | At least one result is readable |
| `0` | `BUSY` | RO | Operations are queued or in flight |
| others | reserved | RO | Read 0, writes ignored |

#### `IRQ` at `0x018` (W1C)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `1` | `ERR` | W1C | One of the sticky STATUS.ERR_* bits was set |
| `0` | `DONE` | W1C | A result was pushed into the output FIFO |
| others | reserved | RO | Read 0, writes ignored |

#### `CMD` at `0x02C` (RW)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `31` | `GO` | W1S | Queue an operation from OP_X, OP_Y, OP_Z and FUNC |
| `15:8` | `TAG` | RW | Free-form tag returned in RES_FLAGS.TAG |
| `4:0` | `FUNC` | RW | Function code, see the function table |
| others | reserved | RO | Read 0, writes ignored |

#### `RES_FLAGS` at `0x03C` (RO)

| Bits | Name | Access | Description |
|------|------|--------|-------------|
| `23:16` | `TAG` | RO | Tag supplied in CMD.TAG |
| `12:8` | `FUNC` | RO | Function code of this result |
| `3` | `SAT_Z` | RO | Result Z saturated to the format limit |
| `2` | `SAT_Y` | RO | Result Y saturated to the format limit |
| `1` | `SAT_X` | RO | Result X saturated to the format limit |
| `0` | `DOMAIN_ERR` | RO | Operand outside the convergence domain, X/Y/Z forced to 0 |
| others | reserved | RO | Read 0, writes ignored |


## Function codes

| `FUNC` | Name | System | Mode | Operands | Result | Convergence domain | Gain |
|-------:|------|--------|------|----------|--------|--------------------|------|
| 0 | `SIN_COS` | circular | rotation | Z = angle in radians | X = cos(Z), Y = sin(Z) | whole representable range of Z | compensated, x0 preloaded with 1/K |
| 1 | `ROTATE` | circular | rotation | X, Y = vector, Z = angle | X, Y = K * R(Z) * (X,Y) | whole representable range of Z | exposed as K_CIRC |
| 2 | `ATAN2` | circular | vectoring | X, Y = vector | Z = atan2(Y,X), X = K * hypot(X,Y) | all four quadrants, no restriction | Z exact, X scaled by K_CIRC |
| 3 | `SINH_COSH` | hyperbolic | rotation | Z = argument | X = cosh(Z), Y = sinh(Z) | |Z| <= LIM_HYP | compensated, x0 preloaded with 1/Kh |
| 4 | `HROTATE` | hyperbolic | rotation | X, Y = vector, Z = argument | X, Y = Kh * Rh(Z) * (X,Y) | |Z| <= LIM_HYP | exposed as K_HYP |
| 5 | `ATANH` | hyperbolic | vectoring | X, Y = vector | Z = atanh(Y/X), X = Kh * sqrt(X^2 - Y^2) | X != 0 and |Y/X| <= TANH_LIM_HYP | Z exact, X scaled by K_HYP |
| 6 | `EXP` | hyperbolic | rotation | Z = exponent | X = Y = exp(Z) | |Z| <= LIM_HYP | compensated, x0 = y0 = 1/Kh |
| 7 | `LN` | hyperbolic | vectoring | X = argument | Z = ln(X) | X > 0 and (X-1)/(X+1) within TANH_LIM_HYP | exact, no gain |
| 8 | `MUL` | linear | rotation | X, Z = factors | Y = X * Z | |Z| <= LIM_LIN | none, gain is 1 |
| 9 | `DIV` | linear | vectoring | Y = numerator, X = denominator | Z = Y / X | X != 0 and |Y/X| <= LIM_LIN | none, gain is 1 |
