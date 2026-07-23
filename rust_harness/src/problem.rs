//! Port of the problem definition from `problem.py` (see `docs/problem.md`):
//! the implicit binary tree, the batch of walkers, the hash function, and a
//! pure-Rust reference implementation to check candidate kernels against.
//!
//! Tree/Input generation here uses a small local PRNG (`SplitMix64`), *not*
//! Python's `random` module — it is not bit-for-bit identical to Python's
//! generator and isn't meant to be. For pure-Rust property tests (arbitrary
//! small trees, fast `cargo test` iteration) that doesn't matter: any
//! reasonably-random tree exercises the algorithm the same way. Where
//! bit-for-bit parity with the actual benchmark's data matters — i.e.
//! checking your kernel against the exact 147,734-cycle-baseline workload —
//! use the exported fixtures from `tools/export_fixtures.py` instead (see
//! `fixtures.rs`), which carry the real memory image out of Python.

use crate::isa::AluOp;
use std::collections::HashMap;

/// The 6-stage mixing function's constants, ported verbatim from
/// `HASH_STAGES` in `problem.py`: `(op1, val1, op2, op3, val3)`, applied as
/// `a = (a op1 val1) op2 (a op3 val3)`.
pub const HASH_STAGES: [(AluOp, u32, AluOp, AluOp, u32); 6] = [
    (AluOp::Add, 0x7ED55D16, AluOp::Add, AluOp::Shl, 12),
    (AluOp::Xor, 0xC761C23C, AluOp::Xor, AluOp::Shr, 19),
    (AluOp::Add, 0x165667B1, AluOp::Add, AluOp::Shl, 5),
    (AluOp::Add, 0xD3A2646C, AluOp::Xor, AluOp::Shl, 9),
    (AluOp::Add, 0xFD7046C5, AluOp::Add, AluOp::Shl, 3),
    (AluOp::Xor, 0xB55A4F09, AluOp::Xor, AluOp::Shr, 16),
];

/// Pure-function version of `myhash` in `problem.py` — not how the kernel
/// actually computes it (the kernel emits `alu` ops for this, see
/// `builder::build_hash`), but the ground truth used to check a candidate
/// kernel's output and to build value traces for `debug::Compare`.
pub fn myhash(mut a: u32) -> u32 {
    for &(op1, val1, op2, op3, val3) in HASH_STAGES.iter() {
        let left = op1.apply(a, val1);
        let right = op3.apply(a, val3);
        a = op2.apply(left, right);
    }
    a
}

/// Segment functions of the 11-mixing-op fused hash form (the shape the
/// kernel actually emits, see `dag.rs::emit_hash` and perf_takehome.py's
/// `_fused_hash_constants`), exposed so the fusion-search superoptimizer
/// (`bin/fusion_search.rs`) and the minimality tests below can name each
/// inter-op cut point:
///
///   a --stage0--> b --stage1--> c --f23--> d --stage4--> e --stage5--> out
///    1 madd        shr,xor,xor    2 madd     1 madd        xor,shr,xor
///                                 + 1 xor
///
/// = 11 ops (12 with the `val ^ node_val` fold-in, 13 with `out & 1`).
pub mod hashseg {
    /// stage0 multiplier `1 + 2^12`.
    pub const K0: u32 = 4097;
    pub const C0: u32 = 0x7ED5_5D16;
    pub const C1: u32 = 0xC761_C23C;
    pub const SH1: u32 = 19;
    /// stage2 multiplier `1 + 2^5`.
    pub const KP: u32 = 33;
    /// `C2 + C3` (stage2+3 fusion's p-branch constant).
    pub const AP: u32 = 0xE9F8_CC1D;
    /// `33 * 2^9` (stage3's `<<9` folded into the q-branch multiplier).
    pub const KQ: u32 = 16896;
    /// `C2 << 9` (mod 2^32).
    pub const AQ: u32 = 0xACCF_6200;
    /// stage4 multiplier `1 + 2^3`.
    pub const K4: u32 = 9;
    pub const C4: u32 = 0xFD70_46C5;
    pub const C5: u32 = 0xB55A_4F09;
    pub const SH5: u32 = 16;

