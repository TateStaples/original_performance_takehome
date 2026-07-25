//! Fast local iteration loop: build the naive kernel, run it against an
//! exported fixture with step-by-step debug compares enabled, and report
//! the cycle count — the Rust-side equivalent of
//! `perf_takehome.py Tests.test_kernel_cycles`, without paying Python's
//! per-cycle interpreter overhead.
//!
//! Usage: cargo run --release --bin simulate -- <fixture.json>

use perf_harness::{builder, fixtures::Fixture, machine::Machine};
use std::env;
use std::time::Instant;

fn main() {
    let args: Vec<String> = env::args().collect();
    let fixture_path = args.get(1).unwrap_or_else(|| {
        eprintln!("usage: simulate <fixture.json>");
        std::process::exit(2);
    });

    let fixture = Fixture::load(fixture_path);
    let params = &fixture.params;
    let program = builder::build_kernel_naive(
        params.forest_height,
        params.n_nodes,
        params.batch_size,
        params.rounds,
    );

    let mut machine = Machine::new(fixture.mem_in.clone(), program);
    if fixture.trace.is_empty() {
        // No per-step trace in this fixture (e.g. the full-scale "baseline"
        // fixture, which omits it — see tools/export_fixtures.py) -- so
        // there's nothing for a debug::Compare to check against; skip
        // straight to the final-memory comparison below instead.
        machine.enable_debug = false;
    } else {
        machine = machine.with_value_trace(fixture.trace.clone());
    }

    let start = Instant::now();
    machine.run(); // first pause: header is loaded
    machine.run(); // second pause: kernel body ran to completion
    let elapsed = start.elapsed();

    let is_correct = machine.mem == fixture.mem_out;
    println!("CYCLES: {}", machine.cycle);
    println!("wall time: {elapsed:?}");
    println!("correct: {is_correct}");
    if !is_correct {
        let first_diff = machine
            .mem
            .iter()
            .zip(fixture.mem_out.iter())
            .position(|(actual, expected)| actual != expected);
        eprintln!("first mismatch at mem[{first_diff:?}]");
        std::process::exit(1);
    }
}
