//! P5-D: fan-out suffix MITM — the region P5-B named and could not reach.
//!
//! Every suffix family ever searched (G-10, H-016, H-025, P3-F, P5-B) is a
//! CHAIN: each suffix op reads only the running value (+ constants). The real
//! 11-op hash has FAN-OUT in its back half (three intermediates read twice).
//! This binary extends the P5-B MITM (global_mitm.rs, validated) to suffixes
//! that read the meet value m AND one earlier live value r:
//!
//!   [<=3-op FULL-SHAPE DAG prefix; m = final value; r = any runtime slot,
//!    including temps left unreferenced by the DAG (they become r)]
//!     -> j = g(m, r)      the JOIN (forward-computed; g need not be
//!                          invertible: xor/add/sub/rsub/and/or/mul/shifts/
//!                          m*K+r/r*K+m for the odd link multipliers)
//!     -> [optional solved xor/affine meet]  (engine C probe machinery)
//!     -> [invertible pooled suffix chain <= 6 ops]
//!
//! The joined value j is tabled exactly like a P5-B forward prefix (exact +
//! xor-norm + affine-canon keys), so engine C is reused verbatim. Coverage
//! framing: a kf3+join entry is a 4-op DAG whose final op reads the previous
//! temp plus one older live value — the entire enumerable increment the P5-D
//! shape census identified (join-at-4; 494 of 1.1e12 shapes at n=10).
//!
//! Also optional (--gen-shift-links): generalized xorshift chain links
//! v+(v>>s), v-(v>>s), (v>>s)-v with iterative inverses (fan-out of the
//! chain value under +/- instead of xor), roundtrip-asserted at startup.
//!
//! Usage:
//!   fanout_mitm --selftest
//!   fanout_mitm full_hash_core --kf 3 --join-g xor --join-r all \
//!       --max-chain 6 --fwd-shard 0/12
//!   fanout_mitm round12 --kf 3 --join-g xor --join-r y --fwd-shard 0/12

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
    MultiplyAddAffine(usize, u32, u32),
    /// vals[i] * k + vals[j] — the maddk join (constant multiplier that need
    /// not be in the DAG const pool).
    MaddConstMul(usize, u32, usize),
}

type TargetFn = dyn Fn(&[u32]) -> u32 + Sync;

struct Ctx<'a> {
    input_count: usize,
    base_names: Vec<String>,
    base_vals: Vec<ProbeValues>,
    base_is_const: Vec<bool>,
    target: ProbeValues,
    should_stop: AtomicBool,
    finds: Mutex<Vec<Vec<Inst>>>,
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
            _ => unreachable!("only raw DAG insts are pushed"),
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
            Inst::MultiplyAddAffine(i, k, c) => multiply_add(vals[i], k, c),
            Inst::MaddConstMul(i, k, j) => vals[i].wrapping_mul(k).wrapping_add(vals[j]),
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
            Inst::MultiplyAddAffine(a, k, c) => {
                format!("madd({}, {:#010x}, {:#010x})", name(a, ctx), k, c)
            }
            Inst::MaddConstMul(a, k, b) => {
                format!("madd({}, {:#010x}, {})", name(a, ctx), k, name(b, ctx))
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

// ---------------------------------------------------------------------------
// MITM machinery (transcribed from global_mitm.rs, P5-B validated)
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

/// LEMMA (P5-D, exhaustive at width 12 + witnessed at width 32): the
/// additive xorshift analogues v+(v>>s), v-(v>>s), (v>>s)-v are NEVER
/// bijections mod 2^w for any s in 1..w. Since every unary chain link of a
/// bijective composite must itself be bijective, these ops are PROVABLY
/// absent from all chain suffixes — excluding them loses no coverage.
fn additive_shift_lemma_check() -> bool {
    let w = 12u32;
    let m = (1u32 << w) - 1;
    for s in 1..w {
        for f in [
            |v: u32, s: u32, m: u32| (v.wrapping_add(v >> s)) & m,
            |v: u32, s: u32, m: u32| (v.wrapping_sub(v >> s)) & m,
            |v: u32, s: u32, m: u32| ((v >> s).wrapping_sub(v)) & m,
        ] {
            let mut seen = vec![false; 1 << w];
            let mut bij = true;
            for v in 0..=m {
                let x = f(v, s, m) as usize;
                if seen[x] {
                    bij = false;
                    break;
                }
                seen[x] = true;
            }
            if bij {
                return false; // some family IS bijective — lemma would be wrong
            }
        }
    }
    true
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
        Inst::MaddConstMul(i, _, j) => i == idx || j == idx,
        _ => false,
    }
}

