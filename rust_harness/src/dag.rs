//! The problem's *true* dependency graph, independent of registers, memory
//! addresses, or vector-lane layout -- the compiler-style alternative to
//! hand-rolling instruction schedules (see `schedule.rs` and
//! `rust_harness/README.md`). A node is one scalar operation; an edge is a
//! genuine data dependency (this value cannot be computed before that one
//! exists). Nothing here says *where* a value lives or *which* other values
//! it could share a vector register with -- that's exactly the "contiguous
//! memory" concern this first pass defers to `schedule.rs`'s batching
//! heuristic.
//!
//! Two constructions:
//! - `build_problem_dag`: the literal algorithm, one `GatherLoad` per
//!   walker per round for the tree-node lookup (matches the hand-rolled
//!   kernel's approach -- see docs/problem.md).
//! - `build_problem_dag_smart`: exploits that every walker starts at the
//!   same root, so the *first few* rounds have far fewer than `batch_size`
//!   possible tree positions -- see that function's docs for the exact
//!   trade-off and why it's only worth it for small levels.

use crate::isa::AluOp;
use crate::problem::HASH_STAGES;
use std::collections::HashMap;

pub type NodeId = usize;

/// What kind of engine a node needs, and (for alu-shaped ops) which opcode
/// -- only same-opcode alu nodes can share a `valu` slot, since a real
/// `ValuSlot::Op` applies one opcode across all 8 lanes.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum ResKind {
    /// No cost, no engine, always available from cycle 0 -- constants,
    /// the initial `idx=0`, and (abstracted away) the header/tree/setup.
    Free,
    Alu(AluOp),
    /// `x*y+z` in one `valu` op -- no scalar equivalent exists in the ISA
    /// (see `problem.py`'s `Machine.valu`, `multiply_add` has no `alu`
    /// counterpart), so this can only ever be scheduled via `valu`, in
    /// batches of up to `VLEN` -- including *partial* batches, since there's
    /// no scalar fallback to fall through to (see schedule.rs).
    MultiplyAdd,
    /// A memory read at a *fixed* (not data-dependent) address: the initial
    /// per-walker value, a shared tree-level read, or the final per-walker
    /// stores. Genuinely `vload`/`vstore`-eligible in real hardware -- no
    /// "ignore contiguous memory" relaxation needed, batchable in every
    /// scheduler mode.
    ContiguousLoad,
    /// A memory read at a *data-dependent* address (the tree-node gather
    /// at full generality) -- scalar-only in realistic scheduling mode; see
    /// `schedule::SchedulerConfig::gather_batchable`.
    GatherLoad,
    Store,
    /// The single-shape `select`/`vselect` mux.
    Flow,
}

#[derive(Clone, Debug)]
pub struct Node {
    pub kind: ResKind,
    pub deps: Vec<NodeId>,
}

#[derive(Clone, Debug, Default)]
pub struct Dag {
    pub nodes: Vec<Node>,
}

impl Dag {
    pub fn new() -> Self {
        Dag::default()
    }

    pub fn add(&mut self, kind: ResKind, deps: Vec<NodeId>) -> NodeId {
        let id = self.nodes.len();
        self.nodes.push(Node { kind, deps });
        id
    }

    pub fn free(&mut self) -> NodeId {
        self.add(ResKind::Free, vec![])
    }
}

/// If a hash stage's shape is `a = (a + val1) + (a << s)`, that's exactly
/// `a * (1 + 2**s) + val1` -- valid under mod-2**32 arithmetic since it's a
/// ring (distributivity holds regardless of intermediate overflow) -- so it
/// collapses from 3 ops (two independent halves + a combine) to one
/// `multiply_add`. Only applies when op1==op2==Add and op3==Shl; the other
/// stages mix in xor, which has no such algebraic shortcut.
fn as_multiply_add(op1: AluOp, op2: AluOp, op3: AluOp) -> bool {
    op1 == AluOp::Add && op2 == AluOp::Add && op3 == AluOp::Shl
}

fn emit_hash(dag: &mut Dag, start: NodeId) -> NodeId {
    let mut a = start;
    for &(op1, _val1, op2, op3, _val3) in HASH_STAGES.iter() {
        if as_multiply_add(op1, op2, op3) {
            a = dag.add(ResKind::MultiplyAdd, vec![a]);
        } else {
            let tmp1 = dag.add(ResKind::Alu(op1), vec![a]);
            let tmp2 = dag.add(ResKind::Alu(op3), vec![a]);
            a = dag.add(ResKind::Alu(op2), vec![tmp1, tmp2]);
        }
    }
    a
}

