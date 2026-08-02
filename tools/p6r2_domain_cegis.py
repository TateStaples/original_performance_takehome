#!/usr/bin/env python3
"""P6 R2: DOMAIN-RESTRICTED hash shortening — round 0 only.

Domain fact (verified, tests/frozen_problem.py):
  :417  tree values  = randint(0, 2**30 - 1)   -> nv   < 2^30
  :434  indices start at 0 (root)              -> node = root at round 0
  :435  input values = randint(0, 2**30 - 1)   -> val0 < 2^30
  => round-0 hash input x = val0 ^ root_nv < 2^30 (top 2 bits zero), for
  all 32 round-0 group-rounds. Round 11 does NOT qualify: walkers are back
  at the root but val is a full-width 32-bit hash output.

Question: does a template T with <= 10 ops over {madd, shr, xorc, xor2}
satisfy T(x) == myhash(x) for ALL x in [0, 2^30)? Outputs are full 32-bit
(they feed round 1) — only the INPUT domain shrinks.

Soundness:
  * All z3 samples are drawn from [0, 2^30). UNSAT on such samples =>
    no constant assignment matches even those in-domain points => the
    template cannot match myhash on the domain. SOUND refutation of the
    RESTRICTED claim (and implied by nothing previously run: the P5
    batteries constrained OUT-of-domain samples too, so neither their
    UNSATs nor their theorems transfer here in general).
  * SAT candidates are verified OUTSIDE z3: 2^20 sweep + 10M random
    30-bit, then a FULL exhaustive 2^30 numpy sweep before FOUND is
    declared. TIMEOUT is reported OPEN, never closed.

Usage (repo root):
  python3 tools/p6r2_domain_cegis.py selftest
  python3 tools/p6r2_domain_cegis.py del1   [budget_s] [timeout_each_s]
  python3 tools/p6r2_domain_cegis.py del2   [budget_s] [timeout_each_s]
  python3 tools/p6r2_domain_cegis.py prefix3 [budget_s] [timeout_each_s]
  python3 tools/p6r2_domain_cegis.py prefix2 [budget_s] [timeout_each_s]
  python3 tools/p6r2_domain_cegis.py sw9pairs s1a,s2a s1b,s2b ... [timeout_each_s]
  python3 tools/p6r2_domain_cegis.py sw9free [timeout_s]
  python3 tools/p6r2_domain_cegis.py lemmas
"""
import sys
import time
import random
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from p5d_cegis import (  # noqa: E402
    MASK, myhash, REAL_11, delete_ops, eval_template_py,
    C0, C1,
)

import z3  # noqa: E402

DOMAIN_BITS = 30
DOMAIN = 1 << DOMAIN_BITS


# --------------------------------------------------------------- references
def prefix_ref(x):
    """stage2(stage1(x)) of myhash: the part whose input IS domain-limited."""
    v = (x * 4097 + C0) & MASK
    return ((v ^ C1) ^ (v >> 19)) & MASK


def myhash_frozen(a):
    """Independent recomputation straight from frozen_problem HASH_STAGES."""
    stages = [
        ("+", 0x7ED55D16, "+", "<<", 12),
        ("^", 0xC761C23C, "^", ">>", 19),
        ("+", 0x165667B1, "+", "<<", 5),
        ("+", 0xD3A2646C, "^", "<<", 9),
        ("+", 0xFD7046C5, "+", "<<", 3),
        ("^", 0xB55A4F09, "^", ">>", 16),
    ]
    fns = {
        "+": lambda x, y: (x + y) & MASK,
        "^": lambda x, y: x ^ y,
        "<<": lambda x, y: (x << y) & MASK,
        ">>": lambda x, y: x >> y,
    }
    for op1, val1, op2, op3, val3 in stages:
        a = fns[op2](fns[op1](a, val1), fns[op3](a, val3))
    return a


def myhash_np(x):
    import numpy as np
    x = x.astype(np.uint32)
    with __import__("numpy").errstate(over="ignore"):
        v = x * np.uint32(4097) + np.uint32(C0)
        v = (v ^ np.uint32(C1)) ^ (v >> np.uint32(19))
        p = v * np.uint32(33) + np.uint32(0xE9F8CC1D)
        q = v * np.uint32(16896) + np.uint32(0xACCF6200)
        v = p ^ q
        v = v * np.uint32(9) + np.uint32(0xFD7046C5)
        return (v ^ np.uint32(0xB55A4F09)) ^ (v >> np.uint32(16))


