//! P5-H: STOKE-style stochastic superoptimizer for the hash.
//!
//! Searches straight-line programs over the machine's alu/valu vocabulary
//! (8 useful binops + Lt/Eq + multiply_add) with a per-program pool of
//! MUTABLE 32-bit constants — the arbitrary-constant coverage every MITM
//! run to date lacks (all prior coverage used a 12-const structured pool).
//!
//! Campaigns:
//!   cal : planted-compression calibration. Target = 10-op function
//!         sigma16(stage4(f23(stage1(stage0(x))))); seed = 12-op program
//!         with stage0's madd re-expanded to shl+add+add. The search must
//!         re-fuse it (find a correct program with <=10 non-nop ops).
//!   t1  : myhash(x), 1 input.  Interesting at <=10 (structural), <=9 (wins).
//!   t2  : myhash(x^y), 2 inputs (round body). Interesting at <=10, win <=10
//!         per brief (round12 12 ops today; <=10 is the k<=9.5 regime).
//!   t3  : myhash(myhash(x^y1)^y2), 3 inputs, 24 ops today, target <=19.
//!
//! MCMC: Metropolis with temperature --temp over cost = hamming-error(bits,
//! over the chain's battery) + opw * (non-nop op count). Moves: opcode flip,
//! operand flip, constant perturbation (bitflip/random/arith neighborhood),
//! instruction swap, instruction replace, dst flip, nop toggle. Restarts
//! alternate random programs and mutated/truncated copies of the real form
//! (STOKE's transformation-search mode).
//!
//! Any err==0-on-battery candidate goes through the cascade: 256 -> 65,536
//! -> 10^7 random + edge battery. Only full-cascade passes are FINDs.
//! Failures inject counterexamples into the chain's local battery.
//!
//! Checkpoints JSON to tools/p5h_ckpt_<campaign>_s<slots>.json each slice.
//! NEVER backgrounded; run in foreground slices <=8 min (--seconds).

use perf_harness::problem::{hashseg, myhash};
use std::io::Write as IoWrite;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

const NCONSTS: usize = 12;
const NREGS: usize = 10; // r0..r9; inputs occupy the first ninputs

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Opc {
    Add,
    Sub,
    Mul,
    Xor,
    And,
    Or,
    Shl,
    Shr,
    Lt,
    Eq,
    Madd,
    Nop,
}

impl Opc {
    fn name(self) -> &'static str {
        match self {
            Opc::Add => "add",
            Opc::Sub => "sub",
            Opc::Mul => "mul",
            Opc::Xor => "xor",
            Opc::And => "and",
            Opc::Or => "or",
            Opc::Shl => "shl",
            Opc::Shr => "shr",
            Opc::Lt => "lt",
            Opc::Eq => "eq",
            Opc::Madd => "madd",
            Opc::Nop => "nop",
        }
    }
}

// Weighted opcode table for random proposals (madd/xor/add/shr-heavy: the
// hash family lives there; Lt/Eq/And/Or kept reachable but rare).
const OPC_TABLE: [Opc; 22] = [
    Opc::Add,
    Opc::Add,
    Opc::Add,
    Opc::Sub,
    Opc::Mul,
    Opc::Mul,
    Opc::Xor,
    Opc::Xor,
    Opc::Xor,
    Opc::And,
    Opc::Or,
    Opc::Shl,
    Opc::Shl,
    Opc::Shr,
    Opc::Shr,
    Opc::Shr,
    Opc::Lt,
    Opc::Eq,
    Opc::Madd,
    Opc::Madd,
    Opc::Madd,
    Opc::Madd,
];

