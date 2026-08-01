#!/usr/bin/env python3
"""P5-C: capacity feasibility of frame-breaks at k=11/10/9 hash ops, both boards.

Model (decomposed from the P3 ~946 floor design, RESEARCH.md):
  pool_base = alu+valu lane-ops with ZERO fold overflow      = 53,286
      (56,654 census - 8 * 421 folds that sat on valu at C=946)
  F         = flow-eligible ops (tournament folds + omf sels) = 1,366
  load      = 1,890 slots ; store ~ 96
  Hash inside pool_base at k=11: 46,464 lane-ops; each op removed: -4,224.

Cycle law:  feasible at C iff
   pool_base + 8*max(0, F - C) <= 60C   and   load <= 2C   and store <= 2C.

Mechanisms (per group-round deltas):
  serve-more-L4  : load -8, F +15                       (P3-C exchange rate)
  sort+window-L5 : one-time sort a=2 (+320 vec-eq pool, +1024 store, +128 load)
                   then 32 gr: load -7/gr, valu +8 bc/gr, F +7 sel/gr,
                   minus gather ops (-1 madd pool, -1 omf F per gr)
  with-idx lean writeback: pool +1,536 (192 vec: 5 madds + 1 extract x32), store +32
"""
import math

POOL0, F0, LOAD0, STORE0 = 53_286, 1_366, 1_890, 96

def min_cycles(pool, F, load, store):
    for C in range(600, 1400):
        if pool + 8 * max(0, F - C) <= 60 * C and load <= 2 * C and store <= 2 * C:
            return C
    return None

def binding(pool, F, load, store, C):
    b = []
    if pool + 8 * max(0, F - (C - 1)) > 60 * (C - 1): b.append("pool/flow")
    if load > 2 * (C - 1): b.append("load")
    if store > 2 * (C - 1): b.append("store")
    return "+".join(b) or "?"

def show(name, pool, F, load, store):
    C = min_cycles(pool, F, load, store)
    print(f"{name:52s} pool={pool:6d} F={F:5d} load={load:5d} st={store:5d}"
          f" -> floor {C:4d} ({binding(pool,F,load,store,C)})")
    return C

for board, target, extra_pool, extra_store in (("no-idx", 889, 0, 0),
                                               ("with-idx", 904, 1536, 32)):
    print(f"=== {board} board (target {target}) ===")
    for k in (11, 10, 9):
        pool = POOL0 - (11 - k) * 4224 + extra_pool
        st = STORE0 + extra_store
        show(f"k={k} shape as-is", pool, F0, LOAD0, st)
        best = min(((min_cycles(pool, F0 + 15 * n, LOAD0 - 8 * n, st), n)
                    for n in range(0, 30)), key=lambda t: t[0])
        C, n = best
        show(f"k={k} + serve-more-L4 x{n}", pool, F0 + 15 * n, LOAD0 - 8 * n, st)
        show(f"k={k} + sort(a=2)+window-L5",
             pool + 320 * 8 + 32 * (8 - 1) * 8, F0 + 32 * (7 - 1),
             LOAD0 + 128 - 7 * 32, st + 1024)
        # combined: sort+window AND serve-more
        best = min(((min_cycles(pool + 320*8 + 32*7*8, F0 + 192 + 15*n,
                                LOAD0 + 128 - 224 - 8*n, st + 1024), n)
                    for n in range(0, 30)), key=lambda t: t[0])
        C, n = best
        show(f"k={k} + sort+window + serve-more x{n}",
             pool + 320*8 + 32*7*8, F0 + 192 + 15*n, LOAD0 - 96 - 8*n, st + 1024)
    print()

print("phi accounting: needed load relief at k=10:")
print("  no-idx : 1890 -> 1778 = 112 slots = 14 gr of serve-more (has 29 available)")
print("  with-idx: 1890 -> 1808 = 82 slots = 11 gr")
print("serve-more cost 15 F-ops/gr vs sort route ~736 vec-eq + net -96 ld: dominated")
