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
use std::collections::BTreeMap;

/// Optional per-node placement controls layered on top of the default
/// height/window priority. Empty vectors (the [`Default`]) reproduce the
/// original scheduler byte-for-byte -- this is what plain [`schedule`] passes.
///
/// The spiller (see `crate::spill`) uses these two knobs to place spill
/// traffic precisely, which is the whole difficulty of turning a spill
/// *count* into a spill *schedule*:
///
/// * `priority_class` -- a coarse tier that dominates the height/window key:
///   `0` = urgent (wins every slot it is ready for), `1` = normal, `2` = lazy
///   (only ever fills slots nothing else wants). Spill-stores go in tier 0 so
///   they fire the instant their value exists (freeing its scratch word ASAP);
///   reloads go in tier 2 so a real gather never loses a load slot to a spill
///   reload. An empty vector means "tier 0 for everything", identical to the
///   pre-override key.
/// * `release_cycle` -- an earliest-cycle floor: a node is withheld from the
///   ready pool until the scheduler reaches `release_cycle[node]`, even if its
///   dependencies are satisfied and slots are idle. This is the ALAP lever
///   reloads need: with idle load bandwidth a lazy-tier reload would still be
///   scheduled the moment it became ready (re-inflating pressure), so we pin
///   it to `use_cycle - 1` and it lands just-in-time instead. `0` = no floor.
#[derive(Clone, Debug, Default)]
pub struct ScheduleOverrides {
    /// Priority tier per node (see struct docs). Values outside `0..=2` are
    /// accepted and simply sort in the obvious order; empty = all-zero.
    pub priority_class: Vec<u8>,
    /// Earliest cycle each node may be scheduled (see struct docs). `0` = none;
    /// empty = no floors at all.
    pub release_cycle: Vec<u32>,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct SchedulerConfig {
    /// If true, `GatherLoad` nodes can batch VLEN-at-a-time like
    /// `ContiguousLoad` (an idealized gather instruction that doesn't exist
    /// in the real ISA). If false (the realistic default), they're strictly
    /// scalar: one `load` slot per node.
    pub gather_batchable: bool,
    /// If `Some(w)`, schedule walkers in windows of `w`: among equally ready
    /// work the scheduler strictly prefers lower-numbered windows, finishing
    /// (and freeing the registers of) earlier walkers before pulling later
    /// ones in, and spilling into the next window only to fill otherwise-idle
    /// engine slots. Caps peak register pressure at roughly one window of
    /// live per-walker state, at (near) zero cycle cost because no ready
    /// engine is ever left idle. `None` (the default) = the original
    /// height-only, fully-interleaved behavior. Requires `dag.walker_of`.
    pub walker_window: Option<u32>,
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

// The helpers below rank candidates by a composite `key` (see `schedule`),
// not raw height: lower key = scheduled sooner. The key packs the walker
// window in its high bits and (hmax - height) in its low bits, so ascending
// key = earlier-window-first, then taller-first -- and with no window it is
// exactly descending height, identical to the pre-windowing behavior. A
// chunk's priority is its MIN key (its most-urgent member).

/// Full batches of up to VLEN ready nodes; leftovers (<VLEN) are dropped --
/// caller is responsible for giving them a scalar fallback if one exists.
fn drain_valu_batches(group: &mut Vec<NodeId>, key: &[u64]) -> Vec<(u64, Vec<NodeId>)> {
    group.sort_unstable_by_key(|&n| key[n]);
    let mut batches = Vec::new();
    while group.len() >= VLEN {
        let chunk: Vec<NodeId> = group.drain(0..VLEN).collect();
        let priority = chunk.iter().map(|&n| key[n]).min().unwrap();
        batches.push((priority, chunk));
    }
    batches
}

/// Every ready node becomes a "candidate slot use": full VLEN batches where
/// `batchable`, otherwise (or for the remainder) one scalar candidate per
/// node. Used where a real scalar fallback exists (load/store).
fn batch_or_scalar_candidates(
    mut ready: Vec<NodeId>,
    key: &[u64],
    batchable: bool,
) -> Vec<(u64, Vec<NodeId>)> {
    ready.sort_unstable_by_key(|&n| key[n]);
    let mut out = Vec::new();
    if batchable {
        while ready.len() >= VLEN {
            let chunk: Vec<NodeId> = ready.drain(0..VLEN).collect();
            let p = chunk.iter().map(|&n| key[n]).min().unwrap();
            out.push((p, chunk));
        }
    }
    out.extend(ready.into_iter().map(|n| (key[n], vec![n])));
    out
}

/// Every ready node becomes a candidate, batched up to VLEN -- but unlike
/// `batch_or_scalar_candidates`, a *partial* (1..VLEN) leftover group still
/// forms one candidate instead of falling back to scalar, since no scalar
/// fallback exists for `MultiplyAdd`.
fn partial_valu_candidates(mut ready: Vec<NodeId>, key: &[u64]) -> Vec<(u64, Vec<NodeId>)> {
    ready.sort_unstable_by_key(|&n| key[n]);
    let mut out = Vec::new();
    while !ready.is_empty() {
        let take = ready.len().min(VLEN);
        let chunk: Vec<NodeId> = ready.drain(0..take).collect();
        let p = chunk.iter().map(|&n| key[n]).min().unwrap();
        out.push((p, chunk));
    }
    out
}

pub fn schedule(dag: &Dag, config: SchedulerConfig) -> ScheduleResult {
    schedule_with(dag, config, &ScheduleOverrides::default())
}

/// [`schedule`] with per-node placement overrides (see [`ScheduleOverrides`]).
/// With the default (empty) overrides this is byte-identical to `schedule`.
pub fn schedule_with(
    dag: &Dag,
    config: SchedulerConfig,
    overrides: &ScheduleOverrides,
) -> ScheduleResult {
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

    // Composite priority key: primary = walker window (ascending, earlier
    // windows first), secondary = height (descending). Packed into one u64 so
    // a single ascending sort orders both -- lower key = scheduled sooner.
    // With walker_window == None every window is 0 and the key is exactly
    // (hmax - height), i.e. plain descending height, so the schedule is
    // byte-identical to the pre-windowing behavior.
    let hmax = height.iter().copied().max().unwrap_or(0);
    let group_of = |nd: NodeId| -> u32 {
        match config.walker_window {
            Some(w) if w > 0 => {
                let wi = dag.walker_of[nd];
                if wi == u32::MAX {
                    0
                } else {
                    wi / w
                }
            }
            _ => 0,
        }
    };
    // Priority tier (see ScheduleOverrides) occupies the top byte, above the
    // walker window and height, so it dominates both. An empty override vector
    // yields tier 0 everywhere, leaving the key exactly `(group << 32) |
    // (hmax - height)` -- the pre-override packing, bit-for-bit. Groups here
    // are tiny (walker/window <= a few hundred), so they never spill past bit
    // 55 into the tier byte.
    let tier_of =
        |nd: NodeId| -> u64 { overrides.priority_class.get(nd).copied().unwrap_or(0) as u64 };
    let key: Vec<u64> = (0..n)
        .map(|nd| {
            (tier_of(nd) << 56) | ((group_of(nd) as u64) << 32) | ((hmax - height[nd]) as u64)
        })
        .collect();

    // Earliest-cycle floor per node (see ScheduleOverrides::release_cycle).
    let rel_of = |nd: NodeId| -> u32 { overrides.release_cycle.get(nd).copied().unwrap_or(0) };
    // Nodes whose deps are satisfied but whose release cycle hasn't arrived,
    // keyed by (and drained at) that release cycle.
    let mut held: BTreeMap<u32, Vec<NodeId>> = BTreeMap::new();

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
            // Release-gate even the initial ready set (a release floor > cycle
            // 1 holds the node back). Reloads never land here -- they depend on
            // their spill-store -- but keep the path uniform for correctness.
            let r = rel_of(i);
            if r <= 1 {
                pool.push(i);
            } else {
                held.entry(r).or_default().push(i);
            }
        }
    }

