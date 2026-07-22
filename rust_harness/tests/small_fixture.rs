//! Fast, small-scale correctness test with full step-by-step debug compares
//! enabled — this is the one to run constantly while developing (`cargo
//! test small_fixture`, milliseconds), vs. `matches_python_baseline`'s
//! full-scale (but debug-disabled) run.

use perf_harness::builder::build_kernel_naive;
use perf_harness::fixtures::Fixture;
use perf_harness::machine::Machine;

fn fixture_path(name: &str) -> String {
    format!("{}/tests/fixtures/{name}.json", env!("CARGO_MANIFEST_DIR"))
}

#[test]
fn naive_kernel_passes_every_debug_compare_on_the_small_fixture() {
    let fixture = Fixture::load(fixture_path("small"));
    let p = &fixture.params;
    assert!(!fixture.trace.is_empty(), "small fixture should carry a value trace");

    let program = build_kernel_naive(p.forest_height, p.n_nodes, p.batch_size, p.rounds);
    let mut machine = Machine::new(fixture.mem_in.clone(), program).with_trace(fixture.trace.clone());

    machine.run();
    machine.run();

    assert_eq!(machine.mem, fixture.mem_out);
}