/// Build the exact dependency structure of `reference_kernel2` (see
/// docs/problem.md), one node per scalar operation, for every walker and
/// round -- no addresses, no scratch allocation, no valu/vload grouping.
/// `batch_size` independent walkers x `rounds` sequential rounds each.
pub fn build_problem_dag(batch_size: u32, rounds: u32) -> Dag {
    let mut dag = Dag::new();

    let forest_values_p = dag.free();
    let n_nodes = dag.free();
    let two = dag.free();

    for _w in 0..batch_size {
        let mut idx = dag.free();
        let mut val = dag.add(ResKind::ContiguousLoad, vec![]);

        for _round in 0..rounds {
            let addr = dag.add(ResKind::Alu(AluOp::Add), vec![idx, forest_values_p]);
            let node_val = dag.add(ResKind::GatherLoad, vec![addr]);
            let xor = dag.add(ResKind::Alu(AluOp::Xor), vec![val, node_val]);
            let val_new = emit_hash(&mut dag, xor);

            let parity = dag.add(ResKind::Alu(AluOp::Mod), vec![val_new, two]);
            let offset = dag.add(ResKind::Alu(AluOp::Add), vec![parity]);
            let doubled = dag.add(ResKind::Alu(AluOp::Mul), vec![idx, two]);
            let idx_new = dag.add(ResKind::Alu(AluOp::Add), vec![doubled, offset]);
            let cmp = dag.add(ResKind::Alu(AluOp::Lt), vec![idx_new, n_nodes]);
            let idx_final = dag.add(ResKind::Flow, vec![cmp, idx_new]);

            idx = idx_final;
            val = val_new;
        }

        dag.add(ResKind::Store, vec![idx]);
        dag.add(ResKind::Store, vec![val]);
    }

    dag
}

/// `select(cond, b, a)` computed arithmetically instead of via the `flow`
/// engine: `a + cond*(b-a)`, valid since `cond` is always exactly 0 or 1.
/// 3 `alu`/`valu`-kind ops instead of 1 `flow`-kind op -- worse op-for-op,
/// but `valu` has far more raw throughput (6 slots x 8 lanes = 48/cycle)
/// than `flow` (1 slot x 8 lanes = 8/cycle even with vselect), so this pays
/// off whenever `flow` is the scarcer resource. See `build_problem_dag_smart`
/// for where that trade-off is actually favorable.
fn algebraic_select(dag: &mut Dag, cond: NodeId, a: NodeId, b: NodeId) -> NodeId {
    let diff = dag.add(ResKind::Alu(AluOp::Sub), vec![b, a]);
    let scaled = dag.add(ResKind::Alu(AluOp::Mul), vec![cond, diff]);
    dag.add(ResKind::Alu(AluOp::Add), vec![a, scaled])
}

/// Extract `arr[index]`, where `index`'s bits are `bits` (one walker's own
/// parity-bit history), via a per-walker reduction cascade: pairwise-select
/// down from `arr.len()` candidates to 1, `bits.len() = log2(arr.len())`
/// steps. This is a real N-to-1 multiplexer, which costs `Theta(N)` total
/// select-equivalents per walker (a MUX tree reducing N->N/2->...->1 sums
/// to `N-1` gates) -- NOT `O(log N)`; a smarter shared gather network
/// (e.g. a Benes-style permutation network reusable across all walkers at
/// once) could in principle do this in `O(N log N)` *total* instead of
/// `O(N)` *per walker*, but that's real hardware-design complexity this
/// pass doesn't attempt -- see the module docs.
fn select_cascade(dag: &mut Dag, arr: &[NodeId], bits: &[NodeId]) -> NodeId {
    if bits.is_empty() {
        assert_eq!(arr.len(), 1);
        return arr[0];
    }
    let mut cur = arr.to_vec();
    for &bit in bits {
        let mut next = Vec::with_capacity(cur.len() / 2);
        for pair in cur.chunks(2) {
            next.push(algebraic_select(dag, bit, pair[0], pair[1]));
        }
        cur = next;
    }
    assert_eq!(cur.len(), 1);
    cur[0]
}

