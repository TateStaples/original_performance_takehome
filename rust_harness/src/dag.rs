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
pub enum NodeKind {
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
    pub kind: NodeKind,
    pub deps: Vec<NodeId>,
}

/// The *purpose* of a node, orthogonal to which engine it uses (`NodeKind`).
/// Lets us ask "what fraction of the arithmetic is the hash vs. the index
/// bookkeeping vs. getting the tree value to the walker" -- see the
/// `breakdown` binary.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Default)]
pub enum NodeCategory {
    /// Shared constants / setup, initial per-walker value load.
    #[default]
    Setup,
    /// Computing/mixing the hashed value: the `val ^ node_val` fold-in and
    /// every `emit_hash` op.
    Hash,
    /// The index recurrence: parity, `2*idx + 1 + parity`, wraparound.
    Idx,
    /// Getting `node_val = tree[idx]` to the walker: the gather address + load,
    /// or (smart dag) the shared level read + the select cascade that routes
    /// it. This is the "gather vs. routing" work.
    Routing,
    /// Final per-walker stores.
    Store,
}

#[derive(Clone, Debug, Default)]
pub struct Dag {
    pub nodes: Vec<Node>,
    /// Walker index that produced each node (parallel to `nodes`).
    /// `u32::MAX` for nodes owned by no single walker (shared setup
    /// constants, shared level arrays). Pure metadata; lets a
    /// register-pressure-aware scheduler group work by walker without
    /// re-deriving ownership from node indices.
    pub walker_of: Vec<u32>,
    /// Purpose of each node (parallel to `nodes`); see `NodeCategory`.
    pub category: Vec<NodeCategory>,
    /// Walker currently being emitted; `add` tags new nodes with it.
    /// `u32::MAX` outside any walker loop.
    cur_walker: u32,
    /// Purpose currently being emitted; `add` tags new nodes with it.
    cur_category: NodeCategory,
}

impl Dag {
    pub fn new() -> Self {
        Dag {
            nodes: Vec::new(),
            walker_of: Vec::new(),
            category: Vec::new(),
            cur_walker: u32::MAX,
            cur_category: NodeCategory::Setup,
        }
    }

    pub fn add(&mut self, kind: NodeKind, deps: Vec<NodeId>) -> NodeId {
        let id = self.nodes.len();
        self.nodes.push(Node { kind, deps });
        self.walker_of.push(self.cur_walker);
        self.category.push(self.cur_category);
        id
    }

