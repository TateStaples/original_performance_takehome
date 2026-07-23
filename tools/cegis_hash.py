#!/usr/bin/env python3
"""
H-025: CEGIS (counterexample-guided) synthesis of shorter hash programs.

Asks, for a target segment f of the fused 11-op myhash chain and a slot
count k: does ANY k-op straight-line program over the machine's valu op
set, with ARBITRARY free 32-bit constants and arbitrary DAG wiring,
compute f on all 2^32 inputs?

This is strictly stronger coverage per (target, k) than the iter-1
forward-exhaustive and iter-4 MITM searches (which were pool-limited in
interior constants and chain/split-shaped): here every operand constant
is a free 32-bit SMT variable and any slot may read any earlier slot.

Op set and machine-coverage argument
------------------------------------
The kernel's valu mixing ops are: multiply_add(a,b,c) plus elementwise
+ - * ^ & | << >> (div/mod/cmp excluded, as in the iter-1/4 searchers;
they are not used by any hash form and cost the same slot anyway).
We encode 6 opcodes, each operand being (earlier wire | free constant):

    MADD(a,b,c) = a*b + c   XOR  AND  OR  SHL(a,s)  SHR(a,s)

MADD absorbs the rest of the arithmetic ops at equal op count:
    add   a+b        = MADD(a, 1, b)
    sub   a-b        = MADD(b, 0xFFFFFFFF, a)
    mul   a*b        = MADD(a, b, 0)
    shl-by-const     = MADD(a, 2^s, 0)
so SHL is only kept for wire (data-dependent) shift amounts. Shift
semantics match the machine: amounts >= 32 yield 0 (z3 bvshl/bvlshr
agree with `(a << s) % 2**32` / `a >> s` for s >= 32).

Canonicalization / pruning (all SOUND for the cumulative <=k claim: each
excluded program is semantically equal to a program of the SAME length in
canonical form, or to a strictly SHORTER program covered by a smaller-k
run — see comments at the constraints):
  * commutative operand order fixed, const always in the b slot,
  * no identity ops (xor 0, and ~0, or 0, madd *1+0, shift by 0),
  * no constant-valued slots (and 0, or ~0, madd *0, shift >= 32,
    all-const operands),
  * no dead slots (every slot feeds a later slot; last slot = output).

CEGIS loop: synthesize structure+constants against a growing example set
(z3, QF_BV); verify each candidate first on 10M random+structured inputs
(numpy) and then EXACTLY on all 2^32 inputs (z3 with the candidate's
constants fixed); mismatches become new examples.  Outcomes:
  * HIT      — candidate verified on all 2^32 inputs (then: Rust
               bit-exact test + kernel port, handled outside this tool),
  * UNSAT    — certificate: no k-op program over this op set exists
               (relative to any --madds-eq/--ops restriction in force),
  * UNKNOWN  — solver timeout inside the wall budget; no claim.

Usage:
  python tools/cegis_hash.py --selftest
  python tools/cegis_hash.py --target full --k 10 --timeout 1200000
  python tools/cegis_hash.py --target b2d --k 5
"""

import argparse
import json
import random
import sys
import time

import numpy as np
import z3

try:
    import bitwuzla as bw
except ImportError:  # pragma: no cover - bitwuzla is optional
    bw = None

M32 = (1 << 32) - 1

# ---- fused-hash constants (rust_harness/src/problem.rs::hashseg) ----
K0, C0 = 4097, 0x7ED55D16
C1, SH1 = 0xC761C23C, 19
KP, AP = 33, 0xE9F8CC1D
KQ, AQ = 16896, 0xACCF6200
K4, C4 = 9, 0xFD7046C5
C5, SH5 = 0xB55A4F09, 16


# ---- python (concrete) spec ----
def stage0(a):
    return (a * K0 + C0) & M32


def stage1(b):
    return (b ^ C1) ^ (b >> SH1)


def f23(c):
    return ((c * KP + AP) & M32) ^ ((c * KQ + AQ) & M32)


def stage4(d):
    return (d * K4 + C4) & M32


def stage5(e):
    return (e ^ C5) ^ (e >> SH5)


def sigma16(x):
    return x ^ (x >> SH5)


def full(a):
    return stage5(stage4(f23(stage1(stage0(a)))))


# ---- z3 spec builders (mirror of the above over BitVec(32)) ----
def z3_stage0(a):
    return a * K0 + C0


def z3_stage1(b):
    return (b ^ C1) ^ z3.LShR(b, SH1)