    pub fn stage0(a: u32) -> u32 {
        a.wrapping_mul(K0).wrapping_add(C0)
    }
    pub fn stage1(b: u32) -> u32 {
        (b ^ C1) ^ (b >> SH1)
    }
    /// Fused stages 2+3: `p ^ q` with both branches affine in the input.
    pub fn f23(c: u32) -> u32 {
        let p = c.wrapping_mul(KP).wrapping_add(AP);
        let q = c.wrapping_mul(KQ).wrapping_add(AQ);
        p ^ q
    }
    pub fn stage4(d: u32) -> u32 {
        d.wrapping_mul(K4).wrapping_add(C4)
    }
    pub fn stage5(e: u32) -> u32 {
        (e ^ C5) ^ (e >> SH5)
    }
    /// The C5-less xor-shift `x ^ (x >> 16)` — stage 5 as it appears in the
    /// `c5_prexor` primed value domain (H-015), where the `^ C5` is absorbed
    /// into the tree values. Used by the MITM search's primed-domain
    /// cross-round targets (H-016).
    pub fn sigma16(x: u32) -> u32 {
        x ^ (x >> SH5)
    }
    /// The full 11-op composition; equals `myhash` bit-for-bit (tested).
    pub fn fused_hash(a: u32) -> u32 {
        stage5(stage4(f23(stage1(stage0(a)))))
    }

    // ---- 2-op parity extraction (found analytically, confirmed by the
    // fusion search; see `parity_from_d_is_bit_exact`) ----
    //
    // The only bit the idx update needs is `out & 1 = e0 ^ e16 ^ 1` (C5 is
    // odd). A multiply_add can pack XOR-of-two-bits into bit 31: for
    // `t = x*(2^31 + 2^j) + C` mod 2^32 the `2^31*x` term contributes only
    // `x0 << 31`, the `2^j*x` term contributes `x_{31-j}` to bit 31 with no
    // carry INTO bit 31 from the other term, and any constant 2^31 in `C`
    // flips it. So bit31(t) = x0 ^ x_{31-j} ^ C31 exactly, and one `>> 31`
    // extracts it.

    /// `2^31 + 9*2^15`: parity-from-d multiplier (j=15 lifts bit16 of
    /// `9d + C4` to bit 31 after the `*2^15` scaling of stage4's madd).
    pub const PAR_D_K: u32 = 0x8004_8000;
    /// `(C4 << 15) mod 2^32` (no 2^31 term: e0 = d0 ^ 1 and C5_0 = 1 cancel).
    pub const PAR_D_C: u32 = 0x2362_8000;
    /// Bit0 of the final hash, computed from the f23 output `d` in 2 ops
    /// (madd + shr) instead of via stage4+stage5+`&1` (5 ops from `d`).
    pub fn parity_from_d(d: u32) -> u32 {
        d.wrapping_mul(PAR_D_K).wrapping_add(PAR_D_C) >> 31
    }

    /// `2^31 + 2^15`: parity-from-e multiplier.
    pub const PAR_E_K: u32 = 0x8000_8000;
    /// `2^31`: accounts for C5's odd bit0.
    pub const PAR_E_C: u32 = 0x8000_0000;
    /// Bit0 of the final hash from the stage4 output `e` in 2 ops.
    pub fn parity_from_e(e: u32) -> u32 {
        e.wrapping_mul(PAR_E_K).wrapping_add(PAR_E_C) >> 31
    }
}

/// Minimal, dependency-free PRNG (SplitMix64) for generating synthetic test
/// trees/inputs in pure-Rust unit tests. Not related to Python's RNG.
pub struct Rng(u64);

impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng(seed)
    }

    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }

    /// A value in `0..2**30`, matching the range `Tree`/`Input` values are
    /// drawn from in `problem.py` (`random.randint(0, 2**30 - 1)`).
    pub fn next_value(&mut self) -> u32 {
        (self.next_u64() & ((1 << 30) - 1)) as u32
    }
}

#[derive(Clone, Debug)]
pub struct Tree {
    pub height: u32,
    pub values: Vec<u32>,
}

impl Tree {
    pub fn generate(height: u32, rng: &mut Rng) -> Self {
        let n_nodes = (1usize << (height + 1)) - 1;
        let values = (0..n_nodes).map(|_| rng.next_value()).collect();
        Tree { height, values }
    }
}

#[derive(Clone, Debug)]
pub struct Input {
    pub indices: Vec<u32>,
    pub values: Vec<u32>,
    pub rounds: u32,
}

impl Input {
    pub fn generate(batch_size: usize, rounds: u32, rng: &mut Rng) -> Self {
        Input {
            indices: vec![0u32; batch_size],
            values: (0..batch_size).map(|_| rng.next_value()).collect(),
            rounds,
        }
    }
}

/// Where each region lives in the flat memory image built by
/// `build_mem_image`, mirroring the header in `problem.py`.
///
/// Only 7 fields are actually meaningful/readable (`mem[0..6]`, all of
/// which `KernelBuilder.build_kernel` reads at start-up). `problem.py`'s
/// `build_mem_image` *also* writes a would-be `extra_room` pointer to
/// `mem[7]` — but since `forest_values_p == header == 7`, that word is the
/// tree-values array's first element too, and the immediately-following
/// `mem[header:inp_indices_p] = t.values` silently overwrites it. So
/// `mem[7]` ends up holding `tree.values[0]`, not a usable pointer, and
/// nothing in the kernel ever reads it. We reproduce that quirk exactly
/// (rather than "fixing" it) so a `mem_in` built here is byte-for-byte
/// compatible with one exported from the real `problem.py`.
#[derive(Copy, Clone, Debug)]
pub struct MemLayout {
    pub rounds: u32,
    pub n_nodes: u32,
    pub batch_size: u32,
    pub forest_height: u32,
    pub forest_values_p: u32,
    pub inp_indices_p: u32,
    pub inp_values_p: u32,
}

impl MemLayout {
    pub fn from_mem(mem: &[u32]) -> Self {
        MemLayout {
            rounds: mem[0],
            n_nodes: mem[1],
            batch_size: mem[2],
            forest_height: mem[3],
            forest_values_p: mem[4],
            inp_indices_p: mem[5],
            inp_values_p: mem[6],
        }
    }
}

/// Port of `build_mem_image` in `problem.py`: header, then tree values,
/// then indices, then values, then free scratch room. See `MemLayout`'s
/// docs for the `mem[7]`-gets-clobbered quirk this intentionally preserves.
pub fn build_mem_image(tree: &Tree, input: &Input) -> Vec<u32> {
    let header = 7usize;
    let extra_room = tree.values.len() + input.indices.len() * 2 + 8 * 2 + 32;
    let total = header + tree.values.len() + input.indices.len() + input.values.len() + extra_room;
    let mut mem = vec![0u32; total];

    let forest_values_p = header as u32;
    let inp_indices_p = forest_values_p + tree.values.len() as u32;
    let inp_values_p = inp_indices_p + input.indices.len() as u32;
    let extra_room_p = inp_values_p + input.values.len() as u32; // clobbered below, kept for parity

    mem[0] = input.rounds;
    mem[1] = tree.values.len() as u32;
    mem[2] = input.indices.len() as u32;
    mem[3] = tree.height;
    mem[4] = forest_values_p;
    mem[5] = inp_indices_p;
    mem[6] = inp_values_p;
    mem[7] = extra_room_p;

    mem[forest_values_p as usize..inp_indices_p as usize].copy_from_slice(&tree.values);
    mem[inp_indices_p as usize..inp_values_p as usize].copy_from_slice(&input.indices);
    mem[inp_values_p as usize..inp_values_p as usize + input.values.len()]
        .copy_from_slice(&input.values);

    mem
}

