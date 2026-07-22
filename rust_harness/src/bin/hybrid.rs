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
    peak_register_pressure, schedule, schedule_with, simulate_spilling, SchedulerConfig,
};
use perf_harness::spill::build_spilled_dag;
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

    // Concrete placement-aware realization: build a real DAG (constants shared,
    // data spilled) and RE-SCHEDULE it, so the peak is genuinely <=
    // SCRATCH_SIZE (not just a throughput lower bound). This converts the
    // "realizable >= X" bound above into a measured, achievable cycle count.
    //
    // The measured peak has two sources (see src/spill.rs): a *cycle-0 constant
    // floor* of one Free node per walker per constant-use -- 2048 redundant
    // per-walker copies of a handful of shared compile-time constants, which no
    // fixed-schedule spiller can relieve (all born at cycle 0) -- and the
    // genuine *data working set*. Sharing the constants (coalesce) removes the
    // artifact; data spilling handles the rest.
    println!(
        "\nconcrete realization: coalesce shared constants + placement-aware data spill, \
         then RE-SCHEDULE (window={spill_window:?}); re-sched peak must be <= {SCRATCH_SIZE}"
    );
    for k in 0..=fh {
        rescheduled_spill_line(
            &format!("butterfly<=L{k}, gather>L{k}"),
            &build_problem_dag_hybrid(fh, bs, rr, k),
            spill_window,
        );
    }
}

/// Peak register pressure of `result` counting only *data* values (excluding
/// the rematerializable `Free` constants) -- the genuine working set, i.e. what
/// pressure would be once shared constants are coalesced to one word.
fn data_peak(dag: &Dag, result: &perf_harness::schedule::ScheduleResult) -> u64 {
    use perf_harness::dag::ResKind;
    let n = dag.nodes.len();
    let mut deps: Vec<Vec<usize>> = vec![Vec::new(); n];
    for (i, nd) in dag.nodes.iter().enumerate() {
        for &d in &nd.deps {
            deps[d].push(i);
        }
    }
    let maxc = result.cycles as usize;
    let mut delta = vec![0i64; maxc + 2];
    for (i, di) in deps.iter().enumerate() {
        if matches!(dag.nodes[i].kind, ResKind::Store | ResKind::Free) {
            continue;
        }
        let b = result.node_cycle[i] as usize;
        let d = di
            .iter()
            .map(|&x| result.node_cycle[x] as usize)
            .max()
            .unwrap_or(b);
        delta[b] += 1;
        delta[d + 1] -= 1;
    }
    let (mut live, mut peak) = (0i64, 0i64);
    for d in delta.iter().take(maxc + 1) {
        live += d;
        peak = peak.max(live);
    }
    peak as u64
}

/// Build a concrete realized DAG for `dag`'s windowed schedule and re-schedule
/// it, reporting the achievable cycle count and realized peak. Coalescing the
/// constant pool is unconditional; the Belady *data* target starts at the cap
/// and steps down a window at a time only if the re-scheduled peak still
/// overshoots (leaving headroom for just-in-time reload births).
fn rescheduled_spill_line(label: &str, dag: &Dag, window: Option<u32>) {
    let cfg = SchedulerConfig {
        gather_batchable: false,
        walker_window: window,
    };
    let r = schedule(dag, cfg);
    let (orig_peak, _) = peak_register_pressure(dag, &r);
    let dpeak = data_peak(dag, &r);

    // Step the Belady data target down by ~one window at a time, with a floor
    // so an unwindowed (window 0/None) schedule still makes progress.
    let step =
        (perf_harness::isa::VLEN * window.filter(|&w| w > 0).unwrap_or(16) as usize).max(128);
    let mut target = SCRATCH_SIZE;
    let mut best: (u64, u64, usize, usize, usize) = (0, 0, 0, 0, 0);
    for _ in 0..16 {
        let spilled = build_spilled_dag(dag, &r, target);
        let sr = schedule_with(&spilled.dag, cfg, &spilled.overrides);
        let (peak, _) = peak_register_pressure(&spilled.dag, &sr);
        best = (
            sr.cycles,
            peak,
            spilled.coalesced_free,
            spilled.num_stores,
            spilled.num_reloads,
        );
        if peak <= SCRATCH_SIZE as u64 || target <= step {
            break;
        }
        target -= step;
    }
    let (cycles, peak, coalesced, stores, reloads) = best;
    println!(
        "{label:<26} orig {:>4}cyc peak {orig_peak:>4} (data {dpeak:>4})  ->  \
         coalesce {coalesced} const, spill {stores}v/{reloads}r  =>  {cycles}cyc peak {peak} {}",
        r.cycles,
        if peak <= SCRATCH_SIZE as u64 {
            "FITS"
        } else {
            "OVER"
        },
    );
}
