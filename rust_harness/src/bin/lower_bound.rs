//! Compiler-style lower-bound exploration: build the problem's true
//! dependency DAG (dag.rs) and run it through a greedy resource-constrained
//! list scheduler (schedule.rs) that ignores registers/memory layout
//! entirely. Reports both the realistic mode (tree-node gather stays
//! scalar) and the fully-relaxed mode (everything can batch), for
//! comparison against the analytical depth/width bounds and the current
//! hand-rolled kernel.
//!
//! Usage: cargo run --release --bin lower_bound -- <batch_size> <rounds>

use perf_harness::dag::build_problem_dag;
use perf_harness::schedule::{schedule, SchedulerConfig};
use std::env;
use std::time::Instant;

fn main() {
    let args: Vec<String> = env::args().collect();
    let batch_size: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(256);
    let rounds: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(16);

    let t0 = Instant::now();
    let dag = build_problem_dag(batch_size, rounds);
    eprintln!(
        "dag: {} nodes, built in {:?}",
        dag.nodes.len(),
        t0.elapsed()
    );

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
        let result = schedule(&dag, cfg);
        println!("=== {label} ===");
        println!("{result}");
        eprintln!("scheduled in {:?}", t1.elapsed());
    }
}
