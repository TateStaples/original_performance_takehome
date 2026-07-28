"""H-060 step 3: sweep the planned alu/valu balance around the equalization
point.

Baseline (1006 frontier): alu 11,761 slots (floor 981), valu 5,966 slots
(floor 995). One offloaded site trades 1 valu slot for 8 alu slots, so the
floors equalise at x = 17 migrated sites (992/992) and the alu floor binds
beyond ~x = 34.

Two policy directions:
  tie_offload K   race the alu spelling at valu-FREE sites too (ties -> alu)
                  at every K-th offloadable site: valu -> alu migration.
  reclaim M       hand race sites back to valu when alu's win margin <= M:
                  alu -> valu migration.

Usage: python3 tools/h060_sweep.py [--quick]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h060_common as C  # noqa: E402


def probe(name: str, ov: dict[str, Any], base_cfg: dict[str, Any] | None = None,
          verify: bool = False) -> dict[str, Any]:
    cfg = C.frontier(**ov) if base_cfg is None else dict(base_cfg, **ov)
    try:
        _, prog = C.build(cfg)
    except Exception as exc:  # pragma: no cover
        return {"case": name, "error": f"{type(exc).__name__}: {exc}"[:120]}
    cen = C.slot_census(prog)
    fl = C.floors(prog)
    row: dict[str, Any] = {
        "case": name, "cycles": len(prog),
        "alu": cen.get("alu", 0), "valu": cen.get("valu", 0),
        "flow": cen.get("flow", 0), "load": cen.get("load", 0),
        "alu_floor": fl["alu"], "valu_floor": fl["valu"],
        "load_floor": fl["load"],
        "bind": max(fl["alu"], fl["valu"], fl["load"], fl["flow"]),
    }
    row["regret"] = row["cycles"] - row["bind"]
    if verify:
        cyc, ok = C.measure(cfg)
        row["graded"] = cyc
        row["correct"] = ok
    return row


HDR = (f"{'case':<26}{'cyc':>6}{'valu':>7}{'alu':>7}"
       f"{'vfl':>6}{'afl':>6}{'bind':>6}{'reg':>5}  d")


def show(row: dict[str, Any], base: int = 1006) -> None:
    if "error" in row:
        print(f"{row['case']:<26} ERROR {row['error']}")
        return
    d = row["cycles"] - base
    extra = ""
    if "graded" in row:
        extra = f"  graded={row['graded']} correct={row['correct']}"
    print(f"{row['case']:<26}{row['cycles']:>6}{row['valu']:>7}{row['alu']:>7}"
          f"{row['valu_floor']:>6}{row['alu_floor']:>6}{row['bind']:>6}"
          f"{row['regret']:>5}  {d:+d}{extra}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    rows: list[dict[str, Any]] = []
    base = probe("baseline (race)", {})
    rows.append(base)
    print(HDR)
    show(base, base["cycles"])
    b = base["cycles"]

    print("\n--- direction A: tie_offload K (valu -> alu at valu-free sites)")
    ks = [4096, 2048, 1024, 512, 256, 192, 128, 96, 64, 48, 32, 24, 16, 12,
          8, 6, 4, 3, 2, 1]
    if args.quick:
        ks = [1024, 256, 64, 16, 4, 1]
    for k in ks:
        r = probe(f"tie_offload K={k}", {"vec_tie_offload": k})
        rows.append(r)
        show(r, b)

    print("\n--- direction A': phase scan at the best few K")
    for k in ([256, 128, 64] if not args.quick else [128]):
        for ph in range(0, k, max(1, k // 8)):
            r = probe(f"K={k} phase={ph}",
                      {"vec_tie_offload": k, "vec_tie_phase": ph})
            rows.append(r)
            show(r, b)

    print("\n--- direction B: reclaim_margin M (alu -> valu at race sites)")
    for m in ([0, 1, 2, 3, 4, 5, 8, 12, 1000] if not args.quick else [0, 1, 3]):
        r = probe(f"reclaim M={m}", {"vec_reclaim_margin": m})
        rows.append(r)
        show(r, b)

    print("\n--- direction C: both")
    if not args.quick:
        for k in (256, 64, 16):
            for m in (0, 1):
                r = probe(f"K={k} reclaim={m}",
                          {"vec_tie_offload": k, "vec_reclaim_margin": m})
                rows.append(r)
                show(r, b)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(rows, f, indent=1)
        print("wrote", args.json)

    good = [r for r in rows if "cycles" in r and r["cycles"] < b]
    print(f"\n{len(good)} configs below baseline {b}")
    for r in sorted(good, key=lambda r: r["cycles"])[:12]:
        show(r, b)


if __name__ == "__main__":
    main()
