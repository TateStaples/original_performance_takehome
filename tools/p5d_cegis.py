#!/usr/bin/env python3
"""P5-D mission 3: CEGIS (Z3, QF_BV) over shape templates derived from the
real 11-op form — the fan-out shapes the MITM cannot reach (joins at
position >= 5; census: 1.6e9+ such shapes at n=9, unreachable by
enumeration; here we test the ones NEAREST the known form, with FULL
constant freedom).

Method soundness: constraints assert template(x_i) == myhash-like target on
a SAMPLE SET. UNSAT on samples => no constant assignment matches even those
samples => the template is impossible for the full function (sound closure).
SAT => candidate constants, verified bit-exactly outside Z3 (2^20 sweep +
10M random); mismatch adds the counterexample and iterates (CEGIS).
TIMEOUT is reported as OPEN, never as closed.

Templates:
  single-round (target myhash, 11 -> 9): all distinct 9-op DAGs obtained by
  deleting 2 ops from the real form's shape (with cascade simplification),
  constants/multipliers/xor-masks/shifts ALL free.
  two-round boundary (target the primed middle span M(e,y') =
  stage1(stage0(sigma16(e) ^ y')), 7 -> 5): all 2-deletions; a 2-op/round
  boundary saving is the minimum that could matter for the <=19 composite.
"""
import sys
import time
import random
import z3

MASK = (1 << 32) - 1

C0, K0 = 0x7ED55D16, 4097
C1 = 0xC761C23C
KP, AP = 33, 0xE9F8CC1D
KQ, AQ = 16896, 0xACCF6200
K4, C4 = 9, 0xFD7046C5
C5 = 0xB55A4F09


def myhash(v):
    v = (v * 4097 + C0) & MASK
    v = (v ^ C1) ^ (v >> 19)
    p = (v * KP + AP) & MASK
    q = (v * KQ + AQ) & MASK
    v = p ^ q
    v = (v * K4 + C4) & MASK
    return ((v ^ C5) ^ (v >> 16)) & MASK


def sigma16(x):
    return x ^ (x >> 16)


def span_ref(e, y):
    """primed middle span: stage1(stage0(sigma16(e) ^ y))."""
    v = sigma16(e) ^ y
    v = (v * 4097 + C0) & MASK
    return ((v ^ C1) ^ (v >> 19)) & MASK


# ---------------------------------------------------------------------------
# Template machinery. An op: (kind, args...) over slot ids.
#   ("madd", i)      -> t = v[i]*K + C          (K, C free)
#   ("shr", i)       -> t = v[i] >> s           (s free 1..31)
#   ("xorc", i)      -> t = v[i] ^ C            (C free)
#   ("xor2", i, j)   -> t = v[i] ^ v[j]
# Slots: 0..n_inputs-1 = inputs, then one per op.
# ---------------------------------------------------------------------------

REAL_11 = [  # slot of x = 0; op k produces slot k+1
    ("madd", 0),   # 1: b
    ("shr", 1),    # 2: t
    ("xorc", 1),   # 3: u
    ("xor2", 2, 3),  # 4: c
    ("madd", 4),   # 5: p
    ("madd", 4),   # 6: q
    ("xor2", 5, 6),  # 7: d
    ("madd", 7),   # 8: e
    ("shr", 8),    # 9: t2
    ("xorc", 8),   # 10: v
    ("xor2", 9, 10),  # 11: out
]

SPAN_7 = [  # inputs: e=slot0, y=slot1; primed middle span shape (7 ops)
    ("shr", 0),      # 2: e>>16
    ("xor2", 0, 2),  # 3: sigma16(e)
    ("xor2", 1, 3),  # 4: ^ y
    ("madd", 4),     # 5: stage0
    ("shr", 5),      # 6: >>19
    ("xorc", 5),     # 7: ^C1
    ("xor2", 6, 7),  # 8: out
]


def delete_ops(ops, n_inputs, dels):
    """Delete the ops at (0-based) indices in dels; unary deletions forward
    their input; xor2 deletions forward ONE branch (returns list of variants,
    one per branch choice). Dangling ops are then removed (cascade). Returns
    list of (new_ops, desc) or [] if invalid (output deleted twice etc.)."""
    variants = [[]]  # list of branch-choice lists
    for d in sorted(dels):
        if ops[d][0] == "xor2":
            variants = [v + [b] for v in variants for b in (0, 1)]
        else:
            variants = [v + [None] for v in variants]
    out = []
    for choice in variants:
        # forward map: slot -> replacement slot
        fwd = {}
        keep = []
        ch = dict(zip(sorted(dels), choice))
        for k, op in enumerate(ops):
            slot = n_inputs + k
            if k in ch:
                if op[0] == "xor2":
                    src = op[1 + ch[k]]
                else:
                    src = op[1]
                while src in fwd:
                    src = fwd[src]
                fwd[slot] = src
            else:
                keep.append((slot, op))
        # rewire kept ops
        new_ops = []
        slotmap = {i: i for i in range(n_inputs)}
        for slot, op in keep:
            args = []
            for a in op[1:]:
                while a in fwd:
                    a = fwd[a]
                args.append(slotmap[a])
            slotmap[slot] = n_inputs + len(new_ops)
            new_ops.append((op[0],) + tuple(args))
        # cascade: drop ops whose result is never used (except the last)
        changed = True
        while changed:
            changed = False
            used = set(range(n_inputs))
            for op in new_ops:
                used.update(op[1:])
            for k in range(len(new_ops) - 1):
                if n_inputs + k not in used:
                    # remove op k
                    del new_ops[k]
                    remap = {}
                    for s in range(n_inputs + k + 1, n_inputs + len(new_ops) + 1):
                        remap[s] = s - 1
                    new_ops = [
                        (o[0],) + tuple(remap.get(a, a) for a in o[1:]) for o in new_ops
                    ]
                    changed = True
                    break
        # degenerate: xor2 with equal args -> constant 0; drop template
        if any(o[0] == "xor2" and o[1] == o[2] for o in new_ops):
            continue
        if not new_ops:
            continue
        out.append((new_ops, f"del={sorted(dels)} branch={[c for c in choice if c is not None]}"))
    return out