    pub fn free(&mut self) -> NodeId {
        self.add(NodeKind::Free, vec![])
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

/// A stage `a = (a + v1) ^ (a << s)` -- BOTH branches integer-affine in `a`
/// (`a + v1` and `a << s = a * 2^s`), combined by xor. When such a stage is
/// fed by an *affine* stage (so its input is itself affine in an earlier
/// value `a0`), the pair composes to two multiply_adds of `a0` plus one xor,
/// beating the (1 madd + 3 ops) the two stages cost separately (see
/// `emit_hash`). This is the cross-stage reduction the per-stage minimality
/// proof (problem.rs) does not see.
fn as_affine_xor_shift(op1: AluOp, op2: AluOp, op3: AluOp) -> bool {
    op1 == AluOp::Add && op2 == AluOp::Xor && op3 == AluOp::Shl
}

fn emit_hash(dag: &mut Dag, start: NodeId) -> NodeId {
    let mut a = start;
    let mut i = 0;
    while i < HASH_STAGES.len() {
        let (op1, _v1, op2, op3, _v3) = HASH_STAGES[i];
        // Cross-stage fusion: an affine stage immediately followed by an
        // `(a+v)^(a<<s)` stage. Both of the next stage's branches are affine
        // in the affine stage's output, hence affine in *this* stage's input
        // `a`, so each branch collapses to one multiply_add of `a`:
        //   p = a*(K1*Knext) + ...      q = a*(K1*2^s) + ...      out = p ^ q
        // i.e. 2 madd + 1 xor for the *pair*, vs. 1 madd (this stage) + 3 ops
        // (next stage) = 4 done separately. Verified bit-exact in problem.rs
        // (`cross_stage_fusion_is_bit_exact`). Only stage2->stage3 matches
        // here; it drops the hash from 13 to 12 ops/eval.
        if as_multiply_add(op1, op2, op3) && i + 1 < HASH_STAGES.len() {
            let (n1, _nv1, n2, n3, _nv3) = HASH_STAGES[i + 1];
            if as_affine_xor_shift(n1, n2, n3) {
                let p = dag.add(NodeKind::MultiplyAdd, vec![a]);
                let q = dag.add(NodeKind::MultiplyAdd, vec![a]);
                a = dag.add(NodeKind::Alu(n2), vec![p, q]); // n2 == Xor
                i += 2;
                continue;
            }
        }
        if as_multiply_add(op1, op2, op3) {
            a = dag.add(NodeKind::MultiplyAdd, vec![a]);
        } else {
            let left = dag.add(NodeKind::Alu(op1), vec![a]);
            let right = dag.add(NodeKind::Alu(op3), vec![a]);
            a = dag.add(NodeKind::Alu(op2), vec![left, right]);
        }
        i += 1;
    }
    a
}

/// Build the exact dependency structure of `reference_kernel2` (see
/// docs/problem.md), one node per scalar operation, for every walker and
/// round -- no addresses, no scratch allocation, no valu/vload grouping.
/// `batch_size` independent walkers x `rounds` sequential rounds each.
pub fn build_problem_dag(forest_height: u32, batch_size: u32, rounds: u32) -> Dag {
    let mut dag = Dag::new();

    let forest_values_p = dag.free();
    let n_nodes = dag.free();
    let two = dag.free();
    let levels = forest_height + 1;

    for walker in 0..batch_size {
        dag.cur_walker = walker;
        dag.cur_category = NodeCategory::Setup;
        let mut idx = dag.free();
        let mut val = dag.add(NodeKind::ContiguousLoad, vec![]);

        for round in 0..rounds {
            let local_level = round % levels;
            dag.cur_category = NodeCategory::Routing;
            let addr = dag.add(NodeKind::Alu(AluOp::Add), vec![idx, forest_values_p]);
            let node_val = dag.add(NodeKind::GatherLoad, vec![addr]);
            dag.cur_category = NodeCategory::Hash;
            let xor = dag.add(NodeKind::Alu(AluOp::Xor), vec![val, node_val]);
            let val_new = emit_hash(&mut dag, xor);

            dag.cur_category = NodeCategory::Idx;
            let parity = dag.add(NodeKind::Alu(AluOp::Mod), vec![val_new, two]);
            let offset = dag.add(NodeKind::Alu(AluOp::Add), vec![parity]);
            let doubled = dag.add(NodeKind::Alu(AluOp::Mul), vec![idx, two]);
            let idx_new = dag.add(NodeKind::Alu(AluOp::Add), vec![doubled, offset]);

            // The tree is exactly full (n_nodes = 2^(forest_height+1) - 1) and
            // every walker starts at the shared root, so the level of `idx` at
            // round r is deterministically r % levels. Stepping past the
            // deepest level (local_level == forest_height) always overflows
            // n_nodes for every walker regardless of its position within that
            // level -- a statically-known wrap, so it folds to the constant
            // idx = 0. Every other round keeps the genuine compare+select
            // (idx_new is a runtime, data-dependent value). Mirrors
            // build_problem_dag_smart's fold at the same boundary.
            idx = if local_level == forest_height {
                dag.free()
            } else {
                let cmp = dag.add(NodeKind::Alu(AluOp::Lt), vec![idx_new, n_nodes]);
                dag.add(NodeKind::Flow, vec![cmp, idx_new])
            };
            val = val_new;
        }

        dag.cur_category = NodeCategory::Store;
        dag.add(NodeKind::Store, vec![idx]);
        dag.add(NodeKind::Store, vec![val]);
    }

    dag.cur_walker = u32::MAX;
    dag.cur_category = NodeCategory::Setup;
    dag
}

/// How a 2:1 select in the smart-DAG cascade is lowered. `Algebraic` = 3
/// alu/valu ops (see `algebraic_select`); `Flow` = one real 8-wide `vselect`
/// (`NodeKind::Flow`, 1 flow slot/cycle x VLEN lanes). Flow is the UNDER-used
/// engine in smart realistic mode (only the idx-wraparound selects run on it,
/// ~24-31% busy), while valu is the bind (~99%), so `Flow` trades saturated
/// 48-lane/cycle valu throughput for idle 8-lane/cycle flow throughput. That
/// pays whenever flow still has headroom -- see the crossover note on
/// `build_problem_dag_smart_with`.
///
/// CAVEAT (measured): this only wins when valu is a hard bind. Once the
/// scheduler's alu/valu overflow pass (see schedule.rs) is in play, it
/// spreads *algebraic* selects flexibly across the wide alu+valu throughput,
/// whereas `Flow` pins them to the single flow slot -- which then becomes the
/// near-bind. So with balancing on, `Algebraic` is actually faster, and it is
/// the default. `Flow` is kept as an option (and for the isolated analysis).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SelectImpl {
    Algebraic,
    Flow,
}

/// `select(cond, b, a)` computed arithmetically instead of via the `flow`
/// engine: `a + cond*(b-a)`, valid since `cond` is always exactly 0 or 1.
/// 3 `alu`/`valu`-kind ops instead of 1 `flow`-kind op -- worse op-for-op,
/// but `valu` has far more raw throughput (6 slots x 8 lanes = 48/cycle)
/// than `flow` (1 slot x 8 lanes = 8/cycle even with vselect), so this pays
/// off whenever `flow` is the scarcer resource. See `build_problem_dag_smart`
/// for where that trade-off is actually favorable.
fn algebraic_select(dag: &mut Dag, cond: NodeId, a: NodeId, b: NodeId) -> NodeId {
    let diff = dag.add(NodeKind::Alu(AluOp::Sub), vec![b, a]);
    let scaled = dag.add(NodeKind::Alu(AluOp::Mul), vec![cond, diff]);
    dag.add(NodeKind::Alu(AluOp::Add), vec![a, scaled])
}

/// `select(cond, a, b)` via the flow engine's real 8-wide mux: 1
/// `NodeKind::Flow` node instead of `algebraic_select`'s 3. Deps are
/// `[cond, a, b]`; the scheduler already models Flow as 1 slot/cycle x VLEN
/// lanes (see schedule.rs), so no scheduler change is needed. NOTE for any
/// future lowering to `isa::FlowSlot::VSelect` (`dest = a if cond!=0 else b`):
/// `algebraic_select(dag, cond, a, b)` computes `a + cond*(b-a) = (cond? b : a)`,
/// so a faithful VSelect must swap operands (`VSelect{cond, a: b, b: a}`). The
/// abstract DAG only tracks deps + NodeKind, so operand order here does not
/// affect the scheduler's cycle count.
fn flow_select(dag: &mut Dag, cond: NodeId, a: NodeId, b: NodeId) -> NodeId {
    dag.add(NodeKind::Flow, vec![cond, a, b])
}

/// Extract `candidates[index]`, where `index`'s bits are `bits` (one walker's own
/// parity-bit history), via a per-walker reduction cascade: pairwise-select
/// down from `candidates.len()` candidates to 1, `bits.len() = log2(candidates.len())`
/// steps. This is a real N-to-1 multiplexer, which costs `Theta(N)` total
/// select-equivalents per walker (a MUX tree reducing N->N/2->...->1 sums
/// to `N-1` gates) -- NOT `O(log N)`; a smarter shared gather network
/// (e.g. a Benes-style permutation network reusable across all walkers at
/// once) could in principle do this in `O(N log N)` *total* instead of
/// `O(N)` *per walker*, but that's real hardware-design complexity this
/// pass doesn't attempt -- see the module docs.
fn select_cascade(
    dag: &mut Dag,
    candidates: &[NodeId],
    bits: &[NodeId],
    select_impl: SelectImpl,
) -> NodeId {
    if bits.is_empty() {
        assert_eq!(candidates.len(), 1);
        return candidates[0];
    }
    let mut cur = candidates.to_vec();
    for &bit in bits {
        let mut next = Vec::with_capacity(cur.len() / 2);
        for pair in cur.chunks(2) {
            let selected = match select_impl {
                SelectImpl::Algebraic => algebraic_select(dag, bit, pair[0], pair[1]),
                SelectImpl::Flow => flow_select(dag, bit, pair[0], pair[1]),
            };
            next.push(selected);
        }
        cur = next;
    }
    assert_eq!(cur.len(), 1);
    cur[0]
}

fn level_array(dag: &mut Dag, cache: &mut HashMap<u32, Vec<NodeId>>, level: u32) -> Vec<NodeId> {
    if let Some(cached_values) = cache.get(&level) {
        return cached_values.clone();
    }
    let size = 1usize << level;
    // Contiguous in the tree's implicit-heap layout -- genuinely
    // vload-eligible, no relaxation needed. Tagged as shared (cur_walker =
    // MAX) even though this runs inside a walker iteration: the level array
    // is read once and reused across all walkers/epochs, so it belongs to no
    // single walker's window (see SchedulerConfig::walker_window).
    let saved_walker = dag.cur_walker;
    dag.cur_walker = u32::MAX;
    let level_values: Vec<NodeId> = (0..size)
        .map(|_| dag.add(NodeKind::ContiguousLoad, vec![]))
        .collect();
    dag.cur_walker = saved_walker;
    cache.insert(level, level_values.clone());
    level_values
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
    build_problem_dag_smart_with(forest_height, batch_size, rounds, SelectImpl::Algebraic)
}

/// As [`build_problem_dag_smart`], but chooses how `select_cascade` lowers its
/// 2:1 muxes. `SelectImpl::Flow` offloads them onto the idle flow engine.
/// Uses the default `SMART_LEVEL_THRESHOLD`; see
/// [`build_problem_dag_smart_tuned`] to vary how many levels are shared.
pub fn build_problem_dag_smart_with(
    forest_height: u32,
    batch_size: u32,
    rounds: u32,
    select_impl: SelectImpl,
) -> Dag {
    build_problem_dag_smart_tuned(
        forest_height,
        batch_size,
        rounds,
        select_impl,
        SMART_LEVEL_THRESHOLD,
    )
}

/// As [`build_problem_dag_smart_with`], but with a tunable `share_threshold`:
/// levels `0..share_threshold` (that also have fewer than `batch_size`
/// positions) are read once contiguously and routed to each walker with a
/// `select_cascade`; deeper levels stay per-walker `GatherLoad`. This is the
/// gather-vs-cascade dial.
///
/// The trade is fundamental to this ISA: sharing level `L` replaces
/// `batch_size` data-dependent loads (the gather floor `batch_size/LOAD`) with
/// a per-walker cascade of `2^L - 1` lanewise selects. There is NO cheaper
/// routing than the cascade here -- a butterfly/Beneš network would need a
/// cross-lane shuffle, and the only cross-lane primitive in the ISA is
/// `Broadcast` (scalar->all lanes); everything else (`Op`, `MultiplyAdd`,
/// `VSelect`) is strictly lanewise, so the only way to move a value between
/// lanes is a memory round-trip (store+load) -- i.e. back through the load
/// port, which is the gather we were trying to avoid. So raising the threshold
/// drives the *gather floor* down (fewer loads) but the *arithmetic floor* up
/// (`O(2^L)` selects/walker), and the crossover is where they meet -- see the
/// `frontier` binary for the measured sweep.
pub fn build_problem_dag_smart_tuned(
    forest_height: u32,
    batch_size: u32,
    rounds: u32,
    select_impl: SelectImpl,
    share_threshold: u32,
) -> Dag {
    let mut dag = Dag::new();

    let forest_values_p = dag.free();
    let n_nodes = dag.free();
    let two = dag.free();
    let levels = forest_height + 1;
    let mut level_cache: HashMap<u32, Vec<NodeId>> = HashMap::new();

    for walker in 0..batch_size {
        dag.cur_walker = walker;
        dag.cur_category = NodeCategory::Setup;
        let mut idx = dag.free(); // idx = 0
        let mut val = dag.add(NodeKind::ContiguousLoad, vec![]);
        let mut epoch_bits: Vec<NodeId> = Vec::new();

        for round in 0..rounds {
            let local_level = round % levels;
            if local_level == 0 {
                epoch_bits.clear();
            }

            dag.cur_category = NodeCategory::Routing;
            let node_val =
                if (1u64 << local_level) < batch_size as u64 && local_level < share_threshold {
                    let level_values = level_array(&mut dag, &mut level_cache, local_level);
                    select_cascade(&mut dag, &level_values, &epoch_bits, select_impl)
                } else {
                    let addr = dag.add(NodeKind::Alu(AluOp::Add), vec![idx, forest_values_p]);
                    dag.add(NodeKind::GatherLoad, vec![addr])
                };

            dag.cur_category = NodeCategory::Hash;
            let xor = dag.add(NodeKind::Alu(AluOp::Xor), vec![val, node_val]);
            let val_new = emit_hash(&mut dag, xor);

            dag.cur_category = NodeCategory::Idx;
            let parity = dag.add(NodeKind::Alu(AluOp::Mod), vec![val_new, two]);
            epoch_bits.push(parity);

            let offset = dag.add(NodeKind::Alu(AluOp::Add), vec![parity]);
            let doubled = dag.add(NodeKind::Alu(AluOp::Mul), vec![idx, two]);
            let idx_new = dag.add(NodeKind::Alu(AluOp::Add), vec![doubled, offset]);

            // The tree is exactly full (n_nodes = 2^(forest_height+1) - 1),
            // so stepping past the last level *always* overflows n_nodes
            // for every walker regardless of position within that level --
            // a statically-known wrap, not a runtime decision. See the chat
            // writeup for the inequality. Every other transition keeps the
            // real compare+select (idx_new is genuinely data-dependent).
            idx = if local_level == forest_height {
                dag.free()
            } else {
                let cmp = dag.add(NodeKind::Alu(AluOp::Lt), vec![idx_new, n_nodes]);
                dag.add(NodeKind::Flow, vec![cmp, idx_new])
            };
            val = val_new;
        }

        dag.cur_category = NodeCategory::Store;
        dag.add(NodeKind::Store, vec![idx]);
        dag.add(NodeKind::Store, vec![val]);
    }

    dag.cur_walker = u32::MAX;
    dag.cur_category = NodeCategory::Setup;
    dag
}

/// Same computation as [`build_problem_dag_smart_tuned`], but with the index
/// recurrence *elided* down to its irreducible residue, to validate the
/// "push idx off the ALU" floor. The observation: the router (cascade)
/// consumes the parity *bits* directly, and `idx` is only ever needed as a
/// gather *address* and the final stored value -- never as a per-round
/// integer. So instead of `parity, offset, doubled, idx_new, cmp,
/// wrap-select` (5 alu + 1 flow / round), we keep only two things per round:
/// `parity = val & 1` (1 op, feeds the router), and `pos = 2*pos + parity`
/// as one valu `multiply_add` (the within-epoch position, needed only to form
/// gather addresses; skipped on the last level since the next epoch resets it).
///
/// The wraparound is fully deterministic (full tree), so *every* cmp+select
/// is dropped -- `pos` simply resets to a free `0` at each epoch start. Gather
/// addresses become `pos + (fvp + 2^L - 1)` where the parenthesised part is a
/// compile-time constant (one `Free`). Routing (cascade/gather) is unchanged,
/// so the measured idx drop here is independent of any butterfly-routing work.
pub fn build_problem_dag_idxlite(
    forest_height: u32,
    batch_size: u32,
    rounds: u32,
    select_impl: SelectImpl,
    share_threshold: u32,
) -> Dag {
    let mut dag = Dag::new();

    let levels = forest_height + 1;
    let mut level_cache: HashMap<u32, Vec<NodeId>> = HashMap::new();

    for walker in 0..batch_size {
        dag.cur_walker = walker;
        dag.cur_category = NodeCategory::Setup;
        let mut val = dag.add(NodeKind::ContiguousLoad, vec![]);
        let mut pos = dag.free(); // pos_0 = 0 at the root
        let mut epoch_bits: Vec<NodeId> = Vec::new();

        for round in 0..rounds {
            let local_level = round % levels;
            if local_level == 0 {
                epoch_bits.clear();
                dag.cur_category = NodeCategory::Setup;
                pos = dag.free(); // epoch reset: root position is 0
            }

            dag.cur_category = NodeCategory::Routing;
            let node_val =
                if (1u64 << local_level) < batch_size as u64 && local_level < share_threshold {
                    let level_values = level_array(&mut dag, &mut level_cache, local_level);
                    select_cascade(&mut dag, &level_values, &epoch_bits, select_impl)
                } else {
                    // addr = pos + (fvp + 2^L - 1); the const is compile-time.
                    let addr_base = dag.free();
                    let addr = dag.add(NodeKind::Alu(AluOp::Add), vec![pos, addr_base]);
                    dag.add(NodeKind::GatherLoad, vec![addr])
                };

            dag.cur_category = NodeCategory::Hash;
            let xor = dag.add(NodeKind::Alu(AluOp::Xor), vec![val, node_val]);
            let val_new = emit_hash(&mut dag, xor);

            // idx residue: just the parity bit (feeds the router) and the
            // position accumulator (feeds gather addresses). No offset,
            // doubled, idx_new, cmp, or wrap-select.
            dag.cur_category = NodeCategory::Idx;
            let parity = dag.add(NodeKind::Alu(AluOp::And), vec![val_new]); // val & 1
            epoch_bits.push(parity);
            // `pos` (the within-epoch position) is needed to form gather
            // addresses. Deep levels (2^L >= batch_size) ALWAYS gather, so it
            // must be accumulated every round except the deepest (the next
            // epoch resets it). Only a full-butterfly route of *every* level
            // -- eliminating all gathers -- would remove `pos` entirely and
            // leave the parity bit as the whole idx residue (~85 cyc).
            if local_level != forest_height {
                // pos = 2*pos + parity, one fused multiply_add on valu.
                pos = dag.add(NodeKind::MultiplyAdd, vec![pos, parity]);
            }
            val = val_new;
        }

        dag.cur_category = NodeCategory::Store;
        dag.add(NodeKind::Store, vec![pos]);
        dag.add(NodeKind::Store, vec![val]);
    }

    dag.cur_walker = u32::MAX;
    dag.cur_category = NodeCategory::Setup;
    dag
}

/// The most aggressive construction: route *every* level with a butterfly
/// network instead of the cascade or per-walker gathers, so ALL routing lands
/// on the flow engine and the alu/valu engines carry only hash + parity.
///
/// The butterfly exploits `vselect` + compile-time base offsets to do a
/// conditional static-stride shift (`dest[i] = bit ? data[i+2^k] : data[i]`),
/// which is a routing-network switch. Gathering `level[idx_w]` for all walkers
/// is then a log-depth variable-rotation: `log2(2^L) = L` stages, each one
/// `vselect` (8-wide) per 8 walkers -- i.e. `O(N*L)` total, vs. the cascade's
/// `O(N*2^L)`. Modelled here per-walker as `local_level` flow `vselect`s
/// (the walker's own path through the network), consuming the shared level
/// array and its parity bits. Because the network keys directly on the parity
/// bits, `idx` collapses to parity-only -- NO `pos`, address adds, or gathers.
///
/// This drives the alu/valu (arithmetic) floor to its minimum -- hash + fold +
/// parity = 887 cycles -- but moves ALL routing onto flow (1 slot/cycle,
/// 8-wide), so `build the butterfly and measure` is really a test of whether
/// the arithmetic bound sub-900 is reachable and what flow then costs. See the
/// `breakdown` binary.
pub fn build_problem_dag_butterfly(forest_height: u32, batch_size: u32, rounds: u32) -> Dag {
    let mut dag = Dag::new();

    let levels = forest_height + 1;
    let mut level_cache: HashMap<u32, Vec<NodeId>> = HashMap::new();

    for walker in 0..batch_size {
        dag.cur_walker = walker;
        dag.cur_category = NodeCategory::Setup;
        let mut val = dag.add(NodeKind::ContiguousLoad, vec![]);
        let mut epoch_bits: Vec<NodeId> = Vec::new();

        for round in 0..rounds {
            let local_level = round % levels;
            if local_level == 0 {
                epoch_bits.clear();
            }

            // Butterfly route: `local_level` flow vselects, folding the level
            // array down to this walker's element using its parity bits. The
            // level array itself is a shared contiguous load. Level 0 is the
            // root -- 1 value, 0 selects.
            dag.cur_category = NodeCategory::Routing;
            let level_values = level_array(&mut dag, &mut level_cache, local_level);
            let mut node_val = level_values[0];
            for (k, &bit) in epoch_bits.iter().enumerate() {
                // one butterfly stage = one flow vselect (8-wide), keyed on
                // bit k, mixing in the k-th level-array element as the static
                // shift source (abstract deps; the real op is a vselect
                // between the running value and a statically-offset read).
                let src = level_values[(k + 1).min(level_values.len() - 1)];
                node_val = dag.add(NodeKind::Flow, vec![bit, node_val, src]);
            }

            dag.cur_category = NodeCategory::Hash;
            let xor = dag.add(NodeKind::Alu(AluOp::Xor), vec![val, node_val]);
            let val_new = emit_hash(&mut dag, xor);

            // idx residue: parity bit ONLY -- the butterfly consumes bits
            // directly, so there is no position integer, address, or gather.
            dag.cur_category = NodeCategory::Idx;
            let parity = dag.add(NodeKind::Alu(AluOp::And), vec![val_new]); // val & 1
            epoch_bits.push(parity);
            val = val_new;
        }

        dag.cur_category = NodeCategory::Store;
        // final idx would be assembled once from the last epoch's bits; model
        // it as a single store dependency on the last parity bit.
        let last_bit = *epoch_bits.last().unwrap();
        dag.add(NodeKind::Store, vec![last_bit]);
        dag.add(NodeKind::Store, vec![val]);
    }

    dag.cur_walker = u32::MAX;
    dag.cur_category = NodeCategory::Setup;
    dag
}

/// Hybrid router that balances routing across BOTH the flow engine
/// (butterfly, cheap for shallow levels -- `L` selects/walker) and the load
/// engine (gather, cheap for deep levels -- 2 scalar loads/cycle on the
/// otherwise-idle load port). Levels `<= butterfly_max_level` route via the
/// butterfly (flow); deeper levels gather (load), which requires the `pos`
/// accumulator + address add on alu/valu.
///
/// The point: neither extreme is realizable near the 887 hash floor --
/// all-butterfly floods the 1-slot flow engine (~2080), all-gather pins
/// alu/valu at ~986 via `pos`/addresses. Splitting at the crossover keeps
/// flow, load, AND alu/valu each near the hash floor. Sweep
/// `butterfly_max_level` (see the `breakdown` binary) to find it. Hash uses
/// the cross-stage fusion; idx is parity + a `pos` accumulator maintained only
/// while some deeper level still gathers.
pub fn build_problem_dag_hybrid(
    forest_height: u32,
    batch_size: u32,
    rounds: u32,
    butterfly_max_level: u32,
) -> Dag {
    let mut dag = Dag::new();

    let levels = forest_height + 1;
    let has_gathers = butterfly_max_level < forest_height;
    let mut level_cache: HashMap<u32, Vec<NodeId>> = HashMap::new();

    for walker in 0..batch_size {
        dag.cur_walker = walker;
        dag.cur_category = NodeCategory::Setup;
        let mut val = dag.add(NodeKind::ContiguousLoad, vec![]);
        let mut pos = dag.free();
        let mut epoch_bits: Vec<NodeId> = Vec::new();

        for round in 0..rounds {
            let local_level = round % levels;
            if local_level == 0 {
                epoch_bits.clear();
                dag.cur_category = NodeCategory::Setup;
                pos = dag.free();
            }

            dag.cur_category = NodeCategory::Routing;
            let node_val = if local_level <= butterfly_max_level {
                // Butterfly on flow: `local_level` vselects folding the shared
                // level array by the walker's parity bits.
                let level_values = level_array(&mut dag, &mut level_cache, local_level);
                let mut node_val = level_values[0];
                for (k, &bit) in epoch_bits.iter().enumerate() {
                    let src = level_values[(k + 1).min(level_values.len() - 1)];
                    node_val = dag.add(NodeKind::Flow, vec![bit, node_val, src]);
                }
                node_val
            } else {
                // Gather on load: addr = pos + compile-time base.
                let addr_base = dag.free();
                let addr = dag.add(NodeKind::Alu(AluOp::Add), vec![pos, addr_base]);
                dag.add(NodeKind::GatherLoad, vec![addr])
            };

            dag.cur_category = NodeCategory::Hash;
            let xor = dag.add(NodeKind::Alu(AluOp::Xor), vec![val, node_val]);
            let val_new = emit_hash(&mut dag, xor);

            dag.cur_category = NodeCategory::Idx;
            let parity = dag.add(NodeKind::Alu(AluOp::And), vec![val_new]);
            epoch_bits.push(parity);
            // Maintain `pos` only while some deeper level still gathers (its
            // address needs the accumulated position). If everything is
            // butterflied, pos is never read -- skip it.
            if has_gathers && local_level != forest_height {
                pos = dag.add(NodeKind::MultiplyAdd, vec![pos, parity]);
            }
            val = val_new;
        }

        dag.cur_category = NodeCategory::Store;
        let last_bit = *epoch_bits.last().unwrap();
        dag.add(NodeKind::Store, vec![if has_gathers { pos } else { last_bit }]);
        dag.add(NodeKind::Store, vec![val]);
    }

    dag.cur_walker = u32::MAX;
    dag.cur_category = NodeCategory::Setup;
    dag
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn node_count_matches_hand_count() {
        // Per round: addr, node_val, xor = 3. Hash: stages 0/4 are 1
        // MultiplyAdd each (2); stages 1/5 are 3 nodes each (6); stage2+stage3
        // fuse to 2 MultiplyAdd + 1 xor (3). Total 11 (see emit_hash's
        // cross-stage fusion). Tail: parity, offset, doubled, idx_new, cmp,
        // idx_final = 6. Plus, per walker: 1 free `idx=0` node, 1 initial
        // val load, and 2 final stores. Plus 3 free setup nodes shared
        // across the whole dag.
        let batch_size = 4;
        let rounds = 3;
        // forest_height=10 => levels=11 > rounds, so no round wraps and the
        // per-round shape (incl. the cmp+select tail) is unchanged.
        let dag = build_problem_dag(10, batch_size, rounds);
        let per_round = 3 + 11 + 6;
        let per_walker = 1 + 1 + per_round * rounds as usize + 2; // idx free + val load + rounds + 2 stores
        let expected = 3 + batch_size as usize * per_walker;
        assert_eq!(dag.nodes.len(), expected);
    }

    #[test]
    fn hybrid_routes_across_both_flow_and_load() {
        // The hybrid genuinely splits routing: shallow levels butterfly (flow),
        // deep levels gather (load). A mid crossover must therefore emit BOTH
        // Flow routing nodes and GatherLoad nodes -- unlike the pure extremes
        // (all-butterfly = no gathers; all-gather = no butterfly flow).
        let dag = build_problem_dag_hybrid(10, 256, 16, 5);
        let (mut flow, mut gather) = (0usize, 0usize);
        for (i, node) in dag.nodes.iter().enumerate() {
            if dag.category[i] == NodeCategory::Routing {
                match node.kind {
                    NodeKind::Flow => flow += 1,
                    NodeKind::GatherLoad => gather += 1,
                    _ => {}
                }
            }
            for &dep in &node.deps {
                assert!(dep < i, "node {i} deps on {dep}, not earlier");
            }
        }
        assert!(flow > 0, "hybrid should butterfly shallow levels on flow");
        assert!(gather > 0, "hybrid should gather deep levels on load");
    }

    #[test]
    fn butterfly_hits_sub_900_arithmetic_bound() {
        // The culmination: with the cross-stage hash fusion + parity-only idx
        // + all routing on flow (butterfly), the alu/valu engines carry ONLY
        // hash + fold + parity, so their throughput floor drops below 900.
        let dag = build_problem_dag_butterfly(10, 256, 16);
        let alu_valu = dag
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, NodeKind::Alu(_) | NodeKind::MultiplyAdd))
            .count() as u64;
        // 60 element-ops/cycle across alu (12) + valu (6*8).
        let arith_floor = alu_valu.div_ceil(60);
        assert!(
            arith_floor < 900,
            "arithmetic (alu/valu) floor should be sub-900, got {arith_floor} ({alu_valu} ops)"
        );
        // Idx is parity-only: no MultiplyAdd (pos accumulator) tagged Idx.
        let idx_madd = dag
            .nodes
            .iter()
            .enumerate()
            .filter(|(i, n)| {
                dag.category[*i] == NodeCategory::Idx && matches!(n.kind, NodeKind::MultiplyAdd)
            })
            .count();
        assert_eq!(
            idx_madd, 0,
            "butterfly idx should be parity-only, no pos madd"
        );
        // Routing carries zero alu/valu work -- it's all on flow.
        let routing_arith = dag
            .nodes
            .iter()
            .enumerate()
            .filter(|(i, n)| {
                dag.category[*i] == NodeCategory::Routing
                    && matches!(n.kind, NodeKind::Alu(_) | NodeKind::MultiplyAdd)
            })
            .count();
        assert_eq!(
            routing_arith, 0,
            "butterfly routing must be entirely off alu/valu"
        );
    }

    #[test]
    fn idxlite_elides_the_index_recurrence() {
        let smart = build_problem_dag_smart_tuned(10, 256, 16, SelectImpl::Flow, 4);
        let lite = build_problem_dag_idxlite(10, 256, 16, SelectImpl::Flow, 4);
        let idx_alu = |d: &Dag| {
            d.nodes
                .iter()
                .enumerate()
                .filter(|(i, n)| {
                    d.category[*i] == NodeCategory::Idx && matches!(n.kind, NodeKind::Alu(_))
                })
                .count()
        };
        // idxlite keeps only `parity = val & 1` on the ALU per round; the
        // smart dag's index recurrence is ~5 ALU ops/round. So idxlite's
        // ALU-idx work is well under half.
        assert!(
            idx_alu(&lite) * 2 < idx_alu(&smart),
            "idxlite idx-alu ({}) should be well under smart ({})",
            idx_alu(&lite),
            idx_alu(&smart)
        );
        // And it stays a valid DAG.
        for (i, node) in lite.nodes.iter().enumerate() {
            for &dep in &node.deps {
                assert!(dep < i, "node {i} deps on {dep}, not earlier");
            }
        }
    }

    #[test]
    fn is_acyclic_and_deps_point_backward() {
        let dag = build_problem_dag(10, 4, 3);
        for (i, node) in dag.nodes.iter().enumerate() {
            for &dep in &node.deps {
                assert!(
                    dep < i,
                    "node {i} depends on {dep}, which is not earlier -- not a valid DAG order"
                );
            }
        }
    }

    #[test]
    fn walkers_are_mutually_independent() {
        // No node in walker 0's subgraph should be reachable from walker 1's,
        // or vice versa -- batch_size shouldn't affect the critical path.
        let dag = build_problem_dag(10, 2, 2);
        let per_walker = 1 + 1 + (3 + 11 + 6) * 2 + 2;
        let walker0_range = 3..3 + per_walker;
        let walker1_start = 3 + per_walker;
        for node in &dag.nodes[walker1_start..] {
            for &dep in &node.deps {
                assert!(
                    !walker0_range.contains(&dep),
                    "walker 1 node depends on a walker 0 node ({dep}) -- they should be independent"
                );
            }
        }
    }

    #[test]
    fn emit_hash_uses_eleven_nodes_via_cross_stage_fusion() {
        // Stages 0 and 4 (op1=op2=Add,op3=Shl) are 1 MultiplyAdd each = 2.
        // Stages 1 and 5 (xor-shift) are 3 nodes each = 6. Stage2+stage3 fuse
        // to 2 MultiplyAdd + 1 xor = 3 (see emit_hash). Total 11 nodes, of
        // which 4 are MultiplyAdd (s0, the two fused p/q, s4). This beats the
        // per-stage minimum of 12 -- the cross-stage fusion the per-stage
        // proof in problem.rs does not see.
        let mut dag = Dag::new();
        let start = dag.free();
        let result = emit_hash(&mut dag, start);
        assert_ne!(result, start);
        let multiply_adds = dag
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, NodeKind::MultiplyAdd))
            .count();
        assert_eq!(multiply_adds, 4, "s0 + fused p,q + s4");
        let total_hash_nodes = dag.nodes.len() - 1; // minus the `start` free node
        assert_eq!(
            total_hash_nodes, 11,
            "2 (s0,s4 madd) + 6 (s1,s5) + 3 (s2+s3 fused)"
        );
    }

    #[test]
    fn plain_dag_folds_deterministic_wraparound() {
        // Tree is exactly full, so a walker at the deepest level
        // (local_level == forest_height) always overflows n_nodes and wraps to
        // 0 -- unconditional for every walker. Those rounds drop the
        // cmp(Lt)+select(Flow); every other round keeps them. Mirrors
        // build_problem_dag_smart's fold at the same boundary.
        let forest_height = 2u32;
        let batch_size = 3u32;
        let rounds = 6u32;
        let levels = forest_height + 1;
        let wrap_rounds_per_walker = (0..rounds).filter(|r| r % levels == forest_height).count();
        assert_eq!(wrap_rounds_per_walker, 2); // r = 2 and r = 5

        let dag = build_problem_dag(forest_height, batch_size, rounds);

        let flow = dag
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, NodeKind::Flow))
            .count();
        let lt = dag
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, NodeKind::Alu(crate::isa::AluOp::Lt)))
            .count();

        // Exactly one Lt + one Flow per (walker, non-wrap round); none on wraps.
        let expected_selects = batch_size as usize * (rounds as usize - wrap_rounds_per_walker);
        assert_eq!(flow, expected_selects);
        assert_eq!(lt, expected_selects);

        // Each wrap round replaces cmp+select (2 nodes) with one Free node,
        // i.e. -1 node per wrap round vs the no-fold count.
        let per_round = 3 + 11 + 6; // addr,node_val,xor + hash(11) + tail(6)
        let per_walker = 1 + 1 + per_round * rounds as usize - wrap_rounds_per_walker + 2;
        let expected = 3 + batch_size as usize * per_walker;
        assert_eq!(dag.nodes.len(), expected);
    }

    #[test]
    fn flow_select_impl_moves_cascade_selects_off_alu_onto_flow() {
        let algebraic_dag = build_problem_dag_smart_with(10, 256, 16, SelectImpl::Algebraic);
        let flow_dag = build_problem_dag_smart_with(10, 256, 16, SelectImpl::Flow);
        let flow_count = |d: &Dag| {
            d.nodes
                .iter()
                .filter(|n| matches!(n.kind, NodeKind::Flow))
                .count()
        };
        // 2 epochs x (0+1+3+7)=11 selects/walker x 256 walkers = 5632 selects.
        assert_eq!(flow_count(&flow_dag) - flow_count(&algebraic_dag), 5632);
        // Each algebraic select was 3 nodes; each flow select is 1 => 2 fewer each.
        assert_eq!(algebraic_dag.nodes.len() - flow_dag.nodes.len(), 2 * 5632);
    }

    #[test]
    fn smart_dag_is_acyclic_and_walkers_independent() {
        let dag = build_problem_dag_smart(4, 8, 6); // small tree, small batch, a couple epochs
        for (i, node) in dag.nodes.iter().enumerate() {
            for &dep in &node.deps {
                assert!(dep < i, "node {i} depends on {dep}, not earlier");
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
            .filter(|n| matches!(n.kind, NodeKind::ContiguousLoad))
            .count();
        // Shared level arrays: sizes 1+2+4+8 = 15 ContiguousLoad nodes,
        // read exactly once across both epochs, plus 32 initial-value loads
        // (one per walker, genuinely per-walker, not shared).
        assert_eq!(contiguous_loads, 15 + 32);
    }
}
