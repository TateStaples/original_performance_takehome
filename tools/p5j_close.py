#!/usr/bin/env python3
"""P5-J: decide the 12 OPEN (TIMEOUT) hash11->9 CEGIS deletion templates.

Templates = the 12 nine-op 2-deletion shapes of REAL_11 recorded OPEN in
research/strains/p5d/STATE.md:
  [0,7],[2,3],[2,4],[2,5],[2,7],[2,9],[4,6],[4,7],[4,9],[5,7],[5,9],[7,9]
(sandwich9 explicitly excluded -- owned by P5-I).

Soundness (inherited from tools/p5d_cegis.py, machinery imported not copied
where possible):
  - UNSAT on the sample-constraint set => template impossible for the full
    function (samples are necessary conditions). Sound closure.
  - SAT => constants verified bit-exactly OUTSIDE z3 (2^20 sweep + 10M
    random); mismatch iterates CEGIS. TIMEOUT stays OPEN.

P5-J additions, each individually sound:
  1. CUT-VERTEX LEMMA (generalizes P5-H's odd-multiplier lemma).
     myhash is bijective (P5-H). Dependency paths in these templates have
     strictly increasing slot ids, so if every path input->output passes
     through slot j ("cut"), the whole function factors as G(S(F(x))) with
     S the segment ending at j; on a finite set a bijective composition
     forces every segment bijective, and the segment's LAST op must be
     injective on the full 2^32 domain (its input F is forced surjective).
     Hence:
       - op at a cut is madd  => its multiplier K must be ODD (K&1==1 is a
         sound pre-constraint: every full-function solution satisfies it,
         so sample-UNSAT under it is still a sound closure).
       - op at a cut is shr (s in 1..31) => never injective => the template
         is ANALYTICALLY UNSAT, no solver needed.
  2. SHIFT SPLIT: fixing each ("shr",i) unknown to a concrete value in
     1..31 partitions the search space exactly; UNSAT on every combo is a
     sound closure of the template.

Usage:
  python3 tools/p5j_close.py list
  python3 tools/p5j_close.py quick  --ids 0,1,2 --timeout 60
  python3 tools/p5j_close.py one    --ids 3 --timeout 900 [--no-oddk]
  python3 tools/p5j_close.py split  --ids 3 --timeout 20 --s1-lo 1 --s1-hi 32
          [--s2-lo 1 --s2-hi 32] [--max-iters 4]
All progress printed line-buffered (redirect to a checkpoint log).
"""
import sys
import time
import random
import argparse

sys.path.insert(0, "/Users/tatestaples/Code/original_performance_takehome/tools")
import z3  # noqa: E402
from p5d_cegis import REAL_11, delete_ops, myhash, eval_template_py, MASK  # noqa: E402

OPEN_PAIRS = [(0, 7), (2, 3), (2, 4), (2, 5), (2, 7), (2, 9),
              (4, 6), (4, 7), (4, 9), (5, 7), (5, 9), (7, 9)]
N_INPUTS = 1


def enumerate_9op():
    """Reproduce run_family's enumeration order + dedup for hash11->9.
    Returns list of (ops_tuple, pair, desc, dup_pairs)."""
    n = len(REAL_11)
    seen = {}
    order = []
    for i in range(n):
        for j in range(i + 1, n):
            if n - 1 in (i, j):
                continue
            for new_ops, desc in delete_ops(REAL_11, N_INPUTS, {i, j}):
                if len(new_ops) != 9:
                    continue
                key = tuple(new_ops)
                if key in seen:
                    seen[key].append((i, j, desc))
                    continue
                seen[key] = []
                order.append([key, (i, j), desc, seen[key]])
    return order


def open_templates():
    """The 12 OPEN templates in a stable id order (sorted OPEN_PAIRS)."""
    all9 = enumerate_9op()
    by_pair = {}
    for key, pair, desc, dups in all9:
        by_pair.setdefault(pair, []).append((key, desc, dups))
    out = []
    for pair in OPEN_PAIRS:
        ents = by_pair.get(pair, [])
        for key, desc, dups in ents:
            out.append((pair, list(key), desc, dups))
    return out


