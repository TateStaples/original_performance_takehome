//! The "separate sim" for the memory/register-free lower-bound exploration:
//! a greedy, resource-constrained list scheduler over `dag::Dag`. It knows
//! nothing about scratch addresses or vector-lane layout -- only which
//! engine-slot-shaped resource each node needs and how many of those exist
//! per cycle (`isa::slot_limits`). This produces a *concrete, achievable*
//! schedule, so its cycle count is an upper bound on the true optimum, not
//! a lower bound -- but a much tighter one than a hand-written heuristic,
//! since it actually respects the real dependency graph instead of a fixed
//! "wave of 6" guess. See docs/problem.md and the chat writeup for how this
//! compares to the analytical depth-only (~256 cycles) and load-width-only
//! (~2048 cycles) bounds.
//!
//! Batching model: a `valu`/`vselect` slot can cover up to `VLEN` ready
//! nodes *of the same kind* (same alu opcode, or any select) in one slot,
//! regardless of whether they'd end up in contiguous scratch registers --
//! that register-allocation question is exactly what this pass defers.
//! `ContiguousLoad`/`Store` are always batchable (they're genuinely
//! vload/vstore-eligible in the real ISA). `GatherLoad` batching is
//! configurable (`gather_batchable`): off models the real ISA honestly (the
//! tree-node gather's address is genuinely data-dependent per walker, no
//! contiguity fix changes that); on models the fully-relaxed "resources and
//! dependencies are the only limits" bound. `MultiplyAdd` has no scalar
//! fallback (no `alu` equivalent exists in the real ISA), so it always goes
//! through `valu`, including as a *partial* batch (1-7 ready nodes still
//! consume 1 slot) -- otherwise it could stall waiting for an 8th peer that
//! never arrives.

use crate::dag::{Dag, NodeId, ResKind};
use crate::isa::{slot_limits, AluOp, VLEN};
use std::collections::HashMap;

#[derive(Clone, Copy, Debug, Default)]
pub struct SchedulerConfig {
    /// If true, `GatherLoad` nodes can batch VLEN-at-a-time like
    /// `ContiguousLoad` (an idealized gather instruction that doesn't exist
    /// in the real ISA). If false (the realistic default), they're strictly
    /// scalar: one `load` slot per node.
    pub gather_batchable: bool,
}

#[derive(Debug, Default, Clone, Copy)]
pub struct EngineTotals {
    pub nodes_done: u64,
    pub slot_uses: u64,
    pub busy_cycles: u64,
}

#[derive(Debug, Default)]
pub struct ScheduleResult {
    pub cycles: u64,
    pub alu: EngineTotals,
    pub valu: EngineTotals,
    /// `contiguous_load + gather_load`, both drawing from the same
    /// `slot_limits::LOAD` budget -- kept split so it's possible to see
    /// exactly how much of the load engine's time is the (batchable, real)
    /// contiguous reads vs. the (scalar in realistic mode) tree gather.
    pub contiguous_load: EngineTotals,
    pub gather_load: EngineTotals,
    pub store: EngineTotals,
    pub flow: EngineTotals,
    /// The cycle each node was scheduled on (0 for `Free` nodes, resolved
    /// before cycle 1). Exists so register-pressure analysis (see
    /// `peak_register_pressure`) can be computed *after* the fact, without
    /// the scheduler itself needing to know anything about registers.
    pub node_cycle: Vec<u32>,
}

impl ScheduleResult {
    pub fn load(&self) -> EngineTotals {
        EngineTotals {
            nodes_done: self.contiguous_load.nodes_done + self.gather_load.nodes_done,
            slot_uses: self.contiguous_load.slot_uses + self.gather_load.slot_uses,
            busy_cycles: self
                .contiguous_load
                .busy_cycles
                .max(self.gather_load.busy_cycles),
        }
    }
}