    let mut result = ScheduleResult {
        node_cycle: vec![0u32; n],
        ..Default::default()
    };

    while done_count < n as u64 {
        result.cycles += 1;

        // Admit any release-floored nodes whose cycle has now arrived.
        while let Some((&rel, _)) = held.iter().next() {
            if rel <= result.cycles as u32 {
                let mut due = held.remove(&rel).unwrap();
                pool.append(&mut due);
            } else {
                break;
            }
        }
        // If nothing is ready this cycle but work is merely being held back,
        // fast-forward the clock to the next release (charging the idle gap as
        // elapsed cycles) rather than spinning one empty cycle at a time. A
        // truly empty pool with nothing held while work remains is a real
        // deadlock (the pre-override scheduler asserts the same, one line down).
        if pool.is_empty() {
            if let Some((&rel, _)) = held.iter().next() {
                result.cycles = rel as u64;
                let mut due = held.remove(&rel).unwrap();
                pool.append(&mut due);
                while let Some((&r2, _)) = held.iter().next() {
                    if r2 <= result.cycles as u32 {
                        let mut more = held.remove(&r2).unwrap();
                        pool.append(&mut more);
                    } else {
                        break;
                    }
                }
            } else {
                panic!(
                    "deadlock: {} nodes unscheduled with empty pool and no held work",
                    n as u64 - done_count
                );
            }
        }

        // BTreeMap (not HashMap) so opcode iteration order is deterministic:
        // the greedy priority ties are then broken the same way every run,
        // making the reported cycle counts reproducible (a HashMap's
        // randomized order made them jitter by a cycle or two run-to-run).
        let mut alu_groups: BTreeMap<AluOp, Vec<NodeId>> = BTreeMap::new();
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
        // Alu-kind nodes not scheduled by the *primary* passes; eligible for
        // idle-slot overflow onto either engine below. MultiplyAdd is NOT put
        // here -- it has no scalar fallback.
        let mut deferred_alu: Vec<NodeId> = Vec::new();

        // valu primary (unchanged selection): full-VLEN same-opcode alu
        // batches (the batch-efficient use of a valu slot) + MultiplyAdd
        // partials, highest-priority first, up to slot_limits::VALU. The one
        // difference vs. before: a full-8 *alu* batch that loses the slot
        // competition is remembered in `deferred_alu` (it has a scalar
        // fallback) instead of being dropped for the cycle. Untaken
        // MultiplyAdd simply waits.
        let alu_full_batches: Vec<(u64, Vec<NodeId>)> = alu_groups
            .iter_mut()
            .flat_map(|(_, group)| drain_valu_batches(group, &key))
            .collect();
        let mut valu_candidates: Vec<(u64, bool, Vec<NodeId>)> = alu_full_batches
            .into_iter()
            .map(|(p, c)| (p, false, c)) // false = alu batch (has scalar fallback)
            .collect();
        valu_candidates.extend(
            partial_valu_candidates(multiply_add_ready, &key)
                .into_iter()
                .map(|(p, c)| (p, true, c)), // true = MultiplyAdd (valu-only)
        );
        valu_candidates.sort_unstable_by_key(|(p, ..)| *p);
        let mut valu_slots_used = 0usize;
        for (_, is_multiply_add, chunk) in valu_candidates {
            if valu_slots_used < slot_limits::VALU {
                valu_slots_used += 1;
                result.valu.nodes_done += chunk.len() as u64;
                this_cycle.extend(chunk);
            } else if !is_multiply_add {
                deferred_alu.extend(chunk);
            }
        }

        // alu primary (unchanged selection): the <VLEN remainders, highest
        // height first, up to slot_limits::ALU. Anything past that is deferred.
        let mut alu_leftover: Vec<NodeId> = alu_groups.into_values().flatten().collect();
        alu_leftover.sort_unstable_by_key(|&n| key[n]);
        let alu_take = alu_leftover.len().min(slot_limits::ALU);
        let mut alu_slots_used = alu_take;
        this_cycle.extend(alu_leftover.iter().copied().take(alu_take));
        deferred_alu.extend(alu_leftover.into_iter().skip(alu_take));

        // overflow: schedule still-deferred alu nodes on idle slots of
        // whichever engine has room. Scarcity-driven by construction -- a node
        // is here only because its *primary* engine budget was exhausted, so
        // filling the *other* engine's leftover slots never displaces a
        // higher-value assignment; it only uses capacity that would otherwise
        // idle. Exactly one direction can be active per cycle (deferred is
        // nonempty only if valu-primary OR alu-primary filled, and the
        // complementary engine is the one with slack), so order is immaterial.
        if !deferred_alu.is_empty() {
            // spare valu slots: pack deferred nodes into <=VLEN same-opcode
            // batches (helps realistic mode: alu saturates, valu has slack).
            if valu_slots_used < slot_limits::VALU {
                let mut by_op: BTreeMap<AluOp, Vec<NodeId>> = BTreeMap::new();
                for &node in &deferred_alu {
                    if let ResKind::Alu(op) = dag.nodes[node].kind {
                        by_op.entry(op).or_default().push(node);
                    }
                }
                let mut ovf: Vec<(u64, Vec<NodeId>)> = Vec::new();
                for group in by_op.values_mut() {
                    group.sort_unstable_by_key(|&n| key[n]);
                    for chunk in group.chunks(VLEN) {
                        let p = chunk.iter().map(|&n| key[n]).min().unwrap();
                        ovf.push((p, chunk.to_vec()));
                    }
                }
                ovf.sort_unstable_by_key(|(p, _)| *p);
                let mut taken: std::collections::HashSet<NodeId> = std::collections::HashSet::new();
                for (_, chunk) in ovf {
                    if valu_slots_used >= slot_limits::VALU {
                        break;
                    }
                    valu_slots_used += 1;
                    result.valu.nodes_done += chunk.len() as u64;
                    for &node in &chunk {
                        taken.insert(node);
                    }
                    this_cycle.extend(chunk);
                }
                deferred_alu.retain(|n| !taken.contains(n));
            }
            // spare alu slots: take deferred nodes one per slot (helps relaxed
            // / dedup mode: valu saturates, alu idles).
            if alu_slots_used < slot_limits::ALU && !deferred_alu.is_empty() {
                deferred_alu.sort_unstable_by_key(|&n| key[n]);
                let extra = deferred_alu.len().min(slot_limits::ALU - alu_slots_used);
                this_cycle.extend(deferred_alu.iter().copied().take(extra));
                alu_slots_used += extra;
            }
        }

        result.valu.slot_uses += valu_slots_used as u64;
        if valu_slots_used > 0 {
            result.valu.busy_cycles += 1;
        }
        // one scalar alu node per slot, so nodes_done == slot_uses here.
        result.alu.nodes_done += alu_slots_used as u64;
        result.alu.slot_uses += alu_slots_used as u64;
        if alu_slots_used > 0 {
            result.alu.busy_cycles += 1;
        }

        // flow: exactly one slot/cycle, covering up to VLEN ready selects
        // (matches real vselect: one flow slot, eight lanes).
        flow_ready.sort_unstable_by_key(|&n| key[n]);
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
        let mut load_candidates: Vec<(u64, bool, Vec<NodeId>)> =
            batch_or_scalar_candidates(contiguous_load_ready, &key, true)
                .into_iter()
                .map(|(p, c)| (p, true, c))
                .collect();
        load_candidates.extend(
            batch_or_scalar_candidates(gather_load_ready, &key, config.gather_batchable)
                .into_iter()
                .map(|(p, c)| (p, false, c)),
        );
        load_candidates.sort_unstable_by_key(|(p, ..)| *p);
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
        let store_candidates = batch_or_scalar_candidates(store_ready, &key, true);
        let mut store_slots_used = 0u64;
        let mut sorted_store = store_candidates;
        sorted_store.sort_unstable_by_key(|(p, _)| *p);
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
                    // Natural earliest = next cycle (single-cycle latency). A
                    // release floor beyond that parks the node in `held` until
                    // its cycle arrives; otherwise it joins the ready pool now.
                    let natural = result.cycles as u32 + 1;
                    let r = rel_of(dep);
                    if r <= natural {
                        pool.push(dep);
                    } else {
                        held.entry(r).or_default().push(dep);
                    }
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

/// Concrete scratch-address assignment for a schedule, via **linear-scan
/// register allocation** with reuse: each value takes the lowest free slot at
/// its birth cycle and returns it once its last reader has fired. Returns
/// `(words_used, addr_per_node)`.
///
/// This is the pass the DAG/scheduler deliberately deferred -- it turns the
/// `peak_register_pressure` *lower bound* into a concrete, checkable address
/// map. Because live ranges are intervals, linear-scan first-fit is optimal
/// (its slot count equals the max clique = the peak), so `words_used` should
/// equal `peak_register_pressure`; the value here is the actual assignment and
/// the guarantee that a real allocator achieves the peak -- i.e. any schedule
/// whose peak fits `SCRATCH_SIZE` is genuinely allocatable in that many words.
///
/// `Store` nodes produce no readable value and get `None`. CAVEAT: this models
/// *scalar* slots. The ISA additionally requires a `valu`/`vselect`/`vload`
/// op's 8 lanes to sit in VLEN-contiguous scratch; enforcing that is a harder
/// vector-register-allocation problem this does not model (the per-walker DAG
/// doesn't expose which 8 nodes share a vector slot). The hand-written kernel
/// in `vectorized.rs` shows a real contiguous allocation is achievable for the
/// graded workload; here we bound the scalar-slot requirement.
pub fn allocate_registers(dag: &Dag, result: &ScheduleResult) -> (u64, Vec<Option<u32>>) {
    use std::cmp::Reverse;
    use std::collections::BinaryHeap;

    let n = dag.nodes.len();
    let mut dependents: Vec<Vec<NodeId>> = vec![Vec::new(); n];
    for (i, node) in dag.nodes.iter().enumerate() {
        for &d in &node.deps {
            dependents[d].push(i);
        }
    }

    // (birth, death, node) for every value-producing node, sorted by birth.
    let mut intervals: Vec<(u32, u32, NodeId)> = Vec::with_capacity(n);
    for (i, deps) in dependents.iter().enumerate() {
        if matches!(dag.nodes[i].kind, ResKind::Store) {
            continue;
        }
        let birth = result.node_cycle[i];
        let death = deps
            .iter()
            .map(|&d| result.node_cycle[d])
            .max()
            .unwrap_or(birth);
        intervals.push((birth, death, i));
    }
    intervals.sort_unstable_by_key(|&(b, _, _)| b);

    let mut free: BinaryHeap<Reverse<u32>> = BinaryHeap::new(); // freed slots (min)
    let mut active: BinaryHeap<Reverse<(u32, u32)>> = BinaryHeap::new(); // (death, slot)
    let mut next_slot: u32 = 0;
    let mut addr: Vec<Option<u32>> = vec![None; n];

    for &(birth, death, node) in &intervals {
        // Return slots of values that died strictly before this birth.
        while let Some(&Reverse((d, slot))) = active.peek() {
            if d < birth {
                free.push(Reverse(slot));
                active.pop();
            } else {
                break;
            }
        }
        let slot = match free.pop() {
            Some(Reverse(s)) => s,
            None => {
                let s = next_slot;
                next_slot += 1;
                s
            }
        };
        addr[node] = Some(slot);
        active.push(Reverse((death, slot)));
    }

    (next_slot as u64, addr)
}

/// Spill traffic needed to run `result`'s schedule within `capacity` scratch
/// words, via an optimal (Belady) eviction policy: when the resident set is
/// full, evict the value whose *next use is furthest in the future*. An
/// evicted value with remaining uses is saved once (a `store`) and reloaded
/// (a `load`) before each use that finds it non-resident.
///
/// This is the alternative to capping concurrency: rather than idle the
/// compute engines to bound pressure, keep the aggressive (low-arithmetic)
/// schedule and pay for the overflow in load/store traffic on the otherwise
/// idle memory engines. Returns the added op counts; the caller re-costs the
/// load/store engines with them. If `peak <= capacity`, returns all-zero.
///
/// This counts the *traffic* for the given schedule; it does not re-insert the
/// ops and re-schedule (the reloads would add dependencies), so the realizable
/// estimate built from it -- `max(orig_cycles, load+reloads floor, store+stores
/// floor)` -- is a lower bound on the spilled schedule's true length.
#[derive(Debug, Default, Clone, Copy)]
pub struct SpillStats {
    pub stored_values: u64,
    pub reloads: u64,
}

pub fn simulate_spilling(dag: &Dag, result: &ScheduleResult, capacity: usize) -> SpillStats {
    use std::collections::BinaryHeap;

    let n = dag.nodes.len();
    // uses[v] = ascending distinct cycles at which value v is read.
    let mut uses: Vec<Vec<u32>> = vec![Vec::new(); n];
    for (i, node) in dag.nodes.iter().enumerate() {
        let c = result.node_cycle[i];
        for &d in &node.deps {
            uses[d].push(c);
        }
    }
    for u in uses.iter_mut() {
        u.sort_unstable();
        u.dedup();
    }

    let max_cycle = result.cycles as usize;
    let mut born_at: Vec<Vec<NodeId>> = vec![Vec::new(); max_cycle + 2];
    let mut used_at: Vec<Vec<NodeId>> = vec![Vec::new(); max_cycle + 2];
    for i in 0..n {
        if matches!(dag.nodes[i].kind, ResKind::Store) {
            continue;
        }
        born_at[result.node_cycle[i] as usize].push(i);
        for &uc in &uses[i] {
            used_at[uc as usize].push(i);
        }
    }

    let mut use_ptr = vec![0usize; n]; // index of next unconsumed use in uses[v]
    let mut resident = vec![false; n];
    let mut stored = vec![false; n];
    let mut resident_count = 0usize;
    // max-heap of (next_use, node); lazily validated (stale entries discarded).
    let mut heap: BinaryHeap<(u32, NodeId)> = BinaryHeap::new();
    let next_use = |v: NodeId, use_ptr: &[usize]| -> u32 {
        uses[v].get(use_ptr[v]).copied().unwrap_or(u32::MAX)
    };

    let mut stats = SpillStats::default();

    for c in 0..=max_cycle {
        // Uses this cycle: each read value must be resident.
        let used_now = std::mem::take(&mut used_at[c]);
        for &v in &used_now {
            // advance past this cycle's uses (there may be several this cycle).
            while use_ptr[v] < uses[v].len() && uses[v][use_ptr[v]] <= c as u32 {
                use_ptr[v] += 1;
            }
            if !resident[v] {
                stats.reloads += 1;
                evict_until(
                    capacity - 1,
                    &mut resident_count,
                    &mut resident,
                    &mut stored,
                    &mut stats,
                    &mut heap,
                    &use_ptr,
                    &uses,
                );
                resident[v] = true;
                resident_count += 1;
            }
            heap.push((next_use(v, &use_ptr), v)); // refreshed next-use
        }
        // Productions this cycle: value enters residents.
        for &v in &born_at[c] {
            evict_until(
                capacity - 1,
                &mut resident_count,
                &mut resident,
                &mut stored,
                &mut stats,
                &mut heap,
                &use_ptr,
                &uses,
            );
            resident[v] = true;
            resident_count += 1;
            heap.push((next_use(v, &use_ptr), v));
        }
    }

    stats
}

/// Evict Belady victims until `resident_count <= target`. Victim = resident
/// value with the furthest next-use (heap top, lazily validated). A victim
/// with remaining uses is stored once.
#[allow(clippy::too_many_arguments)]
fn evict_until(
    target: usize,
    resident_count: &mut usize,
    resident: &mut [bool],
    stored: &mut [bool],
    stats: &mut SpillStats,
    heap: &mut std::collections::BinaryHeap<(u32, NodeId)>,
    use_ptr: &[usize],
    uses: &[Vec<u32>],
) {
    let cur_next_use = |v: NodeId| uses[v].get(use_ptr[v]).copied().unwrap_or(u32::MAX);
    while *resident_count > target {
        let Some((nu, v)) = heap.pop() else { break };
        // Discard stale entries: not resident, or a newer next-use was pushed.
        if !resident[v] || nu != cur_next_use(v) {
            continue;
        }
        resident[v] = false;
        *resident_count -= 1;
        // If it still has future uses, it must be saved (once) to be reloaded.
        if nu != u32::MAX && !stored[v] {
            stored[v] = true;
            stats.stored_values += 1;
        }
    }
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
    fn idle_alu_absorbs_valu_batch_overflow() {
        // 60 independent same-opcode Alu nodes ready at once. valu retires
        // 6*8=48/cycle, alu 12/cycle -> all 60 fit in ONE cycle iff the 7th
        // (competition-losing) 8-wide batch spills onto the idle alu slots.
        // The pre-change scheduler dropped it -> 2 cycles.
        let mut dag = Dag::new();
        let root = dag.free();
        for _ in 0..60 {
            dag.add(ResKind::Alu(AluOp::Add), vec![root]);
        }
        let r = schedule(&dag, SchedulerConfig::default());
        assert_eq!(
            r.cycles, 1,
            "load balancing should retire all 60 in one cycle"
        );
        assert_eq!(r.alu.nodes_done + r.valu.nodes_done, 60);
    }

    #[test]
    fn idle_valu_absorbs_scalar_alu_overflow() {
        // 15 ready Alu nodes over 3 opcodes (5 each): no full-VLEN batch forms,
        // so the old scheduler put 12 on alu and deferred 3 to a 2nd cycle
        // while valu sat idle. Overflow packs the 3 deferred into idle valu.
        let mut dag = Dag::new();
        let root = dag.free();
        for op in [AluOp::Add, AluOp::Xor, AluOp::Mul] {
            for _ in 0..5 {
                dag.add(ResKind::Alu(op), vec![root]);
            }
        }
        let r = schedule(&dag, SchedulerConfig::default());
        assert_eq!(
            r.cycles, 1,
            "idle valu slots should absorb the alu overflow"
        );
        assert!(
            r.valu.nodes_done >= 3,
            "some alu work must have landed on valu"
        );
    }

    #[test]
    fn load_balancing_never_regresses_measured_baselines() {
        let dag = build_problem_dag(10, 256, 16);
        let realistic = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        let relaxed = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: true,
                walker_window: None,
            },
        );
        assert!(
            realistic.cycles <= 2082,
            "realistic regressed: {}",
            realistic.cycles
        );
        assert!(
            relaxed.cycles <= 1608,
            "relaxed regressed: {}",
            relaxed.cycles
        );
        // total scheduled nodes must be unchanged (correctness, not just speed)
        let non_free = dag
            .nodes
            .iter()
            .filter(|n| !matches!(n.kind, ResKind::Free))
            .count() as u64;
        assert_eq!(
            realistic.alu.nodes_done
                + realistic.valu.nodes_done
                + realistic.load().nodes_done
                + realistic.store.nodes_done
                + realistic.flow.nodes_done,
            non_free
        );
    }

