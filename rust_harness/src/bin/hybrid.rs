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

fn print_schedule_line(label: &str, dag: &Dag, window: Option<u32>) {
    let schedule_result = schedule(
        dag,
        SchedulerConfig {
            gather_batchable: false,
            walker_window: window,
        },
    );
    let (peak, _) = peak_register_pressure(dag, &schedule_result);
    let busy_pct = |busy_cycles: u64| 100.0 * busy_cycles as f64 / schedule_result.cycles as f64;
    println!(
        "{label:<26} {:>6} cyc   alu {:>3.0}% valu {:>3.0}% flow {:>3.0}% load {:>3.0}%   peak {:>4} {}",
        schedule_result.cycles,
        busy_pct(schedule_result.alu.busy_cycles),
        busy_pct(schedule_result.valu.busy_cycles),
        busy_pct(schedule_result.flow.busy_cycles),
        busy_pct(schedule_result.load().busy_cycles),
        peak,
        if peak <= SCRATCH_SIZE as u64 { "fits" } else { "OVER" },
    );
}

/// For the given schedule (windowed as requested), print the spill traffic
/// needed to fit SCRATCH_SIZE and the resulting realizable-cycle lower bound.
fn print_spill_line(label: &str, dag: &Dag, window: Option<u32>) {
    let schedule_result = schedule(
        dag,
        SchedulerConfig {
            gather_batchable: false,
            walker_window: window,
        },
    );
    let (peak, _) = peak_register_pressure(dag, &schedule_result);
    if peak <= SCRATCH_SIZE as u64 {
        println!(
            "{label:<26} {:>6} cyc   peak {peak:>4} fits -- no spilling needed",
            schedule_result.cycles,
        );
        return;
    }
    let spill_stats = simulate_spilling(dag, &schedule_result, SCRATCH_SIZE);
    let load_slots_per_cycle = slot_limits::LOAD as u64;
    let store_slots_per_cycle = slot_limits::STORE as u64;
    // Memory floors after adding spill traffic to the existing slot uses.
    let load_floor =
        (schedule_result.load().slot_uses + spill_stats.reloads).div_ceil(load_slots_per_cycle);
    let store_floor = (schedule_result.store.slot_uses + spill_stats.stored_values)
        .div_ceil(store_slots_per_cycle);
    let realizable = schedule_result.cycles.max(load_floor).max(store_floor);
    println!(
        "{label:<26} {:>6} cyc   peak {peak:>4} OVER -> spill {} vals / {} reloads   \
         load-floor {} store-floor {}   realizable >= {}",
        schedule_result.cycles,
        spill_stats.stored_values,
        spill_stats.reloads,
        load_floor,
        store_floor,
        realizable,
    );
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let forest_height: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(10);
    let batch_size: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(256);
    let rounds: u32 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(16);
    let window: Option<u32> = args.get(4).and_then(|s| s.parse().ok());

    println!("hybrid flow/load crossover  (fh={forest_height} bs={batch_size} rounds={rounds} window={window:?}); hash floor ~887");
    for butterfly_max_level in 0..=forest_height {
        print_schedule_line(
            &format!("butterfly<=L{butterfly_max_level}, gather>L{butterfly_max_level}"),
            &build_problem_dag_hybrid(forest_height, batch_size, rounds, butterfly_max_level),
            window,
        );
    }
    print_schedule_line(
        "all-butterfly (K>=fh)",
        &build_problem_dag_hybrid(forest_height, batch_size, rounds, forest_height),
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
    for butterfly_max_level in 0..=forest_height {
        print_spill_line(
            &format!("butterfly<=L{butterfly_max_level}, gather>L{butterfly_max_level}"),
            &build_problem_dag_hybrid(forest_height, batch_size, rounds, butterfly_max_level),
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
    for butterfly_max_level in 0..=forest_height {
        rescheduled_spill_line(
            &format!("butterfly<=L{butterfly_max_level}, gather>L{butterfly_max_level}"),
            &build_problem_dag_hybrid(forest_height, batch_size, rounds, butterfly_max_level),
            spill_window,
        );
    }
}

/// Peak register pressure of `schedule_result` counting only *data* values (excluding
/// the rematerializable `Free` constants) -- the genuine working set, i.e. what
/// pressure would be once shared constants are coalesced to one word.
fn data_peak(dag: &Dag, schedule_result: &perf_harness::schedule::ScheduleResult) -> u64 {
    use perf_harness::dag::NodeKind;
    let node_count = dag.nodes.len();
    let mut consumers: Vec<Vec<usize>> = vec![Vec::new(); node_count];
    for (i, node) in dag.nodes.iter().enumerate() {
        for &dep_node in &node.deps {
            consumers[dep_node].push(i);
        }
    }
    let cycle_count = schedule_result.cycles as usize;
    let mut liveness_delta = vec![0i64; cycle_count + 2];
    for (i, node_consumers) in consumers.iter().enumerate() {
        if matches!(dag.nodes[i].kind, NodeKind::Store | NodeKind::Free) {
            continue;
        }
        let birth_cycle = schedule_result.node_cycle[i] as usize;
        let death_cycle = node_consumers
            .iter()
            .map(|&x| schedule_result.node_cycle[x] as usize)
            .max()
            .unwrap_or(birth_cycle);
        liveness_delta[birth_cycle] += 1;
        liveness_delta[death_cycle + 1] -= 1;
    }
    let (mut live, mut peak) = (0i64, 0i64);
    for cycle_delta in liveness_delta.iter().take(cycle_count + 1) {
        live += cycle_delta;
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
    let orig_schedule = schedule(dag, cfg);
    let (orig_peak, _) = peak_register_pressure(dag, &orig_schedule);
    let data_working_set_peak = data_peak(dag, &orig_schedule);

    // Step the Belady data target down by ~one window at a time, with a floor
    // so an unwindowed (window 0/None) schedule still makes progress.
    let step =
        (perf_harness::isa::VLEN * window.filter(|&w| w > 0).unwrap_or(16) as usize).max(128);
    let mut target = SCRATCH_SIZE;
    let mut last_attempt: (u64, u64, usize, usize, usize) = (0, 0, 0, 0, 0);
    for _ in 0..16 {
        let spilled = build_spilled_dag(dag, &orig_schedule, target);
        let spilled_schedule = schedule_with(&spilled.dag, cfg, &spilled.overrides);
        let (peak, _) = peak_register_pressure(&spilled.dag, &spilled_schedule);
        last_attempt = (
            spilled_schedule.cycles,
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
    let (cycles, peak, coalesced, stores, reloads) = last_attempt;
    println!(
        "{label:<26} orig {:>4}cyc peak {orig_peak:>4} (data {data_working_set_peak:>4})  ->  \
         coalesce {coalesced} const, spill {stores}v/{reloads}r  =>  {cycles}cyc peak {peak} {}",
        orig_schedule.cycles,
        if peak <= SCRATCH_SIZE as u64 {
            "FITS"
        } else {
            "OVER"
        },
    );
}