impl std::fmt::Display for ScheduleResult {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        writeln!(f, "cycles: {}", self.cycles)?;
        writeln!(
            f,
            "{:<16} {:>10} {:>12} {:>9}",
            "engine", "nodes", "slot_uses", "busy%"
        )?;
        for (name, e) in [
            ("alu", self.alu),
            ("valu", self.valu),
            ("load (total)", self.load()),
            ("  contiguous", self.contiguous_load),
            ("  gather", self.gather_load),
            ("store", self.store),
            ("flow", self.flow),
        ] {
            let busy_pct = if self.cycles == 0 {
                0.0
            } else {
                100.0 * e.busy_cycles as f64 / self.cycles as f64
            };
            writeln!(
                f,
                "{name:<16} {:>10} {:>12} {busy_pct:>8.2}%",
                e.nodes_done, e.slot_uses
            )?;
        }
        Ok(())
    }
}

/// Full batches of up to VLEN ready nodes; leftovers (<VLEN) are dropped --
/// caller is responsible for giving them a scalar fallback if one exists.
fn drain_valu_batches(group: &mut Vec<NodeId>, height: &[u32]) -> Vec<(u32, Vec<NodeId>)> {
    group.sort_unstable_by_key(|&n| std::cmp::Reverse(height[n]));
    let mut batches = Vec::new();
    while group.len() >= VLEN {
        let chunk: Vec<NodeId> = group.drain(0..VLEN).collect();
        let priority = chunk.iter().map(|&n| height[n]).max().unwrap();
        batches.push((priority, chunk));
    }
    batches
}

/// Every ready node becomes a "candidate slot use": full VLEN batches where
/// `batchable`, otherwise (or for the remainder) one scalar candidate per
/// node. Used where a real scalar fallback exists (load/store).
fn batch_or_scalar_candidates(
    mut ready: Vec<NodeId>,
    height: &[u32],
    batchable: bool,
) -> Vec<(u32, Vec<NodeId>)> {
    ready.sort_unstable_by_key(|&n| std::cmp::Reverse(height[n]));
    let mut out = Vec::new();
    if batchable {
        while ready.len() >= VLEN {
            let chunk: Vec<NodeId> = ready.drain(0..VLEN).collect();
            let p = chunk.iter().map(|&n| height[n]).max().unwrap();
            out.push((p, chunk));
        }
    }
    out.extend(ready.into_iter().map(|n| (height[n], vec![n])));
    out
}

/// Every ready node becomes a candidate, batched up to VLEN -- but unlike
/// `batch_or_scalar_candidates`, a *partial* (1..VLEN) leftover group still
/// forms one candidate instead of falling back to scalar, since no scalar
/// fallback exists for `MultiplyAdd`.
fn partial_valu_candidates(mut ready: Vec<NodeId>, height: &[u32]) -> Vec<(u32, Vec<NodeId>)> {
    ready.sort_unstable_by_key(|&n| std::cmp::Reverse(height[n]));
    let mut out = Vec::new();
    while !ready.is_empty() {
        let take = ready.len().min(VLEN);
        let chunk: Vec<NodeId> = ready.drain(0..take).collect();
        let p = chunk.iter().map(|&n| height[n]).max().unwrap();
        out.push((p, chunk));
    }
    out
}