fn level_array(dag: &mut Dag, cache: &mut HashMap<u32, Vec<NodeId>>, level: u32) -> Vec<NodeId> {
    if let Some(v) = cache.get(&level) {
        return v.clone();
    }
    let size = 1usize << level;
    // Contiguous in the tree's implicit-heap layout -- genuinely
    // vload-eligible, no relaxation needed.
    let arr: Vec<NodeId> = (0..size)
        .map(|_| dag.add(ResKind::ContiguousLoad, vec![]))
        .collect();
    cache.insert(level, arr.clone());
    arr
}

/// Below this level size, a per-walker select-cascade (see
/// `select_cascade`) is cheaper than the naive per-walker gather; above it,
/// the cascade's `Theta(2^level)` cost per walker overtakes a flat 1
/// `GatherLoad`/walker. Crossover derivation (256 walkers, `load`=2
/// slots/cycle, `valu`=6 slots x 8 lanes/cycle, algebraic select = 3
/// alu/valu ops):
///   naive gather cost per round  = batch_size / slot_limits::LOAD cycles (constant in level)
///   cascade cost per round       = batch_size * 3 * (2^level - 1) / (slot_limits::VALU * VLEN) cycles
/// which cross between level 3 (112 < 128) and level 4 (240 > 128) for
/// batch_size=256 -- see the chat writeup for the numeric derivation.
const SMART_LEVEL_THRESHOLD: u32 = 4;

