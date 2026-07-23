//! H-003: machine search for hash fusions beyond the 11-mixing-op form.
//!
//! Exhaustive-in-pool superoptimizer over straight-line programs built from
//! the machine's actual ops — `multiply_add(a,b,c)` (32-bit wrap, valu-only)
//! and the alu binaries `add, sub, mul, xor, and, or, shl, shr` — searching
//! for shorter programs bit-identical to segments of the fused `myhash`
//! chain (see `problem::hashseg` for the cut points):
//!
//!   a -1op-> b -3op-> c -3op-> d -1op-> e -3op-> out   (+ fold-in, + &1)
//!
//! Search space per target, stated precisely (this is what "exhaustive"
//! means below — anything outside it is NOT ruled out):
//!   * programs of exactly k ops for k = 1 .. kmax (iterative deepening);
//!   * every op's operands are the target's inputs, previous results, or
//!     constants from the target's POOL (listed per target), EXCEPT the
//!     final op, where xor/add/sub/and/or-constants, shift amounts, and
//!     multiply_add's (K, C) are SOLVED over all 2^32 values from the probe
//!     set instead of pooled;
//!   * ops whose operands are all constants are skipped (a derived constant
//!     outside the pool used >= 2 times is not covered);
//!   * candidates equal to an existing value on all 32 probes are pruned as
//!     duplicates (probabilistic identity: distinct functions colliding on
//!     all probes would be pruned — probes include structured patterns to
//!     make this astronomically unlikely, but it is not a formal proof);
//!   * div/mod/lt/eq are excluded (lt/eq produce 0/1 booleans; div-family
//!     costs the same slot and traps on 0 — neither can shorten a full-width
//!     mixing chain they'd still have to feed through the remaining ops).
//!
//! Every reported find is re-verified against the reference segment function
//! on 10M+ random and structured inputs before it is printed as VERIFIED.
//!
//! H-016 adds a meet-in-the-middle mode (`--mitm`) that reaches one op-depth
//! further than the forward-only search on selected boundary questions; see
//! the "meet-in-the-middle extension" section below for the exact space it
//! covers (and does not cover).
//!
//! Usage:
//!   fusion_search              # standard suite (all depth<=3 questions)
//!   fusion_search --long       # adds the two depth-4 two-input searches
//!   fusion_search g45 par_d    # run specific targets by name
//!   fusion_search --mitm       # H-016 MITM suite (6->5 boundary questions)
//!   fusion_search --mitm --stretch   # + interior 7-op spans at k<=6
//!   fusion_search --mitm b2d   # run specific MITM targets by name

use perf_harness::problem::hashseg as hs;
use perf_harness::problem::{myhash, Rng};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Instant;

/// Probe count: every candidate value is this many parallel evaluations.
const P: usize = 32;
type Vp = [u32; P];

#[derive(Copy, Clone, Debug, PartialEq, Eq)]
enum Op {
    Add,
    Sub,
    Mul,
    Xor,
    And,
    Or,
    Shl,
    Shr,
}
use Op::*;

const BIN_OPS: [Op; 8] = [Add, Sub, Mul, Xor, And, Or, Shl, Shr];

impl Op {
    fn commutative(self) -> bool {
        matches!(self, Add | Mul | Xor | And | Or)
    }
    fn name(self) -> &'static str {
        match self {
            Add => "add",
            Sub => "sub",
            Mul => "mul",
            Xor => "xor",
            And => "and",
            Or => "or",
            Shl => "shl",
            Shr => "shr",
        }
    }
}

/// Bit-exact `Machine.alu` semantics (mod 2^32; shifts >= 32 give 0).
#[inline(always)]
fn bin(op: Op, a: u32, b: u32) -> u32 {
    match op {
        Add => a.wrapping_add(b),
        Sub => a.wrapping_sub(b),
        Mul => a.wrapping_mul(b),
        Xor => a ^ b,
        And => a & b,
        Or => a | b,
        Shl => {
            if b >= 32 {
                0
            } else {
                a << b
            }
        }
        Shr => {
            if b >= 32 {
                0
            } else {
                a >> b
            }
        }
    }
}

/// Bit-exact `ValuSlot::MultiplyAdd`: (a*b + c) mod 2^32.
#[inline(always)]
fn mad(a: u32, b: u32, c: u32) -> u32 {
    a.wrapping_mul(b).wrapping_add(c)
}

/// Inverse of an odd u32 mod 2^32 (Newton iteration).
fn modinv32(a: u32) -> u32 {
    debug_assert!(a & 1 == 1);
    let mut x = 1u32;
    for _ in 0..5 {
        x = x.wrapping_mul(2u32.wrapping_sub(a.wrapping_mul(x)));
    }
    x
}

/// One instruction of a candidate program. Operand `usize`s index the value
/// pool (inputs, then pool constants, then temps in order). The *C variants
/// carry constants solved at the final level (not drawn from the pool).
#[derive(Clone, Debug)]
enum Inst {
    Bin(Op, usize, usize),
    Mad(usize, usize, usize),
    /// op(pool[i], c) with solved constant c.
    BinC(Op, usize, u32),
    /// op(c, pool[i]) with solved constant c (non-commutative right forms).
    CBin(Op, u32, usize),
    /// pool[i] * pool[j] + c.
    MadC(usize, usize, u32),
    /// pool[i] * K + C.
    MadKC(usize, u32, u32),
}

/// A reference target function evaluated on an input tuple.
type TargetFn = dyn Fn(&[u32]) -> u32 + Sync;

struct Ctx<'a> {
    n_inputs: usize,
    base_names: Vec<String>,
    base_vals: Vec<Vp>,
    base_is_const: Vec<bool>,
    target: Vp,
    /// complete candidate programs checked (final-level checks).
    tested: AtomicU64,
    stop: AtomicBool,
    finds: Mutex<Vec<Vec<Inst>>>,
    /// final-level constant solves skipped for lack of an odd pivot.
    unsolved: AtomicU64,
    f: &'a TargetFn,
}

/// Per-thread mutable search state.
struct W {
    vals: Vec<Vp>,
    p0: Vec<u32>,
    is_const: Vec<bool>,
    /// per-temp "has been referenced" flags (parallel to temps only).
    temp_used: Vec<bool>,
    unused_cnt: usize,
    prog: Vec<Inst>,
    n_base: usize,
    tested_local: u64,
}

impl W {
    fn new(ctx: &Ctx) -> W {
        W {
            vals: ctx.base_vals.clone(),
            p0: ctx.base_vals.iter().map(|v| v[0]).collect(),
            is_const: ctx.base_is_const.clone(),
            temp_used: Vec::new(),
            unused_cnt: 0,
            prog: Vec::new(),
            n_base: ctx.base_vals.len(),
            tested_local: 0,
        }
    }

    /// Mark operand as referenced; returns true if it was an unused temp
    /// (so pop can undo).
    fn mark(&mut self, idx: usize) -> bool {
        if idx >= self.n_base && !self.temp_used[idx - self.n_base] {
            self.temp_used[idx - self.n_base] = true;
            self.unused_cnt -= 1;
            true
        } else {
            false
        }
    }

    fn push(&mut self, inst: Inst, v: Vp) -> [bool; 3] {
        let mut undo = [false; 3];
        match inst {
            Inst::Bin(_, i, j) => {
                undo[0] = self.mark(i);
                if j != i {
                    undo[1] = self.mark(j);
                }
            }
            Inst::Mad(i, j, k) => {
                undo[0] = self.mark(i);
                if j != i {
                    undo[1] = self.mark(j);
                }
                if k != i && k != j {
                    undo[2] = self.mark(k);
                }
            }
            _ => unreachable!("solved-const insts are final-level only"),
        }
        self.prog.push(inst);
        self.vals.push(v);
        self.p0.push(v[0]);
        self.is_const.push(false);
        self.temp_used.push(false);
        self.unused_cnt += 1;
        undo
    }

    fn pop(&mut self, undo: [bool; 3]) {
        let inst = self.prog.pop().unwrap();
        self.vals.pop();
        self.p0.pop();
        self.is_const.pop();
        self.temp_used.pop();
        self.unused_cnt -= 1;
        let ops: [usize; 3] = match inst {
            Inst::Bin(_, i, j) => [i, j, usize::MAX],
            Inst::Mad(i, j, k) => [i, j, k],
            _ => unreachable!(),
        };
        for (n, &o) in ops.iter().enumerate() {
            if undo[n] {
                self.temp_used[o - self.n_base] = false;
                self.unused_cnt += 1;
            }
        }
    }

    /// Is `v` (with first probe `v0`) identical on all probes to an existing
    /// pool value? (Duplicate pruning.)
    fn is_dup(&self, v0: u32, v: &Vp) -> bool {
        for (i, &p0) in self.p0.iter().enumerate() {
            if p0 == v0 && &self.vals[i] == v {
                return true;
            }
        }
        false
    }

    /// Indices of temps not yet referenced by any later op.
    fn unused_list(&self) -> Vec<usize> {
        (0..self.temp_used.len())
            .filter(|&t| !self.temp_used[t])
            .map(|t| t + self.n_base)
            .collect()
    }
}

fn eval_bin(op: Op, a: &Vp, b: &Vp) -> Vp {
    let mut out = [0u32; P];
    for p in 0..P {
        out[p] = bin(op, a[p], b[p]);
    }
    out
}

fn eval_mad(a: &Vp, b: &Vp, c: &Vp) -> Vp {
    let mut out = [0u32; P];
    for p in 0..P {
        out[p] = mad(a[p], b[p], c[p]);
    }
    out
}

/// Enumerate every candidate instruction over the current pool (dedup'd,
/// const-const skipped, commutative ops canonicalized) and call `f`.
fn enumerate_level(w: &W, mut f: impl FnMut(Inst, Vp)) {
    let n = w.vals.len();
    for &op in BIN_OPS.iter() {
        for i in 0..n {
            let j0 = if op.commutative() { i } else { 0 };
            for j in j0..n {
                if w.is_const[i] && w.is_const[j] {
                    continue;
                }
                if op == Sub && i == j {
                    continue;
                }
                let v0 = bin(op, w.p0[i], w.p0[j]);
                let v = eval_bin(op, &w.vals[i], &w.vals[j]);
                if w.is_dup(v0, &v) {
                    continue;
                }
                f(Inst::Bin(op, i, j), v);
            }
        }
    }
    for i in 0..n {
        for j in i..n {
            for k in 0..n {
                if w.is_const[i] && w.is_const[j] && w.is_const[k] {
                    continue;
                }
                let v0 = mad(w.p0[i], w.p0[j], w.p0[k]);
                let v = eval_mad(&w.vals[i], &w.vals[j], &w.vals[k]);
                if w.is_dup(v0, &v) {
                    continue;
                }
                f(Inst::Mad(i, j, k), v);
            }
        }
    }
}

fn dfs(ctx: &Ctx, w: &mut W, rem: usize) {
    if ctx.stop.load(Ordering::Relaxed) {
        return;
    }
    // Every temp must eventually be referenced: r remaining ops can consume
    // at most 3 operands each, and all but the last create one more value
    // needing a reference. Prune when that's impossible.
    if w.unused_cnt > 2 * rem + 1 {
        return;
    }
    if rem == 1 {
        final_level(ctx, w);
        return;
    }
    let mut cands: Vec<(Inst, Vp)> = Vec::with_capacity(4096);
    enumerate_level(w, |inst, v| cands.push((inst, v)));
    for (inst, v) in cands {
        if ctx.stop.load(Ordering::Relaxed) {
            return;
        }
        let undo = w.push(inst, v);
        dfs(ctx, w, rem - 1);
        w.pop(undo);
    }
}