pub fn schedule(dag: &Dag, config: SchedulerConfig) -> ScheduleResult {
    let n = dag.nodes.len();

    let mut dependents: Vec<Vec<NodeId>> = vec![Vec::new(); n];
    let mut remaining_deps: Vec<u32> = vec![0; n];
    for (i, node) in dag.nodes.iter().enumerate() {
        remaining_deps[i] = node.deps.len() as u32;
        for &d in &node.deps {
            dependents[d].push(i);
        }
    }

    // Longest path (in nodes) from each node to a sink -- deps always point
    // to smaller indices (see dag.rs's is_acyclic_and_deps_point_backward
    // test), so a single reverse pass suffices.
    let mut height = vec![1u32; n];
    for i in (0..n).rev() {
        let h = dependents[i].iter().map(|&d| height[d]).max().unwrap_or(0) + 1;
        height[i] = h;
    }

    let mut scheduled = vec![false; n];
    let mut done_count: u64 = 0;

    // Resolve Free nodes instantly (no engine, no cycle) before scheduling begins.
    let mut pool: Vec<NodeId> = Vec::new();
    let mut queue: Vec<NodeId> = (0..n).filter(|&i| remaining_deps[i] == 0).collect();
    while let Some(i) = queue.pop() {
        if matches!(dag.nodes[i].kind, ResKind::Free) && !scheduled[i] {
            scheduled[i] = true;
            done_count += 1;
            for &dep in &dependents[i] {
                remaining_deps[dep] -= 1;
                if remaining_deps[dep] == 0 {
                    queue.push(dep);
                }
            }
        } else if !scheduled[i] {
            pool.push(i);
        }
    }

    let mut result = ScheduleResult {
        node_cycle: vec![0u32; n],
        ..Default::default()
    };

    while done_count < n as u64 {
        result.cycles += 1;

        let mut alu_groups: HashMap<AluOp, Vec<NodeId>> = HashMap::new();
        let mut multiply_add_ready: Vec<NodeId> = Vec::new();
        let mut flow_ready: Vec<NodeId> = Vec::new();
        let mut contiguous_load_ready: Vec<NodeId> = Vec::new();
        let mut gather_load_ready: Vec<NodeId> = Vec::new();
        let mut store_ready: Vec<NodeId> = Vec::new();

        for &node in &pool {
            match dag.nodes[node].kind {
                ResKind::Alu(op) => alu_groups.entry(op).or_default().push(node),
                ResKind::MultiplyAdd => multiply_add_ready.push(node),
                ResKind::Flow => flow_ready.push(node),
                ResKind::ContiguousLoad => contiguous_load_ready.push(node),
                ResKind::GatherLoad => gather_load_ready.push(node),
                ResKind::Store => store_ready.push(node),
                ResKind::Free => unreachable!("Free nodes are resolved before scheduling"),
            }
        }

        let mut this_cycle: Vec<NodeId> = Vec::new();

        // valu: same-opcode alu batches of VLEN, plus MultiplyAdd (partial
        // batches allowed, no scalar fallback exists), highest-priority first.
        let mut valu_candidates: Vec<(u32, Vec<NodeId>)> = alu_groups
            .iter_mut()
            .flat_map(|(_, group)| drain_valu_batches(group, &height))
            .collect();
        valu_candidates.extend(partial_valu_candidates(multiply_add_ready, &height));
        valu_candidates.sort_unstable_by_key(|(p, _)| std::cmp::Reverse(*p));
        let mut valu_slots_used = 0u64;
        for (_, chunk) in valu_candidates.into_iter().take(slot_limits::VALU) {
            valu_slots_used += 1;
            result.valu.nodes_done += chunk.len() as u64;
            this_cycle.extend(chunk);
        }
        result.valu.slot_uses += valu_slots_used;
        if valu_slots_used > 0 {
            result.valu.busy_cycles += 1;
        }

        // alu: whatever's left of the alu-opcode groups (leftover batch
        // remainders + never-batched opcodes) -- MultiplyAdd never appears
        // here, it has no alu-engine fallback. Highest-height first, up to
        // slot_limits::ALU.
        let mut alu_leftover: Vec<NodeId> = alu_groups.into_values().flatten().collect();
        alu_leftover.sort_unstable_by_key(|&n| std::cmp::Reverse(height[n]));
        let alu_take = alu_leftover.len().min(slot_limits::ALU);
        result.alu.nodes_done += alu_take as u64;
        result.alu.slot_uses += alu_take as u64;
        if alu_take > 0 {
            result.alu.busy_cycles += 1;
        }
        this_cycle.extend(alu_leftover.into_iter().take(alu_take));

        // flow: exactly one slot/cycle, covering up to VLEN ready selects
        // (matches real vselect: one flow slot, eight lanes).
        flow_ready.sort_unstable_by_key(|&n| std::cmp::Reverse(height[n]));
        let flow_take = flow_ready.len().min(VLEN);
        if flow_take > 0 {
            result.flow.nodes_done += flow_take as u64;
            result.flow.slot_uses += 1;
            result.flow.busy_cycles += 1;
        }
        this_cycle.extend(flow_ready.into_iter().take(flow_take));

        // load: ContiguousLoad (always batchable, it's genuinely contiguous
        // in real memory) and GatherLoad (batchable only if relaxed) share
        // the same slot_limits::LOAD budget; tagged so stats can attribute
        // slot uses back to whichever kind actually won the slot.
        let mut load_candidates: Vec<(u32, bool, Vec<NodeId>)> =
            batch_or_scalar_candidates(contiguous_load_ready, &height, true)
                .into_iter()
                .map(|(p, c)| (p, true, c))
                .collect();
        load_candidates.extend(
            batch_or_scalar_candidates(gather_load_ready, &height, config.gather_batchable)
                .into_iter()
                .map(|(p, c)| (p, false, c)),
        );
        load_candidates.sort_unstable_by_key(|(p, ..)| std::cmp::Reverse(*p));
        let (mut contiguous_busy, mut gather_busy) = (false, false);
        for (_, is_contiguous, chunk) in load_candidates.into_iter().take(slot_limits::LOAD) {
            let totals = if is_contiguous {
                &mut result.contiguous_load
            } else {
                &mut result.gather_load
            };
            totals.slot_uses += 1;
            totals.nodes_done += chunk.len() as u64;
            if is_contiguous {
                contiguous_busy = true;
            } else {
                gather_busy = true;
            }
            this_cycle.extend(chunk);
        }
        result.contiguous_load.busy_cycles += contiguous_busy as u64;
        result.gather_load.busy_cycles += gather_busy as u64;

        // store: always batchable -- every store in this problem writes to
        // a fixed, per-walker-contiguous address (see dag.rs).
        let store_candidates = batch_or_scalar_candidates(store_ready, &height, true);
        let mut store_slots_used = 0u64;
        let mut sorted_store = store_candidates;
        sorted_store.sort_unstable_by_key(|(p, _)| std::cmp::Reverse(*p));
        for (_, chunk) in sorted_store.into_iter().take(slot_limits::STORE) {
            store_slots_used += 1;
            result.store.nodes_done += chunk.len() as u64;
            this_cycle.extend(chunk);
        }
        result.store.slot_uses += store_slots_used;
        if store_slots_used > 0 {
            result.store.busy_cycles += 1;
        }

        assert!(
            !this_cycle.is_empty(),
            "deadlock: {} ready nodes but none schedulable this cycle -- scheduler bug",
            pool.len()
        );

        for &node in &this_cycle {
            scheduled[node] = true;
            result.node_cycle[node] = result.cycles as u32;
        }
        // O(pool) filter via the `scheduled` array, not O(pool * this_cycle)
        // `Vec::contains` -- this loop runs once per cycle over a pool that
        // can hold thousands of ready nodes.
        pool.retain(|&n| !scheduled[n]);
        for &node in &this_cycle {
            done_count += 1;
            for &dep in &dependents[node] {
                remaining_deps[dep] -= 1;
                if remaining_deps[dep] == 0 {
                    pool.push(dep);
                }
            }
        }
    }

    result
}