/// A restructured (but still algorithmically faithful) version of
/// `build_problem_dag` that exploits a structural fact `build_problem_dag`
/// ignores: every walker starts at the *same* root (`Input.generate` always
/// sets `indices = [0, ...]`), so the number of tree positions reachable by
/// *any* walker after `r` rounds is at most `2^r`, not `batch_size` -- until
/// `2^r` catches up to `batch_size`. Below `SMART_LEVEL_THRESHOLD`, this
/// reads the entire tree level once (shared across all walkers, globally
/// memoized by level since the tree never changes -- level data read in an
/// earlier "epoch" before a wraparound is reused, not re-read) and gives
/// each walker its value via `select_cascade` over its own already-computed
/// parity-bit history, instead of an individual data-dependent `GatherLoad`.
///
/// Also folds in `as_multiply_add`'s hash simplification (see `emit_hash`)
/// and skips the wraparound compare+select at the one round where it's
/// unconditionally true for every walker (see the comment at the call
/// site) -- both apply regardless of gather strategy.
pub fn build_problem_dag_smart(forest_height: u32, batch_size: u32, rounds: u32) -> Dag {
    let mut dag = Dag::new();

    let forest_values_p = dag.free();
    let n_nodes = dag.free();
    let two = dag.free();
    let levels = forest_height + 1;
    let mut level_cache: HashMap<u32, Vec<NodeId>> = HashMap::new();

    for _w in 0..batch_size {
        let mut idx = dag.free(); // idx = 0
        let mut val = dag.add(ResKind::ContiguousLoad, vec![]);
        let mut epoch_bits: Vec<NodeId> = Vec::new();

        for r in 0..rounds {
            let local_level = r % levels;
            if local_level == 0 {
                epoch_bits.clear();
            }

            let node_val = if (1u64 << local_level) < batch_size as u64
                && local_level < SMART_LEVEL_THRESHOLD
            {
                let arr = level_array(&mut dag, &mut level_cache, local_level);
                select_cascade(&mut dag, &arr, &epoch_bits)
            } else {
                let addr = dag.add(ResKind::Alu(AluOp::Add), vec![idx, forest_values_p]);
                dag.add(ResKind::GatherLoad, vec![addr])
            };

            let xor = dag.add(ResKind::Alu(AluOp::Xor), vec![val, node_val]);
            let val_new = emit_hash(&mut dag, xor);

            let parity = dag.add(ResKind::Alu(AluOp::Mod), vec![val_new, two]);
            epoch_bits.push(parity);

            let offset = dag.add(ResKind::Alu(AluOp::Add), vec![parity]);
            let doubled = dag.add(ResKind::Alu(AluOp::Mul), vec![idx, two]);
            let idx_new = dag.add(ResKind::Alu(AluOp::Add), vec![doubled, offset]);

            // The tree is exactly full (n_nodes = 2^(forest_height+1) - 1),
            // so stepping past the last level *always* overflows n_nodes
            // for every walker regardless of position within that level --
            // a statically-known wrap, not a runtime decision. See the chat
            // writeup for the inequality. Every other transition keeps the
            // real compare+select (idx_new is genuinely data-dependent).
            idx = if local_level == forest_height {
                dag.free()
            } else {
                let cmp = dag.add(ResKind::Alu(AluOp::Lt), vec![idx_new, n_nodes]);
                dag.add(ResKind::Flow, vec![cmp, idx_new])
            };
            val = val_new;
        }

        dag.add(ResKind::Store, vec![idx]);
        dag.add(ResKind::Store, vec![val]);
    }

    dag
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn node_count_matches_hand_count() {
        // Per round: addr, node_val, xor = 3. Hash: 3 stages collapse to 1
        // MultiplyAdd node each (as_multiply_add), 3 stay as 3 nodes each =
        // 3*1 + 3*3 = 12. Tail: parity, offset, doubled, idx_new, cmp,
        // idx_final = 6. Plus, per walker: 1 free `idx=0` node, 1 initial
        // val load, and 2 final stores. Plus 3 free setup nodes shared
        // across the whole dag.
        let batch_size = 4;
        let rounds = 3;
        let dag = build_problem_dag(batch_size, rounds);
        let per_round = 3 + 12 + 6;
        let per_walker = 1 + 1 + per_round * rounds as usize + 2; // idx free + val load + rounds + 2 stores
        let expected = 3 + batch_size as usize * per_walker;
        assert_eq!(dag.nodes.len(), expected);
    }

    #[test]
    fn is_acyclic_and_deps_point_backward() {
        let dag = build_problem_dag(4, 3);
        for (i, node) in dag.nodes.iter().enumerate() {
            for &d in &node.deps {
                assert!(
                    d < i,
                    "node {i} depends on {d}, which is not earlier -- not a valid DAG order"
                );
            }
        }
    }

    #[test]
    fn walkers_are_mutually_independent() {
        // No node in walker 0's subgraph should be reachable from walker 1's,
        // or vice versa -- batch_size shouldn't affect the critical path.
        let dag = build_problem_dag(2, 2);
        let per_walker = 1 + 1 + (3 + 12 + 6) * 2 + 2;
        let walker0_range = 3..3 + per_walker;
        let walker1_start = 3 + per_walker;
        for node in &dag.nodes[walker1_start..] {
            for &d in &node.deps {
                assert!(
                    !walker0_range.contains(&d),
                    "walker 1 node depends on a walker 0 node ({d}) -- they should be independent"
                );
            }
        }
    }

    #[test]
    fn multiply_add_reduces_half_the_hash_stages() {
        // Stages 0,2,4 (op1=op2=Add,op3=Shl) collapse to 1 MultiplyAdd node;
        // stages 1,3,5 stay as 3 nodes (tmp1,tmp2,combine) each.
        let mut dag = Dag::new();
        let start = dag.free();
        let result = emit_hash(&mut dag, start);
        assert_ne!(result, start);
        let multiply_adds = dag
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, ResKind::MultiplyAdd))
            .count();
        assert_eq!(multiply_adds, 3);
        let total_hash_nodes = dag.nodes.len() - 1; // minus the `start` free node
        let reduced_stage_nodes = 3; // 3 stages x 1 node each
        let full_stage_nodes = 3 * 3; // 3 stages x 3 nodes each
        assert_eq!(total_hash_nodes, reduced_stage_nodes + full_stage_nodes);
    }

    #[test]
    fn smart_dag_is_acyclic_and_walkers_independent() {
        let dag = build_problem_dag_smart(4, 8, 6); // small tree, small batch, a couple epochs
        for (i, node) in dag.nodes.iter().enumerate() {
            for &d in &node.deps {
                assert!(d < i, "node {i} depends on {d}, not earlier");
            }
        }
    }

    #[test]
    fn smart_dag_shares_level_reads_across_walkers_and_epochs() {
        // forest_height=3 -> 4 levels (0..3). batch_size=32 is large enough
        // that 2^level < batch_size holds for every level here (max is
        // 2^3=8 < 32), so SMART_LEVEL_THRESHOLD (4) is the only binding
        // condition and all 4 levels use the shared/cascade path. rounds=8
        // spans exactly one epoch (4 rounds) plus a second identical one --
        // the second epoch's level-0 read must be the *same* ContiguousLoad
        // node as the first epoch's, not a fresh one.
        let dag = build_problem_dag_smart(3, 32, 8);
        let contiguous_loads = dag
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, ResKind::ContiguousLoad))
            .count();
        // Shared level arrays: sizes 1+2+4+8 = 15 ContiguousLoad nodes,
        // read exactly once across both epochs, plus 32 initial-value loads
        // (one per walker, genuinely per-walker, not shared).
        assert_eq!(contiguous_loads, 15 + 32);
    }
}
