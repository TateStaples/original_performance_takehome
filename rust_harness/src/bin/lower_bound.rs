//! Compiler-style lower-bound exploration: build the problem's true
//! dependency DAG (dag.rs) and run it through a greedy resource-constrained
//! list scheduler (schedule.rs) that ignores registers/memory layout
//! entirely. Reports the plain DAG (literal algorithm, per-walker gather
//! every round) and the "smart" DAG (exploits the shared root -- see
//! dag::build_problem_dag_smart) in both realistic (gather stays scalar)
//! and fully-relaxed (gather can batch too, idealized) scheduler modes, for
//! comparison against the analytical depth/width bounds and the current
//! hand-rolled kernel (4,990 cycles at batch_size=256, rounds=16).
//!
//! Usage: cargo run --release --bin lower_bound -- <forest_height> <batch_size> <rounds>

use perf_harness::dag::{build_problem_dag, build_problem_dag_smart, Dag};
use perf_harness::isa::SCRATCH_SIZE;
use perf_harness::schedule::{peak_register_pressure, schedule, SchedulerConfig};
use std::env;
use std::time::Instant;

fn main() {
    let args: Vec<String> = env::args().collect();
    let forest_height: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(10);
    let batch_size: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(256);
    let rounds: u32 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(16);

    let dags: [(&str, Dag); 2] = [
        (
            "plain (literal per-walker gather)",
            build_problem_dag(batch_size, rounds),
        ),
        (
            "smart (shared-root bounded fan-out)",
            build_problem_dag_smart(forest_height, batch_size, rounds),
        ),
    ];

    for (dag_label, dag) in &dags {
        println!("##### dag: {dag_label} ({} nodes) #####", dag.nodes.len());
        for (label, cfg) in [
            (
                "realistic (gather stays scalar)",
                SchedulerConfig {
                    gather_batchable: false,
                },
            ),
            (
                "fully relaxed (gather can batch too)",
                SchedulerConfig {
                    gather_batchable: true,
                },
            ),
        ] {
            let t1 = Instant::now();
            let result = schedule(dag, cfg);
            let (peak, peak_cycle) = peak_register_pressure(dag, &result);
            println!("=== {label} ===");
            println!("{result}");
            println!(
                "peak register pressure: {peak} words (at cycle {peak_cycle}) -- {} SCRATCH_SIZE={SCRATCH_SIZE}",
                if peak > SCRATCH_SIZE as u64 { format!("{:.1}x OVER", peak as f64 / SCRATCH_SIZE as f64) } else { "within".to_string() }
            );
            eprintln!("scheduled in {:?}", t1.elapsed());
        }
    }
}