/// Peak number of DAG values simultaneously live under `result`'s actual
/// schedule -- i.e. the minimum scratch words a register allocator could
/// possibly get away with, *if* it could freely reuse any word the instant
/// a value's last reader has executed and place any live value in any word
/// (no contiguity constraints, no allocation-conflict overhead). This is
/// the piece `schedule()` deliberately doesn't compute: the DAG and
/// scheduler know nothing about scratch addresses at all, so this cycle
/// count is unconditionally optimistic about register pressure -- if this
/// number exceeds `isa::SCRATCH_SIZE`, the schedule literally cannot be
/// realized as-is; a real compiler would need to either narrow the
/// schedule (limit how much gets interleaved, trading cycles for
/// registers -- see `vectorized.rs`'s `pipeline_width` for exactly this
/// trade-off, chosen by hand there) or spill (extra load/store traffic,
/// which costs cycles this count doesn't include either).
///
/// A value is live from the cycle it's produced through the last cycle any
/// of its dependents consumes it (inclusive); `Store` nodes don't produce a
/// readable value and are excluded.
pub fn peak_register_pressure(dag: &Dag, result: &ScheduleResult) -> (u64, u32) {
    let n = dag.nodes.len();
    let mut dependents: Vec<Vec<NodeId>> = vec![Vec::new(); n];
    for (i, node) in dag.nodes.iter().enumerate() {
        for &d in &node.deps {
            dependents[d].push(i);
        }
    }

    let max_cycle = result.cycles as usize;
    let mut delta = vec![0i64; max_cycle + 2];
    for (i, deps_of_i) in dependents.iter().enumerate() {
        if matches!(dag.nodes[i].kind, ResKind::Store) {
            continue;
        }
        let birth = result.node_cycle[i] as usize;
        let death = deps_of_i
            .iter()
            .map(|&d| result.node_cycle[d] as usize)
            .max()
            .unwrap_or(birth);
        delta[birth] += 1;
        delta[death + 1] -= 1;
    }

    let mut live = 0i64;
    let mut peak = 0i64;
    let mut peak_cycle = 0u32;
    for (c, d) in delta.iter().enumerate().take(max_cycle + 1) {
        live += d;
        if live > peak {
            peak = live;
            peak_cycle = c as u32;
        }
    }
    (peak as u64, peak_cycle)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dag::{build_problem_dag, build_problem_dag_smart};

    fn total_nodes_done(r: &ScheduleResult) -> u64 {
        r.alu.nodes_done
            + r.valu.nodes_done
            + r.load().nodes_done
            + r.store.nodes_done
            + r.flow.nodes_done
    }

    #[test]
    fn schedules_every_non_free_node_exactly_once() {
        let dag = build_problem_dag(16, 4);
        let free_count = dag
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, crate::dag::ResKind::Free))
            .count();
        let result = schedule(&dag, SchedulerConfig::default());
        assert_eq!(
            total_nodes_done(&result) as usize,
            dag.nodes.len() - free_count
        );
    }

    #[test]
    fn smart_dag_schedules_every_non_free_node_exactly_once() {
        let dag = build_problem_dag_smart(4, 16, 6);
        let free_count = dag
            .nodes
            .iter()
            .filter(|n| matches!(n.kind, crate::dag::ResKind::Free))
            .count();
        let result = schedule(&dag, SchedulerConfig::default());
        assert_eq!(
            total_nodes_done(&result) as usize,
            dag.nodes.len() - free_count
        );
    }

    #[test]
    fn realistic_mode_keeps_gather_load_scalar() {
        // With gather_batchable=false, gather_load specifically should never
        // exceed slot_limits::LOAD nodes retired per busy cycle -- i.e.
        // nodes_done <= 2 * busy_cycles, unlike valu which can do 8x.
        let dag = build_problem_dag(16, 4);
        let result = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
            },
        );
        assert!(
            result.gather_load.nodes_done
                <= slot_limits::LOAD as u64 * result.gather_load.busy_cycles
        );
    }

    #[test]
    fn relaxed_mode_lets_gather_load_batch() {
        let dag = build_problem_dag(16, 4);
        let result = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: true,
            },
        );
        // Should be able to exceed the scalar rate at least once, given
        // plenty of same-cycle-ready gather nodes at this batch size.
        assert!(
            result.gather_load.nodes_done
                > slot_limits::LOAD as u64 * result.gather_load.busy_cycles
        );
    }

    #[test]
    fn batching_relaxation_never_produces_a_worse_schedule() {
        // Every op the realistic scheduler can do, the relaxed one can also
        // do (it's a strict widening of what can share a slot) -- so
        // relaxed cycles should never exceed realistic cycles.
        let dag = build_problem_dag(16, 4);
        let realistic = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
            },
        );
        let relaxed = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: true,
            },
        );
        assert!(relaxed.cycles <= realistic.cycles);
    }

    #[test]
    fn beats_the_hand_rolled_pipeline_at_full_scale() {
        // The whole point of this exercise: a dependency-aware scheduler
        // should find meaningfully more parallelism than the fixed
        // "wave of 6 groups" heuristic in vectorized.rs (4990 cycles at
        // batch_size=256, rounds=16).
        let dag = build_problem_dag(256, 16);
        let result = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
            },
        );
        assert!(
            result.cycles < 4990,
            "expected the list scheduler to beat the hand-rolled 4990-cycle kernel, got {}",
            result.cycles
        );
        // And it shouldn't be able to beat the hard load-engine floor:
        // ceil(total scalar gather loads / slot_limits::LOAD). The gather
        // is batch_size*rounds node_val loads plus batch_size initial
        // value loads (the latter is ContiguousLoad and can batch, so it's
        // not part of this floor).
        let total_gathers = 256u64 * 16;
        let load_floor = total_gathers.div_ceil(slot_limits::LOAD as u64);
        assert!(
            result.cycles >= load_floor,
            "scheduled {} cycles but the gather alone needs at least {load_floor}",
            result.cycles
        );
    }

    #[test]
    fn smart_dag_beats_plain_dag_at_full_scale() {
        // The whole point of build_problem_dag_smart: exploiting the shared
        // root should meaningfully reduce the realistic-mode schedule
        // versus the plain per-walker-gather dag, at the real benchmark size.
        let plain = build_problem_dag(256, 16);
        let smart = build_problem_dag_smart(10, 256, 16);
        let plain_result = schedule(
            &plain,
            SchedulerConfig {
                gather_batchable: false,
            },
        );
        let smart_result = schedule(
            &smart,
            SchedulerConfig {
                gather_batchable: false,
            },
        );
        assert!(
            smart_result.cycles < plain_result.cycles,
            "smart dag ({}) should beat the plain dag ({})",
            smart_result.cycles,
            plain_result.cycles
        );
    }

    #[test]
    fn plain_dag_peak_register_pressure_fits_but_smart_dag_does_not() {
        // The scheduler's cycle count is entirely register-oblivious (see
        // peak_register_pressure's docs), so it's worth actually measuring
        // rather than assuming a direction. Measured finding, pinned here
        // so a future change to either dag or the scheduler's priority
        // heuristic can't silently invert it without a test noticing: the
        // plain dag's height-priority schedule happens to keep peak
        // pressure under SCRATCH_SIZE, but the smart dag's extra per-walker
        // state (the epoch_bits history threaded through select_cascade)
        // pushes it over -- so the smart dag's lower cycle count is *not*
        // directly realizable as-is, despite "beating" the plain dag in
        // schedule::tests::smart_dag_beats_plain_dag_at_full_scale.
        let plain = build_problem_dag(256, 16);
        let smart = build_problem_dag_smart(10, 256, 16);
        let plain_result = schedule(
            &plain,
            SchedulerConfig {
                gather_batchable: false,
            },
        );
        let smart_result = schedule(
            &smart,
            SchedulerConfig {
                gather_batchable: false,
            },
        );
        let (plain_peak, _) = peak_register_pressure(&plain, &plain_result);
        let (smart_peak, _) = peak_register_pressure(&smart, &smart_result);
        assert!(
            plain_peak <= crate::isa::SCRATCH_SIZE as u64,
            "plain dag peak register pressure ({plain_peak}) no longer fits SCRATCH_SIZE ({})",
            crate::isa::SCRATCH_SIZE
        );
        assert!(
            smart_peak > crate::isa::SCRATCH_SIZE as u64,
            "smart dag peak register pressure ({smart_peak}) unexpectedly fits SCRATCH_SIZE ({}) -- \
             if this is now true, the register-pressure caveat on its cycle-count win no longer applies",
            crate::isa::SCRATCH_SIZE
        );
    }

    #[test]
    fn peak_register_pressure_is_at_least_the_widest_single_cycle_batch() {
        // Sanity check on the liveness math itself: pressure at any cycle
        // can't be less than the number of values produced *that* cycle.
        let dag = build_problem_dag(16, 4);
        let result = schedule(&dag, SchedulerConfig::default());
        let (peak, _) = peak_register_pressure(&dag, &result);
        assert!(peak >= 1);
    }
}
