#!/usr/bin/env python3
"""P5-L part 2: z3 closures for the 2-round composite mechanism accounting.

Subcommands:
  merge3   -- can the merged sigma product M(v) = v ^ (v>>16) ^ (v>>19) be
              implemented in 3 ops? Extended vocab {madd(K,C), shr(s),
              xorc(C), andc(C), orc(C)} unary + {xor2, add2, sub2, and2,
              or2, mul2} binary, all constants free. UNSAT on samples =>
              no 3-op form (sound). Supports the "merged sigma costs 4 =
              2+2 separate, saving 0" leg of the accounting.
  span6    -- P5-D's SPAN_7 boundary span (primed 2-round boundary
              stage1(stage0(sigma16(e)^y))) at 6 ops: all 1-deletion
              templates, full constant freedom (extends P5-D's span7->5
              UNSAT to the 1-op-saving tier, deletion family).
  commute  -- madd<->sigma commutation, both directions, boundary (K,s):
              dir1: E? affine B, odd K'', C'', C:
                    A v: K*sigma_s(v) + C == B(K''*v + C'')
              dir2: E? affine B, odd K'', C'', C:
                    A v: sigma_s(K*v + C) == K''*B(v) + C''
              B is ELIMINATED via the quadruple criterion (f affine <=>
              f(x)^f(y)^f(z)^f(x^y^z) == 0 for all x,y,z), leaving
              unknowns (K'', iK'', C'', C) only. UNSAT on sampled triples
              => no affine B exists (sound). SAT => external affinity
              verification; counterexample triples iterate (CEGIS).

Soundness note: UNSAT is always sound closure (samples are necessary
conditions). TIMEOUT is reported OPEN, never closed.
"""
import random
import sys
import time

import z3

MASK = (1 << 32) - 1


def sigma(v, s):
    return (v ^ (v >> s)) & MASK


def merged(v):
    return (v ^ (v >> 16) ^ (v >> 19)) & MASK


# =========================================================================
# merge3
# =========================================================================
UNARY = ["madd", "shr", "xorc", "andc", "orc"]
BINARY = ["xor2", "add2", "sub2", "and2", "or2", "mul2"]


def gen_shapes3():
    """All 3-op shapes, slot0 = input; op k -> slot k+1. Prune: slot2 must
    be read by op3; slot1 by op2 or op3."""
    shapes = []
    op1s = [(k, 0) for k in UNARY]  # binaries on (0,0) degenerate/subsumed
    for o1 in op1s:
        op2s = []
        for k in UNARY:
            for i in (0, 1):
                op2s.append((k, i))
        for k in BINARY:
            if k == "sub2":
                op2s += [(k, 0, 1), (k, 1, 0)]
            elif k == "mul2":
                op2s += [(k, 0, 1), (k, 0, 0), (k, 1, 1)]
            else:
                op2s.append((k, 0, 1))
        for o2 in op2s:
            slot1_used_by_2 = 1 in o2[1:]
            op3s = []
            for k in UNARY:
                for i in (0, 1, 2):
                    op3s.append((k, i))
            for k in BINARY:
                pairs = [(0, 1), (0, 2), (1, 2)]
                if k == "sub2":
                    for a, b in pairs:
                        op3s += [(k, a, b), (k, b, a)]
                elif k == "mul2":
                    op3s += [(k, a, b) for a, b in pairs]
                    op3s += [(k, i, i) for i in (0, 1, 2)]
                else:
                    op3s += [(k, a, b) for a, b in pairs]
            for o3 in op3s:
                if 2 not in o3[1:]:
                    continue  # op2 dead
                if not slot1_used_by_2 and 1 not in o3[1:]:
                    continue  # op1 dead
                shapes.append([o1, o2, o3])
    return shapes


def build_unknowns(ops, tag):
    unknowns = []
    for k, op in enumerate(ops):
        if op[0] == "madd":
            unknowns.append((z3.BitVec(f"{tag}K{k}", 32), z3.BitVec(f"{tag}C{k}", 32)))
        elif op[0] == "shr":
            unknowns.append((z3.BitVec(f"{tag}S{k}", 32),))
        elif op[0] in ("xorc", "andc", "orc"):
            unknowns.append((z3.BitVec(f"{tag}X{k}", 32),))
        else:
            unknowns.append(())
    return unknowns


def sym_eval(ops, unknowns, xin):
    v = list(xin)
    for k, op in enumerate(ops):
        u = unknowns[k]
        kind = op[0]
        if kind == "madd":
            v.append(v[op[1]] * u[0] + u[1])
        elif kind == "shr":
            v.append(z3.LShR(v[op[1]], u[0]))
        elif kind == "xorc":
            v.append(v[op[1]] ^ u[0])
        elif kind == "andc":
            v.append(v[op[1]] & u[0])
        elif kind == "orc":
            v.append(v[op[1]] | u[0])
        elif kind == "xor2":
            v.append(v[op[1]] ^ v[op[2]])
        elif kind == "add2":
            v.append(v[op[1]] + v[op[2]])
        elif kind == "sub2":
            v.append(v[op[1]] - v[op[2]])
        elif kind == "and2":
            v.append(v[op[1]] & v[op[2]])
        elif kind == "or2":
            v.append(v[op[1]] | v[op[2]])
        elif kind == "mul2":
            v.append(v[op[1]] * v[op[2]])
        else:
            raise ValueError(kind)
    return v[-1]