/// Operand: register (< 64) or constant-pool slot (>= 64, idx-64).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
struct Operand(u8);
impl Operand {
    fn reg(i: usize) -> Self {
        Operand(i as u8)
    }
    fn konst(i: usize) -> Self {
        Operand(64 + i as u8)
    }
    fn is_const(self) -> bool {
        self.0 >= 64
    }
    fn idx(self) -> usize {
        (self.0 & 63) as usize
    }
    fn show(self) -> String {
        if self.is_const() {
            format!("c{}", self.idx())
        } else {
            format!("r{}", self.idx())
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct Op {
    opc: Opc,
    dst: u8,
    a: Operand,
    b: Operand,
    c: Operand, // madd only: a*b+c
}

#[derive(Clone)]
struct Prog {
    ops: Vec<Op>,
    consts: [u32; NCONSTS],
    ninputs: usize,
}

impl Prog {
    fn nonnop(&self) -> usize {
        self.ops.iter().filter(|o| o.opc != Opc::Nop).count()
    }
    fn show(&self) -> String {
        let mut s = String::new();
        for (i, o) in self.ops.iter().enumerate() {
            if o.opc == Opc::Nop {
                s.push_str(&format!("  {:2}: nop\n", i));
            } else if o.opc == Opc::Madd {
                s.push_str(&format!(
                    "  {:2}: r{} = madd({}, {}, {})\n",
                    i,
                    o.dst,
                    o.a.show(),
                    o.b.show(),
                    o.c.show()
                ));
            } else {
                s.push_str(&format!(
                    "  {:2}: r{} = {}({}, {})\n",
                    i,
                    o.dst,
                    o.opc.name(),
                    o.a.show(),
                    o.b.show()
                ));
            }
        }
        s.push_str("  consts:");
        for (i, c) in self.consts.iter().enumerate() {
            s.push_str(&format!(" c{}=0x{:08X}", i, c));
        }
        s.push('\n');
        s
    }
    fn serialize(&self) -> String {
        // compact canonical text (also the dedupe key)
        let mut s = String::new();
        for o in &self.ops {
            if o.opc == Opc::Nop {
                continue;
            }
            s.push_str(&format!(
                "{} d{} {} {} {};",
                o.opc.name(),
                o.dst,
                o.a.0,
                o.b.0,
                if o.opc == Opc::Madd { o.c.0 } else { 255 }
            ));
        }
        s.push('|');
        // only constants actually referenced matter for the key
        let mut used = [false; NCONSTS];
        for o in &self.ops {
            if o.opc == Opc::Nop {
                continue;
            }
            for oper in [o.a, o.b] {
                if oper.is_const() {
                    used[oper.idx()] = true;
                }
            }
            if o.opc == Opc::Madd && o.c.is_const() {
                used[o.c.idx()] = true;
            }
        }
        for i in 0..NCONSTS {
            if used[i] {
                s.push_str(&format!("c{}={:08X};", i, self.consts[i]));
            }
        }
        s
    }
}

#[inline(always)]
fn alu(opc: Opc, a: u32, b: u32) -> u32 {
    match opc {
        Opc::Add => a.wrapping_add(b),
        Opc::Sub => a.wrapping_sub(b),
        Opc::Mul => a.wrapping_mul(b),
        Opc::Xor => a ^ b,
        Opc::And => a & b,
        Opc::Or => a | b,
        Opc::Shl => {
            if b >= 32 {
                0
            } else {
                a << b
            }
        }
        Opc::Shr => {
            if b >= 32 {
                0
            } else {
                a >> b
            }
        }
        Opc::Lt => (a < b) as u32,
        Opc::Eq => (a == b) as u32,
        Opc::Madd | Opc::Nop => unreachable!(),
    }
}

/// Evaluate: inputs preloaded into r0..; output = result of last non-nop op.
#[inline(always)]
fn eval(p: &Prog, inputs: &[u32]) -> u32 {
    let mut regs = [0u32; NREGS];
    regs[..inputs.len()].copy_from_slice(inputs);
    let mut out = 0u32;
    for o in &p.ops {
        if o.opc == Opc::Nop {
            continue;
        }
        let av = if o.a.is_const() {
            p.consts[o.a.idx()]
        } else {
            regs[o.a.idx()]
        };
        let bv = if o.b.is_const() {
            p.consts[o.b.idx()]
        } else {
            regs[o.b.idx()]
        };
        let v = if o.opc == Opc::Madd {
            let cv = if o.c.is_const() {
                p.consts[o.c.idx()]
            } else {
                regs[o.c.idx()]
            };
            av.wrapping_mul(bv).wrapping_add(cv)
        } else {
            alu(o.opc, av, bv)
        };
        regs[o.dst as usize] = v;
        out = v;
    }
    out
}

// ---------------- targets ----------------

#[derive(Clone, Copy, PartialEq)]
enum Campaign {
    Cal,
    T1,
    T2,
    T3,
    S9,    // sandwich9 shape-restricted: does madd/sigma/madd/sigma/madd == myhash?
    S9Cal, // planted sandwich9 recovery (calibration for the s9 machinery)
}

impl Campaign {
    fn name(self) -> &'static str {
        match self {
            Campaign::Cal => "cal",
            Campaign::T1 => "t1",
            Campaign::T2 => "t2",
            Campaign::T3 => "t3",
            Campaign::S9 => "s9",
            Campaign::S9Cal => "s9cal",
        }
    }
    fn ninputs(self) -> usize {
        match self {
            Campaign::Cal | Campaign::T1 | Campaign::S9 | Campaign::S9Cal => 1,
            Campaign::T2 => 2,
            Campaign::T3 => 3,
        }
    }
    fn target(self, x: &[u32]) -> u32 {
        match self {
            // 10-op calibration function: full fused hash minus stage5's
            // constant xor (sigma16 instead of stage5).
            Campaign::Cal => hashseg::sigma16(hashseg::stage4(hashseg::f23(
                hashseg::stage1(hashseg::stage0(x[0])),
            ))),
            Campaign::T1 | Campaign::S9 => myhash(x[0]),
            Campaign::T2 => myhash(x[0] ^ x[1]),
            Campaign::T3 => myhash(myhash(x[0] ^ x[1]) ^ x[2]),
            Campaign::S9Cal => s9_eval(&S9_PLANTED, x[0]),
        }
    }
}

// ---------------- RNG ----------------

struct Rng(u64);
impl Rng {
    fn new(seed: u64) -> Self {
        Rng(seed.wrapping_mul(0x9E3779B97F4A7C15) | 1)
    }
    #[inline(always)]
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    #[inline(always)]
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
    #[inline(always)]
    fn u32(&mut self) -> u32 {
        (self.next() >> 32) as u32
    }
    #[inline(always)]
    fn f64(&mut self) -> f64 {
        (self.next() >> 11) as f64 / (1u64 << 53) as f64
    }
}

// ---------------- seeds (the REAL forms) ----------------

const REAL_CONSTS: [u32; NCONSTS] = [
    4097,        // c0  stage0 multiplier
    0x7ED5_5D16, // c1  stage0 add
    19,          // c2  stage1 shift
    0xC761_C23C, // c3  stage1 xor
    33,          // c4  f23 p mult
    0xE9F8_CC1D, // c5  f23 p const
    16896,       // c6  f23 q mult
    0xACCF_6200, // c7  f23 q const
    9,           // c8  stage4 mult
    0xFD70_46C5, // c9  stage4 add
    16,          // c10 stage5 shift
    0xB55A_4F09, // c11 stage5 xor
];

/// The fused 11-op myhash over register base `rb` (input in reg `src`),
/// writing temps into rb, rb+1, rb+2. Returns op list.
fn real_hash_ops(src: usize, rb: usize) -> Vec<Op> {
    let r = |i: usize| Operand::reg(i);
    let c = |i: usize| Operand::konst(i);
    let (t0, t1, t2) = (rb as u8, (rb + 1) as u8, (rb + 2) as u8);
    vec![
        Op { opc: Opc::Madd, dst: t0, a: r(src), b: c(0), c: c(1) }, // b
        Op { opc: Opc::Shr, dst: t1, a: r(t0 as usize), b: c(2), c: c(0) },
        Op { opc: Opc::Xor, dst: t2, a: r(t0 as usize), b: c(3), c: c(0) },
        Op { opc: Opc::Xor, dst: t0, a: r(t2 as usize), b: r(t1 as usize), c: c(0) }, // cc
        Op { opc: Opc::Madd, dst: t1, a: r(t0 as usize), b: c(4), c: c(5) }, // p
        Op { opc: Opc::Madd, dst: t2, a: r(t0 as usize), b: c(6), c: c(7) }, // q
        Op { opc: Opc::Xor, dst: t0, a: r(t1 as usize), b: r(t2 as usize), c: c(0) }, // d
        Op { opc: Opc::Madd, dst: t1, a: r(t0 as usize), b: c(8), c: c(9) }, // e
        Op { opc: Opc::Shr, dst: t2, a: r(t1 as usize), b: c(10), c: c(0) },
        Op { opc: Opc::Xor, dst: t0, a: r(t1 as usize), b: c(11), c: c(0) },
        Op { opc: Opc::Xor, dst: t0, a: r(t0 as usize), b: r(t2 as usize), c: c(0) },
    ]
}

fn seed_prog(camp: Campaign) -> Prog {
    let ni = camp.ninputs();
    match camp {
        // s9 campaigns have no known-correct seed; s9_chain never calls this.
        Campaign::S9 | Campaign::S9Cal => s9_prog(&S9_PLANTED),
        Campaign::T1 => Prog { ops: real_hash_ops(0, 1), consts: REAL_CONSTS, ninputs: ni },
        Campaign::T2 => {
            let mut ops = vec![Op {
                opc: Opc::Xor,
                dst: 2,
                a: Operand::reg(0),
                b: Operand::reg(1),
                c: Operand::konst(0),
            }];
            ops.extend(real_hash_ops(2, 3));
            Prog { ops, consts: REAL_CONSTS, ninputs: ni }
        }
        Campaign::T3 => {
            let mut ops = vec![Op {
                opc: Opc::Xor,
                dst: 3,
                a: Operand::reg(0),
                b: Operand::reg(1),
                c: Operand::konst(0),
            }];
            ops.extend(real_hash_ops(3, 4));
            // fold in y2 (r2): hash output currently in r4? real_hash_ops(3,4)
            // leaves result in r4 (t0 = rb). fold: r3 = r4 ^ r2, hash again.
            ops.push(Op {
                opc: Opc::Xor,
                dst: 3,
                a: Operand::reg(4),
                b: Operand::reg(2),
                c: Operand::konst(0),
            });
            ops.extend(real_hash_ops(3, 4));
            Prog { ops, consts: REAL_CONSTS, ninputs: ni }
        }
        Campaign::Cal => {
            // 12-op planted: stage0 madd expanded to shl+add+add, and stage5
            // reduced to sigma16 (shr+xor, no const xor) => 10-op true form.
            let r = |i: usize| Operand::reg(i);
            let c = |i: usize| Operand::konst(i);
            let mut consts = REAL_CONSTS;
            consts[0] = 12; // stage0 shift amount replaces the 4097 multiplier
            // Spare slot keeps 4097 available: real campaigns' seed pools
            // contain all their madd multipliers, so calibration must not be
            // strictly harder in the constant dimension than the real task.
            // (Const-discovery is exercised by the mutation moves regardless.)
            consts[11] = 4097;
            let ops = vec![
                Op { opc: Opc::Shl, dst: 1, a: r(0), b: c(0), c: c(0) }, // x<<12
                Op { opc: Opc::Add, dst: 2, a: r(0), b: r(1), c: c(0) }, // x+ (x<<12)
                Op { opc: Opc::Add, dst: 1, a: r(2), b: c(1), c: c(0) }, // +C0  = b
                Op { opc: Opc::Shr, dst: 2, a: r(1), b: c(2), c: c(0) },
                Op { opc: Opc::Xor, dst: 3, a: r(1), b: c(3), c: c(0) },
                Op { opc: Opc::Xor, dst: 1, a: r(3), b: r(2), c: c(0) }, // cc
                Op { opc: Opc::Madd, dst: 2, a: r(1), b: c(4), c: c(5) },
                Op { opc: Opc::Madd, dst: 3, a: r(1), b: c(6), c: c(7) },
                Op { opc: Opc::Xor, dst: 1, a: r(2), b: r(3), c: c(0) }, // d
                Op { opc: Opc::Madd, dst: 2, a: r(1), b: c(8), c: c(9) }, // e
                Op { opc: Opc::Shr, dst: 3, a: r(2), b: c(10), c: c(0) },
                Op { opc: Opc::Xor, dst: 1, a: r(2), b: r(3), c: c(0) }, // sigma16
            ];
            Prog { ops, consts, ninputs: ni }
        }
    }
}

// ---------------- test batteries ----------------

fn edge_values() -> Vec<u32> {
    let mut v = vec![0u32, 1, 2, 3, 0x7FFF_FFFF, 0x8000_0000, 0xFFFF_FFFF, 0xFFFF_FFFE];
    for k in 0..32 {
        v.push(1u32 << k);
        v.push((1u32 << k).wrapping_sub(1));
        v.push(!(1u32 << k));
    }
    v.extend_from_slice(&REAL_CONSTS);
    v
}

fn make_battery(camp: Campaign, n: usize, seed: u64, edges: bool) -> Vec<(Vec<u32>, u32)> {
    let ni = camp.ninputs();
    let mut rng = Rng::new(seed);
    let mut out = Vec::with_capacity(n + 64);
    if edges {
        let ev = edge_values();
        if ni == 1 {
            for &x in &ev {
                out.push((vec![x], camp.target(&[x])));
            }
        } else {
            // pair every edge value with a few random partners + all-edge diag
            for &x in &ev {
                let mut inp = vec![x];
                for _ in 1..ni {
                    inp.push(ev[rng.below(ev.len())]);
                }
                let t = camp.target(&inp);
                out.push((inp, t));
                let mut inp2 = vec![x];
                for _ in 1..ni {
                    inp2.push(rng.u32());
                }
                let t2 = camp.target(&inp2);
                out.push((inp2, t2));
            }
        }
    }
    while out.len() < n {
        let inp: Vec<u32> = (0..ni).map(|_| rng.u32()).collect();
        let t = camp.target(&inp);
        out.push((inp, t));
    }
    out
}

/// err in hamming bits over battery, early-abort when > cutoff (return u32::MAX).
#[inline(always)]
fn err_bits(p: &Prog, battery: &[(Vec<u32>, u32)], cutoff: u32) -> u32 {
    let mut e = 0u32;
    for (inp, want) in battery {
        e += (eval(p, inp) ^ want).count_ones();
        if e > cutoff {
            return u32::MAX;
        }
    }
    e
}

/// Full cascade. Returns Ok(total_vectors_checked) or Err(counterexample).
fn validate(p: &Prog, camp: Campaign) -> Result<u64, Vec<u32>> {
    let ni = camp.ninputs();
    // level 1: 256
    for (inp, want) in make_battery(camp, 256, 0xB17E5, false) {
        if eval(p, &inp) != want {
            return Err(inp);
        }
    }
    // level 2: 65,536
    for (inp, want) in make_battery(camp, 65_536, 0xC0FFEE, false) {
        if eval(p, &inp) != want {
            return Err(inp);
        }
    }
    // level 3: edges (incl shift boundaries) + 10^7 random
    for (inp, want) in make_battery(camp, 0, 0xED6E5, true) {
        if eval(p, &inp) != want {
            return Err(inp);
        }
    }
    let mut rng = Rng::new(0xDEAD_10CC);
    let mut checked = 256 + 65_536 + 200u64;
    for _ in 0..10_000_000u64 {
        let inp: Vec<u32> = (0..ni).map(|_| rng.u32()).collect();
        let want = camp.target(&inp);
        if eval(p, &inp) != want {
            return Err(inp);
        }
        checked += 1;
    }
    Ok(checked)
}

// ---------------- moves ----------------

const INTERESTING: [u32; 24] = [
    0, 1, 2, 3, 5, 9, 12, 16, 19, 31, 32, 33, 4097, 16896, 0x8000_0000, 0x8000_8000,
    0x8004_8000, 0x7ED5_5D16, 0xC761_C23C, 0xE9F8_CC1D, 0xACCF_6200, 0xFD70_46C5,
    0xB55A_4F09, 0x0001_0001,
];

fn rand_operand(rng: &mut Rng, nregs: usize) -> Operand {
    if rng.below(2) == 0 {
        Operand::reg(rng.below(nregs))
    } else {
        Operand::konst(rng.below(NCONSTS))
    }
}

fn rand_op(rng: &mut Rng, ninputs: usize, nregs: usize) -> Op {
    let opc = OPC_TABLE[rng.below(OPC_TABLE.len())];
    Op {
        opc,
        dst: (ninputs + rng.below(nregs - ninputs)) as u8,
        a: rand_operand(rng, nregs),
        b: rand_operand(rng, nregs),
        c: rand_operand(rng, nregs),
    }
}

fn random_prog(rng: &mut Rng, camp: Campaign, slots: usize) -> Prog {
    let ni = camp.ninputs();
    let mut consts = [0u32; NCONSTS];
    for c in consts.iter_mut() {
        *c = match rng.below(4) {
            0 => REAL_CONSTS[rng.below(NCONSTS)],
            1 => INTERESTING[rng.below(INTERESTING.len())],
            2 => rng.u32(),
            _ => rng.below(33) as u32,
        };
    }
    let ops = (0..slots).map(|_| rand_op(rng, ni, NREGS)).collect();
    Prog { ops, consts, ninputs: ni }
}

/// Seed-derived start: copy the real form, truncate/pad to `slots`, mutate.
fn mutated_seed(rng: &mut Rng, camp: Campaign, slots: usize, kicks: usize) -> Prog {
    let mut p = seed_prog(camp);
    while p.ops.len() > slots {
        let i = rng.below(p.ops.len());
        p.ops.remove(i);
    }
    while p.ops.len() < slots {
        p.ops.push(Op {
            opc: Opc::Nop,
            dst: p.ninputs as u8,
            a: Operand::reg(0),
            b: Operand::reg(0),
            c: Operand::reg(0),
        });
    }
    for _ in 0..kicks {
        apply_move(&mut p, rng);
    }
    p
}

enum Undo {
    Op(usize, Op),
    TwoOps(usize, Op, usize, Op),
    Const(usize, u32),
    Window(usize, [Op; 3], usize),
}

// madd/xor-heavy table for window-replacement proposals.
const WINDOW_TABLE: [Opc; 16] = [
    Opc::Madd,
    Opc::Madd,
    Opc::Madd,
    Opc::Madd,
    Opc::Madd,
    Opc::Madd,
    Opc::Xor,
    Opc::Xor,
    Opc::Xor,
    Opc::Add,
    Opc::Add,
    Opc::Shr,
    Opc::Shr,
    Opc::Mul,
    Opc::Shl,
    Opc::Sub,
];

fn rand_op_window(rng: &mut Rng, ninputs: usize, nregs: usize) -> Op {
    let opc = WINDOW_TABLE[rng.below(WINDOW_TABLE.len())];
    Op {
        opc,
        dst: (ninputs + rng.below(nregs - ninputs)) as u8,
        a: rand_operand(rng, nregs),
        b: rand_operand(rng, nregs),
        c: rand_operand(rng, nregs),
    }
}

fn apply_move(p: &mut Prog, rng: &mut Rng) -> Undo {
    let slots = p.ops.len();
    let ni = p.ninputs;
    match rng.below(19) {
        // window replace (3/19): rewrite a 2-3 op window with FEWER random
        // ops (+nops), pinning the last replacement's dst to the window's
        // original output register — the coordinated multi-op proposal that
        // crosses fusion plateaus (e.g. shl+add+add -> one madd).
        16 | 17 | 18 => {
            let len = 2 + rng.below(2); // 2 or 3
            let len = len.min(slots);
            let start = rng.below(slots - len + 1);
            let mut saved = [p.ops[start]; 3];
            for k in 0..len {
                saved[k] = p.ops[start + k];
            }
            // original window output register = dst of last non-nop in window
            let mut out_dst = None;
            for k in (0..len).rev() {
                if p.ops[start + k].opc != Opc::Nop {
                    out_dst = Some(p.ops[start + k].dst);
                    break;
                }
            }
            let nnew = 1 + rng.below(len - 1); // 1..len-1 new ops
            for k in 0..len {
                if k < nnew {
                    p.ops[start + k] = rand_op_window(rng, ni, NREGS);
                } else {
                    p.ops[start + k].opc = Opc::Nop;
                }
            }
            if let Some(d) = out_dst {
                p.ops[start + nnew - 1].dst = d;
            }
            Undo::Window(start, saved, len)
        }
        _ => apply_small_move(p, rng),
    }
}

fn apply_small_move(p: &mut Prog, rng: &mut Rng) -> Undo {
    let slots = p.ops.len();
    let ni = p.ninputs;
    match rng.below(16) {
        // opcode flip (3/16)
        0 | 1 | 2 => {
            let i = rng.below(slots);
            let old = p.ops[i];
            p.ops[i].opc = OPC_TABLE[rng.below(OPC_TABLE.len())];
            Undo::Op(i, old)
        }
        // operand flip (4/16)
        3 | 4 | 5 | 6 => {
            let i = rng.below(slots);
            let old = p.ops[i];
            let o = rand_operand(rng, NREGS);
            match rng.below(3) {
                0 => p.ops[i].a = o,
                1 => p.ops[i].b = o,
                _ => p.ops[i].c = o,
            }
            Undo::Op(i, old)
        }
        // constant perturbation (4/16)
        7 | 8 | 9 | 10 => {
            let ci = rng.below(NCONSTS);
            let old = p.consts[ci];
            let v = old;
            p.consts[ci] = match rng.below(8) {
                0 => v ^ (1 << rng.below(32)),             // bit flip
                1 => rng.u32(),                            // fresh random
                2 => v.wrapping_add(1),
                3 => v.wrapping_sub(1),
                4 => v.wrapping_shl(1),
                5 => v.wrapping_shr(1),
                6 => INTERESTING[rng.below(INTERESTING.len())],
                _ => v.wrapping_add(1) ^ (1 << rng.below(32)), // combo kick
            };
            Undo::Const(ci, old)
        }
        // instruction swap (2/16)
        11 | 12 => {
            let i = rng.below(slots);
            let j = rng.below(slots);
            let (oi, oj) = (p.ops[i], p.ops[j]);
            p.ops.swap(i, j);
            Undo::TwoOps(i, oi, j, oj)
        }
        // dst flip (1/16)
        13 => {
            let i = rng.below(slots);
            let old = p.ops[i];
            p.ops[i].dst = (ni + rng.below(NREGS - ni)) as u8;
            Undo::Op(i, old)
        }
        // nop toggle (1/16)
        14 => {
            let i = rng.below(slots);
            let old = p.ops[i];
            if old.opc == Opc::Nop {
                p.ops[i] = rand_op(rng, ni, NREGS);
            } else {
                p.ops[i].opc = Opc::Nop;
            }
            Undo::Op(i, old)
        }
        // full instruction replace (1/16)
        _ => {
            let i = rng.below(slots);
            let old = p.ops[i];
            p.ops[i] = rand_op(rng, ni, NREGS);
            Undo::Op(i, old)
        }
    }
}

fn undo_move(p: &mut Prog, u: Undo) {
    match u {
        Undo::Op(i, o) => p.ops[i] = o,
        Undo::TwoOps(i, oi, j, oj) => {
            p.ops[i] = oi;
            p.ops[j] = oj;
        }
        Undo::Const(i, v) => p.consts[i] = v,
        Undo::Window(start, saved, len) => {
            p.ops[start..start + len].copy_from_slice(&saved[..len]);
        }
    }
}

// ---------------- sandwich9: shape-restricted campaign ----------------
//
// Skeleton (9 ops, the single most plausible 9-op shape, undecided by z3):
//   b   = x*K1 + C1                      (madd)
//   c   = b ^ M1 ^ (b >> S1)            (sigma1: shr, xor-const, xor)
//   e   = c*K2 + C2                      (madd)
//   w   = e ^ M2 ^ (e >> S2)            (sigma2)
//   out = w*K3 + C3                      (madd)
//
// Lemma (prunes 7/8 of K-space): myhash is a bijection (all its stage
// multipliers 2^s+1 are odd; xor-shift stages are bijective), so any
// correct sandwich9 is a bijection, so K1,K2,K3 are all ODD (an even
// multiplier makes its madd non-injective, hence the composition too).
//
// Cost: since K3 is odd and sigma2 is bijective, the back half inverts
// analytically: w = (T - C3)*K3^{-1}, e_want = xorshift_inv(w ^ M2, S2).
// cost = sum hamming( e_fwd(x), e_want(myhash(x)) ) — a MITM-style
// midpoint objective that halves the avalanche depth on each side.

#[derive(Clone, Copy, Debug)]
struct S9 {
    k: [u32; 3], // madd multipliers (kept odd)
    c: [u32; 3], // madd addends
    m: [u32; 2], // sigma xor masks
    s: [u32; 2], // sigma shifts, 1..=31
}

/// Planted parameters for the s9cal recovery gate (arbitrary, mixing well).
const S9_PLANTED: S9 = S9 {
    k: [0xA5A5_A5A5, 0x30D0_4A85, 0x0001_9661],
    c: [0x1234_5678, 0x9E37_79B9, 0x7F4A_7C15],
    m: [0xDEAD_BEEF, 0xCAFE_BABE],
    s: [13, 7],
};

#[inline(always)]
fn s9_fwd_mid(p: &S9, x: u32) -> u32 {
    let b = x.wrapping_mul(p.k[0]).wrapping_add(p.c[0]);
    let c = b ^ p.m[0] ^ (b >> p.s[0]);
    c.wrapping_mul(p.k[1]).wrapping_add(p.c[1])
}

fn s9_eval(p: &S9, x: u32) -> u32 {
    let e = s9_fwd_mid(p, x);
    let w = e ^ p.m[1] ^ (e >> p.s[1]);
    w.wrapping_mul(p.k[2]).wrapping_add(p.c[2])
}

/// Inverse of odd k mod 2^32 (Newton–Hensel; x0=k is correct mod 8).
fn mul_inv_odd(k: u32) -> u32 {
    let mut x = k;
    for _ in 0..4 {
        x = x.wrapping_mul(2u32.wrapping_sub(k.wrapping_mul(x)));
    }
    x
}

/// Solve e ^ (e >> s) = y  (s in 1..=31).
#[inline(always)]
fn xorshift_inv(y: u32, s: u32) -> u32 {
    let mut e = y;
    let mut n = s;
    while n < 32 {
        e = y ^ (e >> s);
        n += s;
    }
    e
}

#[inline(always)]
fn s9_bwd_mid(p: &S9, t: u32, k3inv: u32) -> u32 {
    let w = t.wrapping_sub(p.c[2]).wrapping_mul(k3inv);
    xorshift_inv(w ^ p.m[1], p.s[1])
}

fn s9_err(p: &S9, battery: &[(u32, u32)], cutoff: u32) -> u32 {
    let k3inv = mul_inv_odd(p.k[2]);
    let mut e = 0u32;
    for &(x, t) in battery {
        e += (s9_fwd_mid(p, x) ^ s9_bwd_mid(p, t, k3inv)).count_ones();
        if e > cutoff {
            return u32::MAX;
        }
    }
    e
}

// Odd multipliers worth proposing (real ones, 2^j+-1 family, classic mixers).
const S9_KTABLE: [u32; 20] = [
    3, 5, 9, 17, 33, 257, 4097, 65537, 36873, 135201, 297, 0x9E37_79B9,
    0x85EB_CA6B, 0xC2B2_AE35, 0x2545_F491, 0xFF51_AFD7, 0xC4CE_B9FE, 0x0001_0001,
    0x0100_0001, 0x1000_1001,
];
const S9_CTABLE: [u32; 14] = [
    0,
    1,
    0x7ED5_5D16,
    0xC761_C23C,
    0x1656_67B1,
    0xD3A2_646C,
    0xFD70_46C5,
    0xB55A_4F09,
    0xE9F8_CC1D,
    0xACCF_6200,
    0x8000_0000,
    0x8000_8000,
    0xFFFF_FFFF,
    0x5555_5555,
];

fn s9_move(p: &mut S9, rng: &mut Rng) {
    let idx = rng.below(10);
    match idx {
        0..=2 => {
            let v = p.k[idx];
            p.k[idx] = (match rng.below(6) {
                0 => v ^ (1 << (1 + rng.below(31))), // bit flip (never bit0)
                1 => rng.u32(),
                2 => v.wrapping_add(1 << (1 + rng.below(31))),
                3 => v.wrapping_sub(1 << (1 + rng.below(31))),
                4 => S9_KTABLE[rng.below(S9_KTABLE.len())],
                _ => (1u32 << (1 + rng.below(31))).wrapping_add(1), // 2^j+1
            }) | 1;
        }
        3..=5 => {
            let i = idx - 3;
            let v = p.c[i];
            p.c[i] = match rng.below(6) {
                0 => v ^ (1 << rng.below(32)),
                1 => rng.u32(),
                2 => v.wrapping_add(1),
                3 => v.wrapping_sub(1),
                4 => v.wrapping_add(1 << rng.below(32)),
                _ => S9_CTABLE[rng.below(S9_CTABLE.len())],
            };
        }
        6 | 7 => {
            let i = idx - 6;
            let v = p.m[i];
            p.m[i] = match rng.below(6) {
                0 => v ^ (1 << rng.below(32)),
                1 => rng.u32(),
                2 => v.wrapping_add(1),
                3 => v.wrapping_sub(1),
                4 => v ^ (3 << rng.below(31)), // adjacent-bit-pair flip
                _ => S9_CTABLE[rng.below(S9_CTABLE.len())],
            };
        }
        _ => {
            let i = idx - 8;
            p.s[i] = match rng.below(4) {
                0 => 1 + rng.below(31) as u32,
                1 => (p.s[i] + 1).min(31),
                2 => p.s[i].saturating_sub(1).max(1),
                _ => [3u32, 5, 9, 12, 16, 19][rng.below(6)],
            };
        }
    }
}

/// Single-bit perturbation of param `param` (0..3 k, 3..6 c, 6..8 m, 8..10 s).
/// None if the flip is invalid (k bit0 must stay set; s must stay 1..=31).
fn s9_flip(p: &S9, param: usize, bit: usize) -> Option<S9> {
    let mut q = *p;
    match param {
        0..=2 => {
            if bit == 0 {
                return None;
            }
            q.k[param] ^= 1 << bit;
        }
        3..=5 => q.c[param - 3] ^= 1 << bit,
        6 | 7 => q.m[param - 6] ^= 1 << bit,
        _ => {
            if bit >= 5 {
                return None;
            }
            let v = q.s[param - 8] ^ (1 << bit);
            if v == 0 || v > 31 {
                return None;
            }
            q.s[param - 8] = v;
        }
    }
    Some(q)
}

/// Deterministic endgame polish: MCMC locks most params but stalls on small
/// coordinated low-bit residues (measured: 8/10 exact with a C2+2/M2^6
/// barrier). Steepest-descent single flips -> all-pairs -> low-bit triples
/// over c/m params, looping until fixpoint. Returns the polished cost.
fn s9_polish(cur: &mut S9, battery: &[(u32, u32)]) -> u32 {
    let mut cost = s9_err(cur, battery, u32::MAX);
    if cost == 0 {
        return 0;
    }
    loop {
        let mut improved = false;
        // phase 1: single flips, first-improvement sweeps
        for param in 0..10 {
            for bit in 0..32 {
                if let Some(q) = s9_flip(cur, param, bit) {
                    let c2 = s9_err(&q, battery, cost);
                    if c2 < cost {
                        *cur = q;
                        cost = c2;
                        improved = true;
                        if cost == 0 {
                            return 0;
                        }
                    }
                }
            }
        }
        if improved {
            continue;
        }
        // phase 2: all pairs of single-bit flips
        'pairs: for p1 in 0..10 {
            for b1 in 0..32 {
                let Some(q1) = s9_flip(cur, p1, b1) else { continue };
                for p2 in p1..10 {
                    for b2 in 0..32 {
                        if p2 == p1 && b2 <= b1 {
                            continue;
                        }
                        let Some(q2) = s9_flip(&q1, p2, b2) else { continue };
                        let c2 = s9_err(&q2, battery, cost);
                        if c2 < cost {
                            *cur = q2;
                            cost = c2;
                            improved = true;
                            if cost == 0 {
                                return 0;
                            }
                            break 'pairs;
                        }
                    }
                }
            }
        }
        if improved {
            continue;
        }
        // phase 3: triples over the low 8 bits of c/m params (3..8)
        let low: Vec<(usize, usize)> =
            (3..8).flat_map(|p| (0..8).map(move |b| (p, b))).collect();
        'triples: for i in 0..low.len() {
            let Some(q1) = s9_flip(cur, low[i].0, low[i].1) else { continue };
            for j in i + 1..low.len() {
                let Some(q2) = s9_flip(&q1, low[j].0, low[j].1) else { continue };
                for l in j + 1..low.len() {
                    let Some(q3) = s9_flip(&q2, low[l].0, low[l].1) else { continue };
                    let c2 = s9_err(&q3, battery, cost);
                    if c2 < cost {
                        *cur = q3;
                        cost = c2;
                        improved = true;
                        if cost == 0 {
                            return 0;
                        }
                        break 'triples;
                    }
                }
            }
        }
        if !improved {
            return cost;
        }
    }
}