def z3_f23(c):
    return (c * KP + AP) ^ (c * KQ + AQ)


def z3_stage4(d):
    return d * K4 + C4


def z3_stage5(e):
    return (e ^ C5) ^ z3.LShR(e, SH5)


def z3_sigma16(x):
    return x ^ z3.LShR(x, SH5)


def z3_full(a):
    return z3_stage5(z3_stage4(z3_f23(z3_stage1(z3_stage0(a)))))


# name -> (ninputs, current_op_count, py_fn, z3_fn)
TARGETS = {
    # single stages / small spans (iter-1 closed these IN-POOL only)
    "stage1": (1, 3, stage1, z3_stage1),
    "f23": (1, 3, f23, z3_f23),
    "stage5": (1, 3, stage5, z3_stage5),
    "s01": (1, 4, lambda a: stage1(stage0(a)), lambda a: z3_stage1(z3_stage0(a))),
    "f23s4": (1, 4, lambda c: stage4(f23(c)), lambda c: z3_stage4(z3_f23(c))),
    "s45": (1, 4, lambda d: stage5(stage4(d)), lambda d: z3_stage5(z3_stage4(d))),
    # the promoted boundary questions (iter-4 MITM had the kf=4 gap here)
    "b2d": (1, 6, lambda b: f23(stage1(b)), lambda b: z3_f23(z3_stage1(b))),
    "a2d": (
        1,
        7,
        lambda a: f23(stage1(stage0(a))),
        lambda a: z3_f23(z3_stage1(z3_stage0(a))),
    ),
    "b2e": (
        1,
        7,
        lambda b: stage4(f23(stage1(b))),
        lambda b: z3_stage4(z3_f23(z3_stage1(b))),
    ),
    "c2out": (
        1,
        7,
        lambda c: stage5(stage4(f23(c))),
        lambda c: z3_stage5(z3_stage4(z3_f23(c))),
    ),
    "a2e": (
        1,
        8,
        lambda a: stage4(f23(stage1(stage0(a)))),
        lambda a: z3_stage4(z3_f23(z3_stage1(z3_stage0(a)))),
    ),
    "b2out": (
        1,
        8,
        lambda b: stage5(stage4(f23(stage1(b)))),
        lambda b: z3_stage5(z3_stage4(z3_f23(z3_stage1(b)))),
    ),
    # cross-round boundaries (2 inputs)
    "xr5": (
        2,
        6,
        lambda d, n: stage0(stage5(stage4(d)) ^ n),
        lambda d, n: z3_stage0(z3_stage5(z3_stage4(d)) ^ n),
    ),
    "xr3p": (
        2,
        5,
        lambda d, n: stage0(sigma16(stage4(d)) ^ n),
        lambda d, n: z3_stage0(z3_sigma16(z3_stage4(d)) ^ n),
    ),
    # the whole thing
    "full": (1, 11, full, z3_full),
    "foldin": (
        2,
        12,
        lambda v, n: full(v ^ n),
        lambda v, n: z3_full(v ^ n),
    ),
}

OP_MADD, OP_XOR, OP_AND, OP_OR, OP_SHL, OP_SHR = range(6)
OP_NAMES = ["MADD", "XOR", "AND", "OR", "SHL", "SHR"]