def full_domain_verify(ops, n_inputs, consts, ref_np=myhash_np):
    """Exhaustive check of a candidate over ALL 2^30 in-domain inputs."""
    import numpy as np
    assert n_inputs == 1
    CH = 1 << 24
    for base in range(0, DOMAIN, CH):
        x = np.arange(base, base + CH, dtype=np.uint64).astype(np.uint32)
        v = [x]
        ci = 0
        with np.errstate(over="ignore"):
            for op in ops:
                if op[0] == "madd":
                    k, c = consts[ci], consts[ci + 1]
                    ci += 2
                    v.append(v[op[1]] * np.uint32(k) + np.uint32(c))
                elif op[0] == "shr":
                    s = consts[ci]
                    ci += 1
                    v.append(v[op[1]] >> np.uint32(s))
                elif op[0] == "xorc":
                    c = consts[ci]
                    ci += 1
                    v.append(v[op[1]] ^ np.uint32(c))
                else:
                    v.append(v[op[1]] ^ v[op[2]])
            want = ref_np(x)
        bad = np.nonzero(v[-1] != want)[0]
        if len(bad):
            return int(x[bad[0]])
    return None


# --------------------------------------------------------------- CEGIS core
def cegis_domain(ops, n_inputs, ref_fn, desc, solver_timeout_s=90,
                 max_iters=6, fixed_shifts=None, exhaustive_on_pass=True):
    """Domain-restricted CEGIS. Returns (verdict, detail).
    fixed_shifts: optional list assigning concrete values to shr ops in
    order of appearance (None entries stay free)."""
    unknowns = []
    shr_idx = 0
    fixed = {}
    for k, op in enumerate(ops):
        if op[0] == "madd":
            unknowns.append((z3.BitVec(f"K{k}", 32), z3.BitVec(f"C{k}", 32)))
        elif op[0] == "shr":
            u = z3.BitVec(f"S{k}", 32)
            unknowns.append((u,))
            if fixed_shifts is not None and shr_idx < len(fixed_shifts) \
                    and fixed_shifts[shr_idx] is not None:
                fixed[k] = fixed_shifts[shr_idx]
            shr_idx += 1
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

    rng = random.Random(0x30B17)
    dm = DOMAIN - 1
    samples = [tuple(rng.getrandbits(DOMAIN_BITS) for _ in range(n_inputs))
               for _ in range(14)]
    structured = [0, 1, 2, 3, DOMAIN - 1, DOMAIN // 2, DOMAIN // 2 - 1,
                  0x2AAAAAAA, 0x15555555, 0x00FF00FF & dm]
    samples += [(w,) * n_inputs for w in structured]

    s = z3.Solver()
    s.set("timeout", solver_timeout_s * 1000)
    for k, u in enumerate(unknowns):
        if ops[k][0] == "shr":
            if k in fixed:
                s.add(u[0] == fixed[k])
            else:
                s.add(z3.ULT(u[0], 32), z3.UGT(u[0], 0))
    tot = 0.0
    for it in range(max_iters):
        for smp in samples:
            assert all(w < DOMAIN for w in smp), "OUT-OF-DOMAIN SAMPLE (bug)"
            xin = [z3.BitVecVal(w, 32) for w in smp]
            s.add(sym_eval(xin) == z3.BitVecVal(ref_fn(*smp), 32))
        samples = []
        t0 = time.time()
        res = s.check()
        tot += time.time() - t0
        if res == z3.unsat:
            return ("UNSAT", f"iter={it} solve={tot:.1f}s")
        if res == z3.unknown:
            return ("TIMEOUT", f"iter={it} solve={tot:.1f}s")
        m = s.model()
        consts = []
        for k, op in enumerate(ops):
            for u in unknowns[k]:
                consts.append(m.eval(u, model_completion=True).as_long())
        ok, cex = True, None
        for v in range(1 << 20):
            ins = (v,) * n_inputs
            if eval_template_py(ops, n_inputs, consts, ins) != ref_fn(*ins):
                ok, cex = False, ins
                break
        if ok:
            r2 = random.Random(0xF00D5)
            for _ in range(2_000_000):
                ins = tuple(r2.getrandbits(DOMAIN_BITS)
                            for _ in range(n_inputs))
                if eval_template_py(ops, n_inputs, consts, ins) != ref_fn(*ins):
                    ok, cex = False, ins
                    break
        if ok and exhaustive_on_pass and n_inputs == 1:
            ref_np = myhash_np if ref_fn is myhash else None
            if ref_np is None:
                return ("CAND", f"consts={consts} passed 2^20+2M "
                                f"(no np ref for exhaustive)")
            bad = full_domain_verify(ops, n_inputs, consts, ref_np)
            if bad is None:
                return ("FOUND", f"consts={consts} VERIFIED FULL 2^30")
            ok, cex = False, (bad,)
        elif ok:
            return ("CAND", f"consts={consts} passed 2^20+2M")
        samples = [cex]
    return ("GAVE_UP", f"{max_iters} CEGIS iters exhausted solve={tot:.1f}s")