fn s9_random(rng: &mut Rng, flavored: bool) -> S9 {
    if flavored {
        // real-hash-flavored start: draw from the tables with noise
        S9 {
            k: [
                S9_KTABLE[rng.below(S9_KTABLE.len())] | 1,
                S9_KTABLE[rng.below(S9_KTABLE.len())] | 1,
                S9_KTABLE[rng.below(S9_KTABLE.len())] | 1,
            ],
            c: [
                S9_CTABLE[rng.below(S9_CTABLE.len())],
                S9_CTABLE[rng.below(S9_CTABLE.len())],
                S9_CTABLE[rng.below(S9_CTABLE.len())],
            ],
            m: [
                S9_CTABLE[rng.below(S9_CTABLE.len())],
                S9_CTABLE[rng.below(S9_CTABLE.len())],
            ],
            s: [[3u32, 5, 9, 12, 16, 19][rng.below(6)], [3u32, 5, 9, 12, 16, 19][rng.below(6)]],
        }
    } else {
        S9 {
            k: [rng.u32() | 1, rng.u32() | 1, rng.u32() | 1],
            c: [rng.u32(), rng.u32(), rng.u32()],
            m: [rng.u32(), rng.u32()],
            s: [1 + rng.below(31) as u32, 1 + rng.below(31) as u32],
        }
    }
}