/// Depth-1 remaining: enumerate/solve the final op against the target.
fn final_level(ctx: &Ctx, w: &mut W) {
    let unused = w.unused_list();
    if unused.len() > 3 {
        return;
    }
    let t = &ctx.target;
    let t0 = t[0];
    let n = w.vals.len();

    let covers2 = |i: usize, j: usize| unused.iter().all(|&u| u == i || u == j);
    let covers3 = |i: usize, j: usize, k: usize| unused.iter().all(|&u| u == i || u == j || u == k);

    // ---- pooled operands ----
    for &op in BIN_OPS.iter() {
        for i in 0..n {
            let j0 = if op.commutative() { i } else { 0 };
            for j in j0..n {
                if w.is_const[i] && w.is_const[j] {
                    continue;
                }
                w.tested_local += 1;
                if bin(op, w.p0[i], w.p0[j]) != t0 || !covers2(i, j) {
                    continue;
                }
                if (0..P).all(|p| bin(op, w.vals[i][p], w.vals[j][p]) == t[p]) {
                    report(ctx, w, Inst::Bin(op, i, j));
                }
            }
        }
    }
    for i in 0..n {
        for j in i..n {
            for k in 0..n {
                if w.is_const[i] && w.is_const[j] && w.is_const[k] {
                    continue;
                }
                w.tested_local += 1;
                if mad(w.p0[i], w.p0[j], w.p0[k]) != t0 || !covers3(i, j, k) {
                    continue;
                }
                if (0..P).all(|p| mad(w.vals[i][p], w.vals[j][p], w.vals[k][p]) == t[p]) {
                    report(ctx, w, Inst::Mad(i, j, k));
                }
            }
        }
    }

    // ---- solved-constant forms (one non-const pool operand x) ----
    for i in 0..n {
        if w.is_const[i] {
            continue;
        }
        if !unused.iter().all(|&u| u == i) {
            continue; // solved forms use only x; all unused temps must be x
        }
        let x = &w.vals[i];

        // xor / add / sub (both orders): c determined by probe 0.
        let c = t0 ^ x[0];
        w.tested_local += 1;
        if (0..P).all(|p| (x[p] ^ c) == t[p]) {
            report(ctx, w, Inst::BinC(Xor, i, c));
        }
        let c = t0.wrapping_sub(x[0]);
        w.tested_local += 1;
        if (0..P).all(|p| x[p].wrapping_add(c) == t[p]) {
            report(ctx, w, Inst::BinC(Add, i, c));
        }
        let c = x[0].wrapping_sub(t0);
        w.tested_local += 1;
        if (0..P).all(|p| x[p].wrapping_sub(c) == t[p]) {
            report(ctx, w, Inst::BinC(Sub, i, c));
        }
        let c = t0.wrapping_add(x[0]);
        w.tested_local += 1;
        if (0..P).all(|p| c.wrapping_sub(x[p]) == t[p]) {
            report(ctx, w, Inst::CBin(Sub, c, i));
        }

        // and / or: bitwise-solved constant.
        let mut c_and = 0u32;
        for p in 0..P {
            c_and |= x[p] & t[p];
        }
        w.tested_local += 1;
        if (0..P).all(|p| (x[p] & c_and) == t[p]) {
            report(ctx, w, Inst::BinC(And, i, c_and));
        }
        let mut c_or = 0u32;
        for p in 0..P {
            c_or |= t[p] & !x[p];
        }
        w.tested_local += 1;
        if (0..P).all(|p| (x[p] | c_or) == t[p]) {
            report(ctx, w, Inst::BinC(Or, i, c_or));
        }

        // shl / shr by any amount 0..31.
        for s in 0..32u32 {
            w.tested_local += 2;
            if (x[0] << s) == t0 && (0..P).all(|p| (x[p] << s) == t[p]) {
                report(ctx, w, Inst::BinC(Shl, i, s));
            }
            if (x[0] >> s) == t0 && (0..P).all(|p| (x[p] >> s) == t[p]) {
                report(ctx, w, Inst::BinC(Shr, i, s));
            }
        }

        // multiply_add x*K + C with both K and C solved: pick a probe pair
        // with odd difference (K then unique), C follows.
        let mut solved = false;
        'pairs: for p in 0..P {
            for q in (p + 1)..P {
                let dx = x[p].wrapping_sub(x[q]);
                if dx & 1 == 1 {
                    let dt = t[p].wrapping_sub(t[q]);
                    let k = dt.wrapping_mul(modinv32(dx));
                    let c = t[p].wrapping_sub(k.wrapping_mul(x[p]));
                    w.tested_local += 1;
                    if (0..P).all(|r| mad(x[r], k, c) == t[r]) {
                        report(ctx, w, Inst::MadKC(i, k, c));
                    }
                    solved = true;
                    break 'pairs;
                }
            }
        }
        if !solved {
            ctx.unsolved.fetch_add(1, Ordering::Relaxed);
        }
    }

    // multiply_add pool[i]*pool[j] + solved C.
    for i in 0..n {
        for j in i..n {
            if w.is_const[i] && w.is_const[j] {
                continue;
            }
            if !covers2(i, j) {
                continue;
            }
            let c = t0.wrapping_sub(w.p0[i].wrapping_mul(w.p0[j]));
            w.tested_local += 1;
            if (0..P).all(|p| mad(w.vals[i][p], w.vals[j][p], c) == t[p]) {
                report(ctx, w, Inst::MadC(i, j, c));
            }
        }
    }
}

/// A candidate matched all probes: verify against the reference function on
/// 10M+ inputs, then record + print.
fn report(ctx: &Ctx, w: &W, last: Inst) {
    let mut prog = w.prog.clone();
    prog.push(last);
    report_prog(ctx, prog);
}

/// `report` for a fully-assembled program (used by the MITM engines, whose
/// candidates are stitched from forward + meet + suffix-chain parts).
fn report_prog(ctx: &Ctx, prog: Vec<Inst>) {
    let ok = verify(ctx, &prog);
    let txt = render(ctx, &prog);
    println!(
        "  >>> {} candidate ({} ops): {}",
        if ok {
            "VERIFIED"
        } else {
            "FALSE-POSITIVE (probe collision)"
        },
        prog.len(),
        txt
    );
    if ok {
        let mut finds = ctx.finds.lock().unwrap();
        finds.push(prog);
        if finds.len() >= 8 {
            ctx.stop.store(true, Ordering::Relaxed);
        }
    }
}

/// Execute `prog` on concrete inputs (base constants from ctx).
fn run_prog(ctx: &Ctx, prog: &[Inst], inputs: &[u32]) -> u32 {
    let n_base = ctx.base_vals.len();
    let mut vals: Vec<u32> = Vec::with_capacity(n_base + prog.len());
    vals.extend_from_slice(inputs);
    for b in ctx.n_inputs..n_base {
        vals.push(ctx.base_vals[b][0]); // constants are probe-invariant
    }
    for inst in prog {
        let v = match *inst {
            Inst::Bin(op, i, j) => bin(op, vals[i], vals[j]),
            Inst::Mad(i, j, k) => mad(vals[i], vals[j], vals[k]),
            Inst::BinC(op, i, c) => bin(op, vals[i], c),
            Inst::CBin(op, c, i) => bin(op, c, vals[i]),
            Inst::MadC(i, j, c) => mad(vals[i], vals[j], c),
            Inst::MadKC(i, k, c) => mad(vals[i], k, c),
        };
        vals.push(v);
    }
    *vals.last().unwrap()
}

/// 10M random + structured inputs, bit-exact against the reference closure.
fn verify(ctx: &Ctx, prog: &[Inst]) -> bool {
    let mut rng = Rng::new(0xF00D_BEEF);
    let structured: Vec<u32> = vec![
        0,
        1,
        2,
        3,
        255,
        256,
        0xFFFF_FFFF,
        0x8000_0000,
        0x7FFF_FFFF,
        0xAAAA_AAAA,
        0x5555_5555,
        0xFFFF_0000,
        0x0000_FFFF,
        0x0001_0001,
        0xDEAD_BEEF,
        0x0F0F_0F0F,
    ];
    let check = |ins: &[u32]| run_prog(ctx, prog, ins) == (ctx.f)(ins);
    match ctx.n_inputs {
        1 => {
            for &s in &structured {
                if !check(&[s]) {
                    return false;
                }
            }
            for i in 0..(1u32 << 20) {
                if !check(&[i]) {
                    return false;
                }
            }
            for _ in 0..10_000_000 {
                if !check(&[rng.next_u64() as u32]) {
                    return false;
                }
            }
        }
        2 => {
            for &s in &structured {
                for &u in &structured {
                    if !check(&[s, u]) {
                        return false;
                    }
                }
            }
            for _ in 0..10_000_000 {
                if !check(&[rng.next_u64() as u32, rng.next_u64() as u32]) {
                    return false;
                }
            }
        }
        _ => unreachable!(),
    }
    true
}

fn render(ctx: &Ctx, prog: &[Inst]) -> String {
    let n_base = ctx.base_vals.len();
    let name = |idx: usize, ctx: &Ctx| -> String {
        if idx < n_base {
            ctx.base_names[idx].clone()
        } else {
            format!("t{}", idx - n_base + 1)
        }
    };
    let mut out = String::new();
    for (i, inst) in prog.iter().enumerate() {
        let lhs = if i + 1 == prog.len() {
            "out".to_string()
        } else {
            format!("t{}", i + 1)
        };
        let rhs = match *inst {
            Inst::Bin(op, a, b) => format!("{}({}, {})", op.name(), name(a, ctx), name(b, ctx)),
            Inst::Mad(a, b, c) => {
                format!("madd({}, {}, {})", name(a, ctx), name(b, ctx), name(c, ctx))
            }
            Inst::BinC(op, a, c) => format!("{}({}, {:#010x})", op.name(), name(a, ctx), c),
            Inst::CBin(op, c, a) => format!("{}({:#010x}, {})", op.name(), c, name(a, ctx)),
            Inst::MadC(a, b, c) => format!("madd({}, {}, {:#010x})", name(a, ctx), name(b, ctx), c),
            Inst::MadKC(a, k, c) => {
                format!("madd({}, {:#010x}, {:#010x})", name(a, ctx), k, c)
            }
        };
        out.push_str(&format!("{lhs} = {rhs}; "));
    }
    out
}

// ---------------------------------------------------------------------------
// Targets
// ---------------------------------------------------------------------------