class Encoding:
    """k-slot program sketch over ninputs inputs, as z3 constraints."""

    def __init__(self, k, ninputs, allowed_ops, madds_eq=None, madds_max=None,
                 pin_first_madd=False, pin_last_xor=False):
        self.k = k
        self.ninputs = ninputs
        self.op = [z3.BitVec(f"op_{i}", 3) for i in range(k)]
        self.isc = [[z3.Bool(f"isc_{i}_{j}") for j in range(3)] for i in range(k)]
        self.w = [[z3.BitVec(f"w_{i}_{j}", 5) for j in range(3)] for i in range(k)]
        self.K = [[z3.BitVec(f"K_{i}_{j}", 32) for j in range(3)] for i in range(k)]
        cs = []
        for i in range(k):
            op, isc, w, K = self.op[i], self.isc[i], self.w[i], self.K[i]
            cs.append(z3.Or([op == o for o in allowed_ops]))
            nw = ninputs + i  # legal wire indices: 0..nw-1
            for j in range(3):
                cs.append(z3.ULT(w[j], nw))
                # canonical: const operands pin their (unused) wire selector
                cs.append(z3.Implies(isc[j], w[j] == 0))
            is_madd = op == OP_MADD
            # unused operand 2 of non-madd slots is pinned
            cs.append(z3.Implies(z3.Not(is_madd), z3.And(isc[2], K[2] == 0)))
            # MADD(a,b,c): a always a wire (a*b commutes; both-const product
            # folds into c => same-length MADD(c,1,K) covered in this k)
            cs.append(z3.Implies(is_madd, z3.Not(isc[0])))
            #   wire-wire product canonical order (equal allowed: squares)
            cs.append(
                z3.Implies(
                    z3.And(is_madd, z3.Not(isc[1])), z3.ULE(w[1], w[0])
                )
            )
            #   b=0 (const output / identity-with-c) and *1+0 (identity)
            #   reduce to shorter programs -> excluded, covered at k-1
            cs.append(z3.Implies(z3.And(is_madd, isc[1]), K[1] != 0))
            cs.append(
                z3.Implies(
                    z3.And(is_madd, isc[1], isc[2]),
                    z3.Not(z3.And(K[1] == 1, K[2] == 0)),
                )
            )
            # XOR/AND/OR: commutative -> const goes in b; wire-wire strict
            # order (equal wires: x^x=0 const, x&x=x, x|x=x -> shorter)
            for o, badK in (
                (OP_XOR, [0]),
                (OP_AND, [0, M32]),
                (OP_OR, [0, M32]),
            ):
                is_o = op == o
                cs.append(z3.Implies(is_o, z3.Not(isc[0])))
                cs.append(
                    z3.Implies(z3.And(is_o, z3.Not(isc[1])), z3.ULT(w[1], w[0]))
                )
                for bk in badK:
                    cs.append(z3.Implies(z3.And(is_o, isc[1]), K[1] != bk))
            # SHL: shift amount must be a WIRE (const shl == MADD by 2^s,
            # covered in this same k); value operand wire or nonzero const
            cs.append(z3.Implies(op == OP_SHL, z3.Not(isc[1])))
            cs.append(z3.Implies(z3.And(op == OP_SHL, isc[0]), K[0] != 0))
            # SHR: not both const; const amount in [1,31] (0 identity,
            # >=32 const-0 -> shorter); const value nonzero
            is_shr = op == OP_SHR
            cs.append(z3.Implies(is_shr, z3.Not(z3.And(isc[0], isc[1]))))
            cs.append(
                z3.Implies(
                    z3.And(is_shr, isc[1]),
                    z3.And(z3.UGE(K[1], 1), z3.ULE(K[1], 31)),
                )
            )
            cs.append(z3.Implies(z3.And(is_shr, isc[0]), K[0] != 0))
        # dead-code freedom: every slot t < k-1 is read by a later slot
        for t in range(k - 1):
            widx = ninputs + t
            uses = []
            for i in range(t + 1, k):
                for j in range(3):
                    u = z3.And(z3.Not(self.isc[i][j]), self.w[i][j] == widx)
                    if j == 2:
                        u = z3.And(u, self.op[i] == OP_MADD)
                    uses.append(u)
            cs.append(z3.Or(uses))
        if madds_eq is not None or madds_max is not None:
            n_madd = z3.Sum(
                [z3.If(self.op[i] == OP_MADD, 1, 0) for i in range(k)]
            )
            if madds_eq is not None:
                cs.append(n_madd == madds_eq)
            if madds_max is not None:
                cs.append(n_madd <= madds_max)
        if pin_first_madd:
            cs.append(self.op[0] == OP_MADD)
            cs.append(z3.And(self.isc[0][1], self.isc[0][2]))
        if pin_last_xor:
            cs.append(self.op[k - 1] == OP_XOR)
            cs.append(z3.Not(self.isc[k - 1][1]))  # xor of two wires
        self.structural = cs

    def slot_values(self, inputs):
        """Symbolic slot values for one example (inputs: list of BitVec32
        or python ints)."""
        wires = [
            x if isinstance(x, z3.ExprRef) else z3.BitVecVal(x, 32)
            for x in inputs
        ]
        vals = []
        for i in range(self.k):
            ops = []
            for j in range(3):
                mux = wires[0]
                for t in range(1, self.ninputs + i):
                    mux = z3.If(self.w[i][j] == t, wires[t], mux)
                ops.append(z3.If(self.isc[i][j], self.K[i][j], mux))
            o0, o1, o2 = ops
            op = self.op[i]
            v = z3.If(
                op == OP_MADD,
                o0 * o1 + o2,
                z3.If(
                    op == OP_XOR,
                    o0 ^ o1,
                    z3.If(
                        op == OP_AND,
                        o0 & o1,
                        z3.If(op == OP_OR, o0 | o1, z3.If(op == OP_SHL, o0 << o1, z3.LShR(o0, o1))),
                    ),
                ),
            )
            v = z3.simplify(v)
            wires.append(v)
            vals.append(v)
        return vals

    def extract(self, model):
        """Model -> concrete program [(opname, [('w',i)|('c',v)]*3)]."""

        def ev(x):
            return model.eval(x, model_completion=True).as_long()

        prog = []
        for i in range(self.k):
            o = ev(self.op[i])
            operands = []
            nops = 3 if o == OP_MADD else 2
            for j in range(nops):
                if z3.is_true(model.eval(self.isc[i][j], model_completion=True)):
                    operands.append(("c", ev(self.K[i][j])))
                else:
                    operands.append(("w", ev(self.w[i][j])))
            prog.append((OP_NAMES[o], operands))
        return prog