/// Materialize the sandwich as a `Prog` (for the standard validate cascade
/// and for reporting in the common op-listing format).
fn s9_prog(p: &S9) -> Prog {
    let r = |i: usize| Operand::reg(i);
    let c = |i: usize| Operand::konst(i);
    let consts: [u32; NCONSTS] = [
        p.k[0], p.c[0], p.s[0], p.m[0], p.k[1], p.c[1], p.s[1], p.m[1], p.k[2], p.c[2], 0, 0,
    ];
    let ops = vec![
        Op { opc: Opc::Madd, dst: 1, a: r(0), b: c(0), c: c(1) },
        Op { opc: Opc::Shr, dst: 2, a: r(1), b: c(2), c: c(0) },
        Op { opc: Opc::Xor, dst: 3, a: r(1), b: c(3), c: c(0) },
        Op { opc: Opc::Xor, dst: 1, a: r(3), b: r(2), c: c(0) },
        Op { opc: Opc::Madd, dst: 2, a: r(1), b: c(4), c: c(5) },
        Op { opc: Opc::Shr, dst: 3, a: r(2), b: c(6), c: c(0) },
        Op { opc: Opc::Xor, dst: 4, a: r(2), b: c(7), c: c(0) },
        Op { opc: Opc::Xor, dst: 2, a: r(4), b: r(3), c: c(0) },
        Op { opc: Opc::Madd, dst: 1, a: r(2), b: c(8), c: c(9) },
    ];
    Prog { ops, consts, ninputs: 1 }
}