def py_eval(ops, consts, xin):
    v = list(xin)
    ci = 0
    for op in ops:
        kind = op[0]
        if kind == "madd":
            v.append((v[op[1]] * consts[ci] + consts[ci + 1]) & MASK)
            ci += 2
        elif kind == "shr":
            v.append(v[op[1]] >> (consts[ci] & 31))
            ci += 1
        elif kind == "xorc":
            v.append(v[op[1]] ^ consts[ci])
            ci += 1
        elif kind == "andc":
            v.append(v[op[1]] & consts[ci])
            ci += 1
        elif kind == "orc":
            v.append(v[op[1]] | consts[ci])
            ci += 1
        elif kind == "xor2":
            v.append(v[op[1]] ^ v[op[2]])
        elif kind == "add2":
            v.append((v[op[1]] + v[op[2]]) & MASK)
        elif kind == "sub2":
            v.append((v[op[1]] - v[op[2]]) & MASK)
        elif kind == "and2":
            v.append(v[op[1]] & v[op[2]])
        elif kind == "or2":
            v.append(v[op[1]] | v[op[2]])
        elif kind == "mul2":
            v.append((v[op[1]] * v[op[2]]) & MASK)
    return v[-1]


def cegis_shape(ops, ref_fn, timeout_s, n_samples=18, iters=4):
    unknowns = build_unknowns(ops, "m")
    s = z3.Solver()
    s.set("timeout", timeout_s * 1000)
    for k, op in enumerate(ops):
        if op[0] == "shr":
            s.add(z3.ULT(unknowns[k][0], 32), z3.UGT(unknowns[k][0], 0))
    rng = random.Random(0xABCD)
    samples = [rng.getrandbits(32) for _ in range(n_samples)] + [0, 1, MASK, 1 << 31]
    for it in range(iters):
        for smp in samples:
            xin = [z3.BitVecVal(smp, 32)]
            s.add(sym_eval(ops, unknowns, xin) == z3.BitVecVal(ref_fn(smp), 32))
        samples = []
        res = s.check()
        if res == z3.unsat:
            return "UNSAT", it
        if res == z3.unknown:
            return "TIMEOUT", it
        m = s.model()
        consts = []
        for k, op in enumerate(ops):
            for u in unknowns[k]:
                consts.append(m.eval(u, model_completion=True).as_long())
        cex = None
        r2 = random.Random(0xBEEF)
        for _ in range(200_000):
            v = r2.getrandbits(32)
            if py_eval(ops, consts, [v]) != ref_fn(v):
                cex = v
                break
        if cex is None:
            for v in range(1 << 16):
                if py_eval(ops, consts, [v]) != ref_fn(v):
                    cex = v
                    break
        if cex is None:
            return "FOUND", consts
        samples = [cex]
    return "GAVE_UP", iters


def run_merge3(timeout_each=12):
    shapes = gen_shapes3()
    print(f"[merge3] {len(shapes)} pruned 3-op shapes over vocab "
          f"{UNARY}+{BINARY}, target v^(v>>16)^(v>>19)")
    counts = {"UNSAT": 0, "TIMEOUT": 0, "FOUND": 0, "GAVE_UP": 0}
    t0 = time.time()
    open_shapes = []
    for i, ops in enumerate(shapes):
        verdict, detail = cegis_shape(ops, merged, timeout_each)
        counts[verdict] += 1
        if verdict == "FOUND":
            print(f"  !!! FOUND {ops} consts={detail}")
            return counts
        if verdict in ("TIMEOUT", "GAVE_UP"):
            open_shapes.append(ops)
        if (i + 1) % 100 == 0:
            print(f"  ... {i+1}/{len(shapes)} {counts} {time.time()-t0:.0f}s",
                  flush=True)
    print(f"[merge3] DONE {counts} in {time.time()-t0:.0f}s")
    for ops in open_shapes:
        print(f"  OPEN: {ops}")
    return counts


# =========================================================================
# span6 -- reuse p5d machinery
# =========================================================================
def run_span6(timeout_each=180):
    sys.path.insert(0, "/Users/tatestaples/Code/original_performance_takehome/tools")
    import p5d_cegis as p5d

    counts = {"UNSAT": 0, "TIMEOUT": 0, "FOUND": 0, "GAVE_UP": 0, "SKIP": 0}
    t0 = time.time()
    for d in range(len(p5d.SPAN_7) - 1):  # never delete output op
        for new_ops, desc in p5d.delete_ops(p5d.SPAN_7, 2, {d}):
            if len(new_ops) != 6:
                counts["SKIP"] += 1
                print(f"  [span7->6] {desc}: SKIP (cascade to {len(new_ops)} ops)")
                continue
            verdict, detail = p5d.cegis(new_ops, 2, p5d.span_ref, desc,
                                        timeout_each)
            counts[verdict] += 1
            print(f"  [span7->6] {desc} ops=6: {verdict} ({detail})", flush=True)
            if verdict == "FOUND":
                print(f"    !!! ops={new_ops}")
                return counts
    print(f"[span6] DONE {counts} in {time.time()-t0:.0f}s")
    return counts


