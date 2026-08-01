//! P5-B: kf>=3 global hash MITM — the funded Phase-5 search of the regions
//! every prior effort left uncovered.
//!
//! Machinery is transcribed from `fusion_search.rs` (H-003/H-016/H-025
//! verified code) with these EXTENSIONS, none of which exist there:
//!
//!   1. FULL-SHAPE kf=3 forward tables: the existing kf=3/kf=4 arms of
//!      `build_fwd_tab` only enumerate CHAINED prefixes (each temp consumed
//!      by the very next op). The full-shape builder additionally covers the
//!      PARALLEL shape t1=f(x); t2=g(x); t3=h(t1,t2) — the shape of the
//!      stage3/4 twin-madd merge, invisible to every prior kf=3 run.
//!   2. kf=4 chained tables wired into engine C (never wired before).
//!   3. Fwd-table sharding (--fwd-shard I/N over (i1,i2) first/second-level
//!      candidate pairs) + link sharding (--link-shard I/N over engine C's
//!      top-level links) so each run fits an 8-minute slice on a 24GB box.
//!   4. Chain cap raised to 6 (--max-chain 6; 6-op chains = 3 xor-shift
//!      macros under the >=5-op <=1-unary rule), reaching total depth
//!      kf3+meet+6 = 10 — the 11->10 question's depth — for these shapes.
//!   5. New targets: `full_hash_core` (myhash, lean 12-const pool),
//!      `round12` (the TWO-INPUT 12-op round body myhash(x ^ y), never a
//!      MITM target before), `f2ap` / `e2xw` (the two 4-op cross-round
//!      spans P3-F named as depth-3-unsearched).
//!
//! Vocabulary: 8 alu binops + multiply_add (runtime multiplicand included —
//! enumerate_level generates madd over ALL pool triples). Compare/select
//! excluded (closed by G-24), div/mod excluded (closed by P3-F).
//!
//! Every find is verified on 10M+ random + structured inputs before being
//! reported (same battery as fusion_search).
//!
//! Usage:
//!   global_mitm --selftest                 # planted-control regression
//!   global_mitm full_hash_core --ext kf3full --max-chain 6 \
//!       --fwd-shard 0/4 --link-shard 0/2   # one slice
//!   global_mitm round12 --ext kf3full ...
//!   global_mitm f2ap                       # span target (engine A + C)

use perf_harness::problem::hashseg as hs;
use perf_harness::problem::{myhash, Rng};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Instant;

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

#[inline(always)]
fn multiply_add(a: u32, b: u32, c: u32) -> u32 {
    a.wrapping_mul(b).wrapping_add(c)
}

fn modinv32(a: u32) -> u32 {
    debug_assert!(a & 1 == 1);
    let mut x = 1u32;
    for _ in 0..5 {
        x = x.wrapping_mul(2u32.wrapping_sub(a.wrapping_mul(x)));
    }
    x
}

#[derive(Clone, Debug)]
enum Inst {
    Bin(Op, usize, usize),
    MultiplyAdd(usize, usize, usize),
    BinConstRight(Op, usize, u32),
    BinConstLeft(Op, u32, usize),
    MultiplyAddConst(usize, usize, u32),
    MultiplyAddAffine(usize, u32, u32),
}

type TargetFn = dyn Fn(&[u32]) -> u32 + Sync;

struct Ctx<'a> {
    input_count: usize,
    base_names: Vec<String>,
    base_vals: Vec<ProbeValues>,
    base_is_const: Vec<bool>,
    target: ProbeValues,
    tested_count: AtomicU64,
    should_stop: AtomicBool,
    finds: Mutex<Vec<Vec<Inst>>>,
    unsolved_count: AtomicU64,
    reference_fn: &'a TargetFn,
}

struct SearchState {
    vals: Vec<ProbeValues>,
    probe0_vals: Vec<u32>,
    is_const: Vec<bool>,
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

    fn is_dup(&self, candidate_probe0: u32, v: &ProbeValues) -> bool {
        for (i, &p0) in self.probe0_vals.iter().enumerate() {
            if p0 == candidate_probe0 && &self.vals[i] == v {
                return true;
            }
        }
        false
    }

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

