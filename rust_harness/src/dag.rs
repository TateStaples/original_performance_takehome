//! The problem's *true* dependency graph, independent of registers, memory
//! addresses, or vector-lane layout -- the compiler-style alternative to
//! hand-rolling instruction schedules (see `schedule.rs` and
//! `rust_harness/README.md`). A node is one scalar operation; an edge is a
//! genuine data dependency (this value cannot be computed before that one
//! exists). Nothing here says *where* a value lives or *which* other values
//! it could share a vector register with -- that's exactly the "contiguous
//! memory" concern this first pass defers to `schedule.rs`'s batching
//! heuristic.

use crate::isa::AluOp;
use crate::problem::HASH_STAGES;

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
    /// A memory read at a data-dependent address (the tree-node gather) or
    /// a fixed one (the initial value load) -- see `Dag` docs on why this
    /// is scalar-only in the realistic scheduling mode.
    Load,
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

/// Build the exact dependency structure of `reference_kernel2` (see
/// docs/problem.md), one node per scalar operation, for every walker and
/// round -- no addresses, no scratch allocation, no valu/vload grouping.
/// `batch_size` independent walkers x `rounds` sequential rounds each.
pub fn build_problem_dag(batch_size: u32, rounds: u32) -> Dag {
    let mut dag = Dag::new();

    // Abstracts "the header and tree are loaded" -- available from cycle 0.
    let forest_values_p = dag.free();
    let n_nodes = dag.free();
    let two = dag.free();

    for _w in 0..batch_size {
        // indices always start at 0 (Input.generate) -- a build-time
        // constant, not a memory read.
        let mut idx = dag.free();
        // Initial values are genuinely random per walker -- a real memory
        // read, but at a fixed (not data-dependent) address.
        let mut val = dag.add(ResKind::Load, vec![]);

        for _round in 0..rounds {
            let addr = dag.add(ResKind::Alu(AluOp::Add), vec![idx, forest_values_p]);
            let node_val = dag.add(ResKind::Load, vec![addr]);
            let mut a = dag.add(ResKind::Alu(AluOp::Xor), vec![val, node_val]);

            for &(op1, _val1, op2, op3, _val3) in HASH_STAGES.iter() {
                // val1/val3 are compile-time constants -- no data dependency,
                // so they don't appear as `deps` (a Free node would be a
                // no-op edge; omitting it is equivalent and lighter).
                let tmp1 = dag.add(ResKind::Alu(op1), vec![a]);
                let tmp2 = dag.add(ResKind::Alu(op3), vec![a]);
                a = dag.add(ResKind::Alu(op2), vec![tmp1, tmp2]);
            }
            let val_new = a;

            // idx_new = 2*idx + (1 + val_new%2); "doubled" only depends on
            // idx (available since the *start* of this round) so a good
            // scheduler should discover it can run in parallel with the
            // entire hash chain on its own, with no help from us.
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn node_count_matches_hand_count() {
        // Per round: addr, node_val, xor, 18 hash ops, parity, offset,
        // doubled, idx_new, cmp, idx_final = 27. Plus, per walker: 1 free
        // `idx=0` node, 1 initial val load, and 2 final stores. Plus 3 free
        // setup nodes shared across the whole dag.
        let batch_size = 4;
        let rounds = 3;
        let dag = build_problem_dag(batch_size, rounds);
        let per_round = 3 + 18 + 6; // addr+node_val+xor=3, hash=18, tail=6
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
        let per_walker = 1 + 1 + (3 + 18 + 6) * 2 + 2;
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
}