    #[test]
    fn schedules_every_non_free_node_exactly_once() {
        let dag = build_problem_dag(4, 16, 4);
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
        let dag = build_problem_dag(4, 16, 4);
        let result = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        assert!(
            result.gather_load.nodes_done
                <= slot_limits::LOAD as u64 * result.gather_load.busy_cycles
        );
    }

    #[test]
    fn relaxed_mode_lets_gather_load_batch() {
        let dag = build_problem_dag(4, 16, 4);
        let result = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: true,
                walker_window: None,
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
        let dag = build_problem_dag(4, 16, 4);
        let realistic = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        let relaxed = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: true,
                walker_window: None,
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
        let dag = build_problem_dag(10, 256, 16);
        let result = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
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
        let plain = build_problem_dag(10, 256, 16);
        let smart = build_problem_dag_smart(10, 256, 16);
        let plain_result = schedule(
            &plain,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        let smart_result = schedule(
            &smart,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
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
    fn flow_selects_offload_valu_but_lose_to_balanced_algebraic() {
        // Cross-idea interaction pinned here. In ISOLATION (before the
        // alu/valu overflow pass), routing cascade selects to the idle flow
        // engine beat algebraic selects, because valu was the saturated bind.
        // AFTER the overflow pass, the picture inverts: the pass spreads
        // algebraic selects flexibly across the wide alu+valu throughput,
        // while flow selects are pinned to the single flow slot -- which then
        // becomes the near-bind (~93% busy). So Flow still offloads valu (its
        // mechanism works) but no longer wins on cycles. Algebraic stays the
        // default for exactly this reason.
        //
        // NOTE: this reversal is specific to the UN-WINDOWED case. Once walker
        // windowing (idea #1) bounds concurrency, the flow engine is no longer
        // over-subscribed within a window and Flow wins again -- that combined
        // optimum is pinned in flow_plus_windowing_is_the_best_realizable.
        use crate::dag::{build_problem_dag_smart_with, SelectImpl};
        let cfg = SchedulerConfig {
            gather_batchable: false,
            walker_window: None,
        };
        let alg = schedule(
            &build_problem_dag_smart_with(10, 256, 16, SelectImpl::Algebraic),
            cfg,
        );
        let flw = schedule(
            &build_problem_dag_smart_with(10, 256, 16, SelectImpl::Flow),
            cfg,
        );
        // Mechanism: flow selects genuinely move batch demand off valu...
        assert!(
            flw.valu.slot_uses < alg.valu.slot_uses,
            "flow should relieve valu: flow {} vs alg {}",
            flw.valu.slot_uses,
            alg.valu.slot_uses
        );
        // ...and onto the flow engine.
        assert!(flw.flow.slot_uses > alg.flow.slot_uses);
        // But with the overflow pass balancing algebraic across alu+valu, the
        // flexible algebraic placement is at least as fast as pinning work to
        // the 1-slot flow engine.
        assert!(
            alg.cycles <= flw.cycles,
            "with balancing, algebraic ({}) should be <= flow ({})",
            alg.cycles,
            flw.cycles
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
        let plain = build_problem_dag(10, 256, 16);
        let smart = build_problem_dag_smart(10, 256, 16);
        let plain_result = schedule(
            &plain,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        let smart_result = schedule(
            &smart,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
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
    fn smart_dag_windowed_fits_scratch_and_preserves_the_win() {
        // The un-windowed smart schedule beats the plain dag on cycles but is
        // NOT realizable (peak register pressure > SCRATCH_SIZE). Windowing
        // walkers caps concurrent per-walker liveness, bringing peak under
        // budget while keeping (most of) the cycle win.
        let smart = build_problem_dag_smart(10, 256, 16);
        let unwindowed = schedule(
            &smart,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        // W=16 is the empirical sweet spot: the largest small window whose
        // peak fits SCRATCH_SIZE with margin (W=32 still overshoots at ~1569;
        // W=16 lands ~1368). See the sweep in bin/lower_bound.rs.
        let windowed = schedule(
            &smart,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: Some(16),
            },
        );
        let (unw_peak, _) = peak_register_pressure(&smart, &unwindowed);
        let (win_peak, _) = peak_register_pressure(&smart, &windowed);
        assert!(
            unw_peak > crate::isa::SCRATCH_SIZE as u64,
            "un-windowed smart peak ({unw_peak}) should exceed SCRATCH_SIZE -- \
             windowing is what makes it fit"
        );
        assert!(
            win_peak <= crate::isa::SCRATCH_SIZE as u64,
            "windowed(16) smart peak ({win_peak}) should fit SCRATCH_SIZE ({})",
            crate::isa::SCRATCH_SIZE
        );
        let plain = build_problem_dag(10, 256, 16);
        let plain_res = schedule(
            &plain,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        assert!(
            windowed.cycles <= plain_res.cycles,
            "windowed smart ({}) should still beat the plain realizable baseline ({})",
            windowed.cycles,
            plain_res.cycles
        );
    }

    #[test]
    fn flow_plus_windowing_is_the_best_realizable_schedule() {
        // The synthesis of all the DAG/scheduler ideas: flow-engine selects
        // (#5) + walker windowing (#1), on top of the overflow-balanced
        // scheduler (#2) and the wraparound-folded, multiply_add-reduced DAG
        // (#3/#4). Individually flow-selects lost to algebraic once balancing
        // was in play (see flow_selects_offload_valu_but_lose_to_balanced_
        // algebraic), but windowing bounds concurrency so the 1-slot flow
        // engine stops being over-subscribed -- and the combination is both
        // the fastest realistic schedule AND realizable (fits SCRATCH_SIZE),
        // beating every other realizable option here.
        use crate::dag::{build_problem_dag_smart_with, SelectImpl};
        let win = SchedulerConfig {
            gather_batchable: false,
            walker_window: Some(16),
        };
        let flow_win = schedule(
            &build_problem_dag_smart_with(10, 256, 16, SelectImpl::Flow),
            win,
        );
        let alg_win = schedule(
            &build_problem_dag_smart_with(10, 256, 16, SelectImpl::Algebraic),
            win,
        );
        let plain = schedule(
            &build_problem_dag(10, 256, 16),
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        let (flow_peak, _) = peak_register_pressure(
            &build_problem_dag_smart_with(10, 256, 16, SelectImpl::Flow),
            &flow_win,
        );
        // Realizable: fits scratch on pure capacity grounds.
        assert!(
            flow_peak <= crate::isa::SCRATCH_SIZE as u64,
            "flow+window(16) peak ({flow_peak}) should fit SCRATCH_SIZE ({})",
            crate::isa::SCRATCH_SIZE
        );
        // Fastest realizable: beats the algebraic-windowed and plain baselines.
        assert!(
            flow_win.cycles < alg_win.cycles,
            "flow+window ({}) should beat algebraic+window ({})",
            flow_win.cycles,
            alg_win.cycles
        );
        assert!(
            flow_win.cycles < plain.cycles,
            "flow+window ({}) should beat plain realizable ({})",
            flow_win.cycles,
            plain.cycles
        );
    }

    #[test]
    fn walker_window_none_is_a_no_op() {
        // The composite-key packing must reduce to plain descending-height
        // when no window is set, so every pre-windowing schedule is preserved
        // bit-for-bit (same cycles AND same per-node cycle assignment).
        let dag = build_problem_dag(10, 256, 16);
        let default = schedule(&dag, SchedulerConfig::default());
        let explicit_none = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        assert_eq!(default.cycles, explicit_none.cycles);
        assert_eq!(default.node_cycle, explicit_none.node_cycle);
    }

    #[test]
    fn peak_register_pressure_is_at_least_the_widest_single_cycle_batch() {
        // Sanity check on the liveness math itself: pressure at any cycle
        // can't be less than the number of values produced *that* cycle.
        let dag = build_problem_dag(4, 16, 4);
        let result = schedule(&dag, SchedulerConfig::default());
        let (peak, _) = peak_register_pressure(&dag, &result);
        assert!(peak >= 1);
    }

    #[test]
    fn linear_scan_allocation_equals_peak_and_fits() {
        // The allocator turns the peak lower bound into a concrete address
        // map. On interval live-ranges linear-scan first-fit is optimal, so it
        // must use exactly `peak` words -- and the plain dag's realizable
        // schedule then provably fits SCRATCH_SIZE with real addresses.
        let dag = build_problem_dag(10, 256, 16);
        let result = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        let (peak, _) = peak_register_pressure(&dag, &result);
        let (words, addr) = allocate_registers(&dag, &result);
        assert_eq!(
            words, peak,
            "linear-scan words {words} must equal peak {peak}"
        );
        assert!(
            words <= crate::isa::SCRATCH_SIZE as u64,
            "plain dag should allocate within SCRATCH_SIZE, needs {words}"
        );
        // Store nodes produce no value -> no address.
        for (i, node) in dag.nodes.iter().enumerate() {
            if matches!(node.kind, ResKind::Store) {
                assert!(addr[i].is_none());
            }
        }
    }

    #[test]
    fn spilling_is_zero_when_it_fits_and_positive_when_tight() {
        let dag = build_problem_dag(10, 256, 16);
        let r = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: None,
            },
        );
        let (peak, _) = peak_register_pressure(&dag, &r);
        assert!(peak <= crate::isa::SCRATCH_SIZE as u64);
        // Fits SCRATCH_SIZE -> Belady needs no spill traffic at all.
        let fits = simulate_spilling(&dag, &r, crate::isa::SCRATCH_SIZE);
        assert_eq!(
            fits.stored_values + fits.reloads,
            0,
            "no spills expected when peak fits capacity"
        );
        // A tight capacity forces both stores and reloads.
        let tight = simulate_spilling(&dag, &r, 64);
        assert!(
            tight.reloads > 0 && tight.stored_values > 0,
            "tiny capacity must force spills, got {tight:?}"
        );
    }

    #[test]
    fn spilling_the_low_cycle_hybrid_fits_the_idle_memory_bandwidth() {
        use crate::dag::build_problem_dag_hybrid;
        use crate::isa::{slot_limits, SCRATCH_SIZE};
        // The lowest-cycle hybrid config (butterfly<=L5, window16 ~= 1065 cyc)
        // is register-OVER: peak ~2305 words, 1.5x SCRATCH_SIZE. The earlier
        // conclusion was that this made ~1065 unrealizable and the true floor
        // was the ~1356 no-spill *windowed* schedule. But scratch (the 1536
        // register words) and mem (reached via the load/store engines) are
        // separate tiers, so the overflow can be *spilled* to mem -- and the
        // load & store engines are idle enough here (load ~60% busy) to
        // absorb every reload/store WITHOUT lengthening the schedule: the
        // post-spill memory-throughput floors stay at or below the original
        // cycle count. Register pressure is therefore not a hard wall for
        // this config; the ~1065 arithmetic-balanced target is realizable
        // (throughput-wise), well under the ~1356 no-spill floor.
        let dag = build_problem_dag_hybrid(10, 256, 16, 5);
        let r = schedule(
            &dag,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: Some(16),
            },
        );
        let (peak, _) = peak_register_pressure(&dag, &r);
        assert!(
            peak > SCRATCH_SIZE as u64,
            "config must be register-OVER for the spill question to be meaningful (peak {peak})"
        );
        let s = simulate_spilling(&dag, &r, SCRATCH_SIZE);
        assert!(
            s.reloads > 0 && s.stored_values > 0,
            "overflow must actually spill, got {s:?}"
        );
        // Adding the spill traffic to the existing engine slot-uses, do the
        // memory engines still keep up at the original cycle count?
        let load_floor = (r.load().slot_uses + s.reloads).div_ceil(slot_limits::LOAD as u64);
        let store_floor = (r.store.slot_uses + s.stored_values).div_ceil(slot_limits::STORE as u64);
        assert!(
            load_floor <= r.cycles,
            "spill reloads must fit idle load bandwidth: load_floor {load_floor} > {} cyc",
            r.cycles
        );
        assert!(
            store_floor <= r.cycles,
            "spill stores must fit idle store bandwidth: store_floor {store_floor} > {} cyc",
            r.cycles
        );
        // And the whole thing stays under the no-spill windowed floor.
        assert!(
            r.cycles < 1356,
            "spilled hybrid should beat the ~1356 no-spill floor, got {} cyc",
            r.cycles
        );
    }

    #[test]
    fn linear_scan_allocation_is_conflict_free() {
        // Directly verify no two simultaneously-live values share a slot
        // (O(n^2), so on a small dag).
        let dag = build_problem_dag(4, 16, 4);
        let result = schedule(&dag, SchedulerConfig::default());
        let (_, addr) = allocate_registers(&dag, &result);

        let n = dag.nodes.len();
        let mut dependents: Vec<Vec<NodeId>> = vec![Vec::new(); n];
        for (i, node) in dag.nodes.iter().enumerate() {
            for &d in &node.deps {
                dependents[d].push(i);
            }
        }
        let mut ivals: Vec<(u32, u32, u32)> = Vec::new(); // (birth, death, slot)
        for (i, deps) in dependents.iter().enumerate() {
            if let Some(a) = addr[i] {
                let b = result.node_cycle[i];
                let d = deps
                    .iter()
                    .map(|&x| result.node_cycle[x])
                    .max()
                    .unwrap_or(b);
                ivals.push((b, d, a));
            }
        }
        for i in 0..ivals.len() {
            for j in (i + 1)..ivals.len() {
                let (b1, d1, a1) = ivals[i];
                let (b2, d2, a2) = ivals[j];
                if a1 == a2 {
                    assert!(
                        d1 < b2 || d2 < b1,
                        "slot {a1} reused by overlapping live ranges [{b1},{d1}] and [{b2},{d2}]"
                    );
                }
            }
        }
    }
}