struct Target {
    name: &'static str,
    desc: &'static str,
    n_inputs: usize,
    consts: Vec<(&'static str, u32)>,
    kmax: usize,
    current_ops: usize,
    f: Box<TargetFn>,
    long: bool,
}

fn probes(n_inputs: usize) -> Vec<Vec<u32>> {
    let structured: [u32; 14] = [
        0,
        1,
        2,
        3,
        255,
        0xFFFF_FFFF,
        0x8000_0000,
        0x7FFF_FFFF,
        0xAAAA_AAAA,
        0x5555_5555,
        0xFFFF_0000,
        0x0000_FFFF,
        0x0001_0001,
        0xDEAD_BEEF,
    ];
    let mut rng = Rng::new(0x5EED_CAFE);
    let mut out = Vec::with_capacity(P);
    for p in 0..P {
        let mut tup = Vec::with_capacity(n_inputs);
        for k in 0..n_inputs {
            // First rows pair structured values with randoms so single-input
            // structure is exercised; later rows are fully random.
            let v = if p < structured.len() && k == p % n_inputs.max(1) {
                structured[p]
            } else {
                rng.next_u64() as u32
            };
            tup.push(v);
        }
        out.push(tup);
    }
    out
}

fn run_target(tg: &Target, threads: usize) {
    let probes = probes(tg.n_inputs);
    let mut base_names: Vec<String> = Vec::new();
    let mut base_vals: Vec<Vp> = Vec::new();
    let mut base_is_const: Vec<bool> = Vec::new();
    let input_names = ["x", "y"];
    for k in 0..tg.n_inputs {
        base_names.push(input_names[k].to_string());
        let mut v = [0u32; P];
        for (p, tup) in probes.iter().enumerate() {
            v[p] = tup[k];
        }
        base_vals.push(v);
        base_is_const.push(false);
    }
    for (nm, c) in &tg.consts {
        base_names.push(format!("{nm}={c:#010x}"));
        base_vals.push([*c; P]);
        base_is_const.push(true);
    }
    let mut target = [0u32; P];
    for (p, tup) in probes.iter().enumerate() {
        target[p] = (tg.f)(tup);
    }

    println!(
        "== target {} : {} (current {} ops, searching k<= {}) ==",
        tg.name, tg.desc, tg.current_ops, tg.kmax
    );
    println!(
        "   pool: [{}]",
        base_names
            .iter()
            .skip(tg.n_inputs)
            .cloned()
            .collect::<Vec<_>>()
            .join(", ")
    );

    let ctx = Ctx {
        n_inputs: tg.n_inputs,
        base_names,
        base_vals,
        base_is_const,
        target,
        tested: AtomicU64::new(0),
        stop: AtomicBool::new(false),
        finds: Mutex::new(Vec::new()),
        unsolved: AtomicU64::new(0),
        f: &*tg.f,
    };

    // k = 0: target already available?
    for (i, v) in ctx.base_vals.iter().enumerate() {
        if *v == target {
            println!("   !! target equals base value {}", ctx.base_names[i]);
        }
    }

    let t_start = Instant::now();
    search_iterative(&ctx, tg.kmax, threads);

    let finds = ctx.finds.lock().unwrap();
    let unsolved = ctx.unsolved.load(Ordering::Relaxed);
    if finds.is_empty() {
        println!(
            "   RESULT: no program of <= {} ops within this space ({} candidates, {:.1}s{})",
            tg.kmax,
            ctx.tested.load(Ordering::Relaxed),
            t_start.elapsed().as_secs_f64(),
            if unsolved > 0 {
                format!(", {unsolved} madd-K solves skipped: no odd pivot")
            } else {
                String::new()
            }
        );
        println!(
            "   => current {}-op form stands within the searched space\n",
            tg.current_ops
        );
    } else {
        println!(
            "   RESULT: {} verified shorter program(s) found ({} ops < current {})\n",
            finds.len(),
            finds[0].len(),
            tg.current_ops
        );
    }
}

/// The forward-only iterative-deepening search (k = 1..=kmax, exhaustive per
/// k within the ctx's pool): forward DFS to depth k-1 + solved final level.
/// Shared by the legacy suite (`run_target`) and the MITM runner's engine A.
fn search_iterative(ctx: &Ctx, kmax: usize, threads: usize) {
    for k in 1..=kmax {
        if !ctx.finds.lock().unwrap().is_empty() {
            break; // already found something shorter at k-1
        }
        let k_start = Instant::now();
        if k == 1 {
            let mut w = W::new(ctx);
            final_level(ctx, &mut w);
            ctx.tested.fetch_add(w.tested_local, Ordering::Relaxed);
        } else {
            // Thread over first-level candidates.
            let mut l1: Vec<(Inst, Vp)> = Vec::new();
            {
                let w = W::new(ctx);
                enumerate_level(&w, |inst, v| l1.push((inst, v)));
            }
            let next = AtomicU64::new(0);
            std::thread::scope(|scope| {
                for _ in 0..threads {
                    scope.spawn(|| {
                        let mut w = W::new(ctx);
                        loop {
                            let idx = next.fetch_add(1, Ordering::Relaxed) as usize;
                            if idx >= l1.len() || ctx.stop.load(Ordering::Relaxed) {
                                break;
                            }
                            let (inst, v) = l1[idx].clone();
                            let undo = w.push(inst, v);
                            dfs(ctx, &mut w, k - 1);
                            w.pop(undo);
                        }
                        ctx.tested.fetch_add(w.tested_local, Ordering::Relaxed);
                    });
                }
            });
        }
        println!(
            "   k={k}: exhausted in {:.1}s (cumulative candidates tested: {})",
            k_start.elapsed().as_secs_f64(),
            ctx.tested.load(Ordering::Relaxed)
        );
    }
}

fn targets() -> Vec<Target> {
    use hs::*;
    let common = [("zero", 0u32), ("one", 1u32), ("m1", 0xFFFF_FFFF)];
    let mk = |extra: &[(&'static str, u32)]| -> Vec<(&'static str, u32)> {
        common.iter().chain(extra.iter()).cloned().collect()
    };
    vec![
        Target {
            name: "full",
            desc: "entire 6-stage myhash",
            n_inputs: 1,
            consts: mk(&[
                ("C0", C0),
                ("C1", C1),
                ("K0", K0),
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("K4", K4),
                ("C4", C4),
                ("C5", C5),
                ("sh1", 19),
                ("sh5", 16),
                ("s12", 12),
            ]),
            kmax: 3,
            current_ops: 11,
            f: Box::new(|x| myhash(x[0])),
            long: false,
        },
        Target {
            name: "g01",
            desc: "stage1(stage0(a)) [madd,shr,xor,xor]",
            n_inputs: 1,
            consts: mk(&[
                ("C0", C0),
                ("C1", C1),
                ("K0", K0),
                ("p12", 4096),
                ("s12", 12),
                ("sh1", 19),
                ("C1s", C1 >> 19),
                ("C1i", C1 ^ (C1 >> 19)),
                ("C0x1", C0 ^ C1),
            ]),
            kmax: 3,
            current_ops: 4,
            f: Box::new(|x| hs::stage1(hs::stage0(x[0]))),
            long: false,
        },
        Target {
            name: "a2u",
            desc: "sigma19(stage0(a)) (pre-C1 point) [madd,shr,xor]",
            n_inputs: 1,
            consts: mk(&[
                ("C0", C0),
                ("K0", K0),
                ("p12", 4096),
                ("s12", 12),
                ("sh1", 19),
                ("p19", 1 << 19),
            ]),
            kmax: 2,
            current_ops: 3,
            f: Box::new(|x| {
                let b = hs::stage0(x[0]);
                b ^ (b >> 19)
            }),
            long: false,
        },
        Target {
            name: "b2c",
            desc: "stage1 alone [shr,xor,xor]",
            n_inputs: 1,
            consts: mk(&[
                ("C1", C1),
                ("sh1", 19),
                ("C1s", C1 >> 19),
                ("C1i", C1 ^ (C1 >> 19)),
                ("p19", 1 << 19),
                ("p13", 1 << 13),
                ("s13", 13),
            ]),
            kmax: 2,
            current_ops: 3,
            f: Box::new(|x| hs::stage1(x[0])),
            long: false,
        },
        Target {
            name: "g123mid",
            desc: "f23(u ^ C1) (stage1 tail + fused23) [xor,madd,madd,xor]",
            n_inputs: 1,
            consts: mk(&[
                ("C1", C1),
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("KPC1", KP.wrapping_mul(C1)),
                ("KQC1", KQ.wrapping_mul(C1)),
                ("APK", AP.wrapping_add(KP.wrapping_mul(C1))),
                ("AQK", AQ.wrapping_add(KQ.wrapping_mul(C1))),
                ("s5", 5),
                ("s9", 9),
            ]),
            kmax: 3,
            current_ops: 4,
            f: Box::new(|x| hs::f23(x[0] ^ hs::C1)),
            long: false,
        },
        Target {
            name: "f23",
            desc: "fused stage2+3 [madd,madd,xor]",
            n_inputs: 1,
            consts: mk(&[
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("C2", 0x1656_67B1),
                ("C3", 0xD3A2_646C),
                ("s5", 5),
                ("s9", 9),
                ("p9", 512),
            ]),
            kmax: 2,
            current_ops: 3,
            f: Box::new(|x| hs::f23(x[0])),
            long: false,
        },
        Target {
            name: "g234",
            desc: "stage4(f23(c)) [madd,madd,xor,madd]",
            n_inputs: 1,
            consts: mk(&[
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("K4", K4),
                ("C4", C4),
                ("KP9", KP.wrapping_mul(9)),
                ("KQ9", KQ.wrapping_mul(9)),
                ("AP9", AP.wrapping_mul(9).wrapping_add(C4)),
                ("AQ9", AQ.wrapping_mul(9)),
                ("s3", 3),
            ]),
            kmax: 3,
            current_ops: 4,
            f: Box::new(|x| hs::stage4(hs::f23(x[0]))),
            long: false,
        },
        Target {
            name: "g45",
            desc: "stage5(stage4(d)) [madd,xor,shr,xor]",
            n_inputs: 1,
            consts: mk(&[
                ("K4", K4),
                ("C4", C4),
                ("C5", C5),
                ("sh5", 16),
                ("C5s", C5 >> 16),
                ("C5i", C5 ^ (C5 >> 16)),
                ("C45", C4 ^ C5),
                ("s3", 3),
                ("p3", 8),
                ("p16", 1 << 16),
            ]),
            kmax: 3,
            current_ops: 4,
            f: Box::new(|x| hs::stage5(hs::stage4(x[0]))),
            long: false,
        },
        Target {
            name: "e2out",
            desc: "stage5 alone [xor,shr,xor]",
            n_inputs: 1,
            consts: mk(&[
                ("C5", C5),
                ("sh5", 16),
                ("C5s", C5 >> 16),
                ("C5i", C5 ^ (C5 >> 16)),
                ("p16", 1 << 16),
            ]),
            kmax: 2,
            current_ops: 3,
            f: Box::new(|x| hs::stage5(x[0])),
            long: false,
        },
        Target {
            name: "head2",
            desc: "stage0(v ^ n) (fold-in + stage0) [xor,madd]",
            n_inputs: 2,
            consts: mk(&[("C0", C0), ("K0", K0), ("p12", 4096), ("s12", 12)]),
            kmax: 1,
            current_ops: 2,
            f: Box::new(|x| hs::stage0(x[0] ^ x[1])),
            long: false,
        },
        Target {
            name: "head3",
            desc: "stage1(stage0(v ^ n)) (fold-in + 2 stages) [xor,madd,shr,xor,xor]",
            n_inputs: 2,
            consts: vec![
                ("C0", C0),
                ("C1", C1),
                ("K0", K0),
                ("p12", 4096),
                ("sh1", 19),
                ("s12", 12),
            ],
            kmax: 4,
            current_ops: 5,
            f: Box::new(|x| hs::stage1(hs::stage0(x[0] ^ x[1]))),
            long: true,
        },
        Target {
            name: "xr3",
            desc: "next-round madd of sigma16(e)^n (C5 pre-xored into tree) [shr,xor,xor,madd]",
            n_inputs: 2,
            consts: mk(&[
                ("C0", C0),
                ("K0", K0),
                ("sh5", 16),
                ("p16", 1 << 16),
                ("K016", K0.wrapping_mul(1 << 16)),
            ]),
            kmax: 3,
            current_ops: 4,
            f: Box::new(|x| {
                let e = x[0];
                let w = e ^ (e >> 16);
                hs::stage0(w ^ x[1])
            }),
            long: false,
        },
        Target {
            name: "xr4",
            desc: "cross-round: stage0(stage5(e) ^ n) [shr,xor,xor,xor,madd]",
            n_inputs: 2,
            consts: vec![
                ("C0", C0),
                ("C5", C5),
                ("K0", K0),
                ("sh5", 16),
                ("C5i", hs::C5 ^ (hs::C5 >> 16)),
                ("p16", 1 << 16),
            ],
            kmax: 4,
            current_ops: 5,
            f: Box::new(|x| hs::stage0(hs::stage5(x[0]) ^ x[1])),
            long: true,
        },
        Target {
            name: "u2e",
            desc: "stage4(f23(u ^ C1)) (stage1 tail through stage4) [xor,madd,madd,xor,madd]",
            n_inputs: 1,
            consts: vec![
                ("C1", C1),
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("K4", K4),
                ("C4", C4),
                ("KP9", KP.wrapping_mul(9)),
            ],
            kmax: 4,
            current_ops: 5,
            f: Box::new(|x| hs::stage4(hs::f23(x[0] ^ hs::C1))),
            long: true,
        },
        Target {
            name: "par_c_deep",
            desc: "parity bit from stage1 output c in <=4 ops (5 via par_d chain)",
            n_inputs: 1,
            consts: vec![
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("PDK", PAR_D_K),
                ("PDC", PAR_D_C),
                ("s31", 31),
                ("p31", 1 << 31),
            ],
            kmax: 4,
            current_ops: 5,
            f: Box::new(|x| hs::stage5(hs::stage4(hs::f23(x[0]))) & 1),
            long: true,
        },
        Target {
            name: "par_d",
            desc: "parity bit (myhash&1) from f23 output d [vs 5 ops via value chain]",
            n_inputs: 1,
            consts: mk(&[
                ("K4", K4),
                ("C4", C4),
                ("C5", C5),
                ("PDK", PAR_D_K),
                ("PDC", PAR_D_C),
                ("PEK", PAR_E_K),
                ("p31", 1 << 31),
                ("b17", 0x0001_0001),
                ("s31", 31),
                ("s16", 16),
                ("s15", 15),
            ]),
            kmax: 2,
            current_ops: 5,
            f: Box::new(|x| hs::stage5(hs::stage4(x[0])) & 1),
            long: false,
        },
        Target {
            name: "par_e",
            desc: "parity bit from stage4 output e [vs 4 ops via value chain]",
            n_inputs: 1,
            consts: mk(&[
                ("C5", C5),
                ("PEK", PAR_E_K),
                ("PEC", PAR_E_C),
                ("p31", 1 << 31),
                ("b17", 0x0001_0001),
                ("s31", 31),
                ("s16", 16),
                ("s15", 15),
            ]),
            kmax: 2,
            current_ops: 4,
            f: Box::new(|x| hs::stage5(x[0]) & 1),
            long: false,
        },
        Target {
            name: "par_c",
            desc: "parity bit from stage1 output c (before f23)",
            n_inputs: 1,
            consts: mk(&[
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("K4", K4),
                ("C4", C4),
                ("PDK", hs::PAR_D_K),
                ("PDC", hs::PAR_D_C),
                ("p31", 1 << 31),
                ("s31", 31),
                ("s15", 15),
            ]),
            kmax: 3,
            current_ops: 8,
            f: Box::new(|x| hs::stage5(hs::stage4(hs::f23(x[0]))) & 1),
            long: false,
        },
    ]
}

// ---------------------------------------------------------------------------
// H-016: meet-in-the-middle extension
// ---------------------------------------------------------------------------
//
// The forward-only search above is exhaustive-in-pool to depth k by paying
// (branching)^(k-1) x (final-level solve); depth 5 is out of reach for it.
// The MITM engines below reach depth 5-6 on a restricted but explicit space:
//
//   program = [forward prefix over the ctx pool, enumerated exactly like
//              `dfs` above]
//           + [optional MEET op with SOLVED constants: y = m ^ c (any c) or
//              y = K*m + C (any K including even, any C) — found by
//              normalized signature lookup, constants recovered afterwards]
//           + [suffix chain of INVERTIBLE steps with constants from a large
//              "link" pool: y ^ c, K*y + c (K odd), and the 2-op xor-shift
//              macros y ^ (y >> s), y ^ (y << s)]
//
// Two engines cover the two ends of that decomposition:
//   * engine B: forward DFS to depth 3 (like `dfs`), probing tables of all
//     inverted 1-op and 2-op suffix chains at every node;
//   * engine C: DFS over suffix chains up to 5 ops (structure-capped),
//     probing tables of all 0/1/2-op forward prefixes at every node.
// Engine A is the unchanged forward-only search (full j=0 coverage at k<=4).
//
// NOT covered at depth 5+ (honest negative-space statement): programs whose
// last op is non-invertible/non-solvable (and/or/shl/shr with an out-of-pool
// operand, or a binary op of two temps) sitting on top of a depth-4 general
// prefix — i.e. shapes needing forward-4 enumeration; and suffix chains with
// >3 unary links or link constants outside the printed link pool.
//
// Signature normalizations (the "solved meet" trick): for a forward value m
// and required suffix input r, the meet op exists iff
//   xor:    r ^ c = ...   <=> the batteries (m[p]^m[0]) and (r[p]^r[0]) match;
//   affine: r = K*m + C   <=> the difference batteries match after odd-part
//           canonicalization; K even (= 2^t * odd) is handled by storing the
//           canonical battery shifted left by t = 0..=TMAX on the table side.
// Both are exact equivalences (proofs in `affine_canon`'s comment), so a
// table hit + constant solve + full-battery check loses nothing.

/// Max power-of-two factor searched for even meet multipliers K = 2^t * odd.
const TMAX: u32 = 12;
/// Cap on the link-constant pool (printed per target for the honest record).
const LINK_C_CAP: usize = 72;

/// Odd multipliers for backward affine links (`y -> K*y + c`). Chosen as the
/// machine-plausible family: stage multipliers, 2^j +/- 1, small odds, -1.
const LINK_KS: [u32; 16] = [
    1,
    0xFFFF_FFFF, // -1: covers c - y
    3,
    5,
    9,
    17,
    33,
    513,
    4097,
    65537,
    524289,
    31,
    511,
    4095,
    65535,
    297, // 9 * 33
];

const TAG_EXACT: u64 = 0x4558_4143_5421_1111;
const TAG_XORN: u64 = 0x584f_524e_5f5f_2222;
const TAG_AFFN: u64 = 0x4146_464e_5f5f_3333;

/// Identity hasher for u64 keys that are already well-mixed by `hash_words`.
#[derive(Default, Clone)]
struct IdHasher(u64);
impl std::hash::Hasher for IdHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, _: &[u8]) {
        unreachable!("IdHasher is only used with u64 keys")
    }
    fn write_u64(&mut self, v: u64) {
        self.0 = v;
    }
}
type IdMap = HashMap<u64, u32, std::hash::BuildHasherDefault<IdHasher>>;

