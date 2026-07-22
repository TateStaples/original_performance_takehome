//! Print per-engine slot-utilization statistics for a kernel-building
//! function, to check "did the theory actually work" after an optimization
//! step (see docs/problem.md and rust_harness/README.md).
//!
//! Usage: cargo run --release --bin stats -- <naive|valu|pipelined> <n_nodes> <batch_size> <rounds> [pipeline_width]

use perf_harness::builder::build_kernel_naive;
use perf_harness::stats::{analyze, engines_per_bundle_histogram};
use perf_harness::vectorized::build_kernel_vectorized;
use std::env;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 5 {
        eprintln!(
            "usage: {} <naive|valu|pipelined> <n_nodes> <batch_size> <rounds> [pipeline_width]",
            args.first().map(String::as_str).unwrap_or("stats")
        );
        std::process::exit(2);
    }
    let kind = args[1].as_str();
    let n_nodes: u32 = args[2].parse().unwrap();
    let batch_size: u32 = args[3].parse().unwrap();
    let rounds: u32 = args[4].parse().unwrap();

    let program = match kind {
        "naive" => build_kernel_naive(0, n_nodes, batch_size, rounds),
        "valu" => build_kernel_vectorized(batch_size, rounds, 1),
        "pipelined" => {
            let p: usize = args.get(5).map(|s| s.parse().unwrap()).unwrap_or(6);
            build_kernel_vectorized(batch_size, rounds, p)
        }
        other => {
            eprintln!("unknown kind {other:?}, expected naive|valu|pipelined");
            std::process::exit(2);
        }
    };

    let s = analyze(&program);
    println!("{s}");
    println!("engines active per bundle (non-debug, non-empty bundles):");
    for (n, count) in engines_per_bundle_histogram(&program) {
        println!("  {n} engine(s): {count} bundles");
    }
}
