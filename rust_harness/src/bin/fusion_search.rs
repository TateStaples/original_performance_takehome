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
//!   * programs of exactly k ops for k = 1 .. max_ops (iterative deepening);
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
const PROBE_COUNT: usize = 32;
type ProbeValues = [u32; PROBE_COUNT];

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
fn multiply_add(a: u32, b: u32, c: u32) -> u32 {
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
    MultiplyAdd(usize, usize, usize),
    /// op(pool[i], c) with solved constant c.
    BinConstRight(Op, usize, u32),
    /// op(c, pool[i]) with solved constant c (non-commutative right forms).
    BinConstLeft(Op, u32, usize),
    /// pool[i] * pool[j] + c.
    MultiplyAddConst(usize, usize, u32),
    /// pool[i] * K + C.
    MultiplyAddAffine(usize, u32, u32),
}

/// A reference target function evaluated on an input tuple.
type TargetFn = dyn Fn(&[u32]) -> u32 + Sync;

struct Ctx<'a> {
    input_count: usize,
    base_names: Vec<String>,
    base_vals: Vec<ProbeValues>,
    base_is_const: Vec<bool>,
    target: ProbeValues,
    /// complete candidate programs checked (final-level checks).
    tested_count: AtomicU64,
    should_stop: AtomicBool,
    finds: Mutex<Vec<Vec<Inst>>>,
    /// final-level constant solves skipped for lack of an odd pivot.
    unsolved_count: AtomicU64,
    reference_fn: &'a TargetFn,
}

/// Per-thread mutable search state.
struct SearchState {
    vals: Vec<ProbeValues>,
    probe0_vals: Vec<u32>,
    is_const: Vec<bool>,
    /// per-temp "has been referenced" flags (parallel to temps only).
    temp_used: Vec<bool>,
    unused_temp_count: usize,
    prog: Vec<Inst>,
    base_count: usize,
    tested_local: u64,
}

impl SearchState {
    fn new(ctx: &Ctx) -> SearchState {
        SearchState {
            vals: ctx.base_vals.clone(),
            probe0_vals: ctx.base_vals.iter().map(|v| v[0]).collect(),
            is_const: ctx.base_is_const.clone(),
            temp_used: Vec::new(),
            unused_temp_count: 0,
            prog: Vec::new(),
            base_count: ctx.base_vals.len(),
            tested_local: 0,
        }
    }

    /// Mark operand as referenced; returns true if it was an unused temp
    /// (so pop can undo).
    fn mark(&mut self, idx: usize) -> bool {
        if idx >= self.base_count && !self.temp_used[idx - self.base_count] {
            self.temp_used[idx - self.base_count] = true;
            self.unused_temp_count -= 1;
            true
        } else {
            false
        }
    }

    fn push(&mut self, inst: Inst, v: ProbeValues) -> [bool; 3] {
        let mut undo = [false; 3];
        match inst {
            Inst::Bin(_, i, j) => {
                undo[0] = self.mark(i);
                if j != i {
                    undo[1] = self.mark(j);
                }
            }
            Inst::MultiplyAdd(i, j, k) => {
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
        self.probe0_vals.push(v[0]);
        self.is_const.push(false);
        self.temp_used.push(false);
        self.unused_temp_count += 1;
        undo
    }

    fn pop(&mut self, undo: [bool; 3]) {
        let inst = self.prog.pop().unwrap();
        self.vals.pop();
        self.probe0_vals.pop();
        self.is_const.pop();
        self.temp_used.pop();
        self.unused_temp_count -= 1;
        let ops: [usize; 3] = match inst {
            Inst::Bin(_, i, j) => [i, j, usize::MAX],
            Inst::MultiplyAdd(i, j, k) => [i, j, k],
            _ => unreachable!(),
        };
        for (n, &o) in ops.iter().enumerate() {
            if undo[n] {
                self.temp_used[o - self.base_count] = false;
                self.unused_temp_count += 1;
            }
        }
    }

    /// Is `v` (with first probe `candidate_probe0`) identical on all probes to an existing
    /// pool value? (Duplicate pruning.)
    fn is_dup(&self, candidate_probe0: u32, v: &ProbeValues) -> bool {
        for (i, &probe0_vals) in self.probe0_vals.iter().enumerate() {
            if probe0_vals == candidate_probe0 && &self.vals[i] == v {
                return true;
            }
        }
        false
    }

    /// Indices of temps not yet referenced by any later op.
    fn unused_list(&self) -> Vec<usize> {
        (0..self.temp_used.len())
            .filter(|&t| !self.temp_used[t])
            .map(|t| t + self.base_count)
            .collect()
    }
}

fn eval_bin(op: Op, a: &ProbeValues, b: &ProbeValues) -> ProbeValues {
    let mut out = [0u32; PROBE_COUNT];
    for p in 0..PROBE_COUNT {
        out[p] = bin(op, a[p], b[p]);
    }
    out
}

fn eval_multiply_add(a: &ProbeValues, b: &ProbeValues, c: &ProbeValues) -> ProbeValues {
    let mut out = [0u32; PROBE_COUNT];
    for p in 0..PROBE_COUNT {
        out[p] = multiply_add(a[p], b[p], c[p]);
    }
    out
}

/// Enumerate every candidate instruction over the current pool (dedup'd,
/// const-const skipped, commutative ops canonicalized) and call `f`.
fn enumerate_level(w: &SearchState, mut f: impl FnMut(Inst, ProbeValues)) {
    let pool_size = w.vals.len();
    for &op in BIN_OPS.iter() {
        for i in 0..pool_size {
            let j0 = if op.commutative() { i } else { 0 };
            for j in j0..pool_size {
                if w.is_const[i] && w.is_const[j] {
                    continue;
                }
                if op == Sub && i == j {
                    continue;
                }
                let candidate_probe0 = bin(op, w.probe0_vals[i], w.probe0_vals[j]);
                let v = eval_bin(op, &w.vals[i], &w.vals[j]);
                if w.is_dup(candidate_probe0, &v) {
                    continue;
                }
                f(Inst::Bin(op, i, j), v);
            }
        }
    }
    for i in 0..pool_size {
        for j in i..pool_size {
            for k in 0..pool_size {
                if w.is_const[i] && w.is_const[j] && w.is_const[k] {
                    continue;
                }
                let candidate_probe0 = multiply_add(w.probe0_vals[i], w.probe0_vals[j], w.probe0_vals[k]);
                let v = eval_multiply_add(&w.vals[i], &w.vals[j], &w.vals[k]);
                if w.is_dup(candidate_probe0, &v) {
                    continue;
                }
                f(Inst::MultiplyAdd(i, j, k), v);
            }
        }
    }
}

fn dfs(ctx: &Ctx, w: &mut SearchState, remaining_ops: usize) {
    if ctx.should_stop.load(Ordering::Relaxed) {
        return;
    }
    // Every temp must eventually be referenced: r remaining ops can consume
    // at most 3 operands each, and all but the last create one more value
    // needing a reference. Prune when that's impossible.
    if w.unused_temp_count > 2 * remaining_ops + 1 {
        return;
    }
    if remaining_ops == 1 {
        final_level(ctx, w);
        return;
    }
    let mut cands: Vec<(Inst, ProbeValues)> = Vec::with_capacity(4096);
    enumerate_level(w, |inst, v| cands.push((inst, v)));
    for (inst, v) in cands {
        if ctx.should_stop.load(Ordering::Relaxed) {
            return;
        }
        let undo = w.push(inst, v);
        dfs(ctx, w, remaining_ops - 1);
        w.pop(undo);
    }
}

/// Depth-1 remaining: enumerate/solve the final op against the target.
fn final_level(ctx: &Ctx, w: &mut SearchState) {
    let unused_temp_indices = w.unused_list();
    if unused_temp_indices.len() > 3 {
        return;
    }
    let target = &ctx.target;
    let target_probe0 = target[0];
    let pool_size = w.vals.len();

    let covers2 = |i: usize, j: usize| unused_temp_indices.iter().all(|&u| u == i || u == j);
    let covers3 = |i: usize, j: usize, k: usize| unused_temp_indices.iter().all(|&u| u == i || u == j || u == k);

    // ---- pooled operands ----
    for &op in BIN_OPS.iter() {
        for i in 0..pool_size {
            let j0 = if op.commutative() { i } else { 0 };
            for j in j0..pool_size {
                if w.is_const[i] && w.is_const[j] {
                    continue;
                }
                w.tested_local += 1;
                if bin(op, w.probe0_vals[i], w.probe0_vals[j]) != target_probe0 || !covers2(i, j) {
                    continue;
                }
                if (0..PROBE_COUNT).all(|p| bin(op, w.vals[i][p], w.vals[j][p]) == target[p]) {
                    report(ctx, w, Inst::Bin(op, i, j));
                }
            }
        }
    }
    for i in 0..pool_size {
        for j in i..pool_size {
            for k in 0..pool_size {
                if w.is_const[i] && w.is_const[j] && w.is_const[k] {
                    continue;
                }
                w.tested_local += 1;
                if multiply_add(w.probe0_vals[i], w.probe0_vals[j], w.probe0_vals[k]) != target_probe0 || !covers3(i, j, k) {
                    continue;
                }
                if (0..PROBE_COUNT).all(|p| multiply_add(w.vals[i][p], w.vals[j][p], w.vals[k][p]) == target[p]) {
                    report(ctx, w, Inst::MultiplyAdd(i, j, k));
                }
            }
        }
    }

    // ---- solved-constant forms (one non-const pool operand sole_operand) ----
    for i in 0..pool_size {
        if w.is_const[i] {
            continue;
        }
        if !unused_temp_indices.iter().all(|&u| u == i) {
            continue; // solved forms use only sole_operand; all unused temps must be sole_operand
        }
        let sole_operand = &w.vals[i];

        // xor / add / sub (both orders): c determined by probe 0.
        let c = target_probe0 ^ sole_operand[0];
        w.tested_local += 1;
        if (0..PROBE_COUNT).all(|p| (sole_operand[p] ^ c) == target[p]) {
            report(ctx, w, Inst::BinConstRight(Xor, i, c));
        }
        let c = target_probe0.wrapping_sub(sole_operand[0]);
        w.tested_local += 1;
        if (0..PROBE_COUNT).all(|p| sole_operand[p].wrapping_add(c) == target[p]) {
            report(ctx, w, Inst::BinConstRight(Add, i, c));
        }
        let c = sole_operand[0].wrapping_sub(target_probe0);
        w.tested_local += 1;
        if (0..PROBE_COUNT).all(|p| sole_operand[p].wrapping_sub(c) == target[p]) {
            report(ctx, w, Inst::BinConstRight(Sub, i, c));
        }
        let c = target_probe0.wrapping_add(sole_operand[0]);
        w.tested_local += 1;
        if (0..PROBE_COUNT).all(|p| c.wrapping_sub(sole_operand[p]) == target[p]) {
            report(ctx, w, Inst::BinConstLeft(Sub, c, i));
        }

        // and / or: bitwise-solved constant.
        let mut c_and = 0u32;
        for p in 0..PROBE_COUNT {
            c_and |= sole_operand[p] & target[p];
        }
        w.tested_local += 1;
        if (0..PROBE_COUNT).all(|p| (sole_operand[p] & c_and) == target[p]) {
            report(ctx, w, Inst::BinConstRight(And, i, c_and));
        }
        let mut c_or = 0u32;
        for p in 0..PROBE_COUNT {
            c_or |= target[p] & !sole_operand[p];
        }
        w.tested_local += 1;
        if (0..PROBE_COUNT).all(|p| (sole_operand[p] | c_or) == target[p]) {
            report(ctx, w, Inst::BinConstRight(Or, i, c_or));
        }

        // shl / shr by any amount 0..31.
        for s in 0..32u32 {
            w.tested_local += 2;
            if (sole_operand[0] << s) == target_probe0 && (0..PROBE_COUNT).all(|p| (sole_operand[p] << s) == target[p]) {
                report(ctx, w, Inst::BinConstRight(Shl, i, s));
            }
            if (sole_operand[0] >> s) == target_probe0 && (0..PROBE_COUNT).all(|p| (sole_operand[p] >> s) == target[p]) {
                report(ctx, w, Inst::BinConstRight(Shr, i, s));
            }
        }

        // multiply_add sole_operand*K + C with both K and C solved: pick a probe pair
        // with odd difference (K then unique), C follows.
        let mut solved = false;
        'pairs: for p in 0..PROBE_COUNT {
            for q in (p + 1)..PROBE_COUNT {
                let dx = sole_operand[p].wrapping_sub(sole_operand[q]);
                if dx & 1 == 1 {
                    let dt = target[p].wrapping_sub(target[q]);
                    let k = dt.wrapping_mul(modinv32(dx));
                    let c = target[p].wrapping_sub(k.wrapping_mul(sole_operand[p]));
                    w.tested_local += 1;
                    if (0..PROBE_COUNT).all(|r| multiply_add(sole_operand[r], k, c) == target[r]) {
                        report(ctx, w, Inst::MultiplyAddAffine(i, k, c));
                    }
                    solved = true;
                    break 'pairs;
                }
            }
        }
        if !solved {
            ctx.unsolved_count.fetch_add(1, Ordering::Relaxed);
        }
    }

    // multiply_add pool[i]*pool[j] + solved C.
    for i in 0..pool_size {
        for j in i..pool_size {
            if w.is_const[i] && w.is_const[j] {
                continue;
            }
            if !covers2(i, j) {
                continue;
            }
            let c = target_probe0.wrapping_sub(w.probe0_vals[i].wrapping_mul(w.probe0_vals[j]));
            w.tested_local += 1;
            if (0..PROBE_COUNT).all(|p| multiply_add(w.vals[i][p], w.vals[j][p], c) == target[p]) {
                report(ctx, w, Inst::MultiplyAddConst(i, j, c));
            }
        }
    }
}

/// A candidate matched all probes: verify against the reference function on
/// 10M+ inputs, then record + print.
fn report(ctx: &Ctx, w: &SearchState, last: Inst) {
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
            ctx.should_stop.store(true, Ordering::Relaxed);
        }
    }
}