fn hash_words(tag: u64, words: &[u32]) -> u64 {
    let mut h = tag ^ 0x9E37_79B9_7F4A_7C15;
    for &w in words {
        h = (h ^ u64::from(w)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        h ^= h >> 29;
    }
    h
}

/// Battery signature invariant under `v -> v ^ c` for any constant c.
fn xor_norm(v: &Vp) -> [u32; P - 1] {
    let mut d = [0u32; P - 1];
    for p in 1..P {
        d[p - 1] = v[p] ^ v[0];
    }
    d
}

/// Battery signature invariant under `v -> K*v + C` for any ODD K and any C
/// (mod 2^32): take differences d[p] = v[p] - v[0], find the first index q of
/// minimal 2-adic valuation s, and multiply everything by the inverse of the
/// odd part d[q] >> s.
///
/// Why it is exact: under v' = K*v + C the differences become d' = K*d, all
/// valuations are preserved (K odd), so the same q is selected; writing
/// d[p] = 2^s * e[p], canon[p] = 2^s * (e[p] * inv(e[q]) mod 2^(32-s)) and
/// the factor K cancels inside the mod-2^(32-s) product. For EVEN K = 2^t*k
/// (t <= TMAX, k odd) the canonical battery of K*v + C equals the canonical
/// battery of v shifted left by t (same derivation, valuations all shift by
/// t) — which is why tables store the t-shifted variants.
///
/// Returns None for a constant battery (all differences zero).
fn affine_canon(v: &Vp) -> Option<[u32; P - 1]> {
    let mut d = [0u32; P - 1];
    let mut s_min = 33u32;
    let mut q = usize::MAX;
    for p in 1..P {
        let dd = v[p].wrapping_sub(v[0]);
        d[p - 1] = dd;
        if dd != 0 {
            let s = dd.trailing_zeros();
            if s < s_min {
                s_min = s;
                q = p - 1;
            }
        }
    }
    if q == usize::MAX {
        return None;
    }
    let inv = modinv32(d[q] >> s_min);
    for x in d.iter_mut() {
        *x = x.wrapping_mul(inv);
    }
    Some(d)
}

fn shl_battery(d: &[u32; P - 1], t: u32) -> [u32; P - 1] {
    let mut out = *d;
    for x in out.iter_mut() {
        *x <<= t;
    }
    out
}

/// Solve `r = m ^ c` over the whole battery (None if inconsistent).
fn solve_xor_meet(m: &Vp, r: &Vp) -> Option<u32> {
    let c = r[0] ^ m[0];
    if (0..P).all(|p| (m[p] ^ c) == r[p]) {
        Some(c)
    } else {
        None
    }
}

/// Solve `r = K*m + C` over the whole battery, K unrestricted (even allowed).
/// Uses the minimal-valuation difference pair; when that valuation is s > 0,
/// K is determined mod 2^(32-s) and the 2^s lifts are tried (capped at 2^12;
/// a cap hit is astronomically unlikely with random probes and would only
/// cost a missed find, never a false one).
fn solve_affine_meet(m: &Vp, r: &Vp) -> Option<(u32, u32)> {
    let mut s_min = 33u32;
    let mut q = 0usize;
    for p in 1..P {
        let d = m[p].wrapping_sub(m[0]);
        if d != 0 {
            let s = d.trailing_zeros();
            if s < s_min {
                s_min = s;
                q = p;
            }
        }
    }
    if s_min > 32 {
        return None; // constant m battery
    }
    let dm = m[q].wrapping_sub(m[0]);
    let dr = r[q].wrapping_sub(r[0]);
    let s = s_min;
    if dr != 0 && dr.trailing_zeros() < s {
        return None;
    }
    let check = |k: u32| -> Option<(u32, u32)> {
        let c = r[0].wrapping_sub(k.wrapping_mul(m[0]));
        if (0..P).all(|p| mad(m[p], k, c) == r[p]) {
            Some((k, c))
        } else {
            None
        }
    };
    if s == 0 {
        return check(dr.wrapping_mul(modinv32(dm)));
    }
    let k0 = (dr >> s).wrapping_mul(modinv32(dm >> s));
    let lifts = 1u64 << s.min(TMAX);
    for u in 0..lifts {
        let k = k0.wrapping_add((u as u32) << (32 - s));
        if let Some(kc) = check(k) {
            return Some(kc);
        }
    }
    None
}

/// Invert `v = x ^ (x >> s)` (s >= 1).
fn un_xsr(v: u32, s: u32) -> u32 {
    let mut x = v;
    for _ in 0..(32 / s + 1) {
        x = v ^ (x >> s);
    }
    x
}

/// Invert `v = x ^ (x << s)` (s >= 1).
fn un_xsl(v: u32, s: u32) -> u32 {
    let mut x = v;
    for _ in 0..(32 / s + 1) {
        x = v ^ (x << s);
    }
    x
}

/// One step of an invertible suffix chain, stored in FORWARD orientation
/// (applied to the chain value on the way toward `out`).
#[derive(Clone, Copy, Debug)]
enum Link {
    /// y -> k*y + c, k odd (covers add/sub/`c - y` via k = 1 / k = -1).
    Aff { k: u32, kinv: u32, c: u32 },
    /// y -> y ^ c.
    XorC(u32),
    /// y -> y ^ (y >> s): 2 machine ops.
    XsR(u32),
    /// y -> y ^ (y << s): 2 machine ops.
    XsL(u32),
}

impl Link {
    fn ops(self) -> usize {
        match self {
            Link::XsR(_) | Link::XsL(_) => 2,
            _ => 1,
        }
    }
    fn is_unary_const(self) -> bool {
        matches!(self, Link::Aff { .. } | Link::XorC(_))
    }
    /// Required INPUT battery given the required OUTPUT battery.
    fn invert(self, r: &Vp) -> Vp {
        let mut out = [0u32; P];
        for p in 0..P {
            out[p] = match self {
                Link::Aff { kinv, c, .. } => r[p].wrapping_sub(c).wrapping_mul(kinv),
                Link::XorC(c) => r[p] ^ c,
                Link::XsR(s) => un_xsr(r[p], s),
                Link::XsL(s) => un_xsl(r[p], s),
            };
        }
        out
    }
    /// Append this step's machine ops to `prog`; `cur` is the index of the
    /// chain value; returns the index of the step's result.
    fn emit(self, cur: usize, n_base: usize, prog: &mut Vec<Inst>) -> usize {
        match self {
            Link::Aff { k, c, .. } => prog.push(Inst::MadKC(cur, k, c)),
            Link::XorC(c) => prog.push(Inst::BinC(Xor, cur, c)),
            Link::XsR(s) => {
                prog.push(Inst::BinC(Shr, cur, s));
                let t = n_base + prog.len() - 1;
                prog.push(Inst::Bin(Xor, cur, t));
            }
            Link::XsL(s) => {
                prog.push(Inst::BinC(Shl, cur, s));
                let t = n_base + prog.len() - 1;
                prog.push(Inst::Bin(Xor, cur, t));
            }
        }
        n_base + prog.len() - 1
    }
}

/// Emit a whole suffix chain (stored outermost-first) after the meet value.
fn emit_chain(links: &[Link], mut cur: usize, n_base: usize, prog: &mut Vec<Inst>) {
    for l in links.iter().rev() {
        cur = l.emit(cur, n_base, prog);
    }
}

/// All suffix-chain steps over a link-constant pool.
fn build_links(cs: &[u32]) -> Vec<Link> {
    let mut out = Vec::new();
    for &c in cs {
        if c != 0 {
            out.push(Link::XorC(c));
        }
    }
    for &k in LINK_KS.iter() {
        let kinv = modinv32(k);
        for &c in cs {
            if k == 1 && c == 0 {
                continue; // identity
            }
            out.push(Link::Aff { k, kinv, c });
        }
    }
    for s in 1..32u32 {
        out.push(Link::XsR(s));
        out.push(Link::XsL(s));
    }
    out
}

/// Link-constant pool: seeds + their pairwise xors/sums/products + shifted
/// variants + powers of two, deduped in priority order and capped (the final
/// pool is printed per target so negatives are precisely scoped).
fn build_link_consts(seed: &[u32], shifts: &[u32]) -> Vec<u32> {
    let mut out: Vec<u32> = Vec::new();
    let push = |v: u32, out: &mut Vec<u32>| {
        if !out.contains(&v) {
            out.push(v);
        }
    };
    for &v in [0u32, 1, 0xFFFF_FFFF].iter() {
        push(v, &mut out);
    }
    for &v in seed {
        push(v, &mut out);
    }
    for &s in shifts {
        push(1u32 << s, &mut out);
    }
    for i in 0..seed.len() {
        for j in (i + 1)..seed.len() {
            push(seed[i] ^ seed[j], &mut out);
        }
    }
    for i in 0..seed.len() {
        for j in i..seed.len() {
            push(seed[i].wrapping_add(seed[j]), &mut out);
        }
    }
    for &v in seed {
        for &s in shifts {
            push(v << s, &mut out);
            push(v >> s, &mut out);
        }
    }
    for i in 0..seed.len() {
        for j in i..seed.len() {
            push(seed[i].wrapping_mul(seed[j]), &mut out);
        }
    }
    out.truncate(LINK_C_CAP);
    out
}

/// A forward prefix (kf ops) whose last value is the meet variable.
struct FwdEntry {
    out: Vp,
    prog: Vec<Inst>,
    out_idx: usize,
}

struct FwdTab {
    kf: usize,
    entries: Vec<FwdEntry>,
    exact: IdMap,
    xorn: IdMap,
    /// Stores canonical batteries shifted by t = 0..=TMAX (even-K meets).
    affn: IdMap,
}

impl FwdTab {
    fn add(&mut self, out: Vp, prog: Vec<Inst>, out_idx: usize) {
        let ek = hash_words(TAG_EXACT, &out);
        if self.exact.contains_key(&ek) {
            return; // battery-identical prefix already stored
        }
        let idx = self.entries.len() as u32;
        self.exact.insert(ek, idx);
        self.xorn
            .entry(hash_words(TAG_XORN, &xor_norm(&out)))
            .or_insert(idx);
        if let Some(canon) = affine_canon(&out) {
            for t in 0..=TMAX {
                self.affn
                    .entry(hash_words(TAG_AFFN, &shl_battery(&canon, t)))
                    .or_insert(idx);
            }
        }
        self.entries.push(FwdEntry { out, prog, out_idx });
    }
}

fn inst_uses(inst: &Inst, idx: usize) -> bool {
    match *inst {
        Inst::Bin(_, i, j) => i == idx || j == idx,
        Inst::Mad(i, j, k) => i == idx || j == idx || k == idx,
        _ => false,
    }
}

/// Build the table of all kf-op forward prefixes (kf <= 2). Every temp except
/// the last (the meet variable) must be referenced, so kf=2 keeps only pairs
/// where the second op uses t1.
fn build_fwd_tab(ctx: &Ctx, kf: usize) -> FwdTab {
    let mut tab = FwdTab {
        kf,
        entries: Vec::new(),
        exact: IdMap::default(),
        xorn: IdMap::default(),
        affn: IdMap::default(),
    };
    let n_base = ctx.base_vals.len();
    match kf {
        0 => {
            for i in 0..ctx.n_inputs {
                tab.add(ctx.base_vals[i], Vec::new(), i);
            }
        }
        1 => {
            let w = W::new(ctx);
            enumerate_level(&w, |inst, v| tab.add(v, vec![inst], n_base));
        }
        2 => {
            let mut w = W::new(ctx);
            let mut l1: Vec<(Inst, Vp)> = Vec::new();
            enumerate_level(&w, |inst, v| l1.push((inst, v)));
            for (i1, v1) in l1 {
                let undo = w.push(i1.clone(), v1);
                enumerate_level(&w, |i2, v2| {
                    if inst_uses(&i2, n_base) {
                        tab.add(v2, vec![i1.clone(), i2], n_base + 1);
                    }
                });
                w.pop(undo);
            }
        }
        _ => unreachable!("forward tables only go to kf = 2"),
    }
    tab
}

/// An inverted suffix chain: `req` is the battery the chain input must equal
/// for `out` to hit the target. `links` are stored outermost-first.
struct BwdEntry {
    req: Vp,
    links: Vec<Link>,
}

struct BwdTab {
    jops: usize,
    entries: Vec<BwdEntry>,
    exact: IdMap,
    xorn: IdMap,
    /// t = 0 canonical keys only; the forward prober shifts its own canon.
    affn: IdMap,
}

impl BwdTab {
    fn new(jops: usize) -> BwdTab {
        BwdTab {
            jops,
            entries: Vec::new(),
            exact: IdMap::default(),
            xorn: IdMap::default(),
            affn: IdMap::default(),
        }
    }
    fn add(&mut self, req: Vp, links: Vec<Link>) {
        let ek = hash_words(TAG_EXACT, &req);
        if self.exact.contains_key(&ek) {
            return;
        }
        let idx = self.entries.len() as u32;
        self.exact.insert(ek, idx);
        self.xorn
            .entry(hash_words(TAG_XORN, &xor_norm(&req)))
            .or_insert(idx);
        if let Some(canon) = affine_canon(&req) {
            self.affn.entry(hash_words(TAG_AFFN, &canon)).or_insert(idx);
        }
        self.entries.push(BwdEntry { req, links });
    }
}

/// Tables of all inverted 1-op and 2-op suffix chains for engine B.
fn build_bwd_tabs(target: &Vp, links: &[Link]) -> Vec<BwdTab> {
    let mut t1 = BwdTab::new(1);
    let mut t2 = BwdTab::new(2);
    for &l in links {
        match l.ops() {
            1 => t1.add(l.invert(target), vec![l]),
            2 => t2.add(l.invert(target), vec![l]),
            _ => unreachable!(),
        }
    }
    for &l1 in links.iter().filter(|l| l.ops() == 1) {
        let r1 = l1.invert(target);
        for &l2 in links.iter().filter(|l| l.ops() == 1) {
            t2.add(l2.invert(&r1), vec![l1, l2]);
        }
    }
    vec![t1, t2]
}

struct MitmStats {
    fwd_nodes: AtomicU64,
    bwd_nodes: AtomicU64,
}

/// Engine B: forward DFS (moderate pool) probing inverted-suffix tables.
struct EngineB<'a> {
    ctx: &'a Ctx<'a>,
    tabs: &'a [BwdTab],
    dmax: usize,
    wanted: u32,
}

