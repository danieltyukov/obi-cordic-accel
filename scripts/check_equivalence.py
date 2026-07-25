#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Diff the recorded results of the two microarchitectures, word for word.

tb/test_equivalence.py runs the same deterministic stimulus through each variant
and writes build/results/equivalence_v{0,1}.json. This compares them directly,
without the model in the middle, and fails on the first differing word.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIELDS = ["func", "x_in", "y_in", "z_in", "x_out", "y_out", "z_out", "flags", "tag"]


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    d = pathlib.Path(argv[0]) if argv else ROOT / "build" / "results"
    pipe_path = d / "equivalence_v0.json"
    iter_path = d / "equivalence_v1.json"

    for p in (pipe_path, iter_path):
        if not p.exists():
            print(f"missing {p}. Run `make test` so both variants record their "
                  f"results first.", file=sys.stderr)
            return 1

    pipe = json.loads(pipe_path.read_text())
    itr = json.loads(iter_path.read_text())

    if pipe["seed"] != itr["seed"]:
        print(f"the two runs used different stimulus seeds: {pipe['seed']} and "
              f"{itr['seed']}", file=sys.stderr)
        return 1
    for key in ("data_width", "frac_bits", "num_stages", "guard_int", "guard_frac"):
        if pipe["config"][key] != itr["config"][key]:
            print(f"the two runs used different {key}: {pipe['config'][key]} and "
                  f"{itr['config'][key]}", file=sys.stderr)
            return 1
    if pipe["config"]["variant"] != 0 or itr["config"]["variant"] != 1:
        print("equivalence_v0.json must be the pipelined run and equivalence_v1.json "
              "the iterative one", file=sys.stderr)
        return 1
    if len(pipe["records"]) != len(itr["records"]):
        print(f"different record counts: {len(pipe['records'])} and "
              f"{len(itr['records'])}", file=sys.stderr)
        return 1

    diffs = []
    for i, (a, b) in enumerate(zip(pipe["records"], itr["records"])):
        if a != b:
            detail = ", ".join(f"{n}: {av} vs {bv}"
                               for n, av, bv in zip(FIELDS, a, b) if av != bv)
            diffs.append(f"case {i}: {detail} (inputs func={a[0]} x={a[1]} "
                         f"y={a[2]} z={a[3]})")

    if diffs:
        print(f"{len(diffs)} of {len(pipe['records'])} results differ between the "
              f"pipelined and iterative variants:", file=sys.stderr)
        for line in diffs[:10]:
            print(f"  {line}", file=sys.stderr)
        return 1

    cfg = pipe["config"]
    print(f"pipelined and iterative variants are bit-identical over "
          f"{len(pipe['records'])} operations "
          f"(Q{cfg['data_width'] - cfg['frac_bits']}.{cfg['frac_bits']}, "
          f"{cfg['num_stages']} stages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