/// Execute `prog` on concrete inputs (base constants from ctx).
fn run_prog(ctx: &Ctx, prog: &[Inst], inputs: &[u32]) -> u32 {
    let base_count = ctx.base_vals.len();
    let mut vals: Vec<u32> = Vec::with_capacity(base_count + prog.len());
    vals.extend_from_slice(inputs);
    for b in ctx.input_count..base_count {
        vals.push(ctx.base_vals[b][0]); // constants are probe-invariant
    }
    for inst in prog {
        let v = match *inst {
            Inst::Bin(op, i, j) => bin(op, vals[i], vals[j]),
            Inst::MultiplyAdd(i, j, k) => multiply_add(vals[i], vals[j], vals[k]),
            Inst::BinConstRight(op, i, c) => bin(op, vals[i], c),
            Inst::BinConstLeft(op, c, i) => bin(op, c, vals[i]),
            Inst::MultiplyAddConst(i, j, c) => multiply_add(vals[i], vals[j], c),
            Inst::MultiplyAddAffine(i, k, c) => multiply_add(vals[i], k, c),
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
    let check = |ins: &[u32]| run_prog(ctx, prog, ins) == (ctx.reference_fn)(ins);
    match ctx.input_count {
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
    let base_count = ctx.base_vals.len();
    let name = |idx: usize, ctx: &Ctx| -> String {
        if idx < base_count {
            ctx.base_names[idx].clone()
        } else {
            format!("t{}", idx - base_count + 1)
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
            Inst::MultiplyAdd(a, b, c) => {
                format!("madd({}, {}, {})", name(a, ctx), name(b, ctx), name(c, ctx))
            }
            Inst::BinConstRight(op, a, c) => format!("{}({}, {:#010x})", op.name(), name(a, ctx), c),
            Inst::BinConstLeft(op, c, a) => format!("{}({:#010x}, {})", op.name(), c, name(a, ctx)),
            Inst::MultiplyAddConst(a, b, c) => format!("madd({}, {}, {:#010x})", name(a, ctx), name(b, ctx), c),
            Inst::MultiplyAddAffine(a, k, c) => {
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
    input_count: usize,
    consts: Vec<(&'static str, u32)>,
    max_ops: usize,
    current_ops: usize,
    reference_fn: Box<TargetFn>,
    is_long_suite: bool,
}

fn probes(input_count: usize) -> Vec<Vec<u32>> {
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
    let mut out = Vec::with_capacity(PROBE_COUNT);
    for p in 0..PROBE_COUNT {
        let mut tup = Vec::with_capacity(input_count);
        for k in 0..input_count {
            // First rows pair structured values with randoms so single-input
            // structure is exercised; later rows are fully random.
            let v = if p < structured.len() && k == p % input_count.max(1) {
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

fn run_target(target_spec: &Target, threads: usize) {
    let probes = probes(target_spec.input_count);
    let mut base_names: Vec<String> = Vec::new();
    let mut base_vals: Vec<ProbeValues> = Vec::new();
    let mut base_is_const: Vec<bool> = Vec::new();
    let input_names = ["x", "y"];
    for k in 0..target_spec.input_count {
        base_names.push(input_names[k].to_string());
        let mut v = [0u32; PROBE_COUNT];
        for (p, tup) in probes.iter().enumerate() {
            v[p] = tup[k];
        }
        base_vals.push(v);
        base_is_const.push(false);
    }
    for (nm, c) in &target_spec.consts {
        base_names.push(format!("{nm}={c:#010x}"));
        base_vals.push([*c; PROBE_COUNT]);
        base_is_const.push(true);
    }
    let mut target = [0u32; PROBE_COUNT];
    for (p, tup) in probes.iter().enumerate() {
        target[p] = (target_spec.reference_fn)(tup);
    }

    println!(
        "== target {} : {} (current {} ops, searching k<= {}) ==",
        target_spec.name, target_spec.desc, target_spec.current_ops, target_spec.max_ops
    );
    println!(
        "   pool: [{}]",
        base_names
            .iter()
            .skip(target_spec.input_count)
            .cloned()
            .collect::<Vec<_>>()
            .join(", ")
    );

    let ctx = Ctx {
        input_count: target_spec.input_count,
        base_names,
        base_vals,
        base_is_const,
        target,
        tested_count: AtomicU64::new(0),
        should_stop: AtomicBool::new(false),
        finds: Mutex::new(Vec::new()),
        unsolved_count: AtomicU64::new(0),
        reference_fn: &*target_spec.reference_fn,
    };

    // k = 0: target already available?
    for (i, v) in ctx.base_vals.iter().enumerate() {
        if *v == target {
            println!("   !! target equals base value {}", ctx.base_names[i]);
        }
    }

    let t_start = Instant::now();
    search_iterative(&ctx, target_spec.max_ops, threads);

    let finds = ctx.finds.lock().unwrap();
    let unsolved_count = ctx.unsolved_count.load(Ordering::Relaxed);
    if finds.is_empty() {
        println!(
            "   RESULT: no program of <= {} ops within this space ({} candidates, {:.1}s{})",
            target_spec.max_ops,
            ctx.tested_count.load(Ordering::Relaxed),
            t_start.elapsed().as_secs_f64(),
            if unsolved_count > 0 {
                format!(", {unsolved_count} madd-K solves skipped: no odd pivot")
            } else {
                String::new()
            }
        );
        println!(
            "   => current {}-op form stands within the searched space\n",
            target_spec.current_ops
        );
    } else {
        println!(
            "   RESULT: {} verified shorter program(s) found ({} ops < current {})\n",
            finds.len(),
            finds[0].len(),
            target_spec.current_ops
        );
    }
}

/// The forward-only iterative-deepening search (k = 1..=max_ops, exhaustive per
/// k within the ctx's pool): forward DFS to depth k-1 + solved final level.
/// Shared by the legacy suite (`run_target`) and the MITM runner's engine A.
fn search_iterative(ctx: &Ctx, max_ops: usize, threads: usize) {
    for op_count in 1..=max_ops {
        if !ctx.finds.lock().unwrap().is_empty() {
            break; // already found something shorter at op_count-1
        }
        let iteration_start = Instant::now();
        if op_count == 1 {
            let mut w = SearchState::new(ctx);
            final_level(ctx, &mut w);
            ctx.tested_count.fetch_add(w.tested_local, Ordering::Relaxed);
        } else {
            // Thread over first-level candidates.
            let mut first_level_candidates: Vec<(Inst, ProbeValues)> = Vec::new();
            {
                let w = SearchState::new(ctx);
                enumerate_level(&w, |inst, v| first_level_candidates.push((inst, v)));
            }
            let next = AtomicU64::new(0);
            std::thread::scope(|scope| {
                for _ in 0..threads {
                    scope.spawn(|| {
                        let mut w = SearchState::new(ctx);
                        loop {
                            let idx = next.fetch_add(1, Ordering::Relaxed) as usize;
                            if idx >= first_level_candidates.len() || ctx.should_stop.load(Ordering::Relaxed) {
                                break;
                            }
                            let (inst, v) = first_level_candidates[idx].clone();
                            let undo = w.push(inst, v);
                            dfs(ctx, &mut w, op_count - 1);
                            w.pop(undo);
                        }
                        ctx.tested_count.fetch_add(w.tested_local, Ordering::Relaxed);
                    });
                }
            });
        }
        println!(
            "   op_count={op_count}: exhausted in {:.1}s (cumulative candidates tested: {})",
            iteration_start.elapsed().as_secs_f64(),
            ctx.tested_count.load(Ordering::Relaxed)
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
            input_count: 1,
            consts: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("STAGE4_MULTIPLIER", STAGE4_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("sh1", 19),
                ("sh5", 16),
                ("s12", 12),
            ]),
            max_ops: 3,
            current_ops: 11,
            reference_fn: Box::new(|x| myhash(x[0])),
            is_long_suite: false,
        },
        Target {
            name: "g01",
            desc: "stage1(stage0(a)) [madd,shr,xor,xor]",
            input_count: 1,
            consts: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("p12", 4096),
                ("s12", 12),
                ("sh1", 19),
                ("C1s", STAGE1_XOR_CONSTANT >> 19),
                ("C1i", STAGE1_XOR_CONSTANT ^ (STAGE1_XOR_CONSTANT >> 19)),
                ("C0x1", STAGE0_ADD_CONSTANT ^ STAGE1_XOR_CONSTANT),
            ]),
            max_ops: 3,
            current_ops: 4,
            reference_fn: Box::new(|x| hs::stage1(hs::stage0(x[0]))),
            is_long_suite: false,
        },
        Target {
            name: "a2u",
            desc: "sigma19(stage0(a)) (pre-STAGE1_XOR_CONSTANT point) [madd,shr,xor]",
            input_count: 1,
            consts: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("p12", 4096),
                ("s12", 12),
                ("sh1", 19),
                ("p19", 1 << 19),
            ]),
            max_ops: 2,
            current_ops: 3,
            reference_fn: Box::new(|x| {
                let b = hs::stage0(x[0]);
                b ^ (b >> 19)
            }),
            is_long_suite: false,
        },
        Target {
            name: "b2c",
            desc: "stage1 alone [shr,xor,xor]",
            input_count: 1,
            consts: mk(&[
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("sh1", 19),
                ("C1s", STAGE1_XOR_CONSTANT >> 19),
                ("C1i", STAGE1_XOR_CONSTANT ^ (STAGE1_XOR_CONSTANT >> 19)),
                ("p19", 1 << 19),
                ("p13", 1 << 13),
                ("s13", 13),
            ]),
            max_ops: 2,
            current_ops: 3,
            reference_fn: Box::new(|x| hs::stage1(x[0])),
            is_long_suite: false,
        },
        Target {
            name: "g123mid",
            desc: "f23(u ^ STAGE1_XOR_CONSTANT) (stage1 tail + fused23) [xor,madd,madd,xor]",
            input_count: 1,
            consts: mk(&[
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("KPC1", F23_P_MULTIPLIER.wrapping_mul(STAGE1_XOR_CONSTANT)),
                ("KQC1", F23_Q_MULTIPLIER.wrapping_mul(STAGE1_XOR_CONSTANT)),
                ("APK", F23_P_CONSTANT.wrapping_add(F23_P_MULTIPLIER.wrapping_mul(STAGE1_XOR_CONSTANT))),
                ("AQK", F23_Q_CONSTANT.wrapping_add(F23_Q_MULTIPLIER.wrapping_mul(STAGE1_XOR_CONSTANT))),
                ("s5", 5),
                ("s9", 9),
            ]),
            max_ops: 3,
            current_ops: 4,
            reference_fn: Box::new(|x| hs::f23(x[0] ^ hs::STAGE1_XOR_CONSTANT)),
            is_long_suite: false,
        },
        Target {
            name: "f23",
            desc: "fused stage2+3 [madd,madd,xor]",
            input_count: 1,
            consts: mk(&[
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("C2", 0x1656_67B1),
                ("C3", 0xD3A2_646C),
                ("s5", 5),
                ("s9", 9),
                ("p9", 512),
            ]),
            max_ops: 2,
            current_ops: 3,
            reference_fn: Box::new(|x| hs::f23(x[0])),
            is_long_suite: false,
        },
        Target {
            name: "g234",
            desc: "stage4(f23(c)) [madd,madd,xor,madd]",
            input_count: 1,
            consts: mk(&[
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("STAGE4_MULTIPLIER", STAGE4_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("KP9", F23_P_MULTIPLIER.wrapping_mul(9)),
                ("KQ9", F23_Q_MULTIPLIER.wrapping_mul(9)),
                ("AP9", F23_P_CONSTANT.wrapping_mul(9).wrapping_add(STAGE4_ADD_CONSTANT)),
                ("AQ9", F23_Q_CONSTANT.wrapping_mul(9)),
                ("s3", 3),
            ]),
            max_ops: 3,
            current_ops: 4,
            reference_fn: Box::new(|x| hs::stage4(hs::f23(x[0]))),
            is_long_suite: false,
        },
        Target {
            name: "g45",
            desc: "stage5(stage4(d)) [madd,xor,shr,xor]",
            input_count: 1,
            consts: mk(&[
                ("STAGE4_MULTIPLIER", STAGE4_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("sh5", 16),
                ("C5s", STAGE5_XOR_CONSTANT >> 16),
                ("C5i", STAGE5_XOR_CONSTANT ^ (STAGE5_XOR_CONSTANT >> 16)),
                ("C45", STAGE4_ADD_CONSTANT ^ STAGE5_XOR_CONSTANT),
                ("s3", 3),
                ("p3", 8),
                ("p16", 1 << 16),
            ]),
            max_ops: 3,
            current_ops: 4,
            reference_fn: Box::new(|x| hs::stage5(hs::stage4(x[0]))),
            is_long_suite: false,
        },
        Target {
            name: "e2out",
            desc: "stage5 alone [xor,shr,xor]",
            input_count: 1,
            consts: mk(&[
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("sh5", 16),
                ("C5s", STAGE5_XOR_CONSTANT >> 16),
                ("C5i", STAGE5_XOR_CONSTANT ^ (STAGE5_XOR_CONSTANT >> 16)),
                ("p16", 1 << 16),
            ]),
            max_ops: 2,
            current_ops: 3,
            reference_fn: Box::new(|x| hs::stage5(x[0])),
            is_long_suite: false,
        },
        Target {
            name: "head2",
            desc: "stage0(v ^ n) (fold-in + stage0) [xor,madd]",
            input_count: 2,
            consts: mk(&[("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT), ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER), ("p12", 4096), ("s12", 12)]),
            max_ops: 1,
            current_ops: 2,
            reference_fn: Box::new(|x| hs::stage0(x[0] ^ x[1])),
            is_long_suite: false,
        },
        Target {
            name: "head3",
            desc: "stage1(stage0(v ^ n)) (fold-in + 2 stages) [xor,madd,shr,xor,xor]",
            input_count: 2,
            consts: vec![
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("p12", 4096),
                ("sh1", 19),
                ("s12", 12),
            ],
            max_ops: 4,
            current_ops: 5,
            reference_fn: Box::new(|x| hs::stage1(hs::stage0(x[0] ^ x[1]))),
            is_long_suite: true,
        },
        Target {
            name: "xr3",
            desc: "next-round madd of sigma16(e)^n (STAGE5_XOR_CONSTANT pre-xored into tree) [shr,xor,xor,madd]",
            input_count: 2,
            consts: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("sh5", 16),
                ("p16", 1 << 16),
                ("K016", STAGE0_MULTIPLIER.wrapping_mul(1 << 16)),
            ]),
            max_ops: 3,
            current_ops: 4,
            reference_fn: Box::new(|x| {
                let e = x[0];
                let sigma16_e = e ^ (e >> 16);
                hs::stage0(sigma16_e ^ x[1])
            }),
            is_long_suite: false,
        },
        Target {
            name: "xr4",
            desc: "cross-round: stage0(stage5(e) ^ n) [shr,xor,xor,xor,madd]",
            input_count: 2,
            consts: vec![
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("sh5", 16),
                ("C5i", hs::STAGE5_XOR_CONSTANT ^ (hs::STAGE5_XOR_CONSTANT >> 16)),
                ("p16", 1 << 16),
            ],
            max_ops: 4,
            current_ops: 5,
            reference_fn: Box::new(|x| hs::stage0(hs::stage5(x[0]) ^ x[1])),
            is_long_suite: true,
        },
        Target {
            name: "u2e",
            desc: "stage4(f23(u ^ STAGE1_XOR_CONSTANT)) (stage1 tail through stage4) [xor,madd,madd,xor,madd]",
            input_count: 1,
            consts: vec![
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("STAGE4_MULTIPLIER", STAGE4_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("KP9", F23_P_MULTIPLIER.wrapping_mul(9)),
            ],
            max_ops: 4,
            current_ops: 5,
            reference_fn: Box::new(|x| hs::stage4(hs::f23(x[0] ^ hs::STAGE1_XOR_CONSTANT))),
            is_long_suite: true,
        },
        Target {
            name: "par_c_deep",
            desc: "parity bit from stage1 output c in <=4 ops (5 via par_d chain)",
            input_count: 1,
            consts: vec![
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("PDK", PARITY_FROM_D_MULTIPLIER),
                ("PDC", PARITY_FROM_D_CONSTANT),
                ("s31", 31),
                ("p31", 1 << 31),
            ],
            max_ops: 4,
            current_ops: 5,
            reference_fn: Box::new(|x| hs::stage5(hs::stage4(hs::f23(x[0]))) & 1),
            is_long_suite: true,
        },
        Target {
            name: "par_d",
            desc: "parity bit (myhash&1) from f23 output d [vs 5 ops via value chain]",
            input_count: 1,
            consts: mk(&[
                ("STAGE4_MULTIPLIER", STAGE4_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("PDK", PARITY_FROM_D_MULTIPLIER),
                ("PDC", PARITY_FROM_D_CONSTANT),
                ("PEK", PARITY_FROM_E_MULTIPLIER),
                ("p31", 1 << 31),
                ("b17", 0x0001_0001),
                ("s31", 31),
                ("s16", 16),
                ("s15", 15),
            ]),
            max_ops: 2,
            current_ops: 5,
            reference_fn: Box::new(|x| hs::stage5(hs::stage4(x[0])) & 1),
            is_long_suite: false,
        },
        Target {
            name: "par_e",
            desc: "parity bit from stage4 output e [vs 4 ops via value chain]",
            input_count: 1,
            consts: mk(&[
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("PEK", PARITY_FROM_E_MULTIPLIER),
                ("PEC", PARITY_FROM_E_CONSTANT),
                ("p31", 1 << 31),
                ("b17", 0x0001_0001),
                ("s31", 31),
                ("s16", 16),
                ("s15", 15),
            ]),
            max_ops: 2,
            current_ops: 4,
            reference_fn: Box::new(|x| hs::stage5(x[0]) & 1),
            is_long_suite: false,
        },
        Target {
            name: "par_c",
            desc: "parity bit from stage1 output c (before f23)",
            input_count: 1,
            consts: mk(&[
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("STAGE4_MULTIPLIER", STAGE4_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("PDK", hs::PARITY_FROM_D_MULTIPLIER),
                ("PDC", hs::PARITY_FROM_D_CONSTANT),
                ("p31", 1 << 31),
                ("s31", 31),
                ("s15", 15),
            ]),
            max_ops: 3,
            current_ops: 8,
            reference_fn: Box::new(|x| hs::stage5(hs::stage4(hs::f23(x[0]))) & 1),
            is_long_suite: false,
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
//           canonical battery shifted left by t = 0..=MAX_EVEN_MULTIPLIER_SHIFT on the table side.
// Both are exact equivalences (proofs in `affine_canon`'s comment), so a
// table hit + constant solve + full-battery check loses nothing.

/// Max power-of-two factor searched for even meet multipliers K = 2^t * odd.
const MAX_EVEN_MULTIPLIER_SHIFT: u32 = 12;
/// Cap on the link-constant pool (printed per target for the honest record).
const LINK_CONSTANT_POOL_CAP: usize = 72;

/// Odd multipliers for backward affine links (`y -> K*y + c`). Chosen as the
/// machine-plausible family: stage multipliers, 2^j +/- 1, small odds, -1.
const ODD_LINK_MULTIPLIERS: [u32; 16] = [
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
const TAG_XOR_NORM: u64 = 0x584f_524e_5f5f_2222;
const TAG_AFFINE_CANON: u64 = 0x4146_464e_5f5f_3333;

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
    for &word in words {
        h = (h ^ u64::from(word)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        h ^= h >> 29;
    }
    h
}

/// Battery signature invariant under `v -> v ^ c` for any constant c.
fn xor_norm(v: &ProbeValues) -> [u32; PROBE_COUNT - 1] {
    let mut d = [0u32; PROBE_COUNT - 1];
    for p in 1..PROBE_COUNT {
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
/// (t <= MAX_EVEN_MULTIPLIER_SHIFT, k odd) the canonical battery of K*v + C equals the canonical
/// battery of v shifted left by t (same derivation, valuations all shift by
/// t) — which is why tables store the t-shifted variants.
///
/// Returns None for a constant battery (all differences zero).
fn affine_canon(v: &ProbeValues) -> Option<[u32; PROBE_COUNT - 1]> {
    let mut d = [0u32; PROBE_COUNT - 1];
    let mut s_min = 33u32;
    let mut q = usize::MAX;
    for p in 1..PROBE_COUNT {
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

fn shl_battery(d: &[u32; PROBE_COUNT - 1], t: u32) -> [u32; PROBE_COUNT - 1] {
    let mut out = *d;
    for x in out.iter_mut() {
        *x <<= t;
    }
    out
}

/// Solve `r = m ^ c` over the whole battery (None if inconsistent).
fn solve_xor_meet(m: &ProbeValues, r: &ProbeValues) -> Option<u32> {
    let c = r[0] ^ m[0];
    if (0..PROBE_COUNT).all(|p| (m[p] ^ c) == r[p]) {
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
fn solve_affine_meet(m: &ProbeValues, r: &ProbeValues) -> Option<(u32, u32)> {
    let mut s_min = 33u32;
    let mut q = 0usize;
    for p in 1..PROBE_COUNT {
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
        if (0..PROBE_COUNT).all(|p| multiply_add(m[p], k, c) == r[p]) {
            Some((k, c))
        } else {
            None
        }
    };
    if s == 0 {
        return check(dr.wrapping_mul(modinv32(dm)));
    }
    let k0 = (dr >> s).wrapping_mul(modinv32(dm >> s));
    let lifts = 1u64 << s.min(MAX_EVEN_MULTIPLIER_SHIFT);
    for lift in 0..lifts {
        let k = k0.wrapping_add((lift as u32) << (32 - s));
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
    fn invert(self, r: &ProbeValues) -> ProbeValues {
        let mut out = [0u32; PROBE_COUNT];
        for p in 0..PROBE_COUNT {
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
    fn emit(self, cur: usize, base_count: usize, prog: &mut Vec<Inst>) -> usize {
        match self {
            Link::Aff { k, c, .. } => prog.push(Inst::MultiplyAddAffine(cur, k, c)),
            Link::XorC(c) => prog.push(Inst::BinConstRight(Xor, cur, c)),
            Link::XsR(s) => {
                prog.push(Inst::BinConstRight(Shr, cur, s));
                let t = base_count + prog.len() - 1;
                prog.push(Inst::Bin(Xor, cur, t));
            }
            Link::XsL(s) => {
                prog.push(Inst::BinConstRight(Shl, cur, s));
                let t = base_count + prog.len() - 1;
                prog.push(Inst::Bin(Xor, cur, t));
            }
        }
        base_count + prog.len() - 1
    }
}

/// Emit a whole suffix chain (stored outermost-first) after the meet value.
fn emit_chain(links: &[Link], mut cur: usize, base_count: usize, prog: &mut Vec<Inst>) {
    for link in links.iter().rev() {
        cur = link.emit(cur, base_count, prog);
    }
}

/// All suffix-chain steps over a link-constant pool.
fn build_links(consts: &[u32]) -> Vec<Link> {
    let mut out = Vec::new();
    for &c in consts {
        if c != 0 {
            out.push(Link::XorC(c));
        }
    }
    for &k in ODD_LINK_MULTIPLIERS.iter() {
        let kinv = modinv32(k);
        for &c in consts {
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
    out.truncate(LINK_CONSTANT_POOL_CAP);
    out
}

/// A forward prefix (prefix_op_count ops) whose last value is the meet variable.
struct FwdEntry {
    out: ProbeValues,
    prog: Vec<Inst>,
    out_idx: usize,
}

struct FwdTab {
    prefix_op_count: usize,
    entries: Vec<FwdEntry>,
    exact: IdMap,
    xor_norm: IdMap,
    /// Stores canonical batteries shifted by t = 0..=MAX_EVEN_MULTIPLIER_SHIFT (even-K meets).
    affine_canon: IdMap,
}

impl FwdTab {
    fn add(&mut self, out: ProbeValues, prog: Vec<Inst>, out_idx: usize) {
        let exact_key = hash_words(TAG_EXACT, &out);
        if self.exact.contains_key(&exact_key) {
            return; // battery-identical prefix already stored
        }
        let idx = self.entries.len() as u32;
        self.exact.insert(exact_key, idx);
        self.xor_norm
            .entry(hash_words(TAG_XOR_NORM, &xor_norm(&out)))
            .or_insert(idx);
        if let Some(canon) = affine_canon(&out) {
            for t in 0..=MAX_EVEN_MULTIPLIER_SHIFT {
                self.affine_canon
                    .entry(hash_words(TAG_AFFINE_CANON, &shl_battery(&canon, t)))
                    .or_insert(idx);
            }
        }
        self.entries.push(FwdEntry { out, prog, out_idx });
    }
}

fn inst_uses(inst: &Inst, idx: usize) -> bool {
    match *inst {
        Inst::Bin(_, i, j) => i == idx || j == idx,
        Inst::MultiplyAdd(i, j, k) => i == idx || j == idx || k == idx,
        _ => false,
    }
}

/// Build the table of all prefix_op_count-op forward prefixes (prefix_op_count <= 2). Every temp except
/// the last (the meet variable) must be referenced, so prefix_op_count=2 keeps only pairs
/// where the second op uses t1.
fn build_fwd_tab(ctx: &Ctx, prefix_op_count: usize) -> FwdTab {
    let mut tab = FwdTab {
        prefix_op_count,
        entries: Vec::new(),
        exact: IdMap::default(),
        xor_norm: IdMap::default(),
        affine_canon: IdMap::default(),
    };
    let base_count = ctx.base_vals.len();
    match prefix_op_count {
        0 => {
            for i in 0..ctx.input_count {
                tab.add(ctx.base_vals[i], Vec::new(), i);
            }
        }
        1 => {
            let w = SearchState::new(ctx);
            enumerate_level(&w, |inst, v| tab.add(v, vec![inst], base_count));
        }
        2 => {
            let mut w = SearchState::new(ctx);
            let mut first_level_candidates: Vec<(Inst, ProbeValues)> = Vec::new();
            enumerate_level(&w, |inst, v| first_level_candidates.push((inst, v)));
            for (i1, v1) in first_level_candidates {
                let undo = w.push(i1.clone(), v1);
                enumerate_level(&w, |i2, v2| {
                    if inst_uses(&i2, base_count) {
                        tab.add(v2, vec![i1.clone(), i2], base_count + 1);
                    }
                });
                w.pop(undo);
            }
        }
        // kf=3 (P-12/H-025 scoping probe only; NOT wired into the default
        // engine C, which stays kf<=2 exactly as verified). Same chaining
        // rule as kf=2, one level deeper: op2 must use t1, op3 must use t2 --
        // "every non-last temp is referenced" is satisfied because each
        // temp is consumed by the very next op.
        3 => {
            let mut w = SearchState::new(ctx);
            let mut first_level_candidates: Vec<(Inst, ProbeValues)> = Vec::new();
            enumerate_level(&w, |inst, v| first_level_candidates.push((inst, v)));
            for (i1, v1) in first_level_candidates {
                let undo1 = w.push(i1.clone(), v1);
                let mut second_level_candidates: Vec<(Inst, ProbeValues)> = Vec::new();
                enumerate_level(&w, |i2, v2| {
                    if inst_uses(&i2, base_count) {
                        second_level_candidates.push((i2, v2));
                    }
                });
                for (i2, v2) in second_level_candidates {
                    let undo2 = w.push(i2.clone(), v2);
                    enumerate_level(&w, |i3, v3| {
                        if inst_uses(&i3, base_count + 1) {
                            tab.add(v3, vec![i1.clone(), i2.clone(), i3], base_count + 2);
                        }
                    });
                    w.pop(undo2);
                }
                w.pop(undo1);
            }
        }
        // kf=4 (iter-11/P-12 follow-up scoping probe only; NOT wired into any
        // verified engine C search yet -- table-construction-cost measurement
        // for the segment-scale targets, same chaining rule one level deeper
        // than kf=3: each temp must be consumed by the very next op.
        4 => {
            let mut w = SearchState::new(ctx);
            let mut l1: Vec<(Inst, ProbeValues)> = Vec::new();
            enumerate_level(&w, |inst, v| l1.push((inst, v)));
            for (i1, v1) in l1 {
                let undo1 = w.push(i1.clone(), v1);
                let mut l2: Vec<(Inst, ProbeValues)> = Vec::new();
                enumerate_level(&w, |i2, v2| {
                    if inst_uses(&i2, base_count) {
                        l2.push((i2, v2));
                    }
                });
                for (i2, v2) in l2 {
                    let undo2 = w.push(i2.clone(), v2);
                    let mut l3: Vec<(Inst, ProbeValues)> = Vec::new();
                    enumerate_level(&w, |i3, v3| {
                        if inst_uses(&i3, base_count + 1) {
                            l3.push((i3, v3));
                        }
                    });
                    for (i3, v3) in l3 {
                        let undo3 = w.push(i3.clone(), v3);
                        enumerate_level(&w, |i4, v4| {
                            if inst_uses(&i4, base_count + 2) {
                                tab.add(v4, vec![i1.clone(), i2.clone(), i3.clone(), i4], base_count + 3);
                            }
                        });
                        w.pop(undo3);
                    }
                    w.pop(undo2);
                }
                w.pop(undo1);
            }
        }
        _ => unreachable!("forward tables only go to kf = 4"),
    }
    tab
}

/// An inverted suffix chain: `req` is the battery the chain input must equal
/// for `out` to hit the target. `links` are stored outermost-first.
struct BwdEntry {
    req: ProbeValues,
    links: Vec<Link>,
}

struct BwdTab {
    suffix_op_count: usize,
    entries: Vec<BwdEntry>,
    exact: IdMap,
    xor_norm: IdMap,
    /// t = 0 canonical keys only; the forward prober shifts its own canon.
    affine_canon: IdMap,
}

impl BwdTab {
    fn new(suffix_op_count: usize) -> BwdTab {
        BwdTab {
            suffix_op_count,
            entries: Vec::new(),
            exact: IdMap::default(),
            xor_norm: IdMap::default(),
            affine_canon: IdMap::default(),
        }
    }
    fn add(&mut self, req: ProbeValues, links: Vec<Link>) {
        let exact_key = hash_words(TAG_EXACT, &req);
        if self.exact.contains_key(&exact_key) {
            return;
        }
        let idx = self.entries.len() as u32;
        self.exact.insert(exact_key, idx);
        self.xor_norm
            .entry(hash_words(TAG_XOR_NORM, &xor_norm(&req)))
            .or_insert(idx);
        if let Some(canon) = affine_canon(&req) {
            self.affine_canon.entry(hash_words(TAG_AFFINE_CANON, &canon)).or_insert(idx);
        }
        self.entries.push(BwdEntry { req, links });
    }
}

/// Tables of all inverted 1-op and 2-op suffix chains for engine B.
fn build_bwd_tabs(target: &ProbeValues, links: &[Link]) -> Vec<BwdTab> {
    let mut one_op_table = BwdTab::new(1);
    let mut two_op_table = BwdTab::new(2);
    for &link in links {
        match link.ops() {
            1 => one_op_table.add(link.invert(target), vec![link]),
            2 => two_op_table.add(link.invert(target), vec![link]),
            _ => unreachable!(),
        }
    }
    for &link1 in links.iter().filter(|link| link.ops() == 1) {
        let req_after_link1 = link1.invert(target);
        for &link2 in links.iter().filter(|link| link.ops() == 1) {
            two_op_table.add(link2.invert(&req_after_link1), vec![link1, link2]);
        }
    }
    vec![one_op_table, two_op_table]
}

struct MitmStats {
    fwd_nodes: AtomicU64,
    bwd_nodes: AtomicU64,
}

/// Engine B: forward DFS (moderate pool) probing inverted-suffix tables.
struct EngineB<'a> {
    ctx: &'a Ctx<'a>,
    tabs: &'a [BwdTab],
    max_forward_depth: usize,
    wanted: u32,
}

impl EngineB<'_> {
    /// Called with `w` already holding >= 1 op (like `dfs`).
    fn dfs(&self, w: &mut SearchState, nodes: &mut u64) {
        if self.ctx.should_stop.load(Ordering::Relaxed) {
            return;
        }
        *nodes += 1;
        let depth = w.prog.len();
        if w.unused_temp_count == 1 {
            self.probe(w, depth);
        }
        if depth >= self.max_forward_depth {
            return;
        }
        if w.unused_temp_count > 2 * (self.max_forward_depth - depth) + 1 {
            return;
        }
        let mut cands: Vec<(Inst, ProbeValues)> = Vec::with_capacity(4096);
        enumerate_level(w, |inst, v| cands.push((inst, v)));
        for (inst, v) in cands {
            if self.ctx.should_stop.load(Ordering::Relaxed) {
                return;
            }
            let undo = w.push(inst, v);
            self.dfs(w, nodes);
            w.pop(undo);
        }
    }

    fn probe(&self, w: &SearchState, depth: usize) {
        let m = *w.vals.last().unwrap();
        let base_count = self.ctx.base_vals.len();
        let cur = base_count + depth - 1;
        let want = |k: usize| self.wanted & (1u32 << k) != 0;
        let exact_key = hash_words(TAG_EXACT, &m);
        let xor_norm_key = hash_words(TAG_XOR_NORM, &xor_norm(&m));
        let canon = affine_canon(&m);
        for tab in self.tabs {
            let j = tab.suffix_op_count;
            if want(depth + j) {
                if let Some(&ei) = tab.exact.get(&exact_key) {
                    let e = &tab.entries[ei as usize];
                    if e.req == m {
                        let mut prog = w.prog.clone();
                        emit_chain(&e.links, cur, base_count, &mut prog);
                        report_prog(self.ctx, prog);
                    }
                }
            }
            if want(depth + 1 + j) {
                if let Some(&ei) = tab.xor_norm.get(&xor_norm_key) {
                    let e = &tab.entries[ei as usize];
                    if let Some(c) = solve_xor_meet(&m, &e.req) {
                        if c != 0 {
                            let mut prog = w.prog.clone();
                            prog.push(Inst::BinConstRight(Xor, cur, c));
                            emit_chain(&e.links, base_count + prog.len() - 1, base_count, &mut prog);
                            report_prog(self.ctx, prog);
                        }
                    }
                }
                if let Some(canon) = &canon {
                    for t in 0..=MAX_EVEN_MULTIPLIER_SHIFT {
                        let key = hash_words(TAG_AFFINE_CANON, &shl_battery(canon, t));
                        if let Some(&ei) = tab.affine_canon.get(&key) {
                            let e = &tab.entries[ei as usize];
                            if let Some((k, c)) = solve_affine_meet(&m, &e.req) {
                                if k != 1 || c != 0 {
                                    let mut prog = w.prog.clone();
                                    prog.push(Inst::MultiplyAddAffine(cur, k, c));
                                    emit_chain(
                                        &e.links,
                                        base_count + prog.len() - 1,
                                        base_count,
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
    max_forward_depth: usize,
    wanted: u32,
    stats: &MitmStats,
    threads: usize,
) {
    let mut first_level_candidates: Vec<(Inst, ProbeValues)> = Vec::new();
    {
        let w = SearchState::new(ctx);
        enumerate_level(&w, |inst, v| first_level_candidates.push((inst, v)));
    }
    let eng = EngineB {
        ctx,
        tabs,
        max_forward_depth,
        wanted,
    };
    let next = AtomicU64::new(0);
    std::thread::scope(|scope| {
        for _ in 0..threads {
            scope.spawn(|| {
                let mut w = SearchState::new(ctx);
                let mut nodes = 0u64;
                loop {
                    let idx = next.fetch_add(1, Ordering::Relaxed) as usize;
                    if idx >= first_level_candidates.len() || ctx.should_stop.load(Ordering::Relaxed) {
                        break;
                    }
                    let (inst, v) = first_level_candidates[idx].clone();
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
    max_chain_ops: usize,
    wanted: u32,
}

impl EngineC<'_> {
    fn dfs(&self, req: &ProbeValues, chain: &mut Vec<Link>, ops: usize, unary_link_count: usize, nodes: &mut u64) {
        if self.ctx.should_stop.load(Ordering::Relaxed) {
            return;
        }
        *nodes += 1;
        self.probe(req, chain, ops);
        if ops >= self.max_chain_ops {
            return;
        }
        for &link in self.links {
            let nops = ops + link.ops();
            if nops > self.max_chain_ops {
                continue;
            }
            let next_unary_link_count = unary_link_count + usize::from(link.is_unary_const());
            if next_unary_link_count > 3 || (nops == 5 && next_unary_link_count > 1) {
                continue;
            }
            let r2 = link.invert(req);
            chain.push(link);
            self.dfs(&r2, chain, nops, next_unary_link_count, nodes);
            chain.pop();
        }
    }

    fn probe(&self, req: &ProbeValues, chain: &[Link], ops: usize) {
        let want = |k: usize| self.wanted & (1u32 << k) != 0;
        let base_count = self.ctx.base_vals.len();
        let exact_key = hash_words(TAG_EXACT, req);
        let xor_norm_key = hash_words(TAG_XOR_NORM, &xor_norm(req));
        let affine_canon_key = affine_canon(req).map(|c| hash_words(TAG_AFFINE_CANON, &c));
        for tab in self.fwd {
            if want(tab.prefix_op_count + ops) {
                if let Some(&ei) = tab.exact.get(&exact_key) {
                    let e = &tab.entries[ei as usize];
                    if e.out == *req {
                        let mut prog = e.prog.clone();
                        emit_chain(chain, e.out_idx, base_count, &mut prog);
                        report_prog(self.ctx, prog);
                    }
                }
            }
            if want(tab.prefix_op_count + 1 + ops) {
                if let Some(&ei) = tab.xor_norm.get(&xor_norm_key) {
                    let e = &tab.entries[ei as usize];
                    if let Some(c) = solve_xor_meet(&e.out, req) {
                        if c != 0 {
                            let mut prog = e.prog.clone();
                            prog.push(Inst::BinConstRight(Xor, e.out_idx, c));
                            emit_chain(chain, base_count + prog.len() - 1, base_count, &mut prog);
                            report_prog(self.ctx, prog);
                        }
                    }
                }
                if let Some(affine_canon_key) = affine_canon_key {
                    if let Some(&ei) = tab.affine_canon.get(&affine_canon_key) {
                        let e = &tab.entries[ei as usize];
                        if let Some((k, c)) = solve_affine_meet(&e.out, req) {
                            if k != 1 || c != 0 {
                                let mut prog = e.prog.clone();
                                prog.push(Inst::MultiplyAddAffine(e.out_idx, k, c));
                                emit_chain(chain, base_count + prog.len() - 1, base_count, &mut prog);
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
    max_chain_ops: usize,
    wanted: u32,
    stats: &MitmStats,
    threads: usize,
) {
    let eng = EngineC {
        ctx,
        links,
        fwd,
        max_chain_ops,
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
                    if idx >= eng.links.len() || ctx.should_stop.load(Ordering::Relaxed) {
                        break;
                    }
                    let link = eng.links[idx];
                    if link.ops() > eng.max_chain_ops {
                        continue;
                    }
                    let req = link.invert(&ctx.target);
                    chain.push(link);
                    eng.dfs(
                        &req,
                        &mut chain,
                        link.ops(),
                        usize::from(link.is_unary_const()),
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
    input_count: usize,
    current_ops: usize,
    /// Engine A (forward-only exhaustive) depth; 0 = already closed in H-003.
    engine_a_kmax: usize,
    /// Engine A pool override (empty = use `pool`). Two-input k=4 runs need a
    /// leaner pool than the MITM engines to stay within a CPU budget.
    engine_a_pool_override: Vec<(&'static str, u32)>,
    /// Forward pool: engines B DFS and engine C's prefix tables.
    pool: Vec<(&'static str, u32)>,
    /// Seeds for the link-constant pool (enriched + capped).
    seed: Vec<u32>,
    shifts: Vec<u32>,
    stretch: bool,
    /// Run engine C (the chain-DFS whale, ~10-16 min/target). When false the
    /// runner prints exactly which shapes the negative then covers.
    enable_engine_c: bool,
    reference_fn: Box<TargetFn>,
}

fn build_ctx<'a>(input_count: usize, consts: &[(&'static str, u32)], reference_fn: &'a TargetFn) -> Ctx<'a> {
    let probes = probes(input_count);
    let mut base_names: Vec<String> = Vec::new();
    let mut base_vals: Vec<ProbeValues> = Vec::new();
    let mut base_is_const: Vec<bool> = Vec::new();
    let input_names = ["x", "y"];
    for (k, nm) in input_names.iter().enumerate().take(input_count) {
        base_names.push((*nm).to_string());
        let mut v = [0u32; PROBE_COUNT];
        for (p, tup) in probes.iter().enumerate() {
            v[p] = tup[k];
        }
        base_vals.push(v);
        base_is_const.push(false);
    }
    for (nm, c) in consts {
        base_names.push(format!("{nm}={c:#010x}"));
        base_vals.push([*c; PROBE_COUNT]);
        base_is_const.push(true);
    }
    let mut target = [0u32; PROBE_COUNT];
    for (p, tup) in probes.iter().enumerate() {
        target[p] = reference_fn(tup);
    }
    Ctx {
        input_count,
        base_names,
        base_vals,
        base_is_const,
        target,
        tested_count: AtomicU64::new(0),
        should_stop: AtomicBool::new(false),
        finds: Mutex::new(Vec::new()),
        unsolved_count: AtomicU64::new(0),
        reference_fn,
    }
}

#[allow(clippy::too_many_lines)]
fn mitm_targets() -> Vec<MTarget> {
    use hs::*;
    let common = [("zero", 0u32), ("one", 1u32), ("m1", 0xFFFF_FFFF)];
    let mk = |extra: &[(&'static str, u32)]| -> Vec<(&'static str, u32)> {
        common.iter().chain(extra.iter()).cloned().collect()
    };
    let c1_shifted_right_19 = STAGE1_XOR_CONSTANT >> 19;
    let c1_xorshift19 = STAGE1_XOR_CONSTANT ^ (STAGE1_XOR_CONSTANT >> 19);
    let c5_shifted_right_16 = STAGE5_XOR_CONSTANT >> 16;
    let c5_xorshift16 = STAGE5_XOR_CONSTANT ^ (STAGE5_XOR_CONSTANT >> 16);
    let c0_shifted_right_19 = STAGE0_ADD_CONSTANT >> 19;
    let kp_times_c1 = F23_P_MULTIPLIER.wrapping_mul(STAGE1_XOR_CONSTANT);
    let kq_times_c1 = F23_Q_MULTIPLIER.wrapping_mul(STAGE1_XOR_CONSTANT);
    let f23_p_branch_at_c1 = F23_P_CONSTANT.wrapping_add(kp_times_c1);
    let f23_q_branch_at_c1 = F23_Q_CONSTANT.wrapping_add(kq_times_c1);
    let kp_times_k4 = F23_P_MULTIPLIER.wrapping_mul(9);
    let kq_times_k4 = F23_Q_MULTIPLIER.wrapping_mul(9);
    let stage4_of_ap = F23_P_CONSTANT.wrapping_mul(9).wrapping_add(STAGE4_ADD_CONSTANT);
    let aq_times_k4 = F23_Q_CONSTANT.wrapping_mul(9);
    let k0_times_65536 = STAGE0_MULTIPLIER.wrapping_mul(1 << 16);
    let k0_times_c4 = STAGE0_MULTIPLIER.wrapping_mul(STAGE4_ADD_CONSTANT);
    let k0_times_c5 = STAGE0_MULTIPLIER.wrapping_mul(STAGE5_XOR_CONSTANT);
    let k0_times_k4 = STAGE0_MULTIPLIER.wrapping_mul(9);
    vec![
        MTarget {
            name: "b2d",
            desc: "stage1 o f23 span: f23(stage1(b)) [shr,xor,xor,madd,madd,xor]",
            input_count: 1,
            current_ops: 6,
            engine_a_kmax: 4,
            engine_a_pool_override: vec![],
            pool: mk(&[
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("C1i", c1_xorshift19),
                ("s19", 19),
                ("s5", 5),
                ("s9", 9),
                ("p19", 1 << 19),
            ]),
            seed: vec![STAGE1_XOR_CONSTANT, F23_P_MULTIPLIER, F23_P_CONSTANT, F23_Q_MULTIPLIER, F23_Q_CONSTANT, c1_shifted_right_19, c1_xorshift19, kp_times_c1, kq_times_c1, f23_p_branch_at_c1, f23_q_branch_at_c1],
            shifts: vec![19, 5, 9, 13, 14],
            stretch: false,
            enable_engine_c: true,
            reference_fn: Box::new(|x| hs::f23(hs::stage1(x[0]))),
        },
        MTarget {
            name: "xr5",
            desc: "cross-round from d: stage0(stage5(stage4(d)) ^ n) [madd,shr,xor,xor,xor,madd]",
            input_count: 2,
            current_ops: 6,
            engine_a_kmax: 4,
            engine_a_pool_override: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("C5i", c5_xorshift16),
                ("s16", 16),
                ("s3", 3),
            ]),
            pool: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("C5i", c5_xorshift16),
                ("STAGE4_MULTIPLIER", 9),
                ("s16", 16),
                ("s3", 3),
                ("s12", 12),
                ("K016", k0_times_65536),
            ]),
            seed: vec![STAGE0_ADD_CONSTANT, STAGE0_MULTIPLIER, STAGE4_ADD_CONSTANT, STAGE5_XOR_CONSTANT, c5_shifted_right_16, c5_xorshift16, k0_times_65536, k0_times_c4, k0_times_c5, k0_times_k4],
            shifts: vec![16, 3, 12, 4, 15],
            stretch: false,
            enable_engine_c: true,
            reference_fn: Box::new(|x| hs::stage0(hs::stage5(hs::stage4(x[0])) ^ x[1])),
        },
        MTarget {
            name: "xr3p",
            desc:
                "primed cross-round from d: stage0(sigma16(stage4(d)) ^ n') [madd,shr,xor,xor,madd]",
            input_count: 2,
            current_ops: 5,
            engine_a_kmax: 4,
            engine_a_pool_override: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE4_MULTIPLIER", 9),
                ("s16", 16),
                ("s3", 3),
            ]),
            pool: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE4_MULTIPLIER", 9),
                ("s16", 16),
                ("s3", 3),
                ("s12", 12),
                ("K016", k0_times_65536),
                ("p16", 1 << 16),
                ("K0C4", k0_times_c4),
            ]),
            seed: vec![STAGE0_ADD_CONSTANT, STAGE0_MULTIPLIER, STAGE4_ADD_CONSTANT, k0_times_65536, k0_times_c4, k0_times_k4],
            shifts: vec![16, 3, 12],
            stretch: false,
            enable_engine_c: true,
            reference_fn: Box::new(|x| hs::stage0(hs::sigma16(hs::stage4(x[0])) ^ x[1])),
        },
        MTarget {
            name: "xr4r",
            desc: "cross-round from e (H-003 xr4, richer pool): stage0(stage5(e) ^ n)",
            input_count: 2,
            current_ops: 5,
            engine_a_kmax: 0,
            engine_a_pool_override: vec![],
            pool: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("C5s", c5_shifted_right_16),
                ("C5i", c5_xorshift16),
                ("s16", 16),
                ("s12", 12),
                ("K016", k0_times_65536),
                ("p16", 1 << 16),
                ("K0C5", k0_times_c5),
            ]),
            seed: vec![STAGE0_ADD_CONSTANT, STAGE0_MULTIPLIER, STAGE5_XOR_CONSTANT, c5_shifted_right_16, c5_xorshift16, k0_times_65536, k0_times_c5],
            shifts: vec![16, 3, 12, 4, 15],
            stretch: false,
            enable_engine_c: false,
            reference_fn: Box::new(|x| hs::stage0(hs::stage5(x[0]) ^ x[1])),
        },
        MTarget {
            name: "head3r",
            desc: "fold-in head (H-003 head3, richer pool): stage1(stage0(v ^ n))",
            input_count: 2,
            current_ops: 5,
            engine_a_kmax: 0,
            engine_a_pool_override: vec![],
            pool: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("C0s", c0_shifted_right_19),
                ("C1s", c1_shifted_right_19),
                ("C1i", c1_xorshift19),
                ("C0x1", STAGE0_ADD_CONSTANT ^ STAGE1_XOR_CONSTANT),
                ("s12", 12),
                ("s19", 19),
                ("p19", 1 << 19),
            ]),
            seed: vec![STAGE0_ADD_CONSTANT, STAGE1_XOR_CONSTANT, STAGE0_MULTIPLIER, c0_shifted_right_19, c1_shifted_right_19, c1_xorshift19, STAGE0_ADD_CONSTANT ^ STAGE1_XOR_CONSTANT],
            shifts: vec![12, 19, 7, 13],
            stretch: false,
            enable_engine_c: false,
            reference_fn: Box::new(|x| hs::stage1(hs::stage0(x[0] ^ x[1]))),
        },
        MTarget {
            name: "head4u",
            desc: "fold-in head to the pre-STAGE1_XOR_CONSTANT point u: sigma19(stage0(v ^ n)) [xor,madd,shr,xor]",
            input_count: 2,
            current_ops: 4,
            engine_a_kmax: 3,
            engine_a_pool_override: vec![],
            pool: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("C0s", c0_shifted_right_19),
                ("s12", 12),
                ("s19", 19),
                ("p19", 1 << 19),
            ]),
            seed: vec![STAGE0_ADD_CONSTANT, STAGE0_MULTIPLIER, c0_shifted_right_19],
            shifts: vec![12, 19, 7, 13],
            stretch: false,
            enable_engine_c: true,
            reference_fn: Box::new(|x| {
                let b = hs::stage0(x[0] ^ x[1]);
                b ^ (b >> 19)
            }),
        },
        MTarget {
            name: "u2er",
            desc: "stage1-tail through stage4 (H-003 u2e, richer pool): stage4(f23(u ^ STAGE1_XOR_CONSTANT))",
            input_count: 1,
            current_ops: 5,
            engine_a_kmax: 0,
            engine_a_pool_override: vec![],
            pool: mk(&[
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("STAGE4_MULTIPLIER", 9),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("KP9", kp_times_k4),
                ("KQ9", kq_times_k4),
                ("s5", 5),
                ("s9", 9),
                ("s3", 3),
            ]),
            seed: vec![STAGE1_XOR_CONSTANT, F23_P_MULTIPLIER, F23_P_CONSTANT, F23_Q_MULTIPLIER, F23_Q_CONSTANT, STAGE4_ADD_CONSTANT, kp_times_k4, kq_times_k4, stage4_of_ap, aq_times_k4, f23_p_branch_at_c1, f23_q_branch_at_c1],
            shifts: vec![5, 9, 3, 14],
            stretch: false,
            enable_engine_c: false,
            reference_fn: Box::new(|x| hs::stage4(hs::f23(x[0] ^ hs::STAGE1_XOR_CONSTANT))),
        },
        MTarget {
            name: "a2d",
            desc: "interior 7-op span: f23(stage1(stage0(a)))",
            input_count: 1,
            current_ops: 7,
            engine_a_kmax: 3,
            engine_a_pool_override: vec![],
            pool: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("C1i", c1_xorshift19),
                ("s12", 12),
                ("s19", 19),
                ("s5", 5),
                ("s9", 9),
            ]),
            seed: vec![STAGE0_ADD_CONSTANT, STAGE1_XOR_CONSTANT, STAGE0_MULTIPLIER, F23_P_MULTIPLIER, F23_P_CONSTANT, F23_Q_MULTIPLIER, F23_Q_CONSTANT, c1_xorshift19, kp_times_c1, kq_times_c1, f23_p_branch_at_c1, f23_q_branch_at_c1],
            shifts: vec![12, 19, 5, 9],
            stretch: true,
            enable_engine_c: false,
            reference_fn: Box::new(|x| hs::f23(hs::stage1(hs::stage0(x[0])))),
        },
        MTarget {
            name: "b2e",
            desc: "interior 7-op span: stage4(f23(stage1(b)))",
            input_count: 1,
            current_ops: 7,
            engine_a_kmax: 3,
            engine_a_pool_override: vec![],
            pool: mk(&[
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("STAGE4_MULTIPLIER", 9),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("C1i", c1_xorshift19),
                ("s19", 19),
                ("s5", 5),
                ("s9", 9),
                ("s3", 3),
            ]),
            seed: vec![STAGE1_XOR_CONSTANT, F23_P_MULTIPLIER, F23_P_CONSTANT, F23_Q_MULTIPLIER, F23_Q_CONSTANT, STAGE4_ADD_CONSTANT, c1_xorshift19, kp_times_k4, kq_times_k4, stage4_of_ap, aq_times_k4],
            shifts: vec![19, 5, 9, 3],
            stretch: true,
            enable_engine_c: false,
            reference_fn: Box::new(|x| hs::stage4(hs::f23(hs::stage1(x[0])))),
        },
        MTarget {
            name: "c2out",
            desc: "interior 7-op span: stage5(stage4(f23(c)))",
            input_count: 1,
            current_ops: 7,
            engine_a_kmax: 3,
            engine_a_pool_override: vec![],
            pool: mk(&[
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("STAGE4_MULTIPLIER", 9),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("C5i", c5_xorshift16),
                ("s5", 5),
                ("s9", 9),
                ("s3", 3),
                ("s16", 16),
            ]),
            seed: vec![F23_P_MULTIPLIER, F23_P_CONSTANT, F23_Q_MULTIPLIER, F23_Q_CONSTANT, STAGE4_ADD_CONSTANT, STAGE5_XOR_CONSTANT, c5_xorshift16, kp_times_k4, kq_times_k4, stage4_of_ap, aq_times_k4],
            shifts: vec![5, 9, 3, 16],
            stretch: true,
            enable_engine_c: false,
            reference_fn: Box::new(|x| hs::stage5(hs::stage4(hs::f23(x[0])))),
        },
        MTarget {
            name: "full_hash",
            desc: "whole 11-op chain, NO waypoint assumption: stage5(stage4(f23(stage1(stage0(a))))) == myhash(a) [madd,shr,xor,xor,madd,madd,xor,madd,xor,shr,xor]",
            input_count: 1,
            current_ops: 11,
            // Engine A here is the expensive one (full k<=4 exhaustive over every
            // stage's constants at once, no segment cut) -- kept to a leaner
            // 16-item pool (12 hashseg consts + common + 1 shift) to stay in
            // budget; the richer 23-item `pool` below (12 hashseg consts + common
            // + 8 shifts) only has to survive engines B/C's DFS-over-tables shapes.
            engine_a_kmax: 4,
            engine_a_pool_override: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("STAGE4_MULTIPLIER", 9),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("C1i", c1_xorshift19),
                ("C5i", c5_xorshift16),
                ("s19", 19),
            ]),
            pool: mk(&[
                ("STAGE0_ADD_CONSTANT", STAGE0_ADD_CONSTANT),
                ("STAGE0_MULTIPLIER", STAGE0_MULTIPLIER),
                ("STAGE1_XOR_CONSTANT", STAGE1_XOR_CONSTANT),
                ("F23_P_MULTIPLIER", F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", F23_Q_CONSTANT),
                ("STAGE4_MULTIPLIER", 9),
                ("STAGE4_ADD_CONSTANT", STAGE4_ADD_CONSTANT),
                ("STAGE5_XOR_CONSTANT", STAGE5_XOR_CONSTANT),
                ("C1i", c1_xorshift19),
                ("C5i", c5_xorshift16),
                ("s12", 12),
                ("s19", 19),
                ("s5", 5),
                ("s9", 9),
                ("s3", 3),
                ("s16", 16),
                ("s13", 13),
                ("s14", 14),
            ]),
            seed: vec![
                STAGE0_ADD_CONSTANT,
                STAGE0_MULTIPLIER,
                STAGE1_XOR_CONSTANT,
                F23_P_MULTIPLIER,
                F23_P_CONSTANT,
                F23_Q_MULTIPLIER,
                F23_Q_CONSTANT,
                STAGE4_ADD_CONSTANT,
                STAGE5_XOR_CONSTANT,
                c1_shifted_right_19,
                c1_xorshift19,
                c5_shifted_right_16,
                c5_xorshift16,
                c0_shifted_right_19,
                kp_times_c1,
                kq_times_c1,
                f23_p_branch_at_c1,
                f23_q_branch_at_c1,
                kp_times_k4,
                kq_times_k4,
                stage4_of_ap,
                aq_times_k4,
                k0_times_65536,
                k0_times_c4,
                k0_times_c5,
                k0_times_k4,
            ],
            shifts: vec![12, 19, 5, 9, 3, 16, 13, 14],
            stretch: true,
            enable_engine_c: true,
            reference_fn: Box::new(|x| hs::fused_hash(x[0])),
        },
    ]
}

fn run_mitm_target(tg: &MTarget, threads: usize, max_kf: usize, force_engine_c: bool) {
    let kmax_use = tg.current_ops - 1;
    let wanted: u32 = (2u32 << kmax_use) - 2; // bits 1..=kmax_use
    println!(
        "== MITM target {} : {} (current {} ops, hunting k <= {}) ==",
        tg.name, tg.desc, tg.current_ops, kmax_use
    );
    let t_start = Instant::now();

    // Engine A: forward-only exhaustive (full j=0 coverage at k <= engine_a_kmax)
    // over the target's engine-A pool.
    let pool_a = if tg.engine_a_pool_override.is_empty() {
        &tg.pool
    } else {
        &tg.engine_a_pool_override
    };
    let ctx_a = build_ctx(tg.input_count, pool_a, &*tg.reference_fn);
    if tg.engine_a_kmax > 0 {
        println!(
            "   engine A (forward exhaustive, k <= {}): pool [{}]",
            tg.engine_a_kmax,
            ctx_a
                .base_names
                .iter()
                .skip(tg.input_count)
                .cloned()
                .collect::<Vec<_>>()
                .join(", ")
        );
        search_iterative(&ctx_a, tg.engine_a_kmax, threads);
    } else {
        println!("   engine A skipped (H-003 closed this span at k <= 4 already)");
    }

    // Shared MITM context (same pool; link constants live outside the ctx).
    let ctx = build_ctx(tg.input_count, &tg.pool, &*tg.reference_fn);
    let link_consts = build_link_consts(&tg.seed, &tg.shifts);
    let links = build_links(&link_consts);
    println!(
        "   link pool: {} constants {:x?}, {} odd Ks, {} links",
        link_consts.len(),
        link_consts,
        ODD_LINK_MULTIPLIERS.len(),
        links.len()
    );
    let stats = MitmStats {
        fwd_nodes: AtomicU64::new(0),
        bwd_nodes: AtomicU64::new(0),
    };

    // Engine B: forward DFS x inverted-suffix tables.
    let bwd_tabs = build_bwd_tabs(&ctx.target, &links);
    let max_forward_depth = 3.min(kmax_use - 1);
    println!(
        "   engine B: fwd DFS to depth {} probing suffix tables (j=1: {} chains, j=2: {} chains)",
        max_forward_depth,
        bwd_tabs[0].entries.len(),
        bwd_tabs[1].entries.len()
    );
    let tb = Instant::now();
    run_engine_b(&ctx, &bwd_tabs, max_forward_depth, wanted, &stats, threads);
    println!(
        "   engine B: {} forward nodes probed in {:.1}s",
        stats.fwd_nodes.load(Ordering::Relaxed),
        tb.elapsed().as_secs_f64()
    );
    drop(bwd_tabs);

    // Engine C: suffix-chain DFS x forward-prefix tables.
    if !tg.enable_engine_c && !force_engine_c {
        println!(
            "   engine C skipped (CPU budget): MITM coverage here = engine B shapes only \
             (forward<=3 + [solved meet]? + 1..2-op invertible suffix)"
        );
        summarize(tg, &ctx_a, &ctx, kmax_use, t_start);
        return;
    }
    if force_engine_c && !tg.enable_engine_c {
        println!(
            "   engine C FORCE-ENABLED via --force-engine-c (target's own enable_engine_c=false; \
             this is a first-time/untested run for this target's chain-DFS cost)"
        );
    }
    // max_kf is normally 2 (the verified/default engine C coverage: kf in
    // {0,1,2}). Iter 9 (P-12 follow-up) adds an opt-in `--kf3` extension that
    // raises this to 3 for a real (not just diagnostic) run -- table-build
    // cost for kf=3 was confirmed cheap (seconds-to-minutes, single-digit-GB
    // peak RSS) at every individual segment target's REAL pool (9-15 items),
    // in contrast to the 23-item `full_hash` pool which hits a memory wall.
    // Adding one more FwdTab only adds O(1) extra hashmap lookups per engine
    // C suffix-DFS node (see EngineC::probe's `for tab in self.fwd` loop), so
    // this does not blow up engine C's own chain-DFS cost.
    let fwd_tabs: Vec<FwdTab> = (0..=max_kf).map(|prefix_op_count| build_fwd_tab(&ctx, prefix_op_count)).collect();
    let max_chain_ops = 5.min(kmax_use);
    println!(
        "   engine C: chain DFS to {} ops (caps: <=3 unary links, 5-op chains need <=1 unary) probing prefix tables ({})",
        max_chain_ops,
        fwd_tabs
            .iter()
            .map(|t| format!("kf={}: {}", t.prefix_op_count, t.entries.len()))
            .collect::<Vec<_>>()
            .join(", ")
    );
    let tc = Instant::now();
    run_engine_c(&ctx, &links, &fwd_tabs, max_chain_ops, wanted, &stats, threads);
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

/// P-12/H-025 kf=3 feasibility scoping probe (NOT wired into any verified
/// search result -- purely diagnostic). Times `build_fwd_tab` at kf=0..=3
/// over increasing prefixes of the `full_hash` target's pool, to empirically
/// calibrate how kf=3's cost actually scales with pool size instead of
/// trusting a hand-derived exponent. Self-limiting: skips remaining kf at a
/// pool size once a single build exceeds 120s, and stops entirely at a
/// 15-minute total wall budget.
fn run_kf_scale_probe() {
    use std::io::Write;
    let all = mitm_targets();
    let tg = all.iter().find(|t| t.name == "full_hash").expect("full_hash target missing");
    println!("== kf-scale probe (P-12 kf=3 feasibility calibration, full_hash pool/fn) ==");
    println!("   full pool has {} consts (incl. common); input_count={}", tg.pool.len(), tg.input_count);
    let probe_deadline = Instant::now() + std::time::Duration::from_secs(900);
    let sizes: Vec<usize> = vec![4, 6, 8, 10, 12, 14, 16, tg.pool.len()];
    'sizes: for &n in &sizes {
        if n > tg.pool.len() {
            continue;
        }
        let pool_subset = &tg.pool[..n];
        let ctx = build_ctx(tg.input_count, pool_subset, &*tg.reference_fn);
        print!("   pool={n:>2} (leaves={:>2}):", n + tg.input_count);
        std::io::stdout().flush().ok();
        for kf in 0..=3usize {
            if Instant::now() >= probe_deadline {
                println!(" [15-min probe budget exhausted, stopping]");
                break 'sizes;
            }
            let t0 = Instant::now();
            let tab = build_fwd_tab(&ctx, kf);
            let dt = t0.elapsed().as_secs_f64();
            print!(" kf{kf}=[{}e,{:.3}s]", tab.entries.len(), dt);
            std::io::stdout().flush().ok();
            if dt > 120.0 {
                println!(" [>120s, skipping larger kf at this pool size]");
                continue 'sizes;
            }
        }
        println!();
    }
    println!("== probe complete ==");
}

/// Real-pool kf=3 feasibility probe for a SPECIFIC named MITM target (iter 9,
/// P-12 follow-up). `--kf-scale` (above) only ever swept synthetic prefixes
/// of `full_hash`'s 23-item pool; this instead builds `build_fwd_tab` at
/// kf=0..=3 using the named target's REAL `pool` field verbatim (whatever
/// engine C would actually use for that target), with a background
/// RSS-sampling thread every 5s for early-warning visibility. Diagnostic
/// only -- not wired into any verified search result.
fn run_kf_scale_target_probe(name: &str) {
    use std::io::Write;
    let all = mitm_targets();
    let tg = all.iter().find(|t| t.name == name).unwrap_or_else(|| {
        eprintln!(
            "no MITM target named {name:?}; available: {}",
            all.iter().map(|t| t.name).collect::<Vec<_>>().join(", ")
        );
        std::process::exit(1);
    });
    println!("== kf-scale-target probe ({}): {} ==", tg.name, tg.desc);
    println!(
        "   REAL pool has {} consts (incl. common); input_count={}; current_ops={}",
        tg.pool.len(),
        tg.input_count,
        tg.current_ops
    );
    let ctx = build_ctx(tg.input_count, &tg.pool, &*tg.reference_fn);

    let done = std::sync::Arc::new(AtomicBool::new(false));
    let done_r = std::sync::Arc::clone(&done);
    let pid = std::process::id();
    let mon = std::thread::spawn(move || {
        while !done_r.load(Ordering::Relaxed) {
            std::thread::sleep(std::time::Duration::from_secs(5));
            if done_r.load(Ordering::Relaxed) {
                break;
            }
            if let Ok(out) = std::process::Command::new("ps").args(["-o", "rss=", "-p", &pid.to_string()]).output() {
                if let Ok(s) = String::from_utf8(out.stdout) {
                    if let Ok(kb) = s.trim().parse::<u64>() {
                        println!("      [rss={:.2} GB]", kb as f64 / 1_048_576.0);
                        std::io::stdout().flush().ok();
                    }
                }
            }
        }
    });

    // Iter 11/P-12 follow-up: extended from kf<=3 to kf<=4 now that
    // build_fwd_tab has a kf=4 arm. Self-limiting: stop before a kf whose
    // build is expected to dwarf the remaining wall budget by bailing out
    // once a single build exceeds 45 minutes (2700s).
    for kf in 0..=4usize {
        let t0 = Instant::now();
        let tab = build_fwd_tab(&ctx, kf);
        let dt = t0.elapsed().as_secs_f64();
        println!("   kf={kf}: {} entries, {dt:.3}s", tab.entries.len());
        std::io::stdout().flush().ok();
        if dt > 2700.0 {
            println!("   [>45min at kf={kf}, stopping before next kf]");
            break;
        }
    }
    done.store(true, Ordering::Relaxed);
    mon.join().ok();
    println!("== probe complete ==");
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let long = args.iter().any(|a| a == "--long");
    let mitm = args.iter().any(|a| a == "--mitm");
    let stretch = args.iter().any(|a| a == "--stretch");
    let kf_scale = args.iter().any(|a| a == "--kf-scale");
    // Opt-in iter-9/P-12 extension: raise engine C's forward-prefix coverage
    // from the verified default kf<=2 to kf<=3 for a real (non-diagnostic)
    // run. Only meaningful with --mitm; the plain forward-only suite is
    // unaffected. Default (no flag) behavior is byte-for-byte unchanged from
    // iter 7/8, so this cannot silently alter any already-verified result.
    let kf3 = args.iter().any(|a| a == "--kf3");
    let max_kf: usize = if kf3 { 3 } else { 2 };
    // Opt-in iter-11/P-12 extension: force engine C on for a named target even
    // when its own MTarget.enable_engine_c is false (a2d/b2e/c2out were an
    // iter-4 CPU-budget guess, never actually timed). Only affects targets
    // whose struct already says `false`; targets that already run engine C
    // (enable_engine_c=true) are unaffected either way. Default (no flag)
    // behavior is byte-for-byte unchanged.
    let force_engine_c = args.iter().any(|a| a == "--force-engine-c");
    let kf_scale_target: Option<String> =
        args.iter().position(|a| a == "--kf-scale-target").and_then(|i| args.get(i + 1).cloned());
    let names: Vec<&String> = args.iter().filter(|a| !a.starts_with("--")).collect();
    if kf_scale {
        run_kf_scale_probe();
        return;
    }
    if let Some(name) = kf_scale_target {
        run_kf_scale_target_probe(&name);
        return;
    }
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
                run_mitm_target(tg, threads, max_kf, force_engine_c);
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
            !tg.is_long_suite || long
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

    fn ctx_for(input_count: usize, consts: &[(&str, u32)], reference_fn: &'static TargetFn) -> Ctx<'static> {
        let probes = probes(input_count);
        let mut base_names = Vec::new();
        let mut base_vals: Vec<ProbeValues> = Vec::new();
        let mut base_is_const = Vec::new();
        for k in 0..input_count {
            base_names.push(format!("in{k}"));
            let mut v = [0u32; PROBE_COUNT];
            for (p, tup) in probes.iter().enumerate() {
                v[p] = tup[k];
            }
            base_vals.push(v);
            base_is_const.push(false);
        }
        for (nm, c) in consts {
            base_names.push(nm.to_string());
            base_vals.push([*c; PROBE_COUNT]);
            base_is_const.push(true);
        }
        let mut target = [0u32; PROBE_COUNT];
        for (p, tup) in probes.iter().enumerate() {
            target[p] = reference_fn(tup);
        }
        Ctx {
            input_count,
            base_names,
            base_vals,
            base_is_const,
            target,
            tested_count: AtomicU64::new(0),
            should_stop: AtomicBool::new(false),
            finds: Mutex::new(Vec::new()),
            unsolved_count: AtomicU64::new(0),
            reference_fn,
        }
    }

    fn search(ctx: &Ctx, max_ops: usize) -> usize {
        for k in 1..=max_ops {
            if !ctx.finds.lock().unwrap().is_empty() {
                return k - 1;
            }
            let mut w = SearchState::new(ctx);
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
                ("F23_P_MULTIPLIER", hs::F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", hs::F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", hs::F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", hs::F23_Q_CONSTANT),
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
        let ctx = ctx_for(1, &[], &F); // empty pool: must solve STAGE0_MULTIPLIER, STAGE0_ADD_CONSTANT
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
            &[("PEK", hs::PARITY_FROM_E_MULTIPLIER), ("PEC", hs::PARITY_FROM_E_CONSTANT), ("s31", 31)],
            &F,
        );
        let k = search(&ctx, 2);
        assert_eq!(k, 2, "parity from e must be found in 2 ops");
    }

    /// Sanity: no 1-op program computes stage1 (xor-shift needs >= 3).
    #[test]
    fn searcher_rejects_one_op_stage1() {
        static F: fn(&[u32]) -> u32 = |x| hs::stage1(x[0]);
        let ctx = ctx_for(1, &[("STAGE1_XOR_CONSTANT", hs::STAGE1_XOR_CONSTANT), ("sh1", 19)], &F);
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
            let mut v = [0u32; PROBE_COUNT];
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
                let mut w = [0u32; PROBE_COUNT];
                for p in 0..PROBE_COUNT {
                    w[p] = multiply_add(v[p], k, c);
                }
                assert_eq!(
                    affine_canon(&w).unwrap(),
                    canon,
                    "canon not invariant under odd K={k:#x}, C={c:#x}"
                );
            }
            for t in 1..=MAX_EVEN_MULTIPLIER_SHIFT {
                let k = 33u32 << t; // even multiplier with odd part 33
                let mut w = [0u32; PROBE_COUNT];
                for p in 0..PROBE_COUNT {
                    w[p] = multiply_add(v[p], k, 0x0BAD_F00D);
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
        let mut m = [0u32; PROBE_COUNT];
        for x in m.iter_mut() {
            *x = rng.next_u64() as u32;
        }
        for &(k, c) in &[
            (0x0000_1234u32, 0x0F0F_0F0Fu32), // even K (val 2)
            (33 << 9, 0xB55A_4F09),           // F23_Q_MULTIPLIER-like: odd part 33, t=9
            (0x8000_0000, 1),                 // extreme valuation
            (4097, 0),                        // odd K
        ] {
            let mut r = [0u32; PROBE_COUNT];
            for p in 0..PROBE_COUNT {
                r[p] = multiply_add(m[p], k, c);
            }
            let (ks, cs) = solve_affine_meet(&m, &r).expect("solve failed");
            for p in 0..PROBE_COUNT {
                assert_eq!(multiply_add(m[p], ks, cs), r[p]);
            }
        }
    }

    /// End-to-end engine C regression: stage5(stage4(d)) must be rediscovered
    /// as a 4-op program shaped [affine meet on d] + [XsR(16)] + [XorC(STAGE5_XOR_CONSTANT)] —
    /// exercising the prefix_op_count=0 prefix table, the affine-normalized meet solve,
    /// chain emission, and full verification.
    #[test]
    fn mitm_engine_c_rediscovers_g45_shape() {
        static F: fn(&[u32]) -> u32 = |x| hs::stage5(hs::stage4(x[0]));
        let ctx = ctx_for(1, &[], &F);
        let link_consts = build_link_consts(&[hs::STAGE5_XOR_CONSTANT], &[16]);
        let links = build_links(&link_consts);
        let fwd_tabs: Vec<FwdTab> = (0..=2).map(|prefix_op_count| build_fwd_tab(&ctx, prefix_op_count)).collect();
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
                ("F23_P_MULTIPLIER", hs::F23_P_MULTIPLIER),
                ("F23_P_CONSTANT", hs::F23_P_CONSTANT),
                ("F23_Q_MULTIPLIER", hs::F23_Q_MULTIPLIER),
                ("F23_Q_CONSTANT", hs::F23_Q_CONSTANT),
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