class BwEncoding:
    """Same sketch encoding, built natively on the bitwuzla API (much
    faster than z3 on these QF_BV synthesis instances)."""

    def __init__(self, k, ninputs, allowed_ops, madds_eq=None, madds_max=None,
                 pin_first_madd=False, pin_last_xor=False, timeout_ms=None,
                 seed=0, bv_solver="bitblast"):
        assert bw is not None, "pip install bitwuzla"
        self.k = k
        self.ninputs = ninputs
        self.tm = tm = bw.TermManager()
        opts = bw.Options()
        opts.set(bw.Option.PRODUCE_MODELS, True)
        if timeout_ms:
            opts.set(bw.Option.TIME_LIMIT_PER, timeout_ms)
        if seed:
            opts.set(bw.Option.SEED, seed)
        if bv_solver != "bitblast":
            # 'prop'/'preprop': local-search modes -- much better at FINDING
            # models (SAT), but 'prop' alone cannot conclude UNSAT; use only
            # on SAT-hunting lanes.
            opts.set(bw.Option.BV_SOLVER, bv_solver)
        self.solver = bw.Bitwuzla(tm, opts)
        self.bv32 = tm.mk_bv_sort(32)
        self.bv3 = tm.mk_bv_sort(3)
        self.bv5 = tm.mk_bv_sort(5)
        self.bv8 = tm.mk_bv_sort(8)
        bool_s = tm.mk_bool_sort()
        self.op = [tm.mk_const(self.bv3, f"op_{i}") for i in range(k)]
        self.isc = [
            [tm.mk_const(bool_s, f"isc_{i}_{j}") for j in range(3)]
            for i in range(k)
        ]
        self.w = [
            [tm.mk_const(self.bv5, f"w_{i}_{j}") for j in range(3)]
            for i in range(k)
        ]
        self.K = [
            [tm.mk_const(self.bv32, f"K_{i}_{j}") for j in range(3)]
            for i in range(k)
        ]

        T = lambda kind, *a: tm.mk_term(kind, list(a))
        self._T = T
        Kd = bw.Kind
        self._b32 = lambda v: tm.mk_bv_value(self.bv32, v & M32)
        b3 = lambda v: tm.mk_bv_value(self.bv3, v)
        b5 = lambda v: tm.mk_bv_value(self.bv5, v)
        b32 = self._b32
        AND = lambda *a: T(Kd.AND, *a) if len(a) > 1 else a[0]
        OR = lambda *a: T(Kd.OR, *a) if len(a) > 1 else a[0]
        NOT = lambda a: T(Kd.NOT, a)
        IMP = lambda a, b: T(Kd.IMPLIES, a, b)
        EQ = lambda a, b: T(Kd.EQUAL, a, b)
        NE = lambda a, b: T(Kd.DISTINCT, a, b)
        ULT = lambda a, b: T(Kd.BV_ULT, a, b)
        ULE = lambda a, b: T(Kd.BV_ULE, a, b)
        self._ITE = lambda c, a, b: T(Kd.ITE, c, a, b)
        self._Kd = Kd

        cs = []
        for i in range(k):
            op, isc, w, Kc = self.op[i], self.isc[i], self.w[i], self.K[i]
            cs.append(OR(*[EQ(op, b3(o)) for o in allowed_ops]))
            nw = ninputs + i
            for j in range(3):
                cs.append(ULT(w[j], b5(nw)))
                cs.append(IMP(isc[j], EQ(w[j], b5(0))))
            is_madd = EQ(op, b3(OP_MADD))
            cs.append(
                IMP(NOT(is_madd), AND(isc[2], EQ(Kc[2], b32(0))))
            )
            cs.append(IMP(is_madd, NOT(isc[0])))
            cs.append(IMP(AND(is_madd, NOT(isc[1])), ULE(w[1], w[0])))
            cs.append(IMP(AND(is_madd, isc[1]), NE(Kc[1], b32(0))))
            cs.append(
                IMP(
                    AND(is_madd, isc[1], isc[2]),
                    NOT(AND(EQ(Kc[1], b32(1)), EQ(Kc[2], b32(0)))),
                )
            )
            for o, badK in (
                (OP_XOR, [0]),
                (OP_AND, [0, M32]),
                (OP_OR, [0, M32]),
            ):
                is_o = EQ(op, b3(o))
                cs.append(IMP(is_o, NOT(isc[0])))
                cs.append(IMP(AND(is_o, NOT(isc[1])), ULT(w[1], w[0])))
                for bk in badK:
                    cs.append(IMP(AND(is_o, isc[1]), NE(Kc[1], b32(bk))))
            is_shl = EQ(op, b3(OP_SHL))
            cs.append(IMP(is_shl, NOT(isc[1])))
            cs.append(IMP(AND(is_shl, isc[0]), NE(Kc[0], b32(0))))
            is_shr = EQ(op, b3(OP_SHR))
            cs.append(IMP(is_shr, NOT(AND(isc[0], isc[1]))))
            cs.append(
                IMP(
                    AND(is_shr, isc[1]),
                    AND(ULE(b32(1), Kc[1]), ULE(Kc[1], b32(31))),
                )
            )
            cs.append(IMP(AND(is_shr, isc[0]), NE(Kc[0], b32(0))))
        for t in range(k - 1):
            widx = ninputs + t
            uses = []
            for i in range(t + 1, k):
                for j in range(3):
                    u = AND(NOT(self.isc[i][j]), EQ(self.w[i][j], b5(widx)))
                    if j == 2:
                        u = AND(u, EQ(self.op[i], b3(OP_MADD)))
                    uses.append(u)
            cs.append(OR(*uses))
        if madds_eq is not None or madds_max is not None:
            one8 = tm.mk_bv_value(self.bv8, 1)
            zero8 = tm.mk_bv_value(self.bv8, 0)
            total = zero8
            for i in range(k):
                total = T(
                    Kd.BV_ADD,
                    total,
                    self._ITE(EQ(self.op[i], b3(OP_MADD)), one8, zero8),
                )
            if madds_eq is not None:
                cs.append(EQ(total, tm.mk_bv_value(self.bv8, madds_eq)))
            if madds_max is not None:
                cs.append(ULE(total, tm.mk_bv_value(self.bv8, madds_max)))
        if pin_first_madd:
            cs.append(EQ(self.op[0], b3(OP_MADD)))
            cs.append(AND(self.isc[0][1], self.isc[0][2]))
        if pin_last_xor:
            cs.append(EQ(self.op[k - 1], b3(OP_XOR)))
            cs.append(NOT(self.isc[k - 1][1]))
        for c in cs:
            self.solver.assert_formula(c)

    def add_example(self, inputs, expected):
        tm, T, Kd, ITE = self.tm, self._T, self._Kd, self._ITE
        b5 = lambda v: tm.mk_bv_value(self.bv5, v)
        wires = [self._b32(x) for x in inputs]
        for i in range(self.k):
            ops = []
            for j in range(3):
                mux = wires[0]
                for t in range(1, self.ninputs + i):
                    mux = ITE(T(Kd.EQUAL, self.w[i][j], b5(t)), wires[t], mux)
                ops.append(ITE(self.isc[i][j], self.K[i][j], mux))
            o0, o1, o2 = ops
            op = self.op[i]
            b3 = lambda v: tm.mk_bv_value(self.bv3, v)
            v = ITE(
                T(Kd.EQUAL, op, b3(OP_MADD)),
                T(Kd.BV_ADD, T(Kd.BV_MUL, o0, o1), o2),
                ITE(
                    T(Kd.EQUAL, op, b3(OP_XOR)),
                    T(Kd.BV_XOR, o0, o1),
                    ITE(
                        T(Kd.EQUAL, op, b3(OP_AND)),
                        T(Kd.BV_AND, o0, o1),
                        ITE(
                            T(Kd.EQUAL, op, b3(OP_OR)),
                            T(Kd.BV_OR, o0, o1),
                            ITE(
                                T(Kd.EQUAL, op, b3(OP_SHL)),
                                T(Kd.BV_SHL, o0, o1),
                                T(Kd.BV_SHR, o0, o1),
                            ),
                        ),
                    ),
                ),
            )
            wires.append(v)
        self.solver.assert_formula(
            T(Kd.EQUAL, wires[-1], self._b32(expected))
        )

    def check(self):
        r = self.solver.check_sat()
        if r == bw.Result.SAT:
            return z3.sat
        if r == bw.Result.UNSAT:
            return z3.unsat
        return z3.unknown

    def extract(self):
        def ev(t):
            v = self.solver.get_value(t).value(10)
            if isinstance(v, bool):
                return int(v)
            return int(v)

        def evb(t):
            v = self.solver.get_value(t).value(10)
            if isinstance(v, bool):
                return v
            return bool(int(v))

        prog = []
        for i in range(self.k):
            o = ev(self.op[i])
            operands = []
            nops = 3 if o == OP_MADD else 2
            for j in range(nops):
                if evb(self.isc[i][j]):
                    operands.append(("c", ev(self.K[i][j])))
                else:
                    operands.append(("w", ev(self.w[i][j])))
            prog.append((OP_NAMES[o], operands))
        return prog


