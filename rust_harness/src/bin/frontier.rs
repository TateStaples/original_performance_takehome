//! Sweep the gather-vs-cascade dial: for each sharing threshold (how many
//! tree levels are read contiguously + routed with a per-walker select
//! cascade, vs. left as per-walker gathers), report the realistic-mode
//! schedule under both select lowerings, with walker windowing on. Answers
//! "how low can we push the schedule by trading gather-loads for cascade
//! selects" -- and shows where the crossover actually is, since the cascade
//! is the only valid routing in this ISA (no cross-lane shuffle -> no cheaper
//! network; see build_problem_dag_smart_tuned).
//!
//! Usage: cargo run --release --bin frontier -- <forest_height> <batch_size> <rounds> [window]

use perf_harness::dag::{build_problem_dag_smart_tuned, SelectImpl};
use perf_harness::isa::SCRATCH_SIZE;
use perf_harness::schedule::{peak_register_pressure, schedule, ScheduleResult, SchedulerConfig};
use std::env;

fn binding_engine(result: &ScheduleResult) -> String {
    let total_cycles = result.cycles as f64;
    let busy_percentage = |engine: &perf_harness::schedule::EngineTotals| {
        100.0 * engine.busy_cycles as f64 / total_cycles
    };
    let mut engine_percentages = [
        ("alu", busy_percentage(&result.alu)),
        ("valu", busy_percentage(&result.valu)),
        ("load", busy_percentage(&result.load())),
        ("flow", busy_percentage(&result.flow)),
    ];
    engine_percentages.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    format!(
        "{} {:.0}%",
        engine_percentages[0].0, engine_percentages[0].1
    )
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let forest_height: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(10);
    let batch_size: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(256);
    let rounds: u32 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(16);
    let window: Option<u32> = args.get(4).and_then(|s| s.parse().ok());

    println!(
        "forest_height={forest_height} batch_size={batch_size} rounds={rounds} window={window:?}  (SCRATCH_SIZE={SCRATCH_SIZE})"
    );
    println!(
        "{:>9} {:>10} {:>8} {:>9} {:>7} {:>7} {:>12}",
        "threshold", "select", "cycles", "gathers", "g-floor", "peak", "binds/fits"
    );

    for select in [SelectImpl::Algebraic, SelectImpl::Flow] {
        for threshold in 0..=(forest_height + 1) {
            let dag =
                build_problem_dag_smart_tuned(forest_height, batch_size, rounds, select, threshold);
            let cfg = SchedulerConfig {
                gather_batchable: false,
                walker_window: window,
            };
            let result = schedule(&dag, cfg);
            let (peak, _) = peak_register_pressure(&dag, &result);
            let gathers = result.gather_load.nodes_done;
            let gather_floor = gathers.div_ceil(2);
            let fit_status = if peak <= SCRATCH_SIZE as u64 {
                "fits"
            } else {
                "OVER"
            };
            println!(
                "{:>9} {:>10} {:>8} {:>9} {:>7} {:>7} {:>5} {:>6}",
                threshold,
                format!("{select:?}"),
                result.cycles,
                gathers,
                gather_floor,
                peak,
                binding_engine(&result),
                fit_status,
            );
        }
        println!();
    }
}