    for i in 0..pool_size {
        if w.is_const[i] {
            continue;
        }
        if !unused_temp_indices.iter().all(|&u| u == i) {
            continue;
        }
        let sole_operand = &w.vals[i];

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

        for s in 0..32u32 {
            w.tested_local += 2;
            if (sole_operand[0] << s) == target_probe0 && (0..PROBE_COUNT).all(|p| (sole_operand[p] << s) == target[p]) {
                report(ctx, w, Inst::BinConstRight(Shl, i, s));
            }
            if (sole_operand[0] >> s) == target_probe0 && (0..PROBE_COUNT).all(|p| (sole_operand[p] >> s) == target[p]) {
                report(ctx, w, Inst::BinConstRight(Shr, i, s));
            }
        }

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

fn report(ctx: &Ctx, w: &SearchState, last: Inst) {
    let mut prog = w.prog.clone();
    prog.push(last);
    report_prog(ctx, prog);
}

fn report_prog(ctx: &Ctx, prog: Vec<Inst>) {
    let ok = verify(ctx, &prog);
    let txt = render(ctx, &prog);
    println!(
        "  >>> {} candidate ({} ops): {}",
        if ok { "VERIFIED" } else { "FALSE-POSITIVE (probe collision)" },
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

fn run_prog(ctx: &Ctx, prog: &[Inst], inputs: &[u32]) -> u32 {
    let base_count = ctx.base_vals.len();
    let mut vals: Vec<u32> = Vec::with_capacity(base_count + prog.len());
    vals.extend_from_slice(inputs);
    for b in ctx.input_count..base_count {
        vals.push(ctx.base_vals[b][0]);
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

fn search_iterative(ctx: &Ctx, max_ops: usize, threads: usize) {
    for op_count in 1..=max_ops {
        if !ctx.finds.lock().unwrap().is_empty() {
            break;
        }
        let iteration_start = Instant::now();
        if op_count == 1 {
            let mut w = SearchState::new(ctx);
            final_level(ctx, &mut w);
            ctx.tested_count.fetch_add(w.tested_local, Ordering::Relaxed);
        } else {
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
            "   engine A op_count={op_count}: exhausted in {:.1}s (cumulative candidates: {})",
            iteration_start.elapsed().as_secs_f64(),
            ctx.tested_count.load(Ordering::Relaxed)
        );
    }
}

// ---------------------------------------------------------------------------
// MITM machinery (transcribed from fusion_search.rs H-016 section)
// ---------------------------------------------------------------------------

const MAX_EVEN_MULTIPLIER_SHIFT: u32 = 12;
const LINK_CONSTANT_POOL_CAP: usize = 72;

const ODD_LINK_MULTIPLIERS: [u32; 16] = [
    1,
    0xFFFF_FFFF,
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
    297,
];

const TAG_EXACT: u64 = 0x4558_4143_5421_1111;
const TAG_XOR_NORM: u64 = 0x584f_524e_5f5f_2222;
const TAG_AFFINE_CANON: u64 = 0x4146_464e_5f5f_3333;

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

fn xor_norm(v: &ProbeValues) -> [u32; PROBE_COUNT - 1] {
    let mut d = [0u32; PROBE_COUNT - 1];
    for p in 1..PROBE_COUNT {
        d[p - 1] = v[p] ^ v[0];
    }
    d
}

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

fn solve_xor_meet(m: &ProbeValues, r: &ProbeValues) -> Option<u32> {
    let c = r[0] ^ m[0];
    if (0..PROBE_COUNT).all(|p| (m[p] ^ c) == r[p]) {
        Some(c)
    } else {
        None
    }
}

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
        return None;
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

fn un_xsr(v: u32, s: u32) -> u32 {
    let mut x = v;
    for _ in 0..(32 / s + 1) {
        x = v ^ (x >> s);
    }
    x
}

fn un_xsl(v: u32, s: u32) -> u32 {
    let mut x = v;
    for _ in 0..(32 / s + 1) {
        x = v ^ (x << s);
    }
    x
}

#[derive(Clone, Copy, Debug)]
enum Link {
    Aff { k: u32, kinv: u32, c: u32 },
    XorC(u32),
    XsR(u32),
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

fn emit_chain(links: &[Link], mut cur: usize, base_count: usize, prog: &mut Vec<Inst>) {
    for link in links.iter().rev() {
        cur = link.emit(cur, base_count, prog);
    }
}

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
                continue;
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
    affine_canon: IdMap,
}

impl FwdTab {
    fn new(prefix_op_count: usize) -> FwdTab {
        FwdTab {
            prefix_op_count,
            entries: Vec::new(),
            exact: IdMap::default(),
            xor_norm: IdMap::default(),
            affine_canon: IdMap::default(),
        }
    }
    fn add(&mut self, out: ProbeValues, prog: Vec<Inst>, out_idx: usize) {
        let exact_key = hash_words(TAG_EXACT, &out);
        if self.exact.contains_key(&exact_key) {
            return;
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

/// kf<=2 tables, exactly as fusion_search builds them.
fn build_fwd_tab_base(ctx: &Ctx, prefix_op_count: usize) -> FwdTab {
    let mut tab = FwdTab::new(prefix_op_count);
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
            let mut l1: Vec<(Inst, ProbeValues)> = Vec::new();
            enumerate_level(&w, |inst, v| l1.push((inst, v)));
            for (i1, v1) in l1 {
                let undo = w.push(i1.clone(), v1);
                enumerate_level(&w, |i2, v2| {
                    if inst_uses(&i2, base_count) {
                        tab.add(v2, vec![i1.clone(), i2], base_count + 1);
                    }
                });
                w.pop(undo);
            }
        }
        _ => unreachable!("build_fwd_tab_base only goes to kf = 2"),
    }
    tab
}

/// NEW (P5-B): kf=3 forward tables in FULL shape coverage — chained
/// (i2 uses t1; i3 uses t2) AND parallel (i2 independent of t1; i3 must then
/// use BOTH t1 and t2). Together these are ALL 3-op DAG shapes in which
/// every non-final temp is referenced (the meet variable is t3).
/// `chained_only` reproduces the old restricted arm (for the negative
/// control). Shard: keep only (i1_idx, i2_idx) pairs with
/// (i1_idx*1000003 + i2_idx) % shard_n == shard_i. Returns None if the
/// entry cap is exceeded (RAM guard).
fn build_fwd_tab3(
    ctx: &Ctx,
    chained_only: bool,
    shard_i: u64,
    shard_n: u64,
    cap: usize,
) -> Option<FwdTab> {
    let mut tab = FwdTab::new(3);
    let base_count = ctx.base_vals.len();
    let mut w = SearchState::new(ctx);
    let mut l1: Vec<(Inst, ProbeValues)> = Vec::new();
    enumerate_level(&w, |inst, v| l1.push((inst, v)));
    for (idx1, (i1, v1)) in l1.iter().enumerate() {
        let undo1 = w.push(i1.clone(), *v1);
        let mut l2: Vec<(Inst, ProbeValues, bool)> = Vec::new();
        enumerate_level(&w, |i2, v2| {
            let uses_t1 = inst_uses(&i2, base_count);
            if uses_t1 || !chained_only {
                l2.push((i2, v2, uses_t1));
            }
        });
        for (idx2, (i2, v2, uses_t1)) in l2.into_iter().enumerate() {
            if ((idx1 as u64) * 1_000_003 + idx2 as u64) % shard_n != shard_i {
                continue;
            }
            let undo2 = w.push(i2.clone(), v2);
            let mut overflow = false;
            enumerate_level(&w, |i3, v3| {
                if tab.entries.len() >= cap {
                    overflow = true;
                    return;
                }
                let ok = if uses_t1 {
                    inst_uses(&i3, base_count + 1)
                } else {
                    inst_uses(&i3, base_count + 1) && inst_uses(&i3, base_count)
                };
                if ok {
                    tab.add(v3, vec![i1.clone(), i2.clone(), i3], base_count + 2);
                }
            });
            w.pop(undo2);
            if overflow {
                println!("   !! fwd tab3 entry cap {cap} exceeded — use more shards");
                return None;
            }
        }
        w.pop(undo1);
    }
    Some(tab)
}

/// NEW (P5-B): kf=4 CHAINED tables (each temp consumed by the very next op),
/// sharded like build_fwd_tab3. Full-shape kf=4 is out of reach; this arm's
/// coverage statement is exactly "chained 4-prefixes".
fn build_fwd_tab4_chained(ctx: &Ctx, shard_i: u64, shard_n: u64, cap: usize) -> Option<FwdTab> {
    let mut tab = FwdTab::new(4);
    let base_count = ctx.base_vals.len();
    let mut w = SearchState::new(ctx);
    let mut l1: Vec<(Inst, ProbeValues)> = Vec::new();
    enumerate_level(&w, |inst, v| l1.push((inst, v)));
    for (idx1, (i1, v1)) in l1.iter().enumerate() {
        let undo1 = w.push(i1.clone(), *v1);
        let mut l2: Vec<(Inst, ProbeValues)> = Vec::new();
        enumerate_level(&w, |i2, v2| {
            if inst_uses(&i2, base_count) {
                l2.push((i2, v2));
            }
        });
        for (idx2, (i2, v2)) in l2.into_iter().enumerate() {
            if ((idx1 as u64) * 1_000_003 + idx2 as u64) % shard_n != shard_i {
                continue;
            }
            let undo2 = w.push(i2.clone(), v2);
            let mut l3: Vec<(Inst, ProbeValues)> = Vec::new();
            enumerate_level(&w, |i3, v3| {
                if inst_uses(&i3, base_count + 1) {
                    l3.push((i3, v3));
                }
            });
            let mut overflow = false;
            for (i3, v3) in l3 {
                let undo3 = w.push(i3.clone(), v3);
                enumerate_level(&w, |i4, v4| {
                    if tab.entries.len() >= cap {
                        overflow = true;
                        return;
                    }
                    if inst_uses(&i4, base_count + 2) {
                        tab.add(v4, vec![i1.clone(), i2.clone(), i3.clone(), i4], base_count + 3);
                    }
                });
                w.pop(undo3);
                if overflow {
                    break;
                }
            }
            w.pop(undo2);
            if overflow {
                println!("   !! fwd tab4 entry cap {cap} exceeded — use more shards");
                return None;
            }
        }
        w.pop(undo1);
    }
    Some(tab)
}

struct MitmStats {
    bwd_nodes: AtomicU64,
}

/// Engine C with parameterized chain cap (up to 6) and link sharding.
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
            if next_unary_link_count > 3 || (nops >= 5 && next_unary_link_count > 1) {
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

#[allow(clippy::too_many_arguments)]
fn run_engine_c(
    ctx: &Ctx,
    links: &[Link],
    fwd: &[FwdTab],
    max_chain_ops: usize,
    wanted: u32,
    stats: &MitmStats,
    threads: usize,
    link_shard_i: u64,
    link_shard_n: u64,
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
                    if (idx as u64) % link_shard_n != link_shard_i {
                        continue;
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
// Targets
// ---------------------------------------------------------------------------

struct GTarget {
    name: &'static str,
    desc: &'static str,
    input_count: usize,
    current_ops: usize,
    /// forward-exhaustive engine A depth (0 = skip).
    engine_a_kmax: usize,
    pool: Vec<(&'static str, u32)>,
    seed: Vec<u32>,
    shifts: Vec<u32>,
    reference_fn: Box<TargetFn>,
}

/// The lean "core" pool: the 10 fused-hash stage constants + the two shift
/// amounts. Chosen so kf=3 full-shape tables fit a 24GB box in a few shards
/// (fusion_search's 23-item full_hash pool is a proven kf=3 memory wall).
fn core_pool() -> Vec<(&'static str, u32)> {
    vec![
        ("C0", hs::STAGE0_ADD_CONSTANT),
        ("K0", hs::STAGE0_MULTIPLIER),
        ("C1", hs::STAGE1_XOR_CONSTANT),
        ("KP", hs::F23_P_MULTIPLIER),
        ("AP", hs::F23_P_CONSTANT),
        ("KQ", hs::F23_Q_MULTIPLIER),
        ("AQ", hs::F23_Q_CONSTANT),
        ("K4", hs::STAGE4_MULTIPLIER),
        ("C4", hs::STAGE4_ADD_CONSTANT),
        ("C5", hs::STAGE5_XOR_CONSTANT),
        ("s19", 19),
        ("s16", 16),
    ]
}

fn full_seed() -> Vec<u32> {
    let c1s = hs::STAGE1_XOR_CONSTANT >> 19;
    let c1i = hs::STAGE1_XOR_CONSTANT ^ c1s;
    let c5s = hs::STAGE5_XOR_CONSTANT >> 16;
    let c5i = hs::STAGE5_XOR_CONSTANT ^ c5s;
    let c0s = hs::STAGE0_ADD_CONSTANT >> 19;
    let kpc1 = hs::F23_P_MULTIPLIER.wrapping_mul(hs::STAGE1_XOR_CONSTANT);
    let kqc1 = hs::F23_Q_MULTIPLIER.wrapping_mul(hs::STAGE1_XOR_CONSTANT);
    vec![
        hs::STAGE0_ADD_CONSTANT,
        hs::STAGE0_MULTIPLIER,
        hs::STAGE1_XOR_CONSTANT,
        hs::F23_P_MULTIPLIER,
        hs::F23_P_CONSTANT,
        hs::F23_Q_MULTIPLIER,
        hs::F23_Q_CONSTANT,
        hs::STAGE4_ADD_CONSTANT,
        hs::STAGE5_XOR_CONSTANT,
        c1s,
        c1i,
        c5s,
        c5i,
        c0s,
        kpc1,
        kqc1,
        hs::F23_P_CONSTANT.wrapping_add(kpc1),
        hs::F23_Q_CONSTANT.wrapping_add(kqc1),
        hs::F23_P_MULTIPLIER.wrapping_mul(9),
        hs::F23_Q_MULTIPLIER.wrapping_mul(9),
        hs::F23_P_CONSTANT.wrapping_mul(9).wrapping_add(hs::STAGE4_ADD_CONSTANT),
        hs::F23_Q_CONSTANT.wrapping_mul(9),
        hs::STAGE0_MULTIPLIER.wrapping_mul(1 << 16),
        hs::STAGE0_MULTIPLIER.wrapping_mul(hs::STAGE4_ADD_CONSTANT),
        hs::STAGE0_MULTIPLIER.wrapping_mul(hs::STAGE5_XOR_CONSTANT),
        hs::STAGE0_MULTIPLIER.wrapping_mul(9),
    ]
}

fn gtargets() -> Vec<GTarget> {
    let common = [("zero", 0u32), ("one", 1u32), ("m1", 0xFFFF_FFFF)];
    let c5s = hs::STAGE5_XOR_CONSTANT >> 16;
    let c5i = hs::STAGE5_XOR_CONSTANT ^ c5s;
    let k016 = hs::STAGE0_MULTIPLIER.wrapping_mul(1 << 16);
    let k0c5 = hs::STAGE0_MULTIPLIER.wrapping_mul(hs::STAGE5_XOR_CONSTANT);
    vec![
        GTarget {
            name: "full_hash_core",
            desc: "whole 11-op hash, core pool: myhash(x), hunting <=10",
            input_count: 1,
            current_ops: 11,
            engine_a_kmax: 0, // H-003 closed k<=4 forward-exhaustive already
            pool: core_pool(),
            seed: full_seed(),
            shifts: vec![12, 19, 5, 9, 3, 16, 13, 14],
            reference_fn: Box::new(|x| myhash(x[0])),
        },
        GTarget {
            name: "round12",
            desc: "TWO-INPUT 12-op round body: myhash(x ^ y) (fold-in + 11), hunting <=11",
            input_count: 2,
            current_ops: 12,
            engine_a_kmax: 3,
            pool: core_pool(),
            seed: full_seed(),
            shifts: vec![12, 19, 5, 9, 3, 16, 13, 14],
            reference_fn: Box::new(|x| myhash(x[0] ^ x[1])),
        },
        GTarget {
            name: "f2ap",
            desc: "cross-round 4-op span f->a' (primed): stage0(sigma16(x) ^ y), hunting <=3",
            input_count: 2,
            current_ops: 4,
            engine_a_kmax: 3,
            pool: common
                .iter()
                .cloned()
                .chain(
                    [
                        ("C0", hs::STAGE0_ADD_CONSTANT),
                        ("K0", hs::STAGE0_MULTIPLIER),
                        ("C5", hs::STAGE5_XOR_CONSTANT),
                        ("C5s", c5s),
                        ("C5i", c5i),
                        ("s16", 16u32),
                        ("s12", 12),
                        ("p16", 1 << 16),
                        ("K016", k016),
                        ("K0C5", k0c5),
                    ]
                    .iter()
                    .cloned(),
                )
                .collect(),
            seed: vec![
                hs::STAGE0_ADD_CONSTANT,
                hs::STAGE0_MULTIPLIER,
                hs::STAGE5_XOR_CONSTANT,
                c5s,
                c5i,
                k016,
                k0c5,
            ],
            shifts: vec![16, 12, 4, 15],
            reference_fn: Box::new(|x| hs::stage0(hs::sigma16(x[0]) ^ x[1])),
        },
        GTarget {
            name: "e2xw",
            desc: "cross-round 4-op span e->x' (primed): sigma16(stage4(x)) ^ y, hunting <=3",
            input_count: 2,
            current_ops: 4,
            engine_a_kmax: 3,
            pool: common
                .iter()
                .cloned()
                .chain(
                    [
                        ("K4", hs::STAGE4_MULTIPLIER),
                        ("C4", hs::STAGE4_ADD_CONSTANT),
                        ("C5", hs::STAGE5_XOR_CONSTANT),
                        ("C5i", c5i),
                        ("s16", 16u32),
                        ("s3", 3),
                        ("p16", 1 << 16),
                    ]
                    .iter()
                    .cloned(),
                )
                .collect(),
            seed: vec![
                hs::STAGE4_ADD_CONSTANT,
                hs::STAGE5_XOR_CONSTANT,
                c5i,
                hs::STAGE4_ADD_CONSTANT << 16,
            ],
            shifts: vec![16, 3, 12],
            reference_fn: Box::new(|x| hs::sigma16(hs::stage4(x[0])) ^ x[1]),
        },
        GTarget {
            // planted positive control for the kf3-FULL machinery: a
            // PARALLEL 3-op prefix (invisible to chained kf3) + affine meet
            // + 4-op suffix chain. 8 machine ops total.
            name: "planted_par",
            desc: "SELFTEST planted: madd33/madd16896 parallel merge + meet + xsr16+xorC1+aff33 suffix",
            input_count: 1,
            current_ops: 9, // pretend, so kmax=8 and the 8-op plant is hunted
            engine_a_kmax: 0,
            pool: vec![
                ("KP", hs::F23_P_MULTIPLIER),
                ("AP", hs::F23_P_CONSTANT),
                ("KQ", hs::F23_Q_MULTIPLIER),
                ("AQ", hs::F23_Q_CONSTANT),
            ],
            seed: vec![
                hs::STAGE1_XOR_CONSTANT,
                0x1656_67B1,
                hs::STAGE4_ADD_CONSTANT,
            ],
            shifts: vec![16],
            reference_fn: Box::new(|x| {
                let t1 = multiply_add(x[0], hs::F23_P_MULTIPLIER, hs::F23_P_CONSTANT);
                let t2 = multiply_add(x[0], hs::F23_Q_MULTIPLIER, hs::F23_Q_CONSTANT);
                let t3 = t1 ^ t2;
                let m = multiply_add(t3, 9, hs::STAGE4_ADD_CONSTANT);
                let u = m ^ (m >> 16);
                let u2 = u ^ hs::STAGE1_XOR_CONSTANT;
                multiply_add(u2, 33, 0x1656_67B1)
            }),
        },
    ]
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

#[derive(Clone, Copy, PartialEq)]
enum Ext {
    None,
    Kf3Full,
    Kf3Chained,
    Kf4Chained,
}

struct RunCfg {
    ext: Ext,
    max_chain: usize,
    fwd_shard: (u64, u64),
    link_shard: (u64, u64),
    tab_cap: usize,
    engine_a_override: Option<usize>,
    skip_base_tabs: bool,
}

fn run_target(tg: &GTarget, cfg: &RunCfg, threads: usize) -> usize {
    let kmax_use = tg.current_ops - 1;
    let wanted: u32 = (2u32 << kmax_use) - 2;
    println!(
        "== global_mitm target {} : {} (current {} ops, hunting k <= {}) ==",
        tg.name, tg.desc, tg.current_ops, kmax_use
    );
    let t_start = Instant::now();
    let ctx = build_ctx(tg.input_count, &tg.pool, &*tg.reference_fn);
    println!(
        "   pool ({}): [{}]",
        tg.pool.len(),
        ctx.base_names.iter().skip(tg.input_count).cloned().collect::<Vec<_>>().join(", ")
    );

    let engine_a_kmax = cfg.engine_a_override.unwrap_or(tg.engine_a_kmax);
    if engine_a_kmax > 0 {
        println!("   engine A (forward exhaustive) k <= {engine_a_kmax}");
        search_iterative(&ctx, engine_a_kmax, threads);
    }

    let link_consts = build_link_consts(&tg.seed, &tg.shifts);
    let links = build_links(&link_consts);
    println!(
        "   link pool: {} constants, {} odd Ks, {} links; link shard {}/{}",
        link_consts.len(),
        ODD_LINK_MULTIPLIERS.len(),
        links.len(),
        cfg.link_shard.0,
        cfg.link_shard.1
    );

    let mut fwd_tabs: Vec<FwdTab> = Vec::new();
    if !cfg.skip_base_tabs {
        for kf in 0..=2usize {
            let t0 = Instant::now();
            let tab = build_fwd_tab_base(&ctx, kf);
            println!("   fwd tab kf={kf}: {} entries ({:.1}s)", tab.entries.len(), t0.elapsed().as_secs_f64());
            fwd_tabs.push(tab);
        }
    }
    let ext_name = match cfg.ext {
        Ext::None => "none",
        Ext::Kf3Full => "kf3full",
        Ext::Kf3Chained => "kf3chained",
        Ext::Kf4Chained => "kf4chained",
    };
    match cfg.ext {
        Ext::None => {}
        Ext::Kf3Full | Ext::Kf3Chained => {
            let t0 = Instant::now();
            let chained = cfg.ext == Ext::Kf3Chained;
            match build_fwd_tab3(&ctx, chained, cfg.fwd_shard.0, cfg.fwd_shard.1, cfg.tab_cap) {
                Some(tab) => {
                    println!(
                        "   fwd tab kf=3 ({}) shard {}/{}: {} entries ({:.1}s)",
                        if chained { "chained" } else { "FULL shape" },
                        cfg.fwd_shard.0,
                        cfg.fwd_shard.1,
                        tab.entries.len(),
                        t0.elapsed().as_secs_f64()
                    );
                    fwd_tabs.push(tab);
                }
                None => {
                    println!("CHECKPOINT target={} ext={} ABORT=tab_cap fwd_shard={}/{}", tg.name, ext_name, cfg.fwd_shard.0, cfg.fwd_shard.1);
                    return 1;
                }
            }
        }
        Ext::Kf4Chained => {
            let t0 = Instant::now();
            match build_fwd_tab4_chained(&ctx, cfg.fwd_shard.0, cfg.fwd_shard.1, cfg.tab_cap) {
                Some(tab) => {
                    println!(
                        "   fwd tab kf=4 (chained) shard {}/{}: {} entries ({:.1}s)",
                        cfg.fwd_shard.0,
                        cfg.fwd_shard.1,
                        tab.entries.len(),
                        t0.elapsed().as_secs_f64()
                    );
                    fwd_tabs.push(tab);
                }
                None => {
                    println!("CHECKPOINT target={} ext={} ABORT=tab_cap fwd_shard={}/{}", tg.name, ext_name, cfg.fwd_shard.0, cfg.fwd_shard.1);
                    return 1;
                }
            }
        }
    }

    let stats = MitmStats {
        bwd_nodes: AtomicU64::new(0),
    };
    let tc = Instant::now();
    run_engine_c(
        &ctx,
        &links,
        &fwd_tabs,
        cfg.max_chain,
        wanted,
        &stats,
        threads,
        cfg.link_shard.0,
        cfg.link_shard.1,
    );
    let chain_nodes = stats.bwd_nodes.load(Ordering::Relaxed);
    println!("   engine C: {} chain nodes probed in {:.1}s (max_chain={})", chain_nodes, tc.elapsed().as_secs_f64(), cfg.max_chain);

    let finds = ctx.finds.lock().unwrap().len();
    let tab_desc: Vec<String> = fwd_tabs.iter().map(|t| format!("kf{}:{}", t.prefix_op_count, t.entries.len())).collect();
    println!(
        "CHECKPOINT target={} ext={} maxchain={} fwd_shard={}/{} link_shard={}/{} tabs=[{}] chain_nodes={} finds={} secs={:.1}",
        tg.name,
        ext_name,
        cfg.max_chain,
        cfg.fwd_shard.0,
        cfg.fwd_shard.1,
        cfg.link_shard.0,
        cfg.link_shard.1,
        tab_desc.join(","),
        chain_nodes,
        finds,
        t_start.elapsed().as_secs_f64()
    );
    if finds == 0 {
        println!("   RESULT: no program of <= {kmax_use} ops in this slice's space\n");
    } else {
        println!("   RESULT: {finds} verified find(s) — see VERIFIED lines above\n");
    }
    finds
}

fn parse_shard(s: &str) -> (u64, u64) {
    let mut it = s.split('/');
    let i = it.next().unwrap().parse().unwrap();
    let n = it.next().unwrap().parse().unwrap();
    assert!(n > 0 && i < n, "bad shard {s}");
    (i, n)
}

/// Planted-control regression for the NEW machinery.
fn selftest(threads: usize) {
    let all = gtargets();
    let tg = all.iter().find(|t| t.name == "planted_par").unwrap();

    // 1. kf3-FULL must find the planted 8-op parallel-prefix form.
    let cfg = RunCfg {
        ext: Ext::Kf3Full,
        max_chain: 5,
        fwd_shard: (0, 1),
        link_shard: (0, 1),
        tab_cap: 50_000_000,
        engine_a_override: None,
        skip_base_tabs: false,
    };
    let finds = run_target(tg, &cfg, threads);
    assert!(finds > 0, "SELFTEST FAIL: kf3-full did not find the planted parallel-prefix form");
    println!("SELFTEST 1 PASS: kf3-full finds the planted parallel form ({finds} find(s))");

    // 2. kf3-CHAINED (the old shape family) must NOT see it — proves the
    //    parallel shape is a real coverage extension. skip_base_tabs so the
    //    only path would be the chained kf3 table.
    let cfg2 = RunCfg {
        ext: Ext::Kf3Chained,
        max_chain: 5,
        fwd_shard: (0, 1),
        link_shard: (0, 1),
        tab_cap: 50_000_000,
        engine_a_override: None,
        skip_base_tabs: true,
    };
    let finds2 = run_target(tg, &cfg2, threads);
    assert!(finds2 == 0, "SELFTEST unexpected: chained kf3 found a form (inspect above — may be a real alternate)");
    println!("SELFTEST 2 PASS: chained kf3 (old family) does NOT see the parallel plant");

    // 3. shard-union control: with 4 fwd shards, exactly >=1 shard finds it.
    let mut shard_finds = 0;
    for i in 0..4u64 {
        let cfgs = RunCfg {
            ext: Ext::Kf3Full,
            max_chain: 5,
            fwd_shard: (i, 4),
            link_shard: (0, 1),
            tab_cap: 50_000_000,
            engine_a_override: None,
            skip_base_tabs: true,
        };
        shard_finds += run_target(tg, &cfgs, threads);
    }
    assert!(shard_finds > 0, "SELFTEST FAIL: no fwd shard of 4 found the plant");
    println!("SELFTEST 3 PASS: shard union preserves coverage ({shard_finds} find(s) across 4 shards)");
    println!("SELFTEST: ALL PASS");
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4);
    if args.iter().any(|a| a == "--selftest") {
        selftest(threads);
        return;
    }
    let get = |flag: &str| -> Option<String> {
        args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1).cloned())
    };
    let ext = match get("--ext").as_deref() {
        None | Some("none") => Ext::None,
        Some("kf3full") => Ext::Kf3Full,
        Some("kf3chained") => Ext::Kf3Chained,
        Some("kf4chained") => Ext::Kf4Chained,
        Some(other) => panic!("unknown --ext {other}"),
    };
    let cfg = RunCfg {
        ext,
        max_chain: get("--max-chain").map_or(5, |v| v.parse().unwrap()),
        fwd_shard: get("--fwd-shard").map_or((0, 1), |v| parse_shard(&v)),
        link_shard: get("--link-shard").map_or((0, 1), |v| parse_shard(&v)),
        tab_cap: get("--tab-cap").map_or(30_000_000, |v| v.parse().unwrap()),
        engine_a_override: get("--engine-a").map(|v| v.parse().unwrap()),
        skip_base_tabs: args.iter().any(|a| a == "--skip-base-tabs"),
    };
    assert!(cfg.max_chain <= 6, "max chain is capped at 6");
    let names: Vec<&String> = args
        .iter()
        .enumerate()
        .filter(|(i, a)| {
            !a.starts_with("--")
                && !(*i > 0
                    && ["--ext", "--max-chain", "--fwd-shard", "--link-shard", "--tab-cap", "--engine-a"]
                        .contains(&args[i - 1].as_str()))
        })
        .map(|(_, a)| a)
        .collect();
    let all = gtargets();
    let mut ran = 0;
    for tg in &all {
        if names.iter().any(|n| n.as_str() == tg.name) {
            run_target(tg, &cfg, threads);
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