def prog_str(prog, ninputs):
    names = [f"x{t}" for t in range(ninputs)]
    lines = []
    for i, (op, operands) in enumerate(prog):
        args = []
        for kind, v in operands:
            args.append(names[v] if kind == "w" else f"0x{v:08X}")
        nm = f"t{i}"
        names.append(nm)
        lines.append(f"  {nm} = {op}({', '.join(args)})")
    return "\n".join(lines)


def eval_prog_numpy(prog, xs):
    """xs: list of ninputs uint64 numpy arrays (values < 2^32)."""
    wires = list(xs)
    for op, operands in prog:
        vals = []
        for kind, v in operands:
            vals.append(wires[v] if kind == "w" else np.uint64(v))
        if op == "MADD":
            r = (vals[0] * vals[1] + vals[2]) & np.uint64(M32)
        elif op == "XOR":
            r = vals[0] ^ vals[1]
        elif op == "AND":
            r = vals[0] & vals[1]
        elif op == "OR":
            r = vals[0] | vals[1]
        elif op == "SHL":
            s = np.minimum(vals[1], np.uint64(63))
            r = np.where(vals[1] >= np.uint64(32), np.uint64(0), (vals[0] << s) & np.uint64(M32))
        elif op == "SHR":
            s = np.minimum(vals[1], np.uint64(63))
            r = np.where(vals[1] >= np.uint64(32), np.uint64(0), vals[0] >> s)
        else:
            raise ValueError(op)
        wires.append(r)
    return wires[-1]


