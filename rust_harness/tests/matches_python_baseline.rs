//! The trust-building test: proves the Rust `Machine` + ported
//! `build_kernel_naive` are faithful to the real Python simulator by
//! running them against a fixture exported straight from `problem.py`
//! (`tools/export_fixtures.py`) for exactly the benchmark workload
//! (`forest_height=10, batch_size=256, rounds=16`) and checking both the
//! cycle count and the final memory against what Python actually produced.
//!
//! If this test ever fails after touching `isa.rs`/`machine.rs`/
//! `builder.rs`, treat it as a port bug, not a fixture problem — regenerate
//! fixtures with `python tools/export_fixtures.py` only if `problem.py`
//! itself changed.

use perf_harness::builder::build_kernel_naive;
use perf_harness::fixtures::Fixture;
use perf_harness::machine::Machine;

fn fixture_path(name: &str) -> String {
    format!("{}/tests/fixtures/{name}.json", env!("CARGO_MANIFEST_DIR"))
}

/// `BASELINE` in `perf_takehome.py` — the shipped, unoptimized kernel's
/// cycle count for this exact workload. Hardcoded (rather than computed) so
/// this test also catches an accidental change to the *naive* baseline
/// itself, not just a Rust/Python mismatch.
const PYTHON_BASELINE_CYCLES: u64 = 147_734;

#[test]
fn naive_kernel_matches_python_cycle_count_and_output() {
    let fixture = Fixture::load(fixture_path("baseline"));
    let p = &fixture.params;
    assert_eq!(p.forest_height, 10);
    assert_eq!(p.batch_size, 256);
    assert_eq!(p.rounds, 16);

    let program = build_kernel_naive(p.forest_height, p.n_nodes, p.batch_size, p.rounds);

    let mut machine = Machine::new(fixture.mem_in.clone(), program);
    machine.enable_debug = false; // no trace loaded for this (large) fixture
    machine.run(); // header-load pause
    machine.run(); // run to completion

    assert_eq!(
        machine.cycle, PYTHON_BASELINE_CYCLES,
        "Rust cycle count diverged from Python's BASELINE — check isa.rs/machine.rs/builder.rs \
         against problem.py/perf_takehome.py for a semantic drift"
    );
    assert_eq!(
        machine.mem, fixture.mem_out,
        "final memory diverged from what Python's reference_kernel2 produced"
    );
}