#[allow(clippy::too_many_arguments)]
fn s9_chain(
    id: usize,
    camp: Campaign, // S9 or S9Cal
    seed: u64,
    temp: f64,
    deadline: Instant,
    restart_after: u64,
    shared: &Shared,
) {
    let mut rng = Rng::new(seed ^ (id as u64).wrapping_mul(0xA24BAED4963EE407));
    // battery of (x, target) pairs: 8 edges + 24 chain-random
    let mut battery: Vec<(u32, u32)> = {
        let mut b: Vec<(u32, u32)> = make_battery(camp, 0, 42, true)
            .into_iter()
            .map(|(inp, t)| (inp[0], t))
            .take(8)
            .collect();
        b.extend(
            make_battery(camp, 24, 2000 + id as u64, false)
                .into_iter()
                .map(|(inp, t)| (inp[0], t)),
        );
        b
    };
    // S9Cal basin measurement: chains id%4 = 0/1/2 start at planted+2/6/12
    // param-kicks, id%4=3 from scratch. S9 (real target) has no planted
    // point: alternate flavored/random starts.
    let s9cal_start = |rng: &mut Rng, id: usize| -> S9 {
        if camp == Campaign::S9Cal && id % 4 < 3 {
            let mut p = S9_PLANTED;
            for _ in 0..[2usize, 6, 12][id % 4] {
                s9_move(&mut p, rng);
            }
            p
        } else {
            let fl = rng.below(2) == 0;
            s9_random(rng, fl)
        }
    };
    let mut cur = s9cal_start(&mut rng, id);
    let mut cur_cost = s9_err(&cur, &battery, u32::MAX);
    let mut local_best = cur_cost;
    let mut polished_at = u32::MAX;
    let mut since_improve = 0u64;
    let mut iters = 0u64;
    let max_uphill = (temp * 30.0) as u32 + 2;
    let mut validated_keys: std::collections::HashSet<String> = Default::default();

    loop {
        iters += 1;
        if iters % 8192 == 0 {
            shared.proposals.fetch_add(8192, Ordering::Relaxed);
            if Instant::now() >= deadline || shared.stop.load(Ordering::Relaxed) {
                return;
            }
        }
        let saved = cur;
        s9_move(&mut cur, &mut rng);
        if rng.below(8) == 0 {
            s9_move(&mut cur, &mut rng); // double-kick: cross 2-param barriers
        }
        let cutoff = cur_cost.saturating_add(max_uphill);
        let new_cost = s9_err(&cur, &battery, cutoff);
        let accept = new_cost <= cur_cost
            || (new_cost != u32::MAX
                && rng.f64() < (-((new_cost - cur_cost) as f64) / temp).exp());
        if !accept {
            cur = saved;
        } else {
            cur_cost = new_cost;
            if cur_cost < local_best {
                local_best = cur_cost;
                since_improve = 0;
            } else {
                since_improve += 1;
            }
        }
        // endgame polish: MCMC stalls on coordinated low-bit residues; the
        // deterministic flip search closes them. Guarded so each descent
        // only pays for polish when it has meaningfully improved.
        if cur_cost < 150 && cur_cost + 10 < polished_at {
            cur_cost = s9_polish(&mut cur, &battery);
            polished_at = cur_cost;
            if cur_cost < local_best {
                local_best = cur_cost;
                since_improve = 0;
            }
        }
        if local_best == cur_cost && since_improve == 0 {
            let milli = (cur_cost as u64) * 1000;
            let prev = shared.best_milli.fetch_min(milli, Ordering::Relaxed);
            if milli < prev {
                let mut bp = shared.best_prog.lock().unwrap();
                let listing = format!("{:?}\n", cur);
                if bp.as_ref().map(|(c2, _, _, _)| (cur_cost as f64) < *c2).unwrap_or(true) {
                    *bp = Some((cur_cost as f64, cur_cost, 9, listing));
                }
            }
        }
        if cur_cost == 0 {
            let prog = s9_prog(&cur);
            let key = prog.serialize();
            if !validated_keys.contains(&key) {
                validated_keys.insert(key.clone());
                shared.zero_hits.fetch_add(1, Ordering::Relaxed);
                match validate(&prog, camp) {
                    Ok(nvec) => {
                        let mut finds = shared.finds.lock().unwrap();
                        let listing = format!("params: {:?}\n{}", cur, prog.show());
                        if !finds.iter().any(|(k2, _, _, _)| *k2 == key) {
                            println!(
                                "\nFIND camp={} nonnop=9 vectors={}\n{}",
                                camp.name(),
                                nvec,
                                listing
                            );
                            finds.push((key, listing, nvec, 9));
                        }
                        drop(finds);
                        shared.stop.store(true, Ordering::Relaxed);
                        return;
                    }
                    Err(cex) => {
                        if battery.len() < 96 {
                            let want = camp.target(&cex);
                            battery.push((cex[0], want));
                        }
                        cur_cost = s9_err(&cur, &battery, u32::MAX);
                        local_best = local_best.max(cur_cost);
                        polished_at = u32::MAX;
                    }
                }
            }
        }
        if since_improve >= restart_after {
            cur = s9cal_start(&mut rng, id);
            cur_cost = s9_err(&cur, &battery, u32::MAX);
            local_best = cur_cost;
            since_improve = 0;
            polished_at = u32::MAX;
        }
    }
}