def eval_prog_z3(prog, xs):
    wires = list(xs)
    for op, operands in prog:
        vals = []
        for kind, v in operands:
            vals.append(wires[v] if kind == "w" else z3.BitVecVal(v, 32))
        if op == "MADD":
            r = vals[0] * vals[1] + vals[2]
        elif op == "XOR":
            r = vals[0] ^ vals[1]
        elif op == "AND":
            r = vals[0] & vals[1]
        elif op == "OR":
            r = vals[0] | vals[1]
        elif op == "SHL":
            r = vals[0] << vals[1]
        elif op == "SHR":
            r = z3.LShR(vals[0], vals[1])
        else:
            raise ValueError(op)
        wires.append(r)
    return wires[-1]


STRUCTURED = [
    0, 1, 2, 3, 255, 256, 0xFFFF, 0x10000, 1 << 31, M32, 0xAAAAAAAA,
    0x55555555, C0, C1, AP, AQ, C4, C5, 0xDEADBEEF, 0x01234567,
]


def verify_candidate(prog, ninputs, py_fn, z3_fn, rng, n_random=10_000_000):
    """Return None if verified on ALL 2^32 inputs, else a counterexample
    tuple. numpy first (cheap), then an exact z3 equivalence check."""
    # structured + random battery
    chunk = 1_000_000
    structured = np.array(STRUCTURED, dtype=np.uint64)
    batches = [tuple(structured if i == 0 else
                     rng.integers(0, 1 << 32, size=len(STRUCTURED), dtype=np.uint64)
                     for i in range(ninputs))]
    done = 0
    while done < n_random:
        m = min(chunk, n_random - done)
        batches.append(
            tuple(rng.integers(0, 1 << 32, size=m, dtype=np.uint64) for _ in range(ninputs))
        )
        done += m
    for xs in batches:
        got = eval_prog_numpy(prog, xs)
        want = np.array(
            [py_fn(*(int(x[i]) for x in xs)) for i in range(len(xs[0]))],
            dtype=np.uint64,
        ) if len(xs[0]) <= len(STRUCTURED) else None
        if want is None:
            # vectorized spec via python would be slow; spec all targets are
            # compositions of numpy-expressible ops -- evaluate via the same
            # machinery using an exact reference program
            want = eval_spec_numpy(py_fn, xs)
        bad = np.nonzero(got != want)[0]
        if len(bad):
            i = int(bad[0])
            return tuple(int(x[i]) for x in xs)
    # exact: z3 equivalence over all 2^32 inputs
    s = z3.SolverFor("QF_BV")
    xs = [z3.BitVec(f"vx{t}", 32) for t in range(ninputs)]
    s.add(eval_prog_z3(prog, xs) != z3_fn(*xs))
    r = s.check()
    if r == z3.unsat:
        return None
    if r == z3.sat:
        m = s.model()
        return tuple(
            m.eval(x, model_completion=True).as_long() for x in xs
        )
    raise RuntimeError("z3 verify returned unknown")