# =========================================================================
# commute
# =========================================================================
def check_affine_ext(fn, rng, n=20_000):
    """External affinity check; returns None or a failing triple."""
    for _ in range(n):
        x, y, z = (rng.getrandbits(32) for _ in range(3))
        if fn(x) ^ fn(y) ^ fn(z) ^ fn(x ^ y ^ z):
            return (x, y, z)
    return None


def run_commute_query(K, s_shift, direction, timeout_s=420, n_triples=24,
                      iters=4):
    """dir1: E? affine B, odd K2, C2, C: A v: K*sigma_s(v)+C == B(K2*v+C2).
       B == Phi o A^{-1}: B(u) = K*sigma(iK2*u - d) + C  (d := iK2*C2; iK2
       odd free <=> (K2,C2) free). Affinity tested in u-space (concrete
       quadruples u4 = u1^u2^u3):
         XOR_i (K*sigma(iK2*u_i - d) + C) == 0.
       dir2: E? affine B, odd K2, C2, C: A v: sigma_s(K*v+C) == K2*B(v)+C2.
       B == madd^{-1} o Psi, affinity in v-space (v4 = v1^v2^v3 concrete):
         XOR_i iK2*(sigma(K*v_i+C) - C2) == 0.
    UNSAT on sampled triples => no affine B (sound)."""
    iK2 = z3.BitVec("iK2", 32)
    d = z3.BitVec("d", 32)
    C2 = z3.BitVec("C2", 32)
    C = z3.BitVec("C", 32)
    s = z3.Tactic("qfbv").solver()
    s.set("timeout", timeout_s * 1000)
    s.add(z3.Extract(0, 0, iK2) == 1)  # odd <=> K'' odd (bijectivity)

    def zsigma(w):
        return w ^ z3.LShR(w, s_shift)

    def add_triple(v1, v2, v3):
        if direction == 1:
            u4 = v1 ^ v2 ^ v3
            terms = []
            for u in (v1, v2, v3, u4):
                arg = iK2 * z3.BitVecVal(u, 32) - d
                terms.append(K * zsigma(arg) + C)
        else:
            v4 = v1 ^ v2 ^ v3
            terms = []
            for v in (v1, v2, v3, v4):
                psi = zsigma(K * z3.BitVecVal(v, 32) + C)
                terms.append(iK2 * (psi - C2))
        s.add(terms[0] ^ terms[1] ^ terms[2] ^ terms[3] == 0)

    rng = random.Random(1000 * K + s_shift + direction)
    triples = [tuple(rng.getrandbits(32) for _ in range(3))
               for _ in range(n_triples)]
    triples += [(0, 1, 2), (1, 1 << 31, MASK)]
    for it in range(iters):
        for t in triples:
            add_triple(*t)
        triples = []
        t0 = time.time()
        res = s.check()
        dt = time.time() - t0
        if res == z3.unsat:
            return "UNSAT", f"iter={it} solve={dt:.1f}s"
        if res == z3.unknown:
            return "TIMEOUT", f"iter={it} solve={dt:.1f}s"
        m = s.model()
        ik2 = m.eval(iK2, model_completion=True).as_long()
        c = m.eval(C, model_completion=True).as_long()
        if direction == 1:
            dd = m.eval(d, model_completion=True).as_long()
            def B(u):
                v = (ik2 * u - dd) & MASK
                return (K * sigma(v, s_shift) + c) & MASK
            desc = f"iK''={ik2:#x} d={dd:#x} C={c:#x}"
        else:
            c2 = m.eval(C2, model_completion=True).as_long()
            def B(v):
                psi = sigma((K * v + c) & MASK, s_shift)
                return (ik2 * (psi - c2)) & MASK
            desc = f"iK''={ik2:#x} C''={c2:#x} C={c:#x}"
        cex = check_affine_ext(B, random.Random(it + 5))
        if cex is None:
            return "FOUND", f"{desc} affine-verified 20k triples"
        triples = [cex]
    return "GAVE_UP", f"{iters} iters"


def run_commute(timeout_each=420):
    queries = [
        (4097, 16, 1, "pull madd0' (K=4097) back through sigma16 (boundary)"),
        (4097, 19, 2, "push madd0' (K=4097) forward through sigma19"),
        (9, 16, 2, "push madd4 (K=9) forward through sigma16 (boundary)"),
        (33, 19, 1, "pull maddP (K=33) back through sigma19 (within-round)"),
    ]
    for K, sh, d, why in queries:
        verdict, detail = run_commute_query(K, sh, d, timeout_each)
        print(f"[commute] K={K} s={sh} dir{d} ({why}): {verdict} ({detail})",
              flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("merge3", "all"):
        run_merge3()
    if which in ("span6", "all"):
        run_span6()
    if which in ("commute", "all"):
        run_commute()
