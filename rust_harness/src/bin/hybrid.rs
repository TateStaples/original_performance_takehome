//! Sweep the hybrid router's flow/load crossover: butterfly levels
//! <= K (flow), gather deeper levels (load). Report the scheduled cycles and
//! per-engine busy% so the balance point -- where no single engine exceeds
//! the ~887 hash floor -- is visible. Also prints the two extremes
//! (all-butterfly, all-gather via idxlite).
//!
//! Usage: cargo run --release --bin hybrid -- <forest_height> <batch_size> <rounds> [window]

use perf_harness::dag::{build_problem_dag_hybrid, Dag};
use perf_harness::schedule::{peak_register_pressure, schedule, SchedulerConfig};
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
        if peak <= 1536 { "fits" } else { "OVER" },
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
}