_SPEC_NUMPY_CACHE = {}


def eval_spec_numpy(py_fn, xs):
    """Vectorized spec evaluation: all specs are compositions over uint64
    numpy arrays of +,*,^,>>,& M32 -- the python spec functions work
    directly on numpy arrays as long as we mask; they only use int ops."""
    outs = py_fn(*[x.astype(np.uint64) for x in xs])
    return outs & np.uint64(M32)


def run_cegis(args):
    ninputs, cur_ops, py_fn, z3_fn = TARGETS[args.target]
    allowed = list(range(6))
    if args.ops:
        allowed = [OP_NAMES.index(o) for o in args.ops.split(",")]
    if args.backend == "bitwuzla":
        enc = BwEncoding(
            args.k,
            ninputs,
            allowed,
            madds_eq=args.madds_eq,
            madds_max=args.madds_max,
            pin_first_madd=args.pin_first_madd,
            pin_last_xor=args.pin_last_xor,
            timeout_ms=args.timeout,
            seed=args.seed + 1,
            bv_solver=args.bv_solver,
        )
        add_example = enc.add_example
        check = enc.check
        get_prog = enc.extract
    else:
        enc = Encoding(
            args.k,
            ninputs,
            allowed,
            madds_eq=args.madds_eq,
            madds_max=args.madds_max,
            pin_first_madd=args.pin_first_madd,
            pin_last_xor=args.pin_last_xor,
        )
        z3.set_param("sat.random_seed", args.seed)
        z3.set_param("smt.random_seed", args.seed)
        s = z3.SolverFor("QF_BV")
        if args.timeout:
            s.set("timeout", args.timeout)
        s.add(enc.structural)
        add_example = lambda ex, out: s.add(
            enc.slot_values(list(ex))[-1] == out
        )
        check = s.check
        get_prog = lambda: enc.extract(s.model())
    rng = np.random.default_rng(args.seed)
    prng = random.Random(args.seed)
    examples = []
    for v in STRUCTURED[: args.init_structured]:
        examples.append(tuple([v] + [prng.randrange(1 << 32) for _ in range(ninputs - 1)]))
    for _ in range(args.init_random):
        examples.append(tuple(prng.randrange(1 << 32) for _ in range(ninputs)))

    for ex in examples:
        add_example(ex, py_fn(*ex))

    t0 = time.time()
    result = {
        "target": args.target,
        "k": args.k,
        "current_ops": cur_ops,
        "madds_eq": args.madds_eq,
        "madds_max": args.madds_max,
        "ops": args.ops,
        "pin_first_madd": args.pin_first_madd,
        "pin_last_xor": args.pin_last_xor,
        "seed": args.seed,
        "backend": args.backend,
        "bv_solver": args.bv_solver,
        "iters": 0,
    }
    it = 0
    while True:
        it += 1
        if args.wall and time.time() - t0 > args.wall:
            result.update(status="WALL_TIMEOUT", examples=len(examples), wall=round(time.time() - t0, 1), iters=it - 1)
            break
        tc = time.time()
        r = check()
        dt = time.time() - tc
        print(
            f"[{args.target} k={args.k}] iter {it}: check={r} in {dt:.1f}s "
            f"({len(examples)} examples)",
            flush=True,
        )
        if r == z3.unsat:
            result.update(status="UNSAT_CERTIFICATE", examples=len(examples), wall=round(time.time() - t0, 1), iters=it)
            break
        if r == z3.unknown:
            result.update(status="UNKNOWN_TIMEOUT", examples=len(examples), wall=round(time.time() - t0, 1), iters=it)
            break
        prog = get_prog()
        print(prog_str(prog, ninputs), flush=True)
        cex = verify_candidate(prog, ninputs, py_fn, z3_fn, rng)
        if cex is None:
            result.update(
                status="HIT_VERIFIED_ALL_2^32",
                examples=len(examples),
                wall=round(time.time() - t0, 1),
                iters=it,
                program=prog,
            )
            break
        print(f"  counterexample: {tuple(hex(c) for c in cex)}", flush=True)
        examples.append(cex)
        add_example(cex, py_fn(*cex))
    print("RESULT " + json.dumps(result), flush=True)
    return result


