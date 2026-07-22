//! Sweep the hybrid router's flow/load crossover: butterfly levels
//! <= K (flow), gather deeper levels (load). Report the scheduled cycles and
//! per-engine busy% so the balance point -- where no single engine exceeds
//! the ~887 hash floor -- is visible. Also prints the two extremes
//! (all-butterfly, all-gather via idxlite).
//!
//! For the *unwindowed* (max-ILP) schedule of each config we also run the
//! Belady spilling simulator (schedule::simulate_spilling) at SCRATCH_SIZE
//! and print a realizable-cycle *lower bound*: spilling the register overflow
//! adds load traffic (reloads) and store traffic (stored values), so the
//! spilled schedule can be no shorter than
//!   max(orig_cycles, (load_slots + reloads)/2, (store_slots + stores)/2).
//! This answers "does the ~1065 hybrid stay below the ~1356 windowed floor
//! once its 2x register overflow is actually spilled to memory?"
//!
//! Usage: cargo run --release --bin hybrid -- <forest_height> <batch_size> <rounds> [window]

use perf_harness::dag::{build_problem_dag_hybrid, Dag};
use perf_harness::isa::{slot_limits, SCRATCH_SIZE};
use perf_harness::schedule::{
    peak_register_pressure, schedule, simulate_spilling, SchedulerConfig,
};
use std::env;

fn line(label: &str, dag: &Dag, window: Option<u32>) {
    let r = schedule(
        dag,
        SchedulerConfig {
            gather_batchable: false,
            walker_window: window,
        },
    );
    let (peak, _) = peak_register_pressure(dag, &r);
    let pct = |b: u64| 100.0 * b as f64 / r.cycles as f64;
    println!(
        "{label:<26} {:>6} cyc   alu {:>3.0}% valu {:>3.0}% flow {:>3.0}% load {:>3.0}%   peak {:>4} {}",
        r.cycles,
        pct(r.alu.busy_cycles),
        pct(r.valu.busy_cycles),
        pct(r.flow.busy_cycles),
        pct(r.load().busy_cycles),
        peak,
        if peak <= SCRATCH_SIZE as u64 { "fits" } else { "OVER" },
    );
}

/// For the given schedule (windowed as requested), print the spill traffic
/// needed to fit SCRATCH_SIZE and the resulting realizable-cycle lower bound.
fn spill_line(label: &str, dag: &Dag, window: Option<u32>) {
    let r = schedule(
        dag,
        SchedulerConfig {
            gather_batchable: false,
            walker_window: window,
        },
    );
    let (peak, _) = peak_register_pressure(dag, &r);
    if peak <= SCRATCH_SIZE as u64 {
        println!(
            "{label:<26} {:>6} cyc   peak {peak:>4} fits -- no spilling needed",
            r.cycles,
        );
        return;
    }
    let s = simulate_spilling(dag, &r, SCRATCH_SIZE);
    let lpc = slot_limits::LOAD as u64;
    let spc = slot_limits::STORE as u64;
    // Memory floors after adding spill traffic to the existing slot uses.
    let load_floor = (r.load().slot_uses + s.reloads).div_ceil(lpc);
    let store_floor = (r.store.slot_uses + s.stored_values).div_ceil(spc);
    let realizable = r.cycles.max(load_floor).max(store_floor);
    println!(
        "{label:<26} {:>6} cyc   peak {peak:>4} OVER -> spill {} vals / {} reloads   \
         load-floor {} store-floor {}   realizable >= {}",
        r.cycles, s.stored_values, s.reloads, load_floor, store_floor, realizable,
    );
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let fh: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(10);
    let bs: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(256);
    let rr: u32 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(16);
    let window: Option<u32> = args.get(4).and_then(|s| s.parse().ok());

    println!("hybrid flow/load crossover  (fh={fh} bs={bs} rounds={rr} window={window:?}); hash floor ~887");
    for k in 0..=fh {
        line(
            &format!("butterfly<=L{k}, gather>L{k}"),
            &build_problem_dag_hybrid(fh, bs, rr, k),
            window,
        );
    }
    line(
        "all-butterfly (K>=fh)",
        &build_problem_dag_hybrid(fh, bs, rr, fh),
        window,
    );

    // The spilling question: the low-cycle configs (e.g. butterfly<=L5,
    // window16 ~= 1065 cyc) are register-OVER. Take *that* schedule and ask
    // how many cycles it costs once the overflow is spilled to the (mostly
    // idle) memory engines. If the realizable lower bound stays under the
    // ~1356 no-spill windowed floor, spilling wins; otherwise windowing does.
    let spill_window = window.or(Some(16));
    println!(
        "\nspill analysis (window={spill_window:?} schedule; load {}/cyc store {}/cyc; \
         best no-spill windowed floor ~1356)",
        slot_limits::LOAD,
        slot_limits::STORE,
    );
    for k in 0..=fh {
        spill_line(
            &format!("butterfly<=L{k}, gather>L{k}"),
            &build_problem_dag_hybrid(fh, bs, rr, k),
            spill_window,
        );
    }
}
