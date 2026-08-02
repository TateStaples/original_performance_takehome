#!/usr/bin/env python3
"""P6-R3: z3 CEGIS verdicts on conjugation-family members M2 (phi=sig16l) and
M3 (phi=sig3l) — the dressed head/tail spans, deletion-family closure.

Member win condition (from tools/p6r3_family.py): interior decomposable floor
= 15 ops vs baseline 11; reaching <=10 needs 5 fused ops. The only local
fusion channels are the dressed spans:
  head span (4 ops):  madd4097( sig_kl(w) ^ n )          hunting <=3 (max save 1)
  tail span (5 ops):  sig_kl( sig16r( 9h + C4 ) )        hunting <=4 (max save 1)
Even if BOTH existed the member saves 2 < 5 => members are DEAD unless a
non-local >=3-op restructuring exists (the standing (S)-gap, out of scope of
any local argument). These sweeps decide whether the local channels exist at
all, within the deletion family of the natural shapes (same coverage class as
P5-D span7->5 / P5-L 3.4b span7->6).

Soundness: cegis() constrains template == reference on samples; UNSAT on
samples => impossible for the full function. FOUND is verified 2^20 + 10M.
Shapes: madd ops have FREE (K, C) — the natural shifts (<<16, <<3) are the
special case K = 2^k, C = 0, so every deletion template is a GENERALIZATION.

Usage: python3 p6r3_cegis.py {control|m2head|m2tail|m3head|m3tail} [budget_s] [timeout_each_s]
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p5d_cegis import cegis, delete_ops, MASK, C0, K0, C4, K4  # noqa: E402


def sig_l(k, x):
    return (x ^ (x << k)) & MASK


def sig_r(k, x):
    return (x ^ (x >> k)) & MASK


# ---- natural shapes -------------------------------------------------------
# inputs: head (w=0, n=1); tail (h=0)

HEAD4 = [           # madd4097( sig_kl(w) ^ n )
    ("madd", 0),    # slot2: w*K + C   (generalizes w<<k)
    ("xor2", 0, 2),  # slot3: sig_kl(w)
    ("xor2", 1, 3),  # slot4: ^ n
    ("madd", 4),    # slot5: stage0 madd (output)
]

TAIL5 = [           # sig_kl( sig16r( 9h + C4 ) )
    ("madd", 0),    # slot1: 9h + C4
    ("shr", 1),     # slot2: >>16
    ("xor2", 1, 2),  # slot3: sig16r
    ("madd", 3),    # slot4: (generalizes <<k)
    ("xor2", 3, 4),  # slot5: output
]


def ref_head(k):
    def f(w, n):
        return (sig_l(k, w) ^ n) * K0 + C0 & MASK
    return f


def ref_tail(k):
    def f(h):
        return sig_l(k, sig_r(16, (h * K4 + C4) & MASK))
    return f


def ref_control(w, n):
    """Planted: madd4097(w ^ n) — HAS a 3-op form inside the deletion family
    (delete op1, take branch to the free madd with K=1, C=0). Must be FOUND."""
    return ((w ^ n) * K0 + C0) & MASK


def run_1del(base_ops, n_inputs, ref_fn, want_ops, name, budget_s, timeout_each):
    n = len(base_ops)
    seen = set()
    results = {"UNSAT": 0, "TIMEOUT": 0, "FOUND": 0, "GAVE_UP": 0, "SKIP": 0}
    t0 = time.time()
    for i in range(n - 1):  # never delete the output op
        for new_ops, desc in delete_ops(base_ops, n_inputs, {i}):
            if len(new_ops) != want_ops:
                results["SKIP"] += 1
                continue
            key = tuple(new_ops)
            if key in seen:
                continue
            seen.add(key)
            if time.time() - t0 > budget_s:
                print(f"[{name}] BUDGET EXHAUSTED after {len(seen)} templates")
                return results
            verdict, detail = cegis(new_ops, n_inputs, ref_fn, desc, timeout_each)
            results[verdict] += 1
            print(f"  [{name}] {desc} ops={len(new_ops)}: {verdict} ({detail})", flush=True)
            if verdict == "FOUND":
                print(f"    !!! ops={new_ops}")
    print(f"[{name}] SUMMARY: {results}  ({time.time()-t0:.0f}s)")
    return results


# ---- ALL-shapes sweep (3-op, 2-input) for the head spans ------------------
# Vocabulary = the REAL_11 op kinds {madd, shr, xorc, xor2}, all constants
# free.  Pruning (all sound):
#   - last op is the output; no dead intermediate results;
#   - both inputs must reach the output;
#   - same-kind unary chains (shr∘shr, xorc∘xorc, madd∘madd) collapse to
#     2-op shapes — skipped as duplicates of the 2-op sweep;
#   - ANALYTIC-UNSAT: if some input has no shr-free path to the output and
#     the shape contains exactly ONE shr, the whole dependence factors
#     through that shr's output (image <= 2^31), while the head target is
#     bijective in each input separately => impossible, no solver needed.


def enum_shapes(n_ops, n_inputs=2):
    kinds_u = ["madd", "shr", "xorc"]

    def rec(ops, n_slots):
        if len(ops) == n_ops:
            yield list(ops)
            return
        for k in kinds_u:
            for i in range(n_slots):
                # skip same-kind unary chain (collapsible)
                if i >= n_inputs and ops[i - n_inputs][0] == k:
                    continue
                yield from rec(ops + [(k, i)], n_slots + 1)
        for i in range(n_slots):
            for j in range(i + 1, n_slots):
                yield from rec(ops + [("xor2", i, j)], n_slots + 1)

    yield from rec([], n_inputs)


def prune_shape(ops, n_inputs=2):
    """Returns None if pruned, else 'Z3' or 'ANALYTIC'."""
    n = len(ops)
    # dead-code: every intermediate result used later
    used = set()
    for op in ops:
        used.update(op[1:])
    for k in range(n - 1):
        if n_inputs + k not in used:
            return None
    # reachability of both inputs + shr-free path per input
    def reaches(src):
        reach = {src}
        clean = {src}
        for k, op in enumerate(ops):
            slot = n_inputs + k
            args = op[1:]
            if any(a in reach for a in args):
                reach.add(slot)
                if op[0] == "shr":
                    pass  # never clean
                elif any(a in clean for a in args):
                    clean.add(slot)
        out = n_inputs + n - 1
        return out in reach, out in clean

    n_shr = sum(1 for op in ops if op[0] == "shr")
    for src in range(n_inputs):
        r, c = reaches(src)
        if not r:
            return None  # output ignores an input: cannot match
        if not c and n_shr == 1:
            return "ANALYTIC"  # factors through one shr: image deficit
    return "Z3"


def run_allshapes(ref_fn, name, n_ops, budget_s, timeout_each, shard=(0, 1)):
    shapes = [s for s in enum_shapes(n_ops)]
    tagged = [(s, prune_shape(s)) for s in shapes]
    live = [(s, t) for s, t in tagged if t is not None]
    z3q = [s for s, t in live if t == "Z3"]
    ana = sum(1 for _, t in live if t == "ANALYTIC")
    lo = len(z3q) * shard[0] // shard[1]
    hi = len(z3q) * shard[1 - 0] // shard[1] if shard[0] + 1 == shard[1] else len(z3q) * (shard[0] + 1) // shard[1]
    mine = z3q[lo:hi]
    print(f"[{name}] {len(shapes)} raw shapes, {len(live)} live, "
          f"{ana} ANALYTIC-UNSAT (single-shr image deficit), {len(z3q)} to z3; "
          f"shard {shard[0]}/{shard[1]} -> {len(mine)} queries")
    results = {"UNSAT": 0, "TIMEOUT": 0, "FOUND": 0, "GAVE_UP": 0}
    t0 = time.time()
    touts = []
    for idx, ops in enumerate(mine):
        if time.time() - t0 > budget_s:
            print(f"[{name}] BUDGET EXHAUSTED at {idx}/{len(mine)}")
            break
        verdict, detail = cegis(ops, 2, ref_fn, str(ops), timeout_each)
        results[verdict] += 1
        if verdict != "UNSAT":
            print(f"  [{name}] shape#{lo+idx} {ops}: {verdict} ({detail})", flush=True)
            if verdict == "TIMEOUT":
                touts.append(ops)
        if verdict == "FOUND":
            print(f"    !!! FOUND {ops}")
            break
        if idx % 100 == 0:
            print(f"  ... {idx}/{len(mine)} ({results})", flush=True)
    print(f"[{name}] SUMMARY: {results} + analytic={ana}  ({time.time()-t0:.0f}s)")
    for t in touts:
        print(f"  OPEN(timeout): {t}")
    return results


if __name__ == "__main__":
    which = sys.argv[1]
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 480
    teach = int(sys.argv[3]) if len(sys.argv) > 3 else 150
    if which == "control":
        run_1del(HEAD4, 2, ref_control, 3, "control(head4->3, planted)", budget, teach)
    elif which == "m2head":
        run_1del(HEAD4, 2, ref_head(16), 3, "M2 sig16l head4->3", budget, teach)
    elif which == "m2tail":
        run_1del(TAIL5, 1, ref_tail(16), 4, "M2 sig16l tail5->4", budget, teach)
    elif which == "m3head":
        run_1del(HEAD4, 2, ref_head(3), 3, "M3 sig3l head4->3", budget, teach)
    elif which == "m3tail":
        run_1del(TAIL5, 1, ref_tail(3), 4, "M3 sig3l tail5->4", budget, teach)
    elif which in ("m2head_all", "m3head_all"):
        k = 16 if which == "m2head_all" else 3
        shard = (0, 1)
        if len(sys.argv) > 4:
            a, b = sys.argv[4].split("/")
            shard = (int(a), int(b))
        run_allshapes(ref_head(k), f"sig{k}l head ALL 3-op shapes", 3,
                      budget, teach, shard)
    else:
        raise SystemExit("unknown member")