impl EngineB<'_> {
    /// Called with `w` already holding >= 1 op (like `dfs`).
    fn dfs(&self, w: &mut W, nodes: &mut u64) {
        if self.ctx.stop.load(Ordering::Relaxed) {
            return;
        }
        *nodes += 1;
        let d = w.prog.len();
        if w.unused_cnt == 1 {
            self.probe(w, d);
        }
        if d >= self.dmax {
            return;
        }
        if w.unused_cnt > 2 * (self.dmax - d) + 1 {
            return;
        }
        let mut cands: Vec<(Inst, Vp)> = Vec::with_capacity(4096);
        enumerate_level(w, |inst, v| cands.push((inst, v)));
        for (inst, v) in cands {
            if self.ctx.stop.load(Ordering::Relaxed) {
                return;
            }
            let undo = w.push(inst, v);
            self.dfs(w, nodes);
            w.pop(undo);
        }
    }

    fn probe(&self, w: &W, d: usize) {
        let m = *w.vals.last().unwrap();
        let n_base = self.ctx.base_vals.len();
        let cur = n_base + d - 1;
        let want = |k: usize| self.wanted & (1u32 << k) != 0;
        let ek = hash_words(TAG_EXACT, &m);
        let xk = hash_words(TAG_XORN, &xor_norm(&m));
        let canon = affine_canon(&m);
        for tab in self.tabs {
            let j = tab.jops;
            if want(d + j) {
                if let Some(&ei) = tab.exact.get(&ek) {
                    let e = &tab.entries[ei as usize];
                    if e.req == m {
                        let mut prog = w.prog.clone();
                        emit_chain(&e.links, cur, n_base, &mut prog);
                        report_prog(self.ctx, prog);
                    }
                }
            }
            if want(d + 1 + j) {
                if let Some(&ei) = tab.xorn.get(&xk) {
                    let e = &tab.entries[ei as usize];
                    if let Some(c) = solve_xor_meet(&m, &e.req) {
                        if c != 0 {
                            let mut prog = w.prog.clone();
                            prog.push(Inst::BinC(Xor, cur, c));
                            emit_chain(&e.links, n_base + prog.len() - 1, n_base, &mut prog);
                            report_prog(self.ctx, prog);
                        }
                    }
                }
                if let Some(canon) = &canon {
                    for t in 0..=TMAX {
                        let key = hash_words(TAG_AFFN, &shl_battery(canon, t));
                        if let Some(&ei) = tab.affn.get(&key) {
                            let e = &tab.entries[ei as usize];
                            if let Some((k, c)) = solve_affine_meet(&m, &e.req) {
                                if k != 1 || c != 0 {
                                    let mut prog = w.prog.clone();
                                    prog.push(Inst::MadKC(cur, k, c));
                                    emit_chain(
                                        &e.links,
                                        n_base + prog.len() - 1,
                                        n_base,
                                        &mut prog,
                                    );
                                    report_prog(self.ctx, prog);
                                    break; // same solve for every t; one hit suffices
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn run_engine_b(
    ctx: &Ctx,
    tabs: &[BwdTab],
    dmax: usize,
    wanted: u32,
    stats: &MitmStats,
    threads: usize,
) {
    let mut l1: Vec<(Inst, Vp)> = Vec::new();
    {
        let w = W::new(ctx);
        enumerate_level(&w, |inst, v| l1.push((inst, v)));
    }
    let eng = EngineB {
        ctx,
        tabs,
        dmax,
        wanted,
    };
    let next = AtomicU64::new(0);
    std::thread::scope(|scope| {
        for _ in 0..threads {
            scope.spawn(|| {
                let mut w = W::new(ctx);
                let mut nodes = 0u64;
                loop {
                    let idx = next.fetch_add(1, Ordering::Relaxed) as usize;
                    if idx >= l1.len() || ctx.stop.load(Ordering::Relaxed) {
                        break;
                    }
                    let (inst, v) = l1[idx].clone();
                    let undo = w.push(inst, v);
                    eng.dfs(&mut w, &mut nodes);
                    w.pop(undo);
                }
                stats.fwd_nodes.fetch_add(nodes, Ordering::Relaxed);
            });
        }
    });
}

/// Engine C: suffix-chain DFS probing forward-prefix tables. Chains are
/// capped at 5 ops, <= 3 unary-const links, and (2 xorshifts + 1 unary) at
/// the full 5-op budget — the structures beyond that are combinatorially out
/// of reach and are declared uncovered in the header comment.
struct EngineC<'a> {
    ctx: &'a Ctx<'a>,
    links: &'a [Link],
    fwd: &'a [FwdTab],
    jmax: usize,
    wanted: u32,
}

impl EngineC<'_> {
    fn dfs(&self, req: &Vp, chain: &mut Vec<Link>, ops: usize, n_u: usize, nodes: &mut u64) {
        if self.ctx.stop.load(Ordering::Relaxed) {
            return;
        }
        *nodes += 1;
        self.probe(req, chain, ops);
        if ops >= self.jmax {
            return;
        }
        for &l in self.links {
            let nops = ops + l.ops();
            if nops > self.jmax {
                continue;
            }
            let nu = n_u + usize::from(l.is_unary_const());
            if nu > 3 || (nops == 5 && nu > 1) {
                continue;
            }
            let r2 = l.invert(req);
            chain.push(l);
            self.dfs(&r2, chain, nops, nu, nodes);
            chain.pop();
        }
    }

    fn probe(&self, req: &Vp, chain: &[Link], ops: usize) {
        let want = |k: usize| self.wanted & (1u32 << k) != 0;
        let n_base = self.ctx.base_vals.len();
        let ek = hash_words(TAG_EXACT, req);
        let xk = hash_words(TAG_XORN, &xor_norm(req));
        let ak = affine_canon(req).map(|c| hash_words(TAG_AFFN, &c));
        for tab in self.fwd {
            if want(tab.kf + ops) {
                if let Some(&ei) = tab.exact.get(&ek) {
                    let e = &tab.entries[ei as usize];
                    if e.out == *req {
                        let mut prog = e.prog.clone();
                        emit_chain(chain, e.out_idx, n_base, &mut prog);
                        report_prog(self.ctx, prog);
                    }
                }
            }
            if want(tab.kf + 1 + ops) {
                if let Some(&ei) = tab.xorn.get(&xk) {
                    let e = &tab.entries[ei as usize];
                    if let Some(c) = solve_xor_meet(&e.out, req) {
                        if c != 0 {
                            let mut prog = e.prog.clone();
                            prog.push(Inst::BinC(Xor, e.out_idx, c));
                            emit_chain(chain, n_base + prog.len() - 1, n_base, &mut prog);
                            report_prog(self.ctx, prog);
                        }
                    }
                }
                if let Some(ak) = ak {
                    if let Some(&ei) = tab.affn.get(&ak) {
                        let e = &tab.entries[ei as usize];
                        if let Some((k, c)) = solve_affine_meet(&e.out, req) {
                            if k != 1 || c != 0 {
                                let mut prog = e.prog.clone();
                                prog.push(Inst::MadKC(e.out_idx, k, c));
                                emit_chain(chain, n_base + prog.len() - 1, n_base, &mut prog);
                                report_prog(self.ctx, prog);
                            }
                        }
                    }
                }
            }
        }
    }
}

fn run_engine_c(
    ctx: &Ctx,
    links: &[Link],
    fwd: &[FwdTab],
    jmax: usize,
    wanted: u32,
    stats: &MitmStats,
    threads: usize,
) {
    let eng = EngineC {
        ctx,
        links,
        fwd,
        jmax,
        wanted,
    };
    let next = AtomicU64::new(0);
    std::thread::scope(|scope| {
        for _ in 0..threads {
            scope.spawn(|| {
                let mut nodes = 0u64;
                let mut chain: Vec<Link> = Vec::with_capacity(8);
                loop {
                    let idx = next.fetch_add(1, Ordering::Relaxed) as usize;
                    if idx >= eng.links.len() || ctx.stop.load(Ordering::Relaxed) {
                        break;
                    }
                    let l = eng.links[idx];
                    if l.ops() > eng.jmax {
                        continue;
                    }
                    let req = l.invert(&ctx.target);
                    chain.push(l);
                    eng.dfs(
                        &req,
                        &mut chain,
                        l.ops(),
                        usize::from(l.is_unary_const()),
                        &mut nodes,
                    );
                    chain.pop();
                }
                stats.bwd_nodes.fetch_add(nodes, Ordering::Relaxed);
            });
        }
    });
}

// ---------------------------------------------------------------------------
// MITM targets and runner
// ---------------------------------------------------------------------------

struct MTarget {
    name: &'static str,
    desc: &'static str,
    n_inputs: usize,
    current_ops: usize,
    /// Engine A (forward-only exhaustive) depth; 0 = already closed in H-003.
    lean_kmax: usize,
    /// Engine A pool override (empty = use `pool`). Two-input k=4 runs need a
    /// leaner pool than the MITM engines to stay within a CPU budget.
    lean: Vec<(&'static str, u32)>,
    /// Forward pool: engines B DFS and engine C's prefix tables.
    pool: Vec<(&'static str, u32)>,
    /// Seeds for the link-constant pool (enriched + capped).
    seed: Vec<u32>,
    shifts: Vec<u32>,
    stretch: bool,
    /// Run engine C (the chain-DFS whale, ~10-16 min/target). When false the
    /// runner prints exactly which shapes the negative then covers.
    engine_c: bool,
    f: Box<TargetFn>,
}

fn build_ctx<'a>(n_inputs: usize, consts: &[(&'static str, u32)], f: &'a TargetFn) -> Ctx<'a> {
    let probes = probes(n_inputs);
    let mut base_names: Vec<String> = Vec::new();
    let mut base_vals: Vec<Vp> = Vec::new();
    let mut base_is_const: Vec<bool> = Vec::new();
    let input_names = ["x", "y"];
    for (k, nm) in input_names.iter().enumerate().take(n_inputs) {
        base_names.push((*nm).to_string());
        let mut v = [0u32; P];
        for (p, tup) in probes.iter().enumerate() {
            v[p] = tup[k];
        }
        base_vals.push(v);
        base_is_const.push(false);
    }
    for (nm, c) in consts {
        base_names.push(format!("{nm}={c:#010x}"));
        base_vals.push([*c; P]);
        base_is_const.push(true);
    }
    let mut target = [0u32; P];
    for (p, tup) in probes.iter().enumerate() {
        target[p] = f(tup);
    }
    Ctx {
        n_inputs,
        base_names,
        base_vals,
        base_is_const,
        target,
        tested: AtomicU64::new(0),
        stop: AtomicBool::new(false),
        finds: Mutex::new(Vec::new()),
        unsolved: AtomicU64::new(0),
        f,
    }
}

#[allow(clippy::too_many_lines)]
fn mitm_targets() -> Vec<MTarget> {
    use hs::*;
    let common = [("zero", 0u32), ("one", 1u32), ("m1", 0xFFFF_FFFF)];
    let mk = |extra: &[(&'static str, u32)]| -> Vec<(&'static str, u32)> {
        common.iter().chain(extra.iter()).cloned().collect()
    };
    let c1s = C1 >> 19;
    let c1i = C1 ^ (C1 >> 19);
    let c5s = C5 >> 16;
    let c5i = C5 ^ (C5 >> 16);
    let c0s = C0 >> 19;
    let kpc1 = KP.wrapping_mul(C1);
    let kqc1 = KQ.wrapping_mul(C1);
    let apk = AP.wrapping_add(kpc1);
    let aqk = AQ.wrapping_add(kqc1);
    let kp9 = KP.wrapping_mul(9);
    let kq9 = KQ.wrapping_mul(9);
    let ap9 = AP.wrapping_mul(9).wrapping_add(C4);
    let aq9 = AQ.wrapping_mul(9);
    let k016 = K0.wrapping_mul(1 << 16);
    let k0c4 = K0.wrapping_mul(C4);
    let k0c5 = K0.wrapping_mul(C5);
    let k09 = K0.wrapping_mul(9);
    vec![
        MTarget {
            name: "b2d",
            desc: "stage1 o f23 span: f23(stage1(b)) [shr,xor,xor,madd,madd,xor]",
            n_inputs: 1,
            current_ops: 6,
            lean_kmax: 4,
            lean: vec![],
            pool: mk(&[
                ("C1", C1),
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("C1i", c1i),
                ("s19", 19),
                ("s5", 5),
                ("s9", 9),
                ("p19", 1 << 19),
            ]),
            seed: vec![C1, KP, AP, KQ, AQ, c1s, c1i, kpc1, kqc1, apk, aqk],
            shifts: vec![19, 5, 9, 13, 14],
            stretch: false,
            engine_c: true,
            f: Box::new(|x| hs::f23(hs::stage1(x[0]))),
        },
        MTarget {
            name: "xr5",
            desc: "cross-round from d: stage0(stage5(stage4(d)) ^ n) [madd,shr,xor,xor,xor,madd]",
            n_inputs: 2,
            current_ops: 6,
            lean_kmax: 4,
            lean: mk(&[
                ("C0", C0),
                ("K0", K0),
                ("C4", C4),
                ("C5", C5),
                ("C5i", c5i),
                ("s16", 16),
                ("s3", 3),
            ]),
            pool: mk(&[
                ("C0", C0),
                ("K0", K0),
                ("C4", C4),
                ("C5", C5),
                ("C5i", c5i),
                ("K4", 9),
                ("s16", 16),
                ("s3", 3),
                ("s12", 12),
                ("K016", k016),
            ]),
            seed: vec![C0, K0, C4, C5, c5s, c5i, k016, k0c4, k0c5, k09],
            shifts: vec![16, 3, 12, 4, 15],
            stretch: false,
            engine_c: true,
            f: Box::new(|x| hs::stage0(hs::stage5(hs::stage4(x[0])) ^ x[1])),
        },
        MTarget {
            name: "xr3p",
            desc:
                "primed cross-round from d: stage0(sigma16(stage4(d)) ^ n') [madd,shr,xor,xor,madd]",
            n_inputs: 2,
            current_ops: 5,
            lean_kmax: 4,
            lean: mk(&[
                ("C0", C0),
                ("K0", K0),
                ("C4", C4),
                ("K4", 9),
                ("s16", 16),
                ("s3", 3),
            ]),
            pool: mk(&[
                ("C0", C0),
                ("K0", K0),
                ("C4", C4),
                ("K4", 9),
                ("s16", 16),
                ("s3", 3),
                ("s12", 12),
                ("K016", k016),
                ("p16", 1 << 16),
                ("K0C4", k0c4),
            ]),
            seed: vec![C0, K0, C4, k016, k0c4, k09],
            shifts: vec![16, 3, 12],
            stretch: false,
            engine_c: true,
            f: Box::new(|x| hs::stage0(hs::sigma16(hs::stage4(x[0])) ^ x[1])),
        },
        MTarget {
            name: "xr4r",
            desc: "cross-round from e (H-003 xr4, richer pool): stage0(stage5(e) ^ n)",
            n_inputs: 2,
            current_ops: 5,
            lean_kmax: 0,
            lean: vec![],
            pool: mk(&[
                ("C0", C0),
                ("C5", C5),
                ("K0", K0),
                ("C5s", c5s),
                ("C5i", c5i),
                ("s16", 16),
                ("s12", 12),
                ("K016", k016),
                ("p16", 1 << 16),
                ("K0C5", k0c5),
            ]),
            seed: vec![C0, K0, C5, c5s, c5i, k016, k0c5],
            shifts: vec![16, 3, 12, 4, 15],
            stretch: false,
            engine_c: false,
            f: Box::new(|x| hs::stage0(hs::stage5(x[0]) ^ x[1])),
        },
        MTarget {
            name: "head3r",
            desc: "fold-in head (H-003 head3, richer pool): stage1(stage0(v ^ n))",
            n_inputs: 2,
            current_ops: 5,
            lean_kmax: 0,
            lean: vec![],
            pool: mk(&[
                ("C0", C0),
                ("C1", C1),
                ("K0", K0),
                ("C0s", c0s),
                ("C1s", c1s),
                ("C1i", c1i),
                ("C0x1", C0 ^ C1),
                ("s12", 12),
                ("s19", 19),
                ("p19", 1 << 19),
            ]),
            seed: vec![C0, C1, K0, c0s, c1s, c1i, C0 ^ C1],
            shifts: vec![12, 19, 7, 13],
            stretch: false,
            engine_c: false,
            f: Box::new(|x| hs::stage1(hs::stage0(x[0] ^ x[1]))),
        },
        MTarget {
            name: "head4u",
            desc: "fold-in head to the pre-C1 point u: sigma19(stage0(v ^ n)) [xor,madd,shr,xor]",
            n_inputs: 2,
            current_ops: 4,
            lean_kmax: 3,
            lean: vec![],
            pool: mk(&[
                ("C0", C0),
                ("K0", K0),
                ("C0s", c0s),
                ("s12", 12),
                ("s19", 19),
                ("p19", 1 << 19),
            ]),
            seed: vec![C0, K0, c0s],
            shifts: vec![12, 19, 7, 13],
            stretch: false,
            engine_c: true,
            f: Box::new(|x| {
                let b = hs::stage0(x[0] ^ x[1]);
                b ^ (b >> 19)
            }),
        },
        MTarget {
            name: "u2er",
            desc: "stage1-tail through stage4 (H-003 u2e, richer pool): stage4(f23(u ^ C1))",
            n_inputs: 1,
            current_ops: 5,
            lean_kmax: 0,
            lean: vec![],
            pool: mk(&[
                ("C1", C1),
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("K4", 9),
                ("C4", C4),
                ("KP9", kp9),
                ("KQ9", kq9),
                ("s5", 5),
                ("s9", 9),
                ("s3", 3),
            ]),
            seed: vec![C1, KP, AP, KQ, AQ, C4, kp9, kq9, ap9, aq9, apk, aqk],
            shifts: vec![5, 9, 3, 14],
            stretch: false,
            engine_c: false,
            f: Box::new(|x| hs::stage4(hs::f23(x[0] ^ hs::C1))),
        },
        MTarget {
            name: "a2d",
            desc: "interior 7-op span: f23(stage1(stage0(a)))",
            n_inputs: 1,
            current_ops: 7,
            lean_kmax: 3,
            lean: vec![],
            pool: mk(&[
                ("C0", C0),
                ("C1", C1),
                ("K0", K0),
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("C1i", c1i),
                ("s12", 12),
                ("s19", 19),
                ("s5", 5),
                ("s9", 9),
            ]),
            seed: vec![C0, C1, K0, KP, AP, KQ, AQ, c1i, kpc1, kqc1, apk, aqk],
            shifts: vec![12, 19, 5, 9],
            stretch: true,
            engine_c: false,
            f: Box::new(|x| hs::f23(hs::stage1(hs::stage0(x[0])))),
        },
        MTarget {
            name: "b2e",
            desc: "interior 7-op span: stage4(f23(stage1(b)))",
            n_inputs: 1,
            current_ops: 7,
            lean_kmax: 3,
            lean: vec![],
            pool: mk(&[
                ("C1", C1),
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("K4", 9),
                ("C4", C4),
                ("C1i", c1i),
                ("s19", 19),
                ("s5", 5),
                ("s9", 9),
                ("s3", 3),
            ]),
            seed: vec![C1, KP, AP, KQ, AQ, C4, c1i, kp9, kq9, ap9, aq9],
            shifts: vec![19, 5, 9, 3],
            stretch: true,
            engine_c: false,
            f: Box::new(|x| hs::stage4(hs::f23(hs::stage1(x[0])))),
        },
        MTarget {
            name: "c2out",
            desc: "interior 7-op span: stage5(stage4(f23(c)))",
            n_inputs: 1,
            current_ops: 7,
            lean_kmax: 3,
            lean: vec![],
            pool: mk(&[
                ("KP", KP),
                ("AP", AP),
                ("KQ", KQ),
                ("AQ", AQ),
                ("K4", 9),
                ("C4", C4),
                ("C5", C5),
                ("C5i", c5i),
                ("s5", 5),
                ("s9", 9),
                ("s3", 3),
                ("s16", 16),
            ]),
            seed: vec![KP, AP, KQ, AQ, C4, C5, c5i, kp9, kq9, ap9, aq9],
            shifts: vec![5, 9, 3, 16],
            stretch: true,
            engine_c: false,
            f: Box::new(|x| hs::stage5(hs::stage4(hs::f23(x[0])))),
        },
    ]
}

fn run_mitm_target(tg: &MTarget, threads: usize) {
    let kmax_use = tg.current_ops - 1;
    let wanted: u32 = (2u32 << kmax_use) - 2; // bits 1..=kmax_use
    println!(
        "== MITM target {} : {} (current {} ops, hunting k <= {}) ==",
        tg.name, tg.desc, tg.current_ops, kmax_use
    );
    let t_start = Instant::now();

    // Engine A: forward-only exhaustive (full j=0 coverage at k <= lean_kmax)
    // over the target's engine-A pool.
    let pool_a = if tg.lean.is_empty() {
        &tg.pool
    } else {
        &tg.lean
    };
    let ctx_a = build_ctx(tg.n_inputs, pool_a, &*tg.f);
    if tg.lean_kmax > 0 {
        println!(
            "   engine A (forward exhaustive, k <= {}): pool [{}]",
            tg.lean_kmax,
            ctx_a
                .base_names
                .iter()
                .skip(tg.n_inputs)
                .cloned()
                .collect::<Vec<_>>()
                .join(", ")
        );
        search_iterative(&ctx_a, tg.lean_kmax, threads);
    } else {
        println!("   engine A skipped (H-003 closed this span at k <= 4 already)");
    }

    // Shared MITM context (same pool; link constants live outside the ctx).
    let ctx = build_ctx(tg.n_inputs, &tg.pool, &*tg.f);
    let link_cs = build_link_consts(&tg.seed, &tg.shifts);
    let links = build_links(&link_cs);
    println!(
        "   link pool: {} constants {:x?}, {} odd Ks, {} links",
        link_cs.len(),
        link_cs,
        LINK_KS.len(),
        links.len()
    );
    let stats = MitmStats {
        fwd_nodes: AtomicU64::new(0),
        bwd_nodes: AtomicU64::new(0),
    };

    // Engine B: forward DFS x inverted-suffix tables.
    let bwd_tabs = build_bwd_tabs(&ctx.target, &links);
    let dmax = 3.min(kmax_use - 1);
    println!(
        "   engine B: fwd DFS to depth {} probing suffix tables (j=1: {} chains, j=2: {} chains)",
        dmax,
        bwd_tabs[0].entries.len(),
        bwd_tabs[1].entries.len()
    );
    let tb = Instant::now();
    run_engine_b(&ctx, &bwd_tabs, dmax, wanted, &stats, threads);
    println!(
        "   engine B: {} forward nodes probed in {:.1}s",
        stats.fwd_nodes.load(Ordering::Relaxed),
        tb.elapsed().as_secs_f64()
    );
    drop(bwd_tabs);

    // Engine C: suffix-chain DFS x forward-prefix tables.
    if !tg.engine_c {
        println!(
            "   engine C skipped (CPU budget): MITM coverage here = engine B shapes only \
             (forward<=3 + [solved meet]? + 1..2-op invertible suffix)"
        );
        summarize(tg, &ctx_a, &ctx, kmax_use, t_start);
        return;
    }
    let fwd_tabs: Vec<FwdTab> = (0..=2).map(|kf| build_fwd_tab(&ctx, kf)).collect();
    let jmax = 5.min(kmax_use);
    println!(
        "   engine C: chain DFS to {} ops (caps: <=3 unary links, 5-op chains need <=1 unary) probing prefix tables (kf=0: {}, kf=1: {}, kf=2: {} prefixes)",
        jmax,
        fwd_tabs[0].entries.len(),
        fwd_tabs[1].entries.len(),
        fwd_tabs[2].entries.len()
    );
    let tc = Instant::now();
    run_engine_c(&ctx, &links, &fwd_tabs, jmax, wanted, &stats, threads);
    println!(
        "   engine C: {} chain nodes probed in {:.1}s",
        stats.bwd_nodes.load(Ordering::Relaxed),
        tc.elapsed().as_secs_f64()
    );

    summarize(tg, &ctx_a, &ctx, kmax_use, t_start);
}

fn summarize(tg: &MTarget, ctx_a: &Ctx, ctx: &Ctx, kmax_use: usize, t_start: Instant) {
    let finds_a = ctx_a.finds.lock().unwrap().len();
    let finds_bc = ctx.finds.lock().unwrap().len();
    if finds_a + finds_bc == 0 {
        println!(
            "   RESULT: no program of <= {kmax_use} ops within the searched MITM space ({:.1}s total)",
            t_start.elapsed().as_secs_f64()
        );
        println!(
            "   => current {}-op form stands within the searched space\n",
            tg.current_ops
        );
    } else {
        println!(
            "   RESULT: {} verified shorter program(s) found — see VERIFIED lines above\n",
            finds_a + finds_bc
        );
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let long = args.iter().any(|a| a == "--long");
    let mitm = args.iter().any(|a| a == "--mitm");
    let stretch = args.iter().any(|a| a == "--stretch");
    let names: Vec<&String> = args.iter().filter(|a| !a.starts_with("--")).collect();
    let threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    if mitm {
        let all = mitm_targets();
        let mut ran = 0;
        for tg in &all {
            let selected = if names.is_empty() {
                !tg.stretch || stretch
            } else {
                names.iter().any(|n| n.as_str() == tg.name)
            };
            if selected {
                run_mitm_target(tg, threads);
                ran += 1;
            }
        }
        if ran == 0 {
            eprintln!(
                "no MITM target matched; available: {}",
                all.iter().map(|t| t.name).collect::<Vec<_>>().join(", ")
            );
            std::process::exit(1);
        }
        return;
    }
    let all = targets();
    let mut ran = 0;
    for tg in &all {
        let selected = if names.is_empty() {
            !tg.long || long
        } else {
            names.iter().any(|n| n.as_str() == tg.name)
        };
        if selected {
            run_target(tg, threads);
            ran += 1;
        }
    }
    if ran == 0 {
        eprintln!(
            "no target matched; available: {}",
            all.iter().map(|t| t.name).collect::<Vec<_>>().join(", ")
        );
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx_for(n_inputs: usize, consts: &[(&str, u32)], f: &'static TargetFn) -> Ctx<'static> {
        let probes = probes(n_inputs);
        let mut base_names = Vec::new();
        let mut base_vals: Vec<Vp> = Vec::new();
        let mut base_is_const = Vec::new();
        for k in 0..n_inputs {
            base_names.push(format!("in{k}"));
            let mut v = [0u32; P];
            for (p, tup) in probes.iter().enumerate() {
                v[p] = tup[k];
            }
            base_vals.push(v);
            base_is_const.push(false);
        }
        for (nm, c) in consts {
            base_names.push(nm.to_string());
            base_vals.push([*c; P]);
            base_is_const.push(true);
        }
        let mut target = [0u32; P];
        for (p, tup) in probes.iter().enumerate() {
            target[p] = f(tup);
        }
        Ctx {
            n_inputs,
            base_names,
            base_vals,
            base_is_const,
            target,
            tested: AtomicU64::new(0),
            stop: AtomicBool::new(false),
            finds: Mutex::new(Vec::new()),
            unsolved: AtomicU64::new(0),
            f,
        }
    }

    fn search(ctx: &Ctx, kmax: usize) -> usize {
        for k in 1..=kmax {
            if !ctx.finds.lock().unwrap().is_empty() {
                return k - 1;
            }
            let mut w = W::new(ctx);
            if k == 1 {
                final_level(ctx, &mut w);
            } else {
                dfs(ctx, &mut w, k);
            }
        }
        let f = ctx.finds.lock().unwrap();
        if f.is_empty() {
            usize::MAX
        } else {
            f[0].len()
        }
    }

    /// End-to-end regression: the searcher must rediscover the stage2+3
    /// fusion (2 madds + xor = 3 ops for the 4-op unfused pair) — the very
    /// fusion that produced the current 11-op kernel hash.
    #[test]
    fn searcher_rediscovers_stage23_fusion() {
        static F: fn(&[u32]) -> u32 = |x| {
            // unfused stage2 then stage3, as in HASH_STAGES
            let a = x[0];
            let b = a.wrapping_mul(33).wrapping_add(0x1656_67B1); // stage2 affine
            (b.wrapping_add(0xD3A2_646C)) ^ (b << 9) // stage3
        };
        let ctx = ctx_for(
            1,
            &[
                ("KP", hs::KP),
                ("AP", hs::AP),
                ("KQ", hs::KQ),
                ("AQ", hs::AQ),
            ],
            &F,
        );
        let k = search(&ctx, 3);
        assert_eq!(k, 3, "stage2+3 must fuse to exactly 3 ops");
        // and every find verifies bit-exactly (report() already checked, but
        // double-check the stored programs here)
        for prog in ctx.finds.lock().unwrap().iter() {
            assert!(verify(&ctx, prog));
        }
    }

    /// A single affine stage must be found as one multiply_add, via the
    /// solved-KC path even when the pool lacks the constants.
    #[test]
    fn searcher_finds_affine_stage_in_one_op_with_solved_constants() {
        static F: fn(&[u32]) -> u32 = |x| hs::stage0(x[0]);
        let ctx = ctx_for(1, &[], &F); // empty pool: must solve K0, C0
        let k = search(&ctx, 1);
        assert_eq!(k, 1, "stage0 is one madd with solved constants");
    }

    /// The searcher must find the 2-op parity-from-e form (madd + shr) when
    /// the trick constants are in the pool — confirming the analytic find.
    #[test]
    fn searcher_confirms_two_op_parity_from_e() {
        static F: fn(&[u32]) -> u32 = |x| hs::stage5(x[0]) & 1;
        let ctx = ctx_for(
            1,
            &[("PEK", hs::PAR_E_K), ("PEC", hs::PAR_E_C), ("s31", 31)],
            &F,
        );
        let k = search(&ctx, 2);
        assert_eq!(k, 2, "parity from e must be found in 2 ops");
    }

    /// Sanity: no 1-op program computes stage1 (xor-shift needs >= 3).
    #[test]
    fn searcher_rejects_one_op_stage1() {
        static F: fn(&[u32]) -> u32 = |x| hs::stage1(x[0]);
        let ctx = ctx_for(1, &[("C1", hs::C1), ("sh1", 19)], &F);
        let k = search(&ctx, 1);
        assert_eq!(k, usize::MAX, "stage1 must not be computable in 1 op");
    }

    // ---- H-016 MITM machinery ----

    #[test]
    fn un_xorshift_roundtrips() {
        let mut rng = Rng::new(42);
        for _ in 0..10_000 {
            let x = rng.next_u64() as u32;
            for s in 1..32u32 {
                assert_eq!(un_xsr(x ^ (x >> s), s), x, "un_xsr failed at s={s}");
                assert_eq!(un_xsl(x ^ (x << s), s), x, "un_xsl failed at s={s}");
            }
        }
    }

    /// The affine canonicalization must be invariant under v -> K*v + C for
    /// odd K, and shift by exactly t for K = 2^t * odd — the two properties
    /// the meet-table lookups rely on.
    #[test]
    fn affine_canon_invariance() {
        let mut rng = Rng::new(7);
        for _ in 0..200 {
            let mut v = [0u32; P];
            for x in v.iter_mut() {
                *x = rng.next_u64() as u32;
            }
            let canon = affine_canon(&v).unwrap();
            for &(k, c) in &[
                (1u32, 0x1234_5678u32),
                (0xFFFF_FFFF, 7),
                (4097, 0x7ED5_5D16),
                (33, 0),
                (0xDEAD_BEEF | 1, 0xCAFE_BABE),
            ] {
                let mut w = [0u32; P];
                for p in 0..P {
                    w[p] = mad(v[p], k, c);
                }
                assert_eq!(
                    affine_canon(&w).unwrap(),
                    canon,
                    "canon not invariant under odd K={k:#x}, C={c:#x}"
                );
            }
            for t in 1..=TMAX {
                let k = 33u32 << t; // even multiplier with odd part 33
                let mut w = [0u32; P];
                for p in 0..P {
                    w[p] = mad(v[p], k, 0x0BAD_F00D);
                }
                assert_eq!(
                    affine_canon(&w).unwrap(),
                    shl_battery(&canon, t),
                    "canon of even-K map must equal canon shifted by t={t}"
                );
            }
        }
    }

    #[test]
    fn solve_affine_meet_recovers_even_multiplier() {
        let mut rng = Rng::new(99);
        let mut m = [0u32; P];
        for x in m.iter_mut() {
            *x = rng.next_u64() as u32;
        }
        for &(k, c) in &[
            (0x0000_1234u32, 0x0F0F_0F0Fu32), // even K (val 2)
            (33 << 9, 0xB55A_4F09),           // KQ-like: odd part 33, t=9
            (0x8000_0000, 1),                 // extreme valuation
            (4097, 0),                        // odd K
        ] {
            let mut r = [0u32; P];
            for p in 0..P {
                r[p] = mad(m[p], k, c);
            }
            let (ks, cs) = solve_affine_meet(&m, &r).expect("solve failed");
            for p in 0..P {
                assert_eq!(mad(m[p], ks, cs), r[p]);
            }
        }
    }

    /// End-to-end engine C regression: stage5(stage4(d)) must be rediscovered
    /// as a 4-op program shaped [affine meet on d] + [XsR(16)] + [XorC(C5)] —
    /// exercising the kf=0 prefix table, the affine-normalized meet solve,
    /// chain emission, and full verification.
    #[test]
    fn mitm_engine_c_rediscovers_g45_shape() {
        static F: fn(&[u32]) -> u32 = |x| hs::stage5(hs::stage4(x[0]));
        let ctx = ctx_for(1, &[], &F);
        let link_cs = build_link_consts(&[hs::C5], &[16]);
        let links = build_links(&link_cs);
        let fwd_tabs: Vec<FwdTab> = (0..=2).map(|kf| build_fwd_tab(&ctx, kf)).collect();
        let stats = MitmStats {
            fwd_nodes: AtomicU64::new(0),
            bwd_nodes: AtomicU64::new(0),
        };
        run_engine_c(&ctx, &links, &fwd_tabs, 4, 1 << 4, &stats, 2);
        let finds = ctx.finds.lock().unwrap();
        assert!(
            !finds.is_empty(),
            "engine C must reconstruct the 4-op stage4+stage5 form"
        );
        for prog in finds.iter() {
            assert!(prog.len() <= 4);
            assert!(verify(&ctx, prog));
        }
    }

    /// End-to-end engine B regression: f23(x) ^ PLANT must be found as
    /// [3-op f23 forward] + [planted xor link] at k=4 via the exact-j1 probe.
    #[test]
    fn mitm_engine_b_finds_planted_suffix() {
        const PLANT: u32 = 0x1234_5678;
        static F: fn(&[u32]) -> u32 = |x| hs::f23(x[0]) ^ PLANT;
        let ctx = ctx_for(
            1,
            &[
                ("KP", hs::KP),
                ("AP", hs::AP),
                ("KQ", hs::KQ),
                ("AQ", hs::AQ),
            ],
            &F,
        );
        let links = build_links(&[0, PLANT]);
        let bwd_tabs = build_bwd_tabs(&ctx.target, &links);
        let stats = MitmStats {
            fwd_nodes: AtomicU64::new(0),
            bwd_nodes: AtomicU64::new(0),
        };
        run_engine_b(&ctx, &bwd_tabs, 3, (2u32 << 4) - 2, &stats, 2);
        let finds = ctx.finds.lock().unwrap();
        assert!(
            !finds.is_empty(),
            "engine B must find the planted 4-op suffix form"
        );
        for prog in finds.iter() {
            assert!(prog.len() <= 4);
            assert!(verify(&ctx, prog));
        }
    }
}
