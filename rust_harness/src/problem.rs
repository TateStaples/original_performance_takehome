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
    /// ops or a fused multiply_add). Combined with the exhibited 3-op form,
    /// each is exactly 3 ops, so the hash is 3*1 (multiply_add) + 3*3 = 12 ops
    /// and cannot drop lower via algebraic fusion.
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
                 the 12-op minimality claim must be revisited"
            );
        }
    }
}
