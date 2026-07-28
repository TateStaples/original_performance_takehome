"""H-063 direction B: census of "X +/- b" / "X + b*K" sites with b a 0/1 parity.

H-029 (idx_select_before_madd / P-14) found the ONE pattern that lets the
flow engine absorb ARITHMETIC rather than merely relocate a select: when a
value is `X + b` with b an exact 0/1 parity and BOTH results (X, X+1) are
already-live registers, the variable add becomes `vselect(b, X1, X0)` --
one flow slot instead of one valu slot, and no arm has to be materialised.
G-27 (infinite-width flow = 0 cycles) says relocating selects is worth
nothing, so this arithmetic-absorbing form is the only flow direction that
can pay.

This tool enumerates every candidate site in the EMITTED stream:

  1. find the 0/1 registers: destinations of the two parity spellings
     (`>> c31` and `& one_vec`), plus anything vselect-ed between two
     0/1 registers (transitively).
  2. find every arithmetic op consuming one -- `+` / `-` on valu or alu,
     and `multiply_add` with the parity in the addend or a multiplicand.
  3. classify the OTHER operand: SETUP-INVARIANT (written only by ops with
     scheduler.tag None, i.e. a loop-invariant constant vector) vs RUNTIME
     (rewritten inside the group loop).  Only the invariant case can have
     both alternatives kept live for free; a runtime operand would need
     X+1 materialised, which costs the op back.

Usage (repo root):
  python3 tools/h063_bsites.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h061_attrib as A  # noqa: E402
import h063_head as HD  # noqa: E402


def main() -> None:
    data, ops, preds, floors = A.capture_stream(None)
    names = HD.name_map(data["scratch_debug"])

    def nm(a):
        return names.get(a, f"@{a}")

    # ---- registers written only during setup (loop-invariant constants) ----
    writers: dict[int, list[int]] = defaultdict(list)
    for i, op in enumerate(ops):
        for w in op[3]:
            writers[w].append(i)
    invariant = {a for a, ws in writers.items()
                 if all(ops[i][10] is None for i in ws)}

    # ---- 0/1-ness by REACHING DEFINITION, not by address ----
    # Scratch addresses are recycled aggressively (st/nv are both the
    # position accumulator AND, on L==0 rounds, the raw parity), so an
    # address-keyed analysis produces false positives.  Walk the ops in
    # EMISSION order (which is dependency order by construction) keeping
    # `is01[addr]` = "the value currently in addr is an exact 0/1".
    c31 = next((a for a, n in names.items() if n == "c31"), None)
    one_vec = next((a for a, n in names.items() if n == "one_vec"), None)
    is01: dict[int, bool] = {}
    op_is01: list[bool] = []          # was each op's OWN result 0/1
    read_is01: list[tuple[bool, ...]] = []   # 0/1-ness of each read, at use time
    n_parity_defs = 0
    for i, op in enumerate(ops):
        engine, slot, reads, writes = op[0], op[1], op[2], op[3]
        o = slot[0]
        read_is01.append(tuple(is01.get(a, False) for a in reads))
        res = False
        if o == ">>" and c31 is not None and c31 in reads:
            res = True
        elif o == "&" and one_vec is not None and one_vec in reads:
            res = True
        elif o in ("vselect", "select"):
            arms = (slot[3], slot[4])
            res = all(is01.get(a, False) for a in arms)
        if res:
            n_parity_defs += 1
        op_is01.append(res)
        for w in writes:
            is01[w] = res

    def r01(i, addr) -> bool:
        try:
            return read_is01[i][list(ops[i][2]).index(addr)]
        except ValueError:
            return False

    print(f"== stream {len(ops)} ops; {n_parity_defs} exact-0/1 definitions ==")
    print(f"   loop-invariant (setup-written-only) registers: {len(invariant)}")

    # ---- consumers ----
    kinds: Counter[str] = Counter()
    rows: Counter[tuple] = Counter()
    for i, op in enumerate(ops):
        engine, slot, reads = op[0], op[1], op[2]
        o = slot[0]
        if o in ("+", "-") and engine in ("valu", "alu"):
            a, b = slot[2], slot[3]
            for p, other in ((a, b), (b, a)):
                if r01(i, p):
                    cls = "INVARIANT" if other in invariant else "runtime"
                    kinds[f"{engine}:{o} X{o}b  other={cls}"] += 1
                    rows[(engine, o, cls, nm(other))] += 1
        elif o == "multiply_add":
            a, b, c = slot[2], slot[3], slot[4]
            if r01(i, c):
                cls = "INVARIANT" if (a in invariant or b in invariant) else "runtime"
                kinds[f"{engine}:madd a*b+b01  mult={cls}"] += 1
                rows[(engine, "madd+par", cls, f"{nm(a)}*{nm(b)}")] += 1
            if r01(i, a) or r01(i, b):
                other = b if r01(i, a) else a
                cls = "INVARIANT" if other in invariant else "runtime"
                kinds[f"{engine}:madd b01*K+X  K={cls}"] += 1
                rows[(engine, "madd par*K", cls, nm(other))] += 1
        elif o in ("vselect", "select"):
            if r01(i, slot[2]):
                arms = (slot[3], slot[4])
                cls = "INVARIANT" if all(x in invariant for x in arms) else "runtime"
                kinds[f"flow:vselect(par) arms={cls}"] += 1
                rows[("flow", "vselect", cls, f"{nm(arms[0])}/{nm(arms[1])}")] += 1

    print("\n-- parity-consuming arithmetic, by shape --")
    for k, n in kinds.most_common():
        print(f"  {n:>5}  {k}")

    print("\n-- by site (engine, op, other-operand class, operand name) --")
    for (eng, o, cls, other), n in rows.most_common(40):
        print(f"  {n:>5}  {eng:<5} {o:<12} {cls:<10} {other}")


if __name__ == "__main__":
    main()