def eval_template_py(ops, n_inputs, consts, inputs):
    v = list(inputs)
    ci = 0
    for op in ops:
        if op[0] == "madd":
            k, c = consts[ci], consts[ci + 1]
            ci += 2
            v.append((v[op[1]] * k + c) & MASK)
        elif op[0] == "shr":
            s = consts[ci]
            ci += 1
            v.append(v[op[1]] >> s)
        elif op[0] == "xorc":
            c = consts[ci]
            ci += 1
            v.append(v[op[1]] ^ c)
        else:
            v.append(v[op[1]] ^ v[op[2]])
    return v[-1]


def cegis(ops, n_inputs, ref_fn, desc, solver_timeout_s=240, max_iters=6):
    """Returns ('UNSAT'|'TIMEOUT'|'FOUND'|'GAVE_UP', detail)."""
    nc = []
    for op in ops:
        if op[0] == "madd":
            nc += ["kc"]
        elif op[0] in ("shr", "xorc"):
            nc += ["s" if op[0] == "shr" else "c"]
    # build z3 unknowns
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
    samples = [tuple(rng.getrandbits(32) for _ in range(n_inputs)) for _ in range(12)]
    samples += [(0,) * n_inputs, (1,) * n_inputs, (MASK,) * n_inputs, (1 << 31,) * n_inputs]
    s = z3.Solver()
    s.set("timeout", solver_timeout_s * 1000)
    for u in unknowns:
        if len(u) == 1 and str(u[0]).startswith("S"):
            s.add(z3.ULT(u[0], 32), z3.UGT(u[0], 0))
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
            return ("TIMEOUT", f"iter={it} solve={dt:.1f}s reason={s.reason_unknown()}")
        # SAT: extract, verify
        m = s.model()
        consts = []
        for k, op in enumerate(ops):
            for u in unknowns[k]:
                consts.append(m.eval(u, model_completion=True).as_long())
        ok = True
        cex = None
        for v in range(1 << 20):
            ins = tuple([v] * n_inputs) if n_inputs == 1 else (v, (v * 2654435761) & MASK)
            if eval_template_py(ops, n_inputs, consts, ins) != ref_fn(*ins):
                ok = False
                cex = ins
                break
        if ok:
            r2 = random.Random(0xF00D)
            for _ in range(10_000_000):
                ins = tuple(r2.getrandbits(32) for _ in range(n_inputs))
                if eval_template_py(ops, n_inputs, consts, ins) != ref_fn(*ins):
                    ok = False
                    cex = ins
                    break
        if ok:
            return ("FOUND", f"consts={consts} VERIFIED 2^20+10M")
        samples = [cex]
    return ("GAVE_UP", f"{max_iters} CEGIS iters exhausted")


def run_family(base_ops, n_inputs, ref_fn, want_ops, name, budget_s, timeout_each):
    """All 2-deletions of base_ops that land on exactly want_ops ops."""
    n = len(base_ops)
    seen = set()
    results = {"UNSAT": 0, "TIMEOUT": 0, "FOUND": 0, "GAVE_UP": 0, "SKIP": 0}
    t_start = time.time()
    lines = []
    for i in range(n):
        for j in range(i + 1, n):
            if n - 1 in (i, j):
                continue  # never delete the output op
            for new_ops, desc in delete_ops(base_ops, n_inputs, {i, j}):
                if len(new_ops) != want_ops:
                    results["SKIP"] += 1
                    continue
                key = tuple(new_ops)
                if key in seen:
                    continue
                seen.add(key)
                if time.time() - t_start > budget_s:
                    lines.append(f"  BUDGET EXHAUSTED with {len(seen)} templates tried")
                    print(f"[{name}] BUDGET EXHAUSTED")
                    return results, lines
                verdict, detail = cegis(new_ops, n_inputs, ref_fn, desc, timeout_each)
                results[verdict] += 1
                line = f"  [{name}] {desc} ops={len(new_ops)}: {verdict} ({detail})"
                lines.append(line)
                print(line, flush=True)
                if verdict == "FOUND":
                    lines.append(f"    !!! ops={new_ops}")
                    print(f"    !!! FOUND: {new_ops}", flush=True)
                    return results, lines
    return results, lines


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 1200
    timeout_each = int(sys.argv[3]) if len(sys.argv) > 3 else 120
    if which in ("span", "all"):
        # PRIORITY 1 (coordinator): 2-round composite entry point — the
        # 7-op primed boundary span at 5 ops (2-op/round saving minimum).
        r, lines = run_family(SPAN_7, 2, span_ref, 5, "span7->5", budget, timeout_each)
        print("SPAN SUMMARY:", r)
    if which in ("hash9", "all"):
        r, lines = run_family(REAL_11, 1, myhash, 9, "hash11->9", budget, timeout_each)
        print("HASH9 SUMMARY:", r)
