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
//! `load`/`store` batching is configurable (`gather_batchable`): off models
//! the real ISA honestly (the tree-node gather's address is genuinely
//! data-dependent per walker, no contiguity fix changes that); on models
//! the fully-relaxed "resources and dependencies are the only limits"
//! bound, to show how much of the gap is specifically the scalar gather.

use crate::dag::{Dag, NodeId, ResKind};
use crate::isa::{slot_limits, AluOp, VLEN};
use std::collections::HashMap;

#[derive(Clone, Copy, Debug, Default)]
pub struct SchedulerConfig {
    /// If true, `load`/`store` nodes can batch VLEN-at-a-time like alu/flow
    /// (an idealized gather/scatter that doesn't exist in the real ISA).
    /// If false (the realistic default), they're strictly scalar: up to
    /// `slot_limits::LOAD`/`STORE` individual nodes per cycle.
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
    pub load: EngineTotals,
    pub store: EngineTotals,
    pub flow: EngineTotals,
}

impl std::fmt::Display for ScheduleResult {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        writeln!(f, "cycles: {}", self.cycles)?;
        writeln!(
            f,
            "{:<7} {:>10} {:>12} {:>9}",
            "engine", "nodes", "slot_uses", "busy%"
        )?;
        for (name, e) in [
            ("alu", self.alu),
            ("valu", self.valu),
            ("load", self.load),
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
                "{name:<7} {:>10} {:>12} {busy_pct:>8.2}%",
                e.nodes_done, e.slot_uses
            )?;
        }
        Ok(())
    }
}

/// A batch of up to VLEN ready nodes sharing the same alu opcode -- the
/// unit a single `valu` slot can retire in one cycle.
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

    let mut result = ScheduleResult::default();

    while done_count < n as u64 {
        result.cycles += 1;

        let mut alu_groups: HashMap<AluOp, Vec<NodeId>> = HashMap::new();
        let mut flow_ready: Vec<NodeId> = Vec::new();
        let mut load_ready: Vec<NodeId> = Vec::new();
        let mut store_ready: Vec<NodeId> = Vec::new();

        for &node in &pool {
            match dag.nodes[node].kind {
                ResKind::Alu(op) => alu_groups.entry(op).or_default().push(node),
                ResKind::Flow => flow_ready.push(node),
                ResKind::Load => load_ready.push(node),
                ResKind::Store => store_ready.push(node),
                ResKind::Free => unreachable!("Free nodes are resolved before scheduling"),
            }
        }

        let mut this_cycle: Vec<NodeId> = Vec::new();

        // valu: batch same-opcode groups of VLEN, highest-priority batches first.
        let mut candidate_batches: Vec<(u32, AluOp, Vec<NodeId>)> = alu_groups
            .iter_mut()
            .flat_map(|(&op, group)| {
                drain_valu_batches(group, &height)
                    .into_iter()
                    .map(move |(p, c)| (p, op, c))
            })
            .collect();
        candidate_batches.sort_unstable_by_key(|(p, ..)| std::cmp::Reverse(*p));
        let mut valu_slots_used = 0u64;
        for (_, _, chunk) in candidate_batches.into_iter().take(slot_limits::VALU) {
            valu_slots_used += 1;
            result.valu.nodes_done += chunk.len() as u64;
            this_cycle.extend(chunk);
        }
        result.valu.slot_uses += valu_slots_used;
        if valu_slots_used > 0 {
            result.valu.busy_cycles += 1;
        }

        // alu: whatever's left (leftover batch remainders + never-batched
        // opcodes), highest-height first, up to slot_limits::ALU.
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

        // load/store: scalar unless gather_batchable relaxes it.
        schedule_mem(
            &mut load_ready,
            &height,
            slot_limits::LOAD,
            config.gather_batchable,
            &mut this_cycle,
            &mut result.load,
        );
        schedule_mem(
            &mut store_ready,
            &height,
            slot_limits::STORE,
            config.gather_batchable,
            &mut this_cycle,
            &mut result.store,
        );

        assert!(
            !this_cycle.is_empty(),
            "deadlock: {} ready nodes but none schedulable this cycle -- scheduler bug",
            pool.len()
        );

        for &node in &this_cycle {
            scheduled[node] = true;
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

fn schedule_mem(
    ready: &mut Vec<NodeId>,
    height: &[u32],
    slots: usize,
    batchable: bool,
    this_cycle: &mut Vec<NodeId>,
    totals: &mut EngineTotals,
) {
    ready.sort_unstable_by_key(|&n| std::cmp::Reverse(height[n]));
    if batchable {
        let mut used = 0usize;
        while ready.len() >= VLEN && used < slots {
            let chunk: Vec<NodeId> = ready.drain(0..VLEN).collect();
            totals.nodes_done += chunk.len() as u64;
            this_cycle.extend(chunk);
            used += 1;
        }
        // leftover fewer-than-VLEN ready nodes still take a scalar slot each.
        let take = ready.len().min(slots - used);
        totals.nodes_done += take as u64;
        this_cycle.extend(ready.drain(0..take));
        totals.slot_uses += used as u64 + take as u64;
        if used + take > 0 {
            totals.busy_cycles += 1;
        }
    } else {
        let take = ready.len().min(slots);
        totals.nodes_done += take as u64;
        totals.slot_uses += take as u64;
        if take > 0 {
            totals.busy_cycles += 1;
        }
        this_cycle.extend(ready.drain(0..take));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dag::build_problem_dag;

    fn total_nodes_done(r: &ScheduleResult) -> u64 {
        r.alu.nodes_done
            + r.valu.nodes_done
            + r.load.nodes_done
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
    fn realistic_mode_keeps_load_scalar() {
        // With gather_batchable=false, load should never exceed
        // slot_limits::LOAD nodes retired per busy cycle on average --
        // i.e. nodes_done <= 2 * busy_cycles, unlike valu which can do 8x.
        let dag = build_problem_dag(16, 4);
        let result = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
            },
        );
        assert!(result.load.nodes_done <= slot_limits::LOAD as u64 * result.load.busy_cycles);
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
        // value loads, all scalar in realistic mode.
        let total_loads = 256u64 * 16 + 256;
        let load_floor = total_loads.div_ceil(slot_limits::LOAD as u64);
        assert!(
            result.cycles >= load_floor,
            "scheduled {} cycles but the load engine alone needs at least {load_floor}",
            result.cycles
        );
    }
}