// ---------------- driver ----------------

struct Shared {
    best_milli: AtomicU64, // best cost*1000 across chains
    proposals: AtomicU64,
    zero_hits: AtomicU64, // battery-perfect candidates seen (pre-cascade)
    validate_bar: AtomicU64, // only cascade candidates with nonnop < this
    stop: AtomicBool,
    finds: Mutex<Vec<(String, String, u64, usize)>>, // (key, listing, vectors, nonnop)
    best_prog: Mutex<Option<(f64, u32, usize, String)>>, // cost, err, nonnop, listing
}

#[allow(clippy::too_many_arguments)]
fn chain(
    id: usize,
    camp: Campaign,
    slots: usize,
    seed: u64,
    temp: f64,
    opw: f64,
    max_ops_report: usize,
    validate_max: usize,
    deadline: Instant,
    restart_after: u64,
    shared: &Shared,
) {
    let mut rng = Rng::new(seed ^ (id as u64).wrapping_mul(0xA24BAED4963EE407));
    // battery: 8 edge vectors + 24 random (chain-seeded randoms)
    let mut battery = make_battery(camp, 0, 42, true);
    battery.truncate(8);
    battery.extend(make_battery(camp, 24, 1000 + id as u64, false));
    let mut cur = match id % 4 {
        0 => mutated_seed(&mut rng, camp, slots, 0), // exact seed (cold chains)
        1 => mutated_seed(&mut rng, camp, slots, 4),
        2 => mutated_seed(&mut rng, camp, slots, 12),
        _ => random_prog(&mut rng, camp, slots),
    };
    let mut validated_keys: std::collections::HashSet<String> = Default::default();
    let cost_of = |p: &Prog, battery: &[(Vec<u32>, u32)]| -> (f64, u32) {
        let e = err_bits(p, battery, u32::MAX);
        (e as f64 + opw * p.nonnop() as f64, e)
    };
    let (mut cur_cost, mut cur_err) = cost_of(&cur, &battery);
    let mut since_improve = 0u64;
    let mut local_best = cur_cost;
    let mut iters = 0u64;
    let max_uphill = (temp * 30.0) as u32 + 2; // accept prob < e^-30 ~ never

    loop {
        iters += 1;
        if iters % 8192 == 0 {
            shared.proposals.fetch_add(8192, Ordering::Relaxed);
            if Instant::now() >= deadline || shared.stop.load(Ordering::Relaxed) {
                shared.proposals.fetch_add(iters % 8192, Ordering::Relaxed);
                return;
            }
        }
        let undo = apply_move(&mut cur, &mut rng);
        let cutoff = cur_cost as u32 + max_uphill;
        let e = err_bits(&cur, &battery, cutoff);
        let new_cost = if e == u32::MAX {
            f64::INFINITY
        } else {
            e as f64 + opw * cur.nonnop() as f64
        };
        let accept = new_cost <= cur_cost
            || (new_cost.is_finite() && rng.f64() < (-(new_cost - cur_cost) / temp).exp());
        if !accept {
            undo_move(&mut cur, undo);
        } else {
            cur_cost = new_cost;
            cur_err = e;
            if cur_cost < local_best {
                local_best = cur_cost;
                since_improve = 0;
                // publish global best
                let milli = (cur_cost * 1000.0) as u64;
                let prev = shared.best_milli.fetch_min(milli, Ordering::Relaxed);
                if milli < prev {
                    let mut bp = shared.best_prog.lock().unwrap();
                    if bp.as_ref().map(|(c, _, _, _)| cur_cost < *c).unwrap_or(true) {
                        *bp = Some((cur_cost, cur_err, cur.nonnop(), cur.show()));
                    }
                }
            } else {
                since_improve += 1;
            }
            // candidate: battery-perfect AND small enough to be interesting.
            // The bar starts at validate_max+1 and drops to each validated
            // find's size, so only strictly-smaller candidates pay the
            // cascade after that (prevents validate storms from err-0 drift).
            if cur_err == 0
                && (cur.nonnop() as u64) < shared.validate_bar.load(Ordering::Relaxed)
            {
                let key = cur.serialize();
                if !validated_keys.contains(&key) {
                    if validated_keys.len() > 200_000 {
                        validated_keys.clear();
                    }
                    validated_keys.insert(key.clone());
                    shared.zero_hits.fetch_add(1, Ordering::Relaxed);
                    match validate(&cur, camp) {
                        Ok(nvec) => {
                            let nn = cur.nonnop();
                            shared.validate_bar.fetch_min(nn as u64, Ordering::Relaxed);
                            let mut finds = shared.finds.lock().unwrap();
                            if !finds.iter().any(|(k, _, _, _)| *k == key) {
                                println!(
                                    "\nFIND camp={} nonnop={} vectors={}\n{}",
                                    camp.name(),
                                    nn,
                                    nvec,
                                    cur.show()
                                );
                                finds.push((key, cur.show(), nvec, nn));
                            }
                            drop(finds);
                            if nn <= max_ops_report {
                                shared.stop.store(true, Ordering::Relaxed);
                                return;
                            }
                            // correct but not small enough: keep compressing
                            since_improve = 0;
                        }
                        Err(cex) => {
                            // inject counterexample (cap battery growth)
                            if battery.len() < 96 {
                                let want = camp.target(&cex);
                                battery.push((cex, want));
                            }
                            let (c, e2) = cost_of(&cur, &battery);
                            cur_cost = c;
                            cur_err = e2;
                            local_best = local_best.max(cur_cost); // rebase
                        }
                    }
                }
            }
        }
        if since_improve >= restart_after {
            // cold chains (id%4==0) restart at/near the exact seed;
            // hot chains mix mutated seeds and random programs.
            let kicks = [0usize, 2, 6, 15][rng.below(4)];
            cur = if id % 4 == 3 && rng.below(2) == 0 {
                random_prog(&mut rng, camp, slots)
            } else if id % 4 == 0 {
                mutated_seed(&mut rng, camp, slots, kicks.min(2))
            } else {
                mutated_seed(&mut rng, camp, slots, kicks)
            };
            let (c, e2) = cost_of(&cur, &battery);
            cur_cost = c;
            cur_err = e2;
            local_best = cur_cost;
            since_improve = 0;
        }
    }
}

