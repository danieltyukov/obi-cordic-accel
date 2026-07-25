#!/usr/bin/env python3
# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
"""Check that every SVG in docs/img is well formed and carries what it should.

Parsed with defusedxml rather than xml.etree: the stdlib parsers resolve external
entities and expand nested ones, so pointing them at a file is an XXE and
billion-laughs risk. These files are generated locally, but a check script that
walks a directory should not be the reason a repository grows a footgun.
"""

import pathlib
import sys

from defusedxml import ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "docs" / "img"
SVG_NS = "{http://www.w3.org/2000/svg}"


def main():
    files = sorted(IMG.glob("*.svg"))
    if not files:
        print(f"no SVG files in {IMG}", file=sys.stderr)
        return 1
    rc = 0
    for path in files:
        try:
            root = ET.parse(path).getroot()
        except Exception as exc:                      # noqa: BLE001
            print(f"{path.name}: does not parse: {exc}", file=sys.stderr)
            rc = 1
            continue
        problems = []
        if root.tag != f"{SVG_NS}svg":
            problems.append("root element is not svg")
        if "viewBox" not in root.attrib:
            problems.append("no viewBox, so it will not scale")
        if root.get("role") != "img" or not root.get("aria-label"):
            problems.append("no role=img with an aria-label")
        # A dark-mode override is part of the contract for these figures.
        style = "".join(e.text or "" for e in root.iter(f"{SVG_NS}style"))
        if "prefers-color-scheme: dark" not in style:
            problems.append("no dark-theme override")
        if "var(--" in path.read_text():
            problems.append("uses CSS custom properties, which librsvg ignores")
        if problems:
            rc = 1
            for p in problems:
                print(f"{path.name}: {p}", file=sys.stderr)
        else:
            print(f"{path.name}: ok ({root.get('width')}x{root.get('height')})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
