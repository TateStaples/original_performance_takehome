//! Builds a kernel program in Rust and prints it as JSON in the exact shape
//! `KernelBuilder.instrs` expects, for `tools/load_rust_kernel.py` to load
//! into a real `perf_takehome.py` `KernelBuilder` for grading.
//!
//! Usage:
//!   cargo run --release --bin gen_kernel -- <forest_height> <n_nodes> <batch_size> <rounds> [out.json]
//!
//! With no output path, writes JSON to stdout.

use perf_harness::{bridge, builder};
use std::env;
use std::fs;

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 5 {
        eprintln!(
            "usage: {} <forest_height> <n_nodes> <batch_size> <rounds> [out.json]",
            args.first().map(String::as_str).unwrap_or("gen_kernel")
        );
        std::process::exit(2);
    }
    let forest_height: u32 = args[1].parse().expect("forest_height must be an integer");
    let n_nodes: u32 = args[2].parse().expect("n_nodes must be an integer");
    let batch_size: u32 = args[3].parse().expect("batch_size must be an integer");
    let rounds: u32 = args[4].parse().expect("rounds must be an integer");

    let program = builder::build_kernel_naive(forest_height, n_nodes, batch_size, rounds);
    let json = bridge::program_to_python_json(&program);
    let json_text = serde_json::to_string(&json).expect("serialize");

    eprintln!(
        "gen_kernel: {} bundles ({} forest_height, {} n_nodes, {} batch_size, {} rounds)",
        program.len(),
        forest_height,
        n_nodes,
        batch_size,
        rounds
    );

    if let Some(path) = args.get(5) {
        fs::write(path, json_text).unwrap_or_else(|e| panic!("writing {path}: {e}"));
        eprintln!("wrote {path}");
    } else {
        println!("{json_text}");
    }
}
