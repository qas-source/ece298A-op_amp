#!/usr/bin/env python3
"""
Summarise a KLayout DRC report (.lyrdb) for a gf180mcuD analog macro.

Separates REAL violations (which you must fix) from the die-level DENSITY rules (PL.8, M1-5.4,
MT.3), which a single small macro generally cannot satisfy and which are met by dummy metal/poly
fill added at chip integration -- so density hits are expected and ignorable (the count varies with
the design, and the TT precheck excludes density entirely).

Usage: drc_summary.py [report.lyrdb]      (default: drc/gf180_drc.lyrdb)
Exit code is 0 iff there are no real violations.
"""
import sys
import xml.etree.ElementTree as ET
from collections import Counter

DENSITY = {"PL.8", "M1.4", "M2.4", "M3.4", "M4.4", "M5.4", "MT.3"}


def summarise(path):
    counts = Counter()
    for item in ET.parse(path).getroot().iter("item"):
        counts[item.findtext("category", "").strip("'")] += 1
    real = {k: v for k, v in counts.items() if k not in DENSITY}
    dens = {k: v for k, v in counts.items() if k in DENSITY}
    print(f"report: {path}")
    print(f"density (integration fill, expected): {sum(dens.values())}  {dict(sorted(dens.items()))}")
    if real:
        print(f"REAL violations: {sum(real.values())}")
        for k, v in sorted(real.items(), key=lambda kv: -kv[1]):
            print(f"   {k}: {v}")
    else:
        print("REAL violations: 0  -- sign-off clean")
    return 0 if not real else 1


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "drc/gf180_drc.lyrdb"
    sys.exit(summarise(path))