# --------------------------------------------------------------- batteries
def battery_deletions(n_dels, want_max_ops, budget_s, timeout_each,
                      only=None, fixed_shifts=None):
    n = len(REAL_11)
    import itertools
    seen = set()
    t0 = time.time()
    summary = {}
    for dels in itertools.combinations(range(n - 1), n_dels):
        if only is not None and set(dels) not in only:
            continue
        for new_ops, desc in delete_ops(REAL_11, 1, set(dels)):
            if len(new_ops) > want_max_ops:
                continue
            key = tuple(new_ops)
            if key in seen:
                continue
            seen.add(key)
            if time.time() - t0 > budget_s:
                print("BUDGET EXHAUSTED", flush=True)
                return summary
            v, d = cegis_domain(new_ops, 1, myhash, desc, timeout_each,
                                fixed_shifts=fixed_shifts)
            fs = f" fs={fixed_shifts}" if fixed_shifts else ""
            summary[v] = summary.get(v, 0) + 1
            print(f"  [del{n_dels}] {desc}{fs} ops={len(new_ops)}: {v} ({d})",
                  flush=True)
            if v == "FOUND":
                print(f"    !!! ops={new_ops}")
                return summary
    return summary


def enum_small_templates(n_ops):
    """All single-input DAG templates with exactly n_ops ops, every
    intermediate slot used, output = last op."""
    kinds_un = ["madd", "shr", "xorc"]
    outs = []

    def rec(ops):
        k = len(ops)
        if k == n_ops:
            used = set()
            for op in ops:
                used.update(op[1:])
            if all(s in used for s in range(1, n_ops)):  # slots 1..n-1 used
                outs.append(tuple(ops))
            return
        slots = list(range(k + 1))
        for kind in kinds_un:
            for i in slots:
                # skip trivial stacking that is provably collapsible:
                # xorc after xorc on same slot chain == one xorc
                rec(ops + [(kind, i)])
        for i in slots:
            for j in slots:
                if i < j:
                    rec(ops + [("xor2", i, j)])

    rec([])
    # cheap canonical dedup: drop templates where two consecutive unary ops
    # of identical kind chain (madd(madd) == madd, xorc(xorc) == xorc,
    # shr(shr) == shr with summed shift only if intermediate unused --
    # intermediate-use requirement already applied, so chained same-kind
    # unary with the intermediate ONLY feeding the next is collapsible).
    keep = []
    for ops in outs:
        bad = False
        usecount = {}
        for op in ops:
            for a in op[1:]:
                usecount[a] = usecount.get(a, 0) + 1
        for k, op in enumerate(ops):
            if op[0] in ("madd", "xorc"):
                src = op[1]
                if src >= 1 and ops[src - 1][0] == op[0] \
                        and usecount.get(src, 0) == 1:
                    bad = True  # collapsible chain -> covered at n_ops-1
                    break
        if not bad:
            keep.append(ops)
    return keep