/// Direct verification of the endgame polish: does the deterministic flip
/// search close (a) the exact measured gate-2 barrier (C2+2, M2^6) and
/// (b) planted + k random s9_move kicks, k = 1..4? Prints per-trial results.
fn s9_polish_test() {
    let battery: Vec<(u32, u32)> = make_battery(Campaign::S9Cal, 0, 42, true)
        .into_iter()
        .map(|(i, t)| (i[0], t))
        .take(8)
        .chain(
            make_battery(Campaign::S9Cal, 24, 3000, false)
                .into_iter()
                .map(|(i, t)| (i[0], t)),
        )
        .collect();
    // (a) exact gate-2 residual
    let mut p = S9_PLANTED;
    p.c[1] = p.c[1].wrapping_add(2);
    p.m[1] ^= 6;
    let c0 = s9_err(&p, &battery, u32::MAX);
    let t0 = Instant::now();
    let c1 = s9_polish(&mut p, &battery);
    println!(
        "polishtest gate2-residual: cost {} -> {} in {:.2}s {}",
        c0,
        c1,
        t0.elapsed().as_secs_f64(),
        if c1 == 0 { "CLOSED" } else { "OPEN" }
    );
    // (b) random kick trials
    let mut rng = Rng::new(999);
    let mut closed = [0u32; 5];
    let mut total = [0u32; 5];
    for trial in 0..40 {
        let kicks = 1 + trial % 4;
        let mut p = S9_PLANTED;
        for _ in 0..kicks {
            s9_move(&mut p, &mut rng);
        }
        let c0 = s9_err(&p, &battery, u32::MAX);
        let t0 = Instant::now();
        let c1 = s9_polish(&mut p, &battery);
        total[kicks] += 1;
        if c1 == 0 {
            closed[kicks] += 1;
        }
        println!(
            "polishtest kicks={} trial={} cost {} -> {} ({:.2}s)",
            kicks,
            trial,
            c0,
            c1,
            t0.elapsed().as_secs_f64()
        );
    }
    for k in 1..5 {
        println!("polishtest summary kicks={}: {}/{} closed", k, closed[k], total[k]);
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mut camp = Campaign::Cal;
    let mut slots = 12usize;
    let mut seconds = 120u64;
    let mut threads = 8usize;
    let mut temp = 3.0f64;
    let mut opw = 0.4f64;
    let mut seed = 1u64;
    let mut max_ops_report = 10usize; // stop the slice when a find at <= this size lands
    let mut validate_max = 11usize; // only cascade-validate candidates at <= this size
    let mut restart_after = 400_000u64;
    let mut ckpt_dir = "tools".to_string();
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "cal" => camp = Campaign::Cal,
            "t1" => camp = Campaign::T1,
            "t2" => camp = Campaign::T2,
            "t3" => camp = Campaign::T3,
            "s9" => camp = Campaign::S9,
            "s9cal" => camp = Campaign::S9Cal,
            "s9polishtest" => {
                s9_polish_test();
                return;
            }
            "--slots" => {
                i += 1;
                slots = args[i].parse().unwrap();
            }
            "--seconds" => {
                i += 1;
                seconds = args[i].parse().unwrap();
            }
            "--threads" => {
                i += 1;
                threads = args[i].parse().unwrap();
            }
            "--temp" => {
                i += 1;
                temp = args[i].parse().unwrap();
            }
            "--opw" => {
                i += 1;
                opw = args[i].parse().unwrap();
            }
            "--seed" => {
                i += 1;
                seed = args[i].parse().unwrap();
            }
            "--max-ops" => {
                i += 1;
                max_ops_report = args[i].parse().unwrap();
            }
            "--validate-max" => {
                i += 1;
                validate_max = args[i].parse().unwrap();
            }
            "--restart-after" => {
                i += 1;
                restart_after = args[i].parse().unwrap();
            }
            "--ckpt-dir" => {
                i += 1;
                ckpt_dir = args[i].clone();
            }
            other => panic!("unknown arg {other}"),
        }
        i += 1;
    }

    // sanity: seed programs are correct
    for c in [Campaign::Cal, Campaign::T1, Campaign::T2, Campaign::T3] {
        let p = seed_prog(c);
        let b = make_battery(c, 4096, 7, true);
        assert_eq!(err_bits(&p, &b, u32::MAX), 0, "seed program wrong for {}", c.name());
    }
    // sanity: s9 midpoint algebra (fwd/bwd inversion) + prog materialization
    {
        let b = make_battery(Campaign::S9Cal, 4096, 7, true);
        let bat: Vec<(u32, u32)> = b.iter().map(|(i, t)| (i[0], *t)).collect();
        assert_eq!(s9_err(&S9_PLANTED, &bat, u32::MAX), 0, "s9 midpoint algebra broken");
        let p = s9_prog(&S9_PLANTED);
        assert_eq!(err_bits(&p, &b, u32::MAX), 0, "s9_prog materialization broken");
        for k in [1u32, 3, 4097, 0xA5A5_A5A5, 0xFF51_AFD7] {
            assert_eq!(k.wrapping_mul(mul_inv_odd(k)), 1, "mul_inv_odd broken");
        }
    }

    let shared = Shared {
        best_milli: AtomicU64::new(u64::MAX),
        proposals: AtomicU64::new(0),
        zero_hits: AtomicU64::new(0),
        validate_bar: AtomicU64::new(validate_max as u64 + 1),
        stop: AtomicBool::new(false),
        finds: Mutex::new(Vec::new()),
        best_prog: Mutex::new(None),
    };
    let start = Instant::now();
    let deadline = start + Duration::from_secs(seconds);

    std::thread::scope(|s| {
        for id in 0..threads {
            let shared = &shared;
            // temperature ladder: chain temps base*{0.25, 0.5, 1.0, 2.0}.
            // Cold chains hold near-correct programs (transformation mode);
            // hot chains explore. id%4==0 is both coldest and seed-started.
            let temp_i = temp * [0.25, 0.5, 1.0, 2.0][id % 4];
            s.spawn(move || {
                let chain_seed =
                    seed.wrapping_mul(0x517C_C1B7_2722_0A95).wrapping_add(id as u64 + 1);
                if camp == Campaign::S9 || camp == Campaign::S9Cal {
                    s9_chain(id, camp, chain_seed, temp_i, deadline, restart_after, shared);
                } else {
                    chain(
                        id,
                        camp,
                        slots,
                        chain_seed,
                        temp_i,
                        opw,
                        max_ops_report,
                        validate_max,
                        deadline,
                        restart_after,
                        shared,
                    );
                }
            });
        }
        // progress ticker
        let shared_ref = &shared;
        s.spawn(move || loop {
            std::thread::sleep(Duration::from_secs(15));
            if Instant::now() >= deadline || shared_ref.stop.load(Ordering::Relaxed) {
                return;
            }
            let bm = shared_ref.best_milli.load(Ordering::Relaxed);
            eprintln!(
                "  t={:.0}s proposals={}M best_cost={} zero_hits={}",
                start.elapsed().as_secs_f64(),
                shared_ref.proposals.load(Ordering::Relaxed) / 1_000_000,
                if bm == u64::MAX { "inf".to_string() } else { format!("{:.3}", bm as f64 / 1000.0) },
                shared_ref.zero_hits.load(Ordering::Relaxed)
            );
        });
    });

    let secs = start.elapsed().as_secs_f64();
    let proposals = shared.proposals.load(Ordering::Relaxed);
    let finds = shared.finds.lock().unwrap();
    let best = shared.best_prog.lock().unwrap();
    let (best_cost, best_err, best_nn) = best
        .as_ref()
        .map(|(c, e, n, _)| (*c, *e, *n))
        .unwrap_or((f64::INFINITY, u32::MAX, 0));
    println!(
        "CHECKPOINT campaign={} slots={} threads={} temp={} opw={} seed={} secs={:.1} proposals={} best_cost={:.3} best_err={} best_nonnop={} zero_hits={} finds={}",
        camp.name(),
        slots,
        threads,
        temp,
        opw,
        seed,
        secs,
        proposals,
        best_cost,
        best_err,
        best_nn,
        shared.zero_hits.load(Ordering::Relaxed),
        finds.len()
    );
    if let Some((c, e, n, listing)) = best.as_ref() {
        println!("BEST cost={:.3} err={} nonnop={}\n{}", c, e, n, listing);
    }

    // checkpoint JSON
    let _ = std::fs::create_dir_all(&ckpt_dir);
    let ckpt_path = format!("{}/p5h_ckpt_{}_s{}.json", ckpt_dir, camp.name(), slots);
    let mut j = String::new();
    j.push_str(&format!(
        "{{\"campaign\":\"{}\",\"slots\":{},\"seed\":{},\"temp\":{},\"opw\":{},\"secs\":{:.1},\"proposals\":{},\"best_cost\":{},\"best_err\":{},\"best_nonnop\":{},\"finds\":[",
        camp.name(), slots, seed, temp, opw, secs, proposals,
        if best_cost.is_finite() { best_cost } else { -1.0 }, best_err as i64, best_nn
    ));
    for (k, (_key, listing, nvec, nn)) in finds.iter().enumerate() {
        if k > 0 {
            j.push(',');
        }
        j.push_str(&format!(
            "{{\"nonnop\":{},\"vectors\":{},\"listing\":{:?}}}",
            nn, nvec, listing
        ));
    }
    j.push_str("]}");
    if let Ok(mut f) = std::fs::File::create(&ckpt_path) {
        let _ = f.write_all(j.as_bytes());
    }
    for (_k, listing, nvec, nn) in finds.iter() {
        println!("VALIDATED-FIND nonnop={} vectors={}\n{}", nn, nvec, listing);
    }
}
