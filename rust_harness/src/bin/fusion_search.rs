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
//! Usage:
//!   fusion_search              # standard suite (all depth<=3 questions)
//!   fusion_search --long       # adds the two depth-4 two-input searches
//!   fusion_search g45 par_d    # run specific targets by name

use perf_harness::problem::hashseg as hs;
use perf_harness::problem::{myhash, Rng};
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
    for k in 1..=tg.kmax {
        if !ctx.finds.lock().unwrap().is_empty() {
            break; // already found something shorter at k-1
        }
        let k_start = Instant::now();
        if k == 1 {
            let mut w = W::new(&ctx);
            final_level(&ctx, &mut w);
            ctx.tested.fetch_add(w.tested_local, Ordering::Relaxed);
        } else {
            // Thread over first-level candidates.
            let mut l1: Vec<(Inst, Vp)> = Vec::new();
            {
                let w = W::new(&ctx);
                enumerate_level(&w, |inst, v| l1.push((inst, v)));
            }
            let next = AtomicU64::new(0);
            std::thread::scope(|scope| {
                for _ in 0..threads {
                    scope.spawn(|| {
                        let mut w = W::new(&ctx);
                        loop {
                            let idx = next.fetch_add(1, Ordering::Relaxed) as usize;
                            if idx >= l1.len() || ctx.stop.load(Ordering::Relaxed) {
                                break;
                            }
                            let (inst, v) = l1[idx].clone();
                            let undo = w.push(inst, v);
                            dfs(&ctx, &mut w, k - 1);
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

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let long = args.iter().any(|a| a == "--long");
    let names: Vec<&String> = args.iter().filter(|a| !a.starts_with("--")).collect();
    let threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
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
}
