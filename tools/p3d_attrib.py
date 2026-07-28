"""P3-D: attribute the G-38 residual (+110 valu vec-ops) between the two
dev builds `l4_gmin=(6,31)` and `(32,6)`, ring-free, b3_last OFF at both ends.

Read-only.  Monkeypatches dev.ListScheduler.put and buckets every emitted
slot by (call-site chain, engine, opcode) and by round, then DIFFS the two
builds so the residual is attributed to named mechanisms rather than guessed.

Usage: python3 tools/p3d_attrib.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dev as D  # noqa: E402
import h061_common as HC  # noqa: E402
from problem import VLEN  # noqa: E402

SKIP = {"put", "emit", "emit_any", "find_free", "ready", "_sched_vec",
        "_sched_multiply_add", "_sched_vselect"}

records: list = []
orig_put = D.ListScheduler.put


def patched_put(self, engine, slot, cycle, reads=(), writes=(),
                mem_read=False, mem_write=False):
    f = sys._getframe(1)
    chain = []
    rnd = lvl = -1
    while f is not None:
        code = f.f_code
        if code.co_filename.endswith("dev.py"):
            name = code.co_name
            if name == "_round_stage_generator":
                rnd = f.f_locals.get("round", -1)
                lvl = f.f_locals.get("L", -1)
            if name not in SKIP:
                chain.append(f"{name}:{f.f_lineno}")
            if name in ("build_kernel_scheduled", "build_kernel"):
                break
        f = f.f_back
    op = slot[0] if isinstance(slot, tuple) else str(slot)
    records.append((tuple(chain[:2]), engine, op, rnd))
    return orig_put(self, engine, slot, cycle, reads, writes,
                    mem_read, mem_write)


D.ListScheduler.put = patched_put  # type: ignore[assignment]


def lane(engine: str, n: int) -> int:
    return n if engine == "alu" else (VLEN * n if engine == "valu" else 0)


def run(gmin):
    records.clear()
    kw = HC.kwargs(gmin=gmin, rings=False, reverse_newest_parity_fold=())
    kb = HC.build(kw)
    by = Counter()
    for chain, engine, op, r in records:
        by[(chain, engine, op)] += 1
    byround = Counter()
    for chain, engine, op, r in records:
        byround[(r, engine)] += 1
    return len(kb.instrs), by, byround, list(records)


def main() -> None:
    cyc_a, a, ra, _ = run((6, 31))
    cyc_b, b, rb, _ = run((32, 6))
    print(f"(6,31) cycles {cyc_a}   (32,6) cycles {cyc_b}")
    for tag, cnt in (("(6,31)", a), ("(32,6)", b)):
        tot = {e: sum(n for (c, en, o), n in cnt.items() if en == e)
               for e in ("alu", "valu", "flow", "load", "store")}
        print(f"  {tag}: " + "  ".join(f"{e} {v}" for e, v in tot.items())
              + f"   alu+valu lane-ops {tot['alu'] + 8*tot['valu']}")

    print("\n== per-call-site DIFF (32,6) - (6,31), by alu+valu lane-ops ==")
    keys = set(a) | set(b)
    rows = []
    for k in keys:
        chain, engine, op = k
        d = b[k] - a[k]
        if d == 0:
            continue
        rows.append((lane(engine, d), d, engine, op, chain))
    rows.sort(key=lambda t: -abs(t[0]) if t[0] else 0)
    net = 0
    for lo, d, engine, op, chain in rows[:26]:
        net += lo
        print(f"  {lo:>+7} lane {d:>+6} slots  {engine:<5}{op:<16} "
              + " <- ".join(chain))
    print(f"  ... {len(rows)} changed sites; net over all = "
          f"{sum(r[0] for r in rows):+d} lane-ops")
    for e in ("flow", "load", "store"):
        print(f"  net {e}: {sum(r[1] for r in rows if r[2] == e):+d} slots")

    print("\n== per-ROUND alu/valu diff ==")
    print(f"  {'round':>6}{'d_alu':>8}{'d_valu':>8}{'d_lane':>9}")
    for r in range(-1, 16):
        da = rb[(r, "alu")] - ra[(r, "alu")]
        dv = rb[(r, "valu")] - ra[(r, "valu")]
        if da or dv:
            print(f"  {r:>6}{da:>+8}{dv:>+8}{da + 8*dv:>+9}")


if __name__ == "__main__":
    main()