def battery_prefix(n_ops, budget_s, timeout_each, lo=0, hi=10**9):
    tmpls = enum_small_templates(n_ops)
    print(f"prefix{n_ops}: {len(tmpls)} templates after dedup "
          f"(running [{lo}:{hi}])", flush=True)
    tmpls = list(enumerate(tmpls))[lo:hi]
    t0 = time.time()
    summary = {}
    for i, ops in tmpls:
        if time.time() - t0 > budget_s:
            print(f"BUDGET EXHAUSTED at {i}/{len(tmpls)}", flush=True)
            break
        v, d = cegis_domain(list(ops), 1, prefix_ref, f"pfx{i}", timeout_each,
                            exhaustive_on_pass=False)
        summary[v] = summary.get(v, 0) + 1
        tag = " ".join(f"{o[0]}{o[1:]}" for o in ops)
        print(f"  [pfx{n_ops} {i}] {tag}: {v} ({d})", flush=True)
        if v in ("FOUND", "CAND"):
            print(f"    !!! candidate ops={ops}")
    return summary


SANDWICH_9 = [
    ("madd", 0), ("shr", 1), ("xorc", 1), ("xor2", 2, 3),
    ("madd", 4), ("shr", 5), ("xorc", 5), ("xor2", 6, 7),
    ("madd", 8),
]


def selftest():
    r = random.Random(1)
    for _ in range(2000):
        x = r.getrandbits(32)
        assert myhash(x) == myhash_frozen(x), x
    import numpy as np
    xs = np.array([r.getrandbits(30) for _ in range(1000)], dtype=np.uint32)
    ys = myhash_np(xs)
    for i in range(1000):
        assert int(ys[i]) == myhash(int(xs[i]))
    # positive control: the real 11-op template with the real constants must
    # pass full_domain_verify
    consts = [4097, C0, 19, C1, 33, 0xE9F8CC1D, 16896, 0xACCF6200,
              9, 0xFD7046C5, 16, 0xB55A4F09]
    # REAL_11 order: madd(K,C), shr(s), xorc(C), xor2, madd, madd, xor2,
    # madd, shr, xorc, xor2
    consts = [4097, C0,  # madd
              19,        # shr
              C1,        # xorc
              33, 0xE9F8CC1D,   # madd p
              16896, 0xACCF6200,  # madd q
              9, 0xFD7046C5,      # madd e
              16,                 # shr
              0xB55A4F09]         # xorc
    bad = full_domain_verify(REAL_11, 1, consts)
    assert bad is None, f"positive control FAILED at {bad}"
    # negative control: perturb one constant -> must be caught
    consts2 = list(consts)
    consts2[1] ^= 1
    bad = full_domain_verify(REAL_11, 1, consts2)
    assert bad is not None, "negative control NOT caught"
    # prefix positive control: 4-op real prefix
    pfx = [("madd", 0), ("shr", 1), ("xorc", 1), ("xor2", 2, 3)]
    for _ in range(2000):
        x = r.getrandbits(30)
        assert eval_template_py(pfx, 1, [4097, C0, 19, C1], (x,)) \
            == prefix_ref(x)
    print("SELFTEST OK (myhash==frozen, np ref, +/- controls, prefix ref)")