def is_cut(ops, j):
    """True iff every dependency path slot0 -> out passes through slot j."""
    nslots = N_INPUTS + len(ops)
    taint = [False] * nslots
    taint[0] = (j != 0)
    for k, op in enumerate(ops):
        slot = N_INPUTS + k
        t = any(taint[a] for a in op[1:])
        taint[slot] = t and (slot != j)
    return not taint[nslots - 1]


def analyze(ops):
    """Per-op cut analysis. Returns (analytic_unsat_reason|None, oddk_idx,
    shr_idx, cut_slots)."""
    oddk, shrs, cuts = [], [], []
    reason = None
    for k, op in enumerate(ops):
        slot = N_INPUTS + k
        if op[0] == "shr":
            shrs.append(k)
        if is_cut(ops, slot):
            cuts.append(slot)
            if op[0] == "madd":
                oddk.append(k)
            elif op[0] == "shr":
                reason = (f"shr at op{k} (slot {slot}) is a cut vertex: "
                          f"segment must be bijective but v>>s (1<=s<=31) is "
                          f"never injective => ANALYTIC UNSAT")
    return reason, oddk, shrs, cuts


def fmt_ops(ops):
    return ";".join(op[0] + "(" + ",".join(map(str, op[1:])) + ")" for op in ops)