/// Pure-Rust reference implementation, ported from `reference_kernel2` in
/// `problem.py`: runs the actual round/walker update in memory and records
/// a value trace with the same `"round|i|field[|hash_stage_idx]"` key
/// scheme used by `tools/export_fixtures.py`'s Python-side trace export —
/// so a `Machine` can be checked against either a Rust-generated tree
/// (fast, no Python involved) or an imported Python fixture (bit-for-bit
/// the graded workload) via the same `DebugSlot::Compare` machinery.
pub fn reference_run(mem: &mut [u32]) -> HashMap<String, u32> {
    let layout = MemLayout::from_mem(mem);
    let mut trace = HashMap::new();

    for h in 0..layout.rounds {
        for i in 0..layout.batch_size {
            let idx_addr = (layout.inp_indices_p + i) as usize;
            let val_addr = (layout.inp_values_p + i) as usize;

            let idx = mem[idx_addr];
            trace.insert(format!("{h}|{i}|idx"), idx);
            let val = mem[val_addr];
            trace.insert(format!("{h}|{i}|val"), val);
            let node_val = mem[(layout.forest_values_p + idx) as usize];
            trace.insert(format!("{h}|{i}|node_val"), node_val);

            let mut a = val ^ node_val;
            for (hi, &(op1, val1, op2, op3, val3)) in HASH_STAGES.iter().enumerate() {
                let left = op1.apply(a, val1);
                let right = op3.apply(a, val3);
                a = op2.apply(left, right);
                trace.insert(format!("{h}|{i}|hash_stage|{hi}"), a);
            }
            let new_val = a;
            trace.insert(format!("{h}|{i}|hashed_val"), new_val);

            let mut new_idx = 2 * idx + if new_val.is_multiple_of(2) { 1 } else { 2 };
            trace.insert(format!("{h}|{i}|next_idx"), new_idx);
            if new_idx >= layout.n_nodes {
                new_idx = 0;
            }
            trace.insert(format!("{h}|{i}|wrapped_idx"), new_idx);

            mem[val_addr] = new_val;
            mem[idx_addr] = new_idx;
        }
    }

    trace
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Values cross-checked directly against `problem.myhash` in Python
    /// (`python3 -c "from problem import myhash; print(myhash(X))"`) — this
    /// is the fastest possible signal that the Rust hash port has drifted
    /// from the real implementation, independent of the fixture files.
    #[test]
    fn myhash_matches_python() {
        assert_eq!(myhash(0), 1800329511);
        assert_eq!(myhash(1), 3028713910);
        assert_eq!(myhash(12345), 3058842707);
        assert_eq!(myhash(0xFFFF_FFFF), 4268016002);
        assert_eq!(myhash(1 << 31), 2122005522);
    }

    #[test]
    fn tree_node_count_matches_perfect_binary_tree() {
        let mut rng = Rng::new(1);
        let t = Tree::generate(3, &mut rng);
        assert_eq!(t.values.len(), 2usize.pow(4) - 1); // 2^(height+1) - 1
    }

    #[test]
    fn reference_run_wraps_at_bottom_of_tree() {
        // height=0 -> a single node (the root). Every step's next_idx is
        // >= 1 >= n_nodes(1), so it must wrap back to 0 every round.
        let mut rng = Rng::new(2);
        let tree = Tree::generate(0, &mut rng);
        assert_eq!(tree.values.len(), 1);
        let input = Input::generate(4, 5, &mut rng);
        let mut mem = build_mem_image(&tree, &input);
        reference_run(&mut mem);
        let layout = MemLayout::from_mem(&mem);
        for i in 0..layout.batch_size {
            let idx = mem[(layout.inp_indices_p + i) as usize];
            assert_eq!(idx, 0, "walker {i} should always wrap back to the root");
        }
    }

    // ---- idea4-hash-fusion: minimality of the 12-op hash ----
    //
    // The DAG collapses hash stages 0/2/4 (op1==op2==Add, op3==Shl) to one
    // `multiply_add` each and leaves stages 1/3/5 as 3 alu ops, for 12 ops
    // total. These two tests pin that 12 is the *algebraic minimum* over this
    // ISA -- an executable proof of the negative result behind idea #4, so a
    // future "surely the hash can be fused further" attempt is answered by a
    // failing/passing test rather than re-derivation.

    /// Recompute one hash exactly the way the DAG emits it (see dag.rs
    /// emit_hash): affine stages (op1==op2==Add, op3==Shl) become one
    /// multiply_add `a*(1+2^s)+val1` mirroring ValuSlot::MultiplyAdd (a*b+c,
    /// wrapping); every other stage stays 3 alu ops.
    fn fused_hash(mut a: u32) -> u32 {
        for &(op1, val1, op2, op3, val3) in HASH_STAGES.iter() {
            if op1 == AluOp::Add && op2 == AluOp::Add && op3 == AluOp::Shl {
                let k = 1u32.wrapping_add(1u32 << (val3 & 31)); // 1 + 2^s
                a = a.wrapping_mul(k).wrapping_add(val1);
            } else {
                let left = op1.apply(a, val1);
                let right = op3.apply(a, val3);
                a = op2.apply(left, right);
            }
        }
        a
    }

    /// The current MultiplyAdd fusion (stages 0/2/4) is bit-exact vs myhash
    /// over edge cases + a large LCG sweep. Guards the algebraic identity
    /// (a+val1)+(a<<s) = a*(1+2^s)+val1 (mod 2^32) against regression.
    #[test]
    fn multiply_add_fusion_is_bit_exact() {
        let mut samples: Vec<u32> = vec![
            0,
            1,
            2,
            3,
            7,
            8,
            255,
            256,
            0x7FFF_FFFF,
            0x8000_0000,
            0xFFFF_FFFF,
            1 << 12,
            1 << 19,
            1 << 9,
            1 << 16,
            1 << 31,
            0xC761_C23C,
            0xD3A2_646C,
            0xB55A_4F09,
            0x7ED5_5D16,
        ];
        let mut x = 0x1234_5678u32;
        for _ in 0..200_000 {
            x = x.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            samples.push(x);
        }
        for &a in &samples {
            assert_eq!(
                fused_hash(a),
                myhash(a),
                "fused hash diverged at a={a:#010x}"
            );
        }
    }

    // Binary ops the search may use (division/modulo ops excluded: they panic
    // on 0 and are irrelevant to xor-shift fusion). MultiplyAdd is added
    // separately as the ISA's only fused 3-input primitive.
    const SEARCH_OPS: [AluOp; 10] = [
        AluOp::Add,
        AluOp::Sub,
        AluOp::Mul,
        AluOp::Xor,
        AluOp::And,
        AluOp::Or,
        AluOp::Shl,
        AluOp::Shr,
        AluOp::Lt,
        AluOp::Eq,
    ];

    fn stage_true(idx: usize, a: u32) -> u32 {
        let (op1, val1, op2, op3, val3) = HASH_STAGES[idx];
        op2.apply(op1.apply(a, val1), op3.apply(a, val3))
    }

    // Constant operand pool for a stage: its own constant, its shift amount,
    // the shift-as-multiply value 2^s (so a Shl->Mul rewrite is reachable),
    // plus generic literals. `a` is prepended live per probe.
    fn const_pool(idx: usize) -> Vec<u32> {
        let (_o1, val1, _o2, _o3, val3) = HASH_STAGES[idx];
        vec![val1, val3, 1u32 << (val3 & 31), 0, 1, 2, 0xFFFF_FFFF]
    }

    /// True iff SOME program of <=2 ISA ops (binary SEARCH_OPS or one
    /// MultiplyAdd) reproduces stage `idx` on EVERY probe. The 3-op reference
    /// decomposition is always reachable at depth 3, so if this returns false
    /// the stage provably needs >=3 ops over this ISA.
    fn two_op_program_exists(idx: usize, probes: &[u32]) -> bool {
        let consts = const_pool(idx);
        let n0 = 1 + consts.len(); // operand pool size (index 0 = a)
        let bases: Vec<Vec<u32>> = probes
            .iter()
            .map(|&a| {
                let mut v = Vec::with_capacity(n0);
                v.push(a);
                v.extend_from_slice(&consts);
                v
            })
            .collect();
        let targets: Vec<u32> = probes.iter().map(|&a| stage_true(idx, a)).collect();

        let mad = |x: u32, y: u32, z: u32| x.wrapping_mul(y).wrapping_add(z);

        // 0-op: an operand already equals the stage output on all probes.
        for i in 0..n0 {
            if bases.iter().zip(&targets).all(|(b, &t)| b[i] == t) {
                return true;
            }
        }
        // 1-op: binary
        for &op in SEARCH_OPS.iter() {
            for i in 0..n0 {
                for j in 0..n0 {
                    if bases
                        .iter()
                        .zip(&targets)
                        .all(|(b, &t)| op.apply(b[i], b[j]) == t)
                    {
                        return true;
                    }
                }
            }
        }
        // 1-op: MultiplyAdd
        for i in 0..n0 {
            for j in 0..n0 {
                for k in 0..n0 {
                    if bases
                        .iter()
                        .zip(&targets)
                        .all(|(b, &t)| mad(b[i], b[j], b[k]) == t)
                    {
                        return true;
                    }
                }
            }
        }

        // Enumerate all first-op specs (t1 lands at extended index n0).
        enum Spec {
            Bin(AluOp, usize, usize),
            Mad(usize, usize, usize),
        }
        let mut firsts: Vec<Spec> = Vec::new();
        for &op in SEARCH_OPS.iter() {
            for i in 0..n0 {
                for j in 0..n0 {
                    firsts.push(Spec::Bin(op, i, j));
                }
            }
        }
        for i in 0..n0 {
            for j in 0..n0 {
                for k in 0..n0 {
                    firsts.push(Spec::Mad(i, j, k));
                }
            }
        }

        let m = n0 + 1;
        let get = |b: &[u32], t1: u32, i: usize| -> u32 {
            if i < n0 {
                b[i]
            } else {
                t1
            }
        };

        for f in &firsts {
            // second op binary
            for &op in SEARCH_OPS.iter() {
                for i in 0..m {
                    for j in 0..m {
                        let ok = bases.iter().zip(&targets).all(|(b, &t)| {
                            let t1 = match *f {
                                Spec::Bin(o, a1, a2) => o.apply(b[a1], b[a2]),
                                Spec::Mad(a1, a2, a3) => mad(b[a1], b[a2], b[a3]),
                            };
                            op.apply(get(b, t1, i), get(b, t1, j)) == t
                        });
                        if ok {
                            return true;
                        }
                    }
                }
            }
            // second op MultiplyAdd
            for i in 0..m {
                for j in 0..m {
                    for k in 0..m {
                        let ok = bases.iter().zip(&targets).all(|(b, &t)| {
                            let t1 = match *f {
                                Spec::Bin(o, a1, a2) => o.apply(b[a1], b[a2]),
                                Spec::Mad(a1, a2, a3) => mad(b[a1], b[a2], b[a3]),
                            };
                            mad(get(b, t1, i), get(b, t1, j), get(b, t1, k)) == t
                        });
                        if ok {
                            return true;
                        }
                    }
                }
            }
        }
        false
    }

    /// Non-affine stages 1/3/5 cannot be computed in <=2 ISA ops (binary alu
    /// ops or a fused multiply_add) *in isolation*. Combined with the exhibited
    /// 3-op form, each is exactly 3 ops when considered alone. NOTE: this is a
    /// *per-stage* (local) bound. It does NOT imply the whole 6-stage hash is
    /// 12 ops minimum -- `cross_stage_fusion_is_bit_exact` shows stage2+stage3
    /// fuse to 3 ops across the boundary (11 mixing ops total), because stage3
    /// fed an affine input becomes two affine branches. This test still
    /// correctly bounds each stage on its own.
    #[test]
    fn nonaffine_stages_need_at_least_three_ops() {
        let mut probes: Vec<u32> = vec![
            0,
            1,
            2,
            3,
            255,
            256,
            0x8000_0000,
            0xFFFF_FFFF,
            0x0F0F_0F0F,
            0xF0F0_F0F0,
            0xAAAA_AAAA,
            0x5555_5555,
            0xDEAD_BEEF,
            0x1234_5678,
            0xCAFE_BABE,
            42,
        ];
        let mut x = 0x9E37_79B9u32;
        for _ in 0..16 {
            x = x.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            probes.push(x);
        }
        for &idx in &[1usize, 3, 5] {
            assert!(
                !two_op_program_exists(idx, &probes),
                "unexpected <=2-op program for non-affine stage {idx}; \
                 the per-stage 3-op bound must be revisited"
            );
        }
    }

    /// The `hashseg` segment decomposition (stage0 .. stage5 as separate
    /// functions with the fused-form constants) recomposes to `myhash`
    /// bit-for-bit — every cut point the fusion search enumerates over is a
    /// true boundary of the real function.
    #[test]
    fn hashseg_composition_matches_myhash() {
        let mut x = 0xA5A5_A5A5u32;
        for i in 0..300_000u32 {
            let a = if i < 8 { i } else { x };
            x = x.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            assert_eq!(
                hashseg::fused_hash(a),
                myhash(a),
                "hashseg composition diverged at a={a:#010x}"
            );
        }
        assert_eq!(hashseg::fused_hash(0xFFFF_FFFF), myhash(0xFFFF_FFFF));
    }

    /// H-003 find: the hash's parity bit (`myhash(a) & 1`, the only bit the
    /// idx update consumes) is computable from the *f23 output* `d` in 2 ops
    /// (one multiply_add + one shr) instead of the 5 ops the value chain
    /// spends from `d` (stage4 madd, stage5's xor/shr/xor, `&1`):
    ///
    ///   parity = (d * 0x80048000 + 0x23628000) >> 31
    ///
    /// Why it must hold universally (not just on sampled inputs): with
    /// e = 9d + C4, parity = e0 ^ e16 ^ C5_0 and e0 = d0 ^ C4_0 = d0 ^ 1, so
    /// parity = d0 ^ e16 (the two odd constants cancel). In
    /// t = d*(2^31 + 9*2^15) + (C4*2^15) mod 2^32, the 2^15-scaled term is
    /// exactly (9d + C4)*2^15 mod 2^32 whose bit31 is e16 (a power-of-two
    /// scaling moves bits without carries), and the 2^31*d term is d0<<31,
    /// which adds into bit 31 with no possible carry from lower bits. Hence
    /// bit31(t) = e16 ^ d0 = parity for EVERY d.
    #[test]
    fn parity_from_d_is_bit_exact() {
        let mut x = 0x1357_9BDFu32;
        for i in 0..1_000_000u32 {
            let a = if i < 16 {
                0x0101_0101u32.wrapping_mul(i)
            } else {
                x
            };
            x = x.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            // d as it occurs in the real chain, plus arbitrary d values.
            let d_real = hashseg::f23(hashseg::stage1(hashseg::stage0(a)));
            assert_eq!(
                hashseg::parity_from_d(d_real),
                myhash(a) & 1,
                "parity_from_d diverged vs myhash at a={a:#010x}"
            );
            let d_any = a;
            assert_eq!(
                hashseg::parity_from_d(d_any),
                hashseg::stage5(hashseg::stage4(d_any)) & 1,
                "parity_from_d diverged at d={d_any:#010x}"
            );
        }
    }

    /// Same trick one stage later: parity from the stage4 output `e` in
    /// 2 ops, `(e * 0x80008000 + 0x80000000) >> 31` (here the constant 2^31
    /// supplies the C5_0 = 1 flip: parity = e0 ^ e16 ^ 1).
    #[test]
    fn parity_from_e_is_bit_exact() {
        let mut x = 0xFEED_F00Du32;
        for i in 0..1_000_000u32 {
            let e = if i < 16 {
                i.wrapping_mul(0x0001_0001)
            } else {
                x
            };
            x = x.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            assert_eq!(
                hashseg::parity_from_e(e),
                hashseg::stage5(e) & 1,
                "parity_from_e diverged at e={e:#010x}"
            );
        }
    }

    /// Cross-stage fusion: stage2 is affine (`b = 33a + C2`) and stage3 is
    /// `(b + C3) ^ (b << 9)` -- both of stage3's branches are integer-affine
    /// in `b`, hence in `a`, so the pair collapses to two multiply_adds of `a`
    /// plus one xor (3 ops), beating the 4 ops (1 madd + 3) they cost apart.
    /// This is what `dag.rs::emit_hash` emits; verified bit-exact here so the
    /// 11-mixing-op hash (arithmetic floor ~819) rests on a checked identity,
    /// not an assertion.
    #[test]
    fn cross_stage_fusion_is_bit_exact() {
        // Derived constants (see the algebra above).
        let c2 = HASH_STAGES[2].1;
        let c3 = HASH_STAGES[3].1;
        let k_p = 1u32.wrapping_add(1 << 5); // 1 + 2^5 = 33 (stage2's multiplier)
        let k_q = k_p.wrapping_mul(1 << 9); // 33 * 2^9 (stage3's <<9 folded in)
        let a_p = c2.wrapping_add(c3); // C2 + C3
        let a_q = c2.wrapping_shl(9); // C2 << 9  (mod 2^32)

        // Recompute myhash with stage2+stage3 replaced by the fused form.
        let cross_fused = |mut a: u32| -> u32 {
            // stage0 (affine): a*(1+2^12) + C0
            a = a
                .wrapping_mul(1u32.wrapping_add(1 << 12))
                .wrapping_add(HASH_STAGES[0].1);
            // stage1 (xor-shift), as-is
            let (o1, v1, o2, o3, v3) = HASH_STAGES[1];
            a = o2.apply(o1.apply(a, v1), o3.apply(a, v3));
            // stage2 + stage3 fused: p = 33a + (C2+C3), q = 33*512*a + C2<<9
            let p = a.wrapping_mul(k_p).wrapping_add(a_p);
            let q = a.wrapping_mul(k_q).wrapping_add(a_q);
            a = p ^ q;
            // stage4 (affine): a*(1+2^3) + C4
            a = a
                .wrapping_mul(1u32.wrapping_add(1 << 3))
                .wrapping_add(HASH_STAGES[4].1);
            // stage5 (xor-shift), as-is
            let (o1, v1, o2, o3, v3) = HASH_STAGES[5];
            o2.apply(o1.apply(a, v1), o3.apply(a, v3))
        };

        let mut samples: Vec<u32> = vec![
            0,
            1,
            2,
            255,
            1 << 31,
            0xFFFF_FFFF,
            c2,
            c3,
            0xDEAD_BEEF,
            0xCAFE_BABE,
        ];
        let mut x = 0x1234_5678u32;
        for _ in 0..500_000 {
            x = x.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            samples.push(x);
        }
        for &a in &samples {
            assert_eq!(
                cross_fused(a),
                myhash(a),
                "cross-stage fusion diverged at {a:#010x}"
            );
        }
    }
}