def lemmas():
    """Numeric witnesses: which structural filters still bind on the
    30-bit domain (all probes IN-domain => sound)."""
    # 1. zero-shr forms are triangular: out bit0 depends only on x bit0.
    #    witness: x, x' in domain with same bit0 but different myhash bit0.
    a, b = myhash(0), myhash(2)
    print(f"myhash(0)&1={a & 1} myhash(2)&1={b & 1} -> "
          f"{'ZERO-SHR DEAD on domain' if (a ^ b) & 1 else 'inconclusive pair'}")
    if not ((a ^ b) & 1):
        for x in range(2, 100, 2):
            if (myhash(0) ^ myhash(x)) & 1:
                print(f"  witness x'={x}")
                break
    # 2. one-shr window: out bit i depends only on x bits <= i+s.
    #    For each s, find in-domain x ≡ x' (mod 2^(s+1)) with different
    #    myhash bit0. Possible only when s+1 < 30.
    r = random.Random(7)
    dead = []
    open_s = []
    for s in range(1, 32):
        if s + 1 >= DOMAIN_BITS:
            open_s.append(s)
            continue
        found = False
        for _ in range(2000):
            x = r.getrandbits(DOMAIN_BITS)
            d = r.getrandbits(DOMAIN_BITS - (s + 1)) << (s + 1)
            if d == 0:
                continue
            x2 = x ^ d
            if (myhash(x) ^ myhash(x2)) & 1:
                found = True
                break
        (dead if found else open_s).append(s)
    print(f"one-shr window kills (in-domain witnesses): s in {dead}")
    print(f"one-shr OPEN on domain (window vacuous/no witness): s in {open_s}")
    # 3. cut-shr counting: injectivity of myhash on domain needs 2^30
    #    distinct outputs; a cut node t>>s has <= 2^(32-s) values.
    print("cut-shr counting: s>=3 at a DAG cut dead (2^(32-s) < 2^30); "
          "s in {1,2} at a cut NOT killed by counting (weakening vs K2).")
    # 4. one-shr s in {29,30,31}: in a one-shr DAG every out bit i is a
    #    function of (x mod 2^(i+1), w) with w = h(x)>>s taking at most
    #    2^(32-s) values -> per residue class, low (i+1) out bits take at
    #    most 2^(32-s) distinct patterns. Count them with IN-domain probes.
    r2 = random.Random(99)
    for s in (29, 30, 31):
        cap = 1 << (32 - s)
        i1 = 32 - s + 1          # look at low i1 bits, 2^i1 = 2*cap patterns
        mod = 1 << i1
        worst = 0
        witness_class = None
        for c in range(mod):
            seen = set()
            for _ in range(4000):
                x = (r2.getrandbits(DOMAIN_BITS - i1) << i1) | c
                seen.add(myhash(x) & (mod - 1))
                if len(seen) > cap:
                    break
            if len(seen) > worst:
                worst, witness_class = len(seen), c
            if worst > cap:
                break
        verdict = "DEAD on domain" if worst > cap else "OPEN"
        print(f"one-shr s={s}: max {worst} low-{i1}-bit patterns per "
              f"class (cap {cap}, class {witness_class}) -> {verdict}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if which == "selftest":
        selftest()
    elif which == "lemmas":
        lemmas()
    elif which == "del1":
        b = int(sys.argv[2]) if len(sys.argv) > 2 else 480
        t = int(sys.argv[3]) if len(sys.argv) > 3 else 60
        only = None
        if len(sys.argv) > 4:
            only = [set(int(w) for w in g.split(","))
                    for g in sys.argv[4].split(":")]
        fs = None
        if len(sys.argv) > 5:
            fs = [int(w) for w in sys.argv[5].split(",")]
        print("DEL1 SUMMARY:", battery_deletions(1, 10, b, t, only, fs))
    elif which == "del2":
        b = int(sys.argv[2]) if len(sys.argv) > 2 else 480
        t = int(sys.argv[3]) if len(sys.argv) > 3 else 45
        only = None
        if len(sys.argv) > 4:
            only = [set(int(w) for w in g.split(","))
                    for g in sys.argv[4].split(":")]
        print("DEL2 SUMMARY:", battery_deletions(2, 9, b, t, only))
    elif which == "prefix3":
        b = int(sys.argv[2]) if len(sys.argv) > 2 else 480
        t = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        lo = int(sys.argv[4]) if len(sys.argv) > 4 else 0
        hi = int(sys.argv[5]) if len(sys.argv) > 5 else 10**9
        print("PREFIX3 SUMMARY:", battery_prefix(3, b, t, lo, hi))
    elif which == "prefix2":
        b = int(sys.argv[2]) if len(sys.argv) > 2 else 240
        t = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        print("PREFIX2 SUMMARY:", battery_prefix(2, b, t))
    elif which == "sw9free":
        t = int(sys.argv[2]) if len(sys.argv) > 2 else 400
        v, d = cegis_domain(SANDWICH_9, 1, myhash, "sw9free", t, 8)
        print(f"SW9FREE: {v} ({d})")
    elif which == "sw9pairs":
        args = sys.argv[2:]
        t = 90
        if args and args[-1].isdigit():
            t = int(args[-1])
            args = args[:-1]
        for a in args:
            s1, s2 = (int(w) for w in a.split(","))
            v, d = cegis_domain(SANDWICH_9, 1, myhash, f"sw9({s1},{s2})", t,
                                6, fixed_shifts=[s1, s2])
            print(f"SW9({s1},{s2}): {v} ({d})", flush=True)
    else:
        raise SystemExit(f"unknown battery {which}")