def cegis_ex(ops, ref_fn, solver_timeout_s, max_iters=6, oddk_idx=(),
             fixed_shifts=None, tag=""):
    """cegis() from p5d_cegis with two sound extras: odd-K pre-constraints
    on cut madds and concrete shift fixing. Same sample seed, same external
    bit-exact validation."""
    unknowns = []
    for k, op in enumerate(ops):
        if op[0] == "madd":
            unknowns.append((z3.BitVec(f"K{k}", 32), z3.BitVec(f"C{k}", 32)))
        elif op[0] == "shr":
            unknowns.append((z3.BitVec(f"S{k}", 32),))
        elif op[0] == "xorc":
            unknowns.append((z3.BitVec(f"X{k}", 32),))
        else:
            unknowns.append(())

    def sym_eval(xin):
        v = list(xin)
        for k, op in enumerate(ops):
            u = unknowns[k]
            if op[0] == "madd":
                v.append(v[op[1]] * u[0] + u[1])
            elif op[0] == "shr":
                v.append(z3.LShR(v[op[1]], u[0]))
            elif op[0] == "xorc":
                v.append(v[op[1]] ^ u[0])
            else:
                v.append(v[op[1]] ^ v[op[2]])
        return v[-1]

    rng = random.Random(0xC0FFEE)
    samples = [tuple(rng.getrandbits(32) for _ in range(N_INPUTS))
               for _ in range(12)]
    samples += [(0,), (1,), (MASK,), (1 << 31,)]
    s = z3.Solver()
    s.set("timeout", solver_timeout_s * 1000)
    for k, op in enumerate(ops):
        if op[0] == "shr":
            u = unknowns[k][0]
            if fixed_shifts and k in fixed_shifts:
                s.add(u == fixed_shifts[k])
            else:
                s.add(z3.ULT(u, 32), z3.UGT(u, 0))
        if op[0] == "madd" and k in oddk_idx:
            s.add(unknowns[k][0] & 1 == 1)
    for it in range(max_iters):
        for smp in samples:
            xin = [z3.BitVecVal(w, 32) for w in smp]
            s.add(sym_eval(xin) == z3.BitVecVal(ref_fn(*smp), 32))
        samples = []
        t0 = time.time()
        res = s.check()
        dt = time.time() - t0
        if res == z3.unsat:
            return ("UNSAT", f"iter={it} solve={dt:.1f}s")
        if res == z3.unknown:
            return ("TIMEOUT", f"iter={it} solve={dt:.1f}s "
                               f"reason={s.reason_unknown()}")
        m = s.model()
        consts = []
        for k, op in enumerate(ops):
            for u in unknowns[k]:
                consts.append(m.eval(u, model_completion=True).as_long())
        ok, cex = True, None
        for v in range(1 << 20):
            ins = (v,)
            if eval_template_py(ops, N_INPUTS, consts, ins) != ref_fn(*ins):
                ok, cex = False, ins
                break
        if ok:
            r2 = random.Random(0xF00D)
            for _ in range(10_000_000):
                ins = (r2.getrandbits(32),)
                if eval_template_py(ops, N_INPUTS, consts, ins) != ref_fn(*ins):
                    ok, cex = False, ins
                    break
        if ok:
            return ("FOUND", f"consts={consts} VERIFIED 2^20+10M")
        samples = [cex]
    return ("GAVE_UP", f"{max_iters} CEGIS iters exhausted")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["list", "quick", "one", "split"])
    ap.add_argument("--ids", default="all",
                    help="comma-separated template ids (0..11) or 'all'")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--max-iters", type=int, default=6)
    ap.add_argument("--no-oddk", action="store_true")
    ap.add_argument("--s1-lo", type=int, default=1)
    ap.add_argument("--s1-hi", type=int, default=32)
    ap.add_argument("--s2-lo", type=int, default=1)
    ap.add_argument("--s2-hi", type=int, default=32)
    args = ap.parse_args()

    tmpls = open_templates()
    if args.mode == "list":
        print(f"OPEN templates recovered: {len(tmpls)}")
        for tid, (pair, ops, desc, dups) in enumerate(tmpls):
            reason, oddk, shrs, cuts = analyze(ops)
            nmadd = sum(1 for o in ops if o[0] == "madd")
            print(f"t{tid}: pair={list(pair)} {desc}")
            print(f"    ops: {fmt_ops(ops)}")
            print(f"    madds={nmadd} shr_ops={shrs} cut_slots={cuts} "
                  f"oddK_madd_ops={oddk} dups={dups}")
            if reason:
                print(f"    ANALYTIC-UNSAT: {reason}")
        return

    ids = (list(range(len(tmpls))) if args.ids == "all"
           else [int(x) for x in args.ids.split(",")])

    if args.mode in ("quick", "one"):
        for tid in ids:
            pair, ops, desc, dups = tmpls[tid]
            reason, oddk, shrs, cuts = analyze(ops)
            if args.no_oddk:
                oddk = []
            if reason:
                print(f"LEDGER t{tid} pair={list(pair)} verdict=UNSAT-ANALYTIC "
                      f"detail=[{reason}] time=0.0s", flush=True)
                continue
            t0 = time.time()
            verdict, detail = cegis_ex(ops, myhash, args.timeout,
                                       args.max_iters, oddk_idx=oddk)
            print(f"LEDGER t{tid} pair={list(pair)} verdict={verdict} "
                  f"oddK={oddk} detail=[{detail}] "
                  f"time={time.time() - t0:.1f}s", flush=True)
        return

    if args.mode == "split":
        for tid in ids:
            pair, ops, desc, dups = tmpls[tid]
            reason, oddk, shrs, cuts = analyze(ops)
            if reason:
                print(f"LEDGER t{tid} verdict=UNSAT-ANALYTIC [{reason}]",
                      flush=True)
                continue
            assert len(shrs) in (1, 2), f"t{tid} has {len(shrs)} shrs"
            n_open = 0
            t0 = time.time()
            s2_range = (range(args.s2_lo, args.s2_hi)
                        if len(shrs) == 2 else [None])
            for s1 in range(args.s1_lo, args.s1_hi):
                for s2 in s2_range:
                    fixed = {shrs[0]: s1}
                    if s2 is not None:
                        fixed[shrs[1]] = s2
                    tc0 = time.time()
                    verdict, detail = cegis_ex(
                        ops, myhash, args.timeout, args.max_iters,
                        oddk_idx=oddk, fixed_shifts=fixed)
                    print(f"COMBO t{tid} s1={s1} s2={s2} verdict={verdict} "
                          f"[{detail}] time={time.time() - tc0:.1f}s",
                          flush=True)
                    if verdict == "FOUND":
                        print(f"!!! FOUND t{tid} ops={ops}", flush=True)
                        return
                    if verdict in ("TIMEOUT", "GAVE_UP"):
                        n_open += 1
            status = "UNSAT-ALL-COMBOS" if n_open == 0 else f"OPEN({n_open})"
            print(f"SPLIT-SUMMARY t{tid} pair={list(pair)} "
                  f"s1=[{args.s1_lo},{args.s1_hi}) s2=[{args.s2_lo},{args.s2_hi}) "
                  f"oddK={oddk} status={status} "
                  f"wall={time.time() - t0:.0f}s", flush=True)
        return


if __name__ == "__main__":
    main()
