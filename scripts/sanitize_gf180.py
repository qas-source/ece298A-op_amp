#!/usr/bin/env python3
"""
gf180mcuD sign-off geometry sanitizer for an already-remapped / hand-drawn gf180 GDS cell.

Three foundry-deck rules are easy to miss because `magic` DRC does NOT check them but the KLayout
sign-off deck (gf180mcu.drc, FEOL/BEOL) does -- and a uniform scale (e.g. a 130nm->180nm port at
1.45x) trips all three:

  * OFFGRID   - every vertex must sit on the 5nm manufacturing grid (a 1.45x scale lands on 1nm).
  * CO.1 / V*.1 - every contact/via must be an EXACT square (Contact 0.22, Via1/2/3 0.26um); a
    scaled cut (IHP 0.16/0.20 -> 0.232/0.275) is rejected.
  * NP.2 / PP.2 - same-type implants closer than 0.40um must merge (abutting cells leave slivers).

This pass:
  1. rebuilds every cut at its exact gf180 size, centred on the 5nm grid;
  2. morph-closes Pplus/Nplus so sub-0.46um same-type gaps merge;
  3. snaps all remaining geometry + labels to the 5nm grid;
  4. writes at the standard 1nm DB precision (so `magic` still recognises PDK std cells).

It preserves the cell's coordinate origin, name and labels -- important for hand-placed cells whose
frame an assembly script's pin offsets depend on (re-deriving the frame silently misplaces them).

Usage: sanitize_gf180.py <in.gds> <out.gds>   (in-place is fine: same path twice)
"""
import sys
import gdstk

GRID = 0.005
CUT_SIZE = {(33, 0): 0.22, (35, 0): 0.26, (38, 0): 0.26, (40, 0): 0.26, (41, 0): 0.26}
IMPLANT = {(31, 0), (32, 0)}     # Pplus, Nplus
IMPLANT_CLOSE = 0.23             # merge same-type implant gaps < 0.46um (> the NP.2/PP.2 0.4um min)


def _snap(v):
    return round(v / GRID) * GRID


def sanitize(in_gds, out_gds):
    lib = gdstk.read_gds(in_gds)
    for cell in lib.cells:
        # 1. rebuild cuts at exact size, centre on-grid
        cuts = [p for p in cell.polygons if (p.layer, p.datatype) in CUT_SIZE]
        spec = []
        for p in cuts:
            xs = p.points[:, 0]; ys = p.points[:, 1]
            if max(xs.max() - xs.min(), ys.max() - ys.min()) > 0.40:
                raise SystemExit(f"{(p.layer, p.datatype)} cut looks like a bar; needs array fill, "
                                 "not a 1:1 exact-square swap")
            spec.append(((p.layer, p.datatype), _snap((xs.min() + xs.max()) / 2),
                         _snap((ys.min() + ys.max()) / 2)))
        cell.remove(*cuts)
        for (lay, cx, cy) in spec:
            s = CUT_SIZE[lay] / 2
            cell.add(gdstk.rectangle((cx - s, cy - s), (cx + s, cy + s), layer=lay[0], datatype=lay[1]))
        # 2. merge same-type implants so sub-0.4um gaps disappear (NP.2/PP.2)
        for lay in IMPLANT:
            imp = [p for p in cell.polygons if (p.layer, p.datatype) == lay]
            if not imp:
                continue
            merged = gdstk.offset(gdstk.offset(imp, IMPLANT_CLOSE, join="miter", use_union=True),
                                  -IMPLANT_CLOSE, join="miter", use_union=True)
            cell.remove(*imp)
            for p in merged:
                cell.add(gdstk.Polygon(p.points, layer=lay[0], datatype=lay[1]))
        # 3. snap remaining geometry + labels to the grid
        bulk = [p for p in cell.polygons if (p.layer, p.datatype) not in CUT_SIZE]
        snapped = [gdstk.Polygon([(_snap(x), _snap(y)) for x, y in p.points],
                                 layer=p.layer, datatype=p.datatype) for p in bulk]
        cell.remove(*bulk)
        for p in snapped:
            cell.add(p)
        for lb in cell.labels:
            lb.origin = (_snap(lb.origin[0]), _snap(lb.origin[1]))
    lib.precision = 1e-9          # standard DB precision (geometry already on the 5nm grid)
    lib.write_gds(out_gds)
    print(f"sanitized {in_gds} -> {out_gds}")


if __name__ == "__main__":
    sanitize(sys.argv[1], sys.argv[2])