def selftest():
    """Calibration: the encoding must (1) rediscover known-length programs
    (SAT+verify), (2) reproduce a known tiny negative, (3) numpy/z3 spec
    agreement with problem.py's myhash."""
    sys.path.insert(0, ".")
    import problem as pb

    prng = random.Random(1)
    for _ in range(2000):
        a = prng.randrange(1 << 32)
        assert full(a) == pb.myhash(a), "fused spec != problem.myhash"
    # numpy spec path agrees with python ints
    xs = np.array([prng.randrange(1 << 32) for _ in range(1000)], dtype=np.uint64)
    want = np.array([full(int(v)) for v in xs], dtype=np.uint64)
    got = eval_spec_numpy(full, (xs,))
    assert np.array_equal(got, want), "numpy spec mismatch"
    print("spec cross-checks OK", flush=True)

    class A:
        pass

    def mk(target, k, **kw):
        a = A()
        a.target, a.k = target, k
        a.madds_eq = kw.get("madds_eq")
        a.madds_max = kw.get("madds_max")
        a.ops = kw.get("ops")
        a.pin_first_madd = kw.get("pin_first_madd", False)
        a.pin_last_xor = kw.get("pin_last_xor", False)
        a.seed = kw.get("seed", 7)
        a.timeout = kw.get("timeout", 600000)
        a.wall = kw.get("wall", 1800)
        a.init_structured = kw.get("init_structured", 4)
        a.init_random = kw.get("init_random", 4)
        a.backend = kw.get("backend", "bitwuzla" if bw else "z3")
        a.bv_solver = kw.get("bv_solver", "bitblast")
        return a

    # (1) SAT at known length: f23 in 3 ops (the stage2+3 fusion exists)
    r = run_cegis(mk("f23", 3))
    assert r["status"] == "HIT_VERIFIED_ALL_2^32", r
    # (2) SAT at known length: s45 in 4 ops
    r = run_cegis(mk("s45", 4))
    assert r["status"] == "HIT_VERIFIED_ALL_2^32", r
    # (3) tiny UNSAT: stage5 in 1 op
    r = run_cegis(mk("stage5", 1))
    assert r["status"] == "UNSAT_CERTIFICATE", r
    print("SELFTEST PASS", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--target", choices=sorted(TARGETS))
    p.add_argument("--k", type=int)
    p.add_argument("--madds-eq", type=int, default=None)
    p.add_argument("--madds-max", type=int, default=None)
    p.add_argument("--ops", default=None, help="comma list, e.g. MADD,XOR,SHR")
    p.add_argument("--pin-first-madd", action="store_true")
    p.add_argument("--pin-last-xor", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--timeout", type=int, default=1_200_000, help="per-check ms")
    p.add_argument("--wall", type=int, default=3600, help="total budget sec")
    p.add_argument("--init-structured", type=int, default=4)
    p.add_argument("--init-random", type=int, default=4)
    p.add_argument(
        "--backend",
        choices=["z3", "bitwuzla"],
        default="bitwuzla" if bw else "z3",
    )
    p.add_argument(
        "--bv-solver",
        choices=["bitblast", "prop", "preprop"],
        default="bitblast",
        help="bitwuzla core; prop/preprop are SAT-hunting only",
    )
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.target or not args.k:
        p.error("--target and --k required")
    run_cegis(args)


if __name__ == "__main__":
    main()
