//! Per-engine slot-utilization statistics for a built `Program`, computed
//! directly from the typed instruction stream (no trace.json/Perfetto
//! needed, unlike the earlier introspection pass on the naive baseline).
//! This is how each optimization step's "did the theory actually work"
//! claim gets checked: e.g. "valu should now be busy every cycle during the
//! hash computation" or "load is the new bottleneck."

use crate::isa::{slot_limits, Bundle, Program};
use std::fmt;

#[derive(Debug, Default, Clone, Copy)]
pub struct EngineStats {
    pub used_slots: u64,
    pub capacity_slots: u64,
    pub busy_cycles: u64, // cycles where this engine has >=1 slot filled
}

impl EngineStats {
    pub fn utilization_pct(&self) -> f64 {
        if self.capacity_slots == 0 {
            0.0
        } else {
            100.0 * self.used_slots as f64 / self.capacity_slots as f64
        }
    }
    pub fn busy_pct(&self, total_cycles: u64) -> f64 {
        if total_cycles == 0 {
            0.0
        } else {
            100.0 * self.busy_cycles as f64 / total_cycles as f64
        }
    }
}

#[derive(Debug, Default)]
pub struct ProgramStats {
    pub total_cycles: u64,
    pub alu: EngineStats,
    pub valu: EngineStats,
    pub load: EngineStats,
    pub store: EngineStats,
    pub flow: EngineStats,
}

pub fn analyze(program: &Program) -> ProgramStats {
    let mut stats = ProgramStats::default();
    for bundle in program {
        if !bundle.costs_a_cycle() {
            continue; // matches Machine's cycle-counting rule (docs/isa.md §2)
        }
        stats.total_cycles += 1;
        accumulate(&mut stats.alu, bundle.alu.len(), slot_limits::ALU);
        accumulate(&mut stats.valu, bundle.valu.len(), slot_limits::VALU);
        accumulate(&mut stats.load, bundle.load.len(), slot_limits::LOAD);
        accumulate(&mut stats.store, bundle.store.len(), slot_limits::STORE);
        accumulate(&mut stats.flow, bundle.flow.len(), slot_limits::FLOW);
    }
    stats
}

fn accumulate(stats: &mut EngineStats, used: usize, limit: usize) {
    stats.used_slots += used as u64;
    stats.capacity_slots += limit as u64;
    if used > 0 {
        stats.busy_cycles += 1;
    }
}

/// Distribution of how many bundles have exactly N non-debug engines active
/// at once (1 = fully serial, like the shipped baseline; higher = better
/// cross-engine packing).
pub fn engines_per_bundle_histogram(program: &Program) -> Vec<(usize, u64)> {
    let mut counts = [0u64; 6];
    for bundle in program {
        if !bundle.costs_a_cycle() {
            continue;
        }
        let active_engine_count = active_engine_count(bundle);
        counts[active_engine_count] += 1;
    }
    counts
        .iter()
        .enumerate()
        .filter(|(_, &c)| c > 0)
        .map(|(active_engine_count, &c)| (active_engine_count, c))
        .collect()
}

fn active_engine_count(bundle: &Bundle) -> usize {
    [
        !bundle.alu.is_empty(),
        !bundle.valu.is_empty(),
        !bundle.load.is_empty(),
        !bundle.store.is_empty(),
        !bundle.flow.is_empty(),
    ]
    .into_iter()
    .filter(|x| *x)
    .count()
}

impl fmt::Display for ProgramStats {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        writeln!(f, "total cycles: {}", self.total_cycles)?;
        writeln!(
            f,
            "{:<7} {:>10} {:>12} {:>9}   {:>9}",
            "engine", "used", "capacity", "fill%", "busy%"
        )?;
        for (name, engine_stats) in [
            ("alu", self.alu),
            ("valu", self.valu),
            ("load", self.load),
            ("store", self.store),
            ("flow", self.flow),
        ] {
            writeln!(
                f,
                "{:<7} {:>10} {:>12} {:>8.2}%   {:>8.2}%",
                name,
                engine_stats.used_slots,
                engine_stats.capacity_slots,
                engine_stats.utilization_pct(),
                engine_stats.busy_pct(self.total_cycles)
            )?;
        }
        Ok(())
    }
}