/// kf<=2 plain tables (for --no-join / --with-base-tabs), as in global_mitm.
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
        _ => unreachable!(),
    }
    tab
}

/// Plain kf=3 FULL-shape table (for --no-join negative control).
fn build_fwd_tab3(ctx: &Ctx, shard_i: u64, shard_n: u64, cap: usize) -> Option<FwdTab> {
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
            l2.push((i2, v2, uses_t1));
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

// ---------------------------------------------------------------------------
// The JOIN (new)
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
enum JoinG {
    JXor,
    JAdd,
    JSub,
    JRSub,
    JAnd,
    JOr,
    JMul,
    JShlMR,
    JShrMR,
    JShlRM,
    JShrRM,
    JMaddUK(u32),
    JMaddRK(u32),
}
use JoinG::*;

impl JoinG {
    fn apply(self, m: u32, r: u32) -> u32 {
        match self {
            JXor => m ^ r,
            JAdd => m.wrapping_add(r),
            JSub => m.wrapping_sub(r),
            JRSub => r.wrapping_sub(m),
            JAnd => m & r,
            JOr => m | r,
            JMul => m.wrapping_mul(r),
            JShlMR => bin(Shl, m, r),
            JShrMR => bin(Shr, m, r),
            JShlRM => bin(Shl, r, m),
            JShrRM => bin(Shr, r, m),
            JMaddUK(k) => m.wrapping_mul(k).wrapping_add(r),
            JMaddRK(k) => r.wrapping_mul(k).wrapping_add(m),
        }
    }
    fn inst(self, m_idx: usize, r_idx: usize) -> Inst {
        match self {
            JXor => Inst::Bin(Xor, m_idx, r_idx),
            JAdd => Inst::Bin(Add, m_idx, r_idx),
            JSub => Inst::Bin(Sub, m_idx, r_idx),
            JRSub => Inst::Bin(Sub, r_idx, m_idx),
            JAnd => Inst::Bin(And, m_idx, r_idx),
            JOr => Inst::Bin(Or, m_idx, r_idx),
            JMul => Inst::Bin(Mul, m_idx, r_idx),
            JShlMR => Inst::Bin(Shl, m_idx, r_idx),
            JShrMR => Inst::Bin(Shr, m_idx, r_idx),
            JShlRM => Inst::Bin(Shl, r_idx, m_idx),
            JShrRM => Inst::Bin(Shr, r_idx, m_idx),
            JMaddUK(k) => Inst::MaddConstMul(m_idx, k, r_idx),
            JMaddRK(k) => Inst::MaddConstMul(r_idx, k, m_idx),
        }
    }
}

fn join_set(name: &str) -> Vec<JoinG> {
    match name {
        "xor" => vec![JXor],
        "add" => vec![JAdd],
        "sub" => vec![JSub],
        "rsub" => vec![JRSub],
        "basic" => vec![JXor, JAdd, JSub, JRSub],
        "ext" => vec![JAnd, JOr, JMul, JShlMR, JShrMR, JShlRM, JShrRM],
        "maddk" => {
            // K=1 duplicates JAdd; K=-1 duplicates JRSub/JSub — excluded.
            let mut v = Vec::new();
            for &k in ODD_LINK_MULTIPLIERS.iter() {
                if k == 1 || k == 0xFFFF_FFFF {
                    continue;
                }
                v.push(JMaddUK(k));
                v.push(JMaddRK(k));
            }
            v
        }
        "all" => {
            let mut v = join_set("basic");
            v.extend(join_set("ext"));
            v.extend(join_set("maddk"));
            v
        }
        other => panic!("unknown join set {other}"),
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum RSel {
    All,
    OnlyX,
    OnlyY,
    OnlyT(usize),
}

impl RSel {
    fn allows(self, r_idx: usize, base_count: usize, input_count: usize) -> bool {
        match self {
            RSel::All => true,
            RSel::OnlyX => r_idx == 0,
            RSel::OnlyY => input_count > 1 && r_idx == 1,
            RSel::OnlyT(t) => r_idx >= base_count && r_idx - base_count == t - 1,
        }
    }
}

/// Given a SearchState with the full DAG (including the final op) pushed,
/// add all (r, g) joined entries. Returns true on cap overflow.
/// r may be: any runtime base input, or any non-final temp. Non-final temps
/// left unreferenced by the DAG MUST become r (else the shape is invalid);
/// if 2+ temps are unreferenced the entry is skipped (double-join territory,
/// outside this family).
fn add_joined(
    tab: &mut FwdTab,
    ctx: &Ctx,
    w: &SearchState,
    gset: &[JoinG],
    rsel: RSel,
    cap: usize,
) -> bool {
    let base_count = ctx.base_vals.len();
    let m_slot = w.vals.len() - 1;
    let n_temps = w.temp_used.len();
    let mut unused: Vec<usize> = Vec::new();
    for t in 0..n_temps - 1 {
        if !w.temp_used[t] {
            unused.push(t + base_count);
        }
    }
    if unused.len() > 1 {
        return false;
    }
    let r_slots: Vec<usize> = if unused.len() == 1 {
        unused
    } else {
        (0..m_slot).filter(|&i| !w.is_const[i]).collect()
    };
    for &r_idx in &r_slots {
        if !rsel.allows(r_idx, base_count, ctx.input_count) {
            continue;
        }
        for &g in gset {
            let mv = &w.vals[m_slot];
            let rv = &w.vals[r_idx];
            let mut j = [0u32; PROBE_COUNT];
            for p in 0..PROBE_COUNT {
                j[p] = g.apply(mv[p], rv[p]);
            }
            if j.iter().all(|&x| x == j[0]) {
                continue; // constant output — cannot be a prefix of a bijection-rich target
            }
            if tab.entries.len() >= cap {
                return true;
            }
            let mut prog = w.prog.clone();
            prog.push(g.inst(m_slot, r_idx));
            let out_idx = base_count + prog.len() - 1;
            tab.add(j, prog, out_idx);
        }
    }
    false
}

/// Joined tables over kf in {1,2} DAG prefixes (all shapes; unreferenced-temp
/// entries included per add_joined's rule).
fn build_joined_base(ctx: &Ctx, kf: usize, gset: &[JoinG], rsel: RSel, cap: usize) -> Option<FwdTab> {
    let mut tab = FwdTab::new(kf + 1);
    let mut w = SearchState::new(ctx);
    let mut l1: Vec<(Inst, ProbeValues)> = Vec::new();
    enumerate_level(&w, |inst, v| l1.push((inst, v)));
    let mut overflow = false;
    for (i1, v1) in l1.iter() {
        if overflow {
            break;
        }
        let undo1 = w.push(i1.clone(), *v1);
        if kf == 1 {
            overflow = add_joined(&mut tab, ctx, &w, gset, rsel, cap);
        } else {
            let mut l2: Vec<(Inst, ProbeValues)> = Vec::new();
            enumerate_level(&w, |i2, v2| l2.push((i2, v2)));
            for (i2, v2) in l2 {
                let undo2 = w.push(i2, v2);
                overflow = add_joined(&mut tab, ctx, &w, gset, rsel, cap);
                w.pop(undo2);
                if overflow {
                    break;
                }
            }
        }
        w.pop(undo1);
    }
    if overflow {
        println!("   !! joined kf{kf} tab cap {cap} exceeded — shard or narrow --join-g/--join-r");
        return None;
    }
    Some(tab)
}

/// Joined tables over kf=3 FULL-shape DAG prefixes, sharded over (l1,l2)
/// pairs exactly like global_mitm's build_fwd_tab3 (union of shards = full
/// coverage). prefix_op_count = 4 (DAG 3 + join 1).
fn build_joined_tab3(
    ctx: &Ctx,
    shard_i: u64,
    shard_n: u64,
    gset: &[JoinG],
    rsel: RSel,
    cap: usize,
) -> Option<FwdTab> {
    let mut tab = FwdTab::new(4);
    let mut w = SearchState::new(ctx);
    let mut l1: Vec<(Inst, ProbeValues)> = Vec::new();
    enumerate_level(&w, |inst, v| l1.push((inst, v)));
    for (idx1, (i1, v1)) in l1.iter().enumerate() {
        let undo1 = w.push(i1.clone(), *v1);
        let mut l2: Vec<(Inst, ProbeValues)> = Vec::new();
        enumerate_level(&w, |i2, v2| l2.push((i2, v2)));
        for (idx2, (i2, v2)) in l2.into_iter().enumerate() {
            if ((idx1 as u64) * 1_000_003 + idx2 as u64) % shard_n != shard_i {
                continue;
            }
            let undo2 = w.push(i2, v2);
            let mut l3: Vec<(Inst, ProbeValues)> = Vec::new();
            enumerate_level(&w, |i3, v3| l3.push((i3, v3)));
            let mut overflow = false;
            for (i3, v3) in l3 {
                let undo3 = w.push(i3, v3);
                overflow = add_joined(&mut tab, ctx, &w, gset, rsel, cap);
                w.pop(undo3);
                if overflow {
                    break;
                }
            }
            w.pop(undo2);
            if overflow {
                println!("   !! joined kf3 tab cap {cap} exceeded — use more shards");
                return None;
            }
        }
        w.pop(undo1);
    }
    Some(tab)
}

// ---------------------------------------------------------------------------
// Engine C (verbatim from global_mitm.rs)
// ---------------------------------------------------------------------------

struct MitmStats {
    bwd_nodes: AtomicU64,
}

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
    pool: Vec<(&'static str, u32)>,
    seed: Vec<u32>,
    shifts: Vec<u32>,
    reference_fn: Box<TargetFn>,
}

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
    vec![
        GTarget {
            name: "full_hash_core",
            desc: "whole 11-op hash, core pool: myhash(x), hunting <=10 (k=9 in wanted)",
            input_count: 1,
            current_ops: 11,
            pool: core_pool(),
            seed: full_seed(),
            shifts: vec![12, 19, 5, 9, 3, 16, 13, 14],
            reference_fn: Box::new(|x| myhash(x[0])),
        },
        GTarget {
            name: "round12",
            desc: "TWO-INPUT 12-op round body: myhash(x ^ y), hunting <=11; r=y is the nv-fanout hole",
            input_count: 2,
            current_ops: 12,
            pool: core_pool(),
            seed: full_seed(),
            shifts: vec![12, 19, 5, 9, 3, 16, 13, 14],
            reference_fn: Box::new(|x| myhash(x[0] ^ x[1])),
        },
        GTarget {
            // SELFTEST: 6-op plant, join at op 4 (r = t1, g = XOR): invisible
            // to [<=3-DAG][meet][chain] (the P5-B family), visible to
            // joined-kf3. NOTE an add-join here would be ABSORBABLE into the
            // preceding madd's runtime addend slot (found by the no-join
            // control in an earlier selftest run) — xor is not (P3-F lemma).
            name: "sp1",
            desc: "SELFTEST joined-kf3 plant: madd,shr19,madd9 | XOR-join t1 | xorC1 meet | aff4097 chain",
            input_count: 1,
            current_ops: 7,
            pool: vec![
                ("KP", hs::F23_P_MULTIPLIER),
                ("AP", hs::F23_P_CONSTANT),
                ("K4", hs::STAGE4_MULTIPLIER),
                ("C4", hs::STAGE4_ADD_CONSTANT),
                ("s19", 19),
            ],
            seed: vec![hs::STAGE0_ADD_CONSTANT, hs::STAGE1_XOR_CONSTANT],
            shifts: vec![19, 16],
            reference_fn: Box::new(|x| {
                let t1 = multiply_add(x[0], hs::F23_P_MULTIPLIER, hs::F23_P_CONSTANT);
                let t2 = t1 >> 19;
                let t3 = multiply_add(t2, hs::STAGE4_MULTIPLIER, hs::STAGE4_ADD_CONSTANT);
                let t4 = t3 ^ t1;
                let t5 = t4 ^ hs::STAGE1_XOR_CONSTANT;
                multiply_add(t5, 4097, hs::STAGE0_ADD_CONSTANT)
            }),
        },
        GTarget {
            // SELFTEST: 4-op plant, join at op 3 with r = x (input fan-out).
            name: "sp2",
            desc: "SELFTEST joined-kf2 plant: madd16896,shr16 | xor-join x | aff33 chain",
            input_count: 1,
            current_ops: 5,
            pool: vec![
                ("KQ", hs::F23_Q_MULTIPLIER),
                ("AQ", hs::F23_Q_CONSTANT),
                ("s16", 16),
            ],
            seed: vec![0x1656_67B1],
            shifts: vec![16],
            reference_fn: Box::new(|x| {
                let t1 = multiply_add(x[0], hs::F23_Q_MULTIPLIER, hs::F23_Q_CONSTANT);
                let t2 = t1 >> 16;
                let t3 = t2 ^ x[0];
                multiply_add(t3, 33, 0x1656_67B1)
            }),
        },
        GTarget {
            // SELFTEST: 5-op plant where the DAG leaves t1 UNREFERENCED and
            // the join consumes it (parallel-branch r).
            name: "sp3",
            desc: "SELFTEST unused-r plant: madd33 (dangling), shr16(x), madd9 | xor-join t1 | aff4097 chain",
            input_count: 1,
            current_ops: 6,
            pool: vec![
                ("KP", hs::F23_P_MULTIPLIER),
                ("AP", hs::F23_P_CONSTANT),
                ("K4", hs::STAGE4_MULTIPLIER),
                ("C4", hs::STAGE4_ADD_CONSTANT),
                ("s16", 16),
            ],
            seed: vec![hs::STAGE0_ADD_CONSTANT],
            shifts: vec![16],
            reference_fn: Box::new(|x| {
                let t1 = multiply_add(x[0], hs::F23_P_MULTIPLIER, hs::F23_P_CONSTANT);
                let t2 = x[0] >> 16;
                let t3 = multiply_add(t2, hs::STAGE4_MULTIPLIER, hs::STAGE4_ADD_CONSTANT);
                let t4 = t3 ^ t1;
                multiply_add(t4, 4097, hs::STAGE0_ADD_CONSTANT)
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
        should_stop: AtomicBool::new(false),
        finds: Mutex::new(Vec::new()),
        reference_fn,
    }
}

struct RunCfg {
    kf: usize,          // 2 => joined kf1+kf2 tabs; 3 => joined kf3 tab
    join_g: String,
    join_r: RSel,
    no_join: bool,      // reproduce the P5-B family (base + kf3full + chain)
    with_base_tabs: bool,
    max_chain: usize,
    fwd_shard: (u64, u64),
    link_shard: (u64, u64),
    tab_cap: usize,
}

fn rsel_name(r: RSel) -> String {
    match r {
        RSel::All => "all".into(),
        RSel::OnlyX => "x".into(),
        RSel::OnlyY => "y".into(),
        RSel::OnlyT(t) => format!("t{t}"),
    }
}

fn run_target(tg: &GTarget, cfg: &RunCfg, threads: usize) -> usize {
    let kmax_use = tg.current_ops - 1;
    let wanted: u32 = (2u32 << kmax_use) - 2;
    println!(
        "== fanout_mitm target {} : {} (current {} ops, hunting k <= {}) ==",
        tg.name, tg.desc, tg.current_ops, kmax_use
    );
    let t_start = Instant::now();
    let ctx = build_ctx(tg.input_count, &tg.pool, &*tg.reference_fn);
    println!(
        "   pool ({}): [{}]",
        tg.pool.len(),
        ctx.base_names.iter().skip(tg.input_count).cloned().collect::<Vec<_>>().join(", ")
    );

    let link_consts = build_link_consts(&tg.seed, &tg.shifts);
    let links = build_links(&link_consts);
    println!(
        "   link pool: {} constants, {} links; link shard {}/{}",
        link_consts.len(),
        links.len(),
        cfg.link_shard.0,
        cfg.link_shard.1
    );

    let mut fwd_tabs: Vec<FwdTab> = Vec::new();
    let mode: String;
    if cfg.no_join {
        mode = "nojoin".into();
        for kf in 0..=2usize {
            let t0 = Instant::now();
            let tab = build_fwd_tab_base(&ctx, kf);
            println!("   fwd tab kf={kf}: {} entries ({:.1}s)", tab.entries.len(), t0.elapsed().as_secs_f64());
            fwd_tabs.push(tab);
        }
        let t0 = Instant::now();
        match build_fwd_tab3(&ctx, cfg.fwd_shard.0, cfg.fwd_shard.1, cfg.tab_cap) {
            Some(tab) => {
                println!(
                    "   fwd tab kf=3 (FULL) shard {}/{}: {} entries ({:.1}s)",
                    cfg.fwd_shard.0,
                    cfg.fwd_shard.1,
                    tab.entries.len(),
                    t0.elapsed().as_secs_f64()
                );
                fwd_tabs.push(tab);
            }
            None => {
                println!("CHECKPOINT bin=fanout target={} mode=nojoin ABORT=tab_cap", tg.name);
                return 1;
            }
        }
    } else {
        let gset = join_set(&cfg.join_g);
        mode = format!("kf{}join", cfg.kf);
        if cfg.with_base_tabs {
            for kf in 0..=2usize {
                let tab = build_fwd_tab_base(&ctx, kf);
                println!("   fwd tab kf={kf}: {} entries", tab.entries.len());
                fwd_tabs.push(tab);
            }
        }
        if cfg.kf == 2 {
            for kf in 1..=2usize {
                let t0 = Instant::now();
                match build_joined_base(&ctx, kf, &gset, cfg.join_r, cfg.tab_cap) {
                    Some(tab) => {
                        println!(
                            "   JOINED tab kf={kf}+g (prefix {} ops) g={} r={}: {} entries ({:.1}s)",
                            kf + 1,
                            cfg.join_g,
                            rsel_name(cfg.join_r),
                            tab.entries.len(),
                            t0.elapsed().as_secs_f64()
                        );
                        fwd_tabs.push(tab);
                    }
                    None => {
                        println!("CHECKPOINT bin=fanout target={} mode={} ABORT=tab_cap", tg.name, mode);
                        return 1;
                    }
                }
            }
        } else {
            let t0 = Instant::now();
            match build_joined_tab3(&ctx, cfg.fwd_shard.0, cfg.fwd_shard.1, &gset, cfg.join_r, cfg.tab_cap) {
                Some(tab) => {
                    println!(
                        "   JOINED tab kf=3+g (prefix 4 ops) g={} r={} shard {}/{}: {} entries ({:.1}s)",
                        cfg.join_g,
                        rsel_name(cfg.join_r),
                        cfg.fwd_shard.0,
                        cfg.fwd_shard.1,
                        tab.entries.len(),
                        t0.elapsed().as_secs_f64()
                    );
                    fwd_tabs.push(tab);
                }
                None => {
                    println!("CHECKPOINT bin=fanout target={} mode={} ABORT=tab_cap fwd_shard={}/{}", tg.name, mode, cfg.fwd_shard.0, cfg.fwd_shard.1);
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
    let tab_desc: Vec<String> = fwd_tabs.iter().map(|t| format!("p{}:{}", t.prefix_op_count, t.entries.len())).collect();
    println!(
        "CHECKPOINT bin=fanout target={} mode={} join_g={} join_r={} maxchain={} fwd_shard={}/{} link_shard={}/{} tabs=[{}] chain_nodes={} finds={} secs={:.1}",
        tg.name,
        mode,
        if cfg.no_join { "-".into() } else { cfg.join_g.clone() },
        if cfg.no_join { "-".into() } else { rsel_name(cfg.join_r) },
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

fn parse_rsel(s: &str) -> RSel {
    match s {
        "all" => RSel::All,
        "x" => RSel::OnlyX,
        "y" => RSel::OnlyY,
        "t1" => RSel::OnlyT(1),
        "t2" => RSel::OnlyT(2),
        other => panic!("unknown --join-r {other}"),
    }
}

fn selftest(threads: usize) {
    let all = gtargets();
    let sp1 = all.iter().find(|t| t.name == "sp1").unwrap();
    let sp2 = all.iter().find(|t| t.name == "sp2").unwrap();
    let sp3 = all.iter().find(|t| t.name == "sp3").unwrap();

    // 0. additive-shift non-bijectivity lemma (why no AddShr-style links).
    assert!(
        additive_shift_lemma_check(),
        "SELFTEST FAIL: additive-shift lemma violated — a v+/-(v>>s) family IS bijective"
    );
    println!("SELFTEST 0 PASS: v+(v>>s)/v-(v>>s)/(v>>s)-v are never bijective (w=12 exhaustive) — additive shift links soundly excluded");

    // 1. joined-kf3 finds the sp1 plant (join at op 4, g=add, r=t1).
    let cfg1 = RunCfg {
        kf: 3,
        join_g: "xor".into(),
        join_r: RSel::All,
        no_join: false,
        with_base_tabs: false,
        max_chain: 3,
        fwd_shard: (0, 1),
        link_shard: (0, 1),
        tab_cap: 50_000_000,
    };
    assert!(run_target(sp1, &cfg1, threads) > 0, "SELFTEST FAIL: joined-kf3 missed sp1");
    println!("SELFTEST 1 PASS: joined-kf3 finds the join-at-4 plant");

    // 2. NEGATIVE control: the P5-B family (base + kf3full + chain) must NOT
    //    see sp1 — proves the join is a real coverage extension.
    let cfg2 = RunCfg {
        kf: 3,
        join_g: "basic".into(),
        join_r: RSel::All,
        no_join: true,
        with_base_tabs: false,
        max_chain: 3,
        fwd_shard: (0, 1),
        link_shard: (0, 1),
        tab_cap: 50_000_000,
    };
    assert!(
        run_target(sp1, &cfg2, threads) == 0,
        "SELFTEST unexpected: no-join family found sp1 (inspect — may be a real alternate spelling)"
    );
    println!("SELFTEST 2 PASS: the chain-only family (P5-B shapes) does NOT see the plant");

    // 3. joined-kf2 finds sp2 (r = x input fan-out).
    let cfg3 = RunCfg {
        kf: 2,
        join_g: "xor".into(),
        join_r: RSel::All,
        no_join: false,
        with_base_tabs: false,
        max_chain: 2,
        fwd_shard: (0, 1),
        link_shard: (0, 1),
        tab_cap: 50_000_000,
    };
    assert!(run_target(sp2, &cfg3, threads) > 0, "SELFTEST FAIL: joined-kf2 missed sp2 (r=x)");
    println!("SELFTEST 3 PASS: joined-kf2 finds the r=x plant");

    // 4. joined-kf3 finds sp3 (DAG leaves t1 dangling; join must adopt it).
    let cfg4 = RunCfg {
        kf: 3,
        join_g: "xor".into(),
        join_r: RSel::All,
        no_join: false,
        with_base_tabs: false,
        max_chain: 2,
        fwd_shard: (0, 1),
        link_shard: (0, 1),
        tab_cap: 50_000_000,
    };
    assert!(run_target(sp3, &cfg4, threads) > 0, "SELFTEST FAIL: joined-kf3 missed the unused-r plant");
    println!("SELFTEST 4 PASS: unused-temp-as-r path works");

    // 5. shard union: sp1 across 4 fwd shards — at least one finds it.
    let mut shard_finds = 0;
    for i in 0..4u64 {
        let cfgs = RunCfg {
            kf: 3,
            join_g: "xor".into(),
            join_r: RSel::All,
            no_join: false,
            with_base_tabs: false,
            max_chain: 3,
            fwd_shard: (i, 4),
            link_shard: (0, 1),
            tab_cap: 50_000_000,
        };
        shard_finds += run_target(sp1, &cfgs, threads);
    }
    assert!(shard_finds > 0, "SELFTEST FAIL: no fwd shard of 4 found sp1");
    println!("SELFTEST 5 PASS: shard union preserves coverage ({shard_finds} find(s))");
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
    let cfg = RunCfg {
        kf: get("--kf").map_or(3, |v| v.parse().unwrap()),
        join_g: get("--join-g").unwrap_or_else(|| "basic".into()),
        join_r: get("--join-r").map_or(RSel::All, |v| parse_rsel(&v)),
        no_join: args.iter().any(|a| a == "--no-join"),
        with_base_tabs: args.iter().any(|a| a == "--with-base-tabs"),
        max_chain: get("--max-chain").map_or(6, |v| v.parse().unwrap()),
        fwd_shard: get("--fwd-shard").map_or((0, 1), |v| parse_shard(&v)),
        link_shard: get("--link-shard").map_or((0, 1), |v| parse_shard(&v)),
        tab_cap: get("--tab-cap").map_or(30_000_000, |v| v.parse().unwrap()),
    };
    assert!(cfg.max_chain <= 6, "max chain is capped at 6");
    assert!(cfg.kf == 2 || cfg.kf == 3, "--kf must be 2 or 3");
    let flags = [
        "--kf",
        "--join-g",
        "--join-r",
        "--max-chain",
        "--fwd-shard",
        "--link-shard",
        "--tab-cap",
    ];
    let names: Vec<&String> = args
        .iter()
        .enumerate()
        .filter(|(i, a)| !a.starts_with("--") && !(*i > 0 && flags.contains(&args[i - 1].as_str())))
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
