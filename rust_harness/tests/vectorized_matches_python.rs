//! Correctness of the vectorized/pipelined kernel (src/vectorized.rs),
//! checked the same way as the naive baseline: against fixtures exported
//! straight from the real problem.py (tools/export_fixtures.py). Run for
//! both pipeline_width=1 (vectorize-only) and pipeline_width=6 (the
//! packing sweet spot -- see vectorized.rs's module docs) since they build
//! genuinely different bundle sequences and either could hide a bug the
//! other doesn't exercise.

use perf_harness::fixtures::Fixture;
use perf_harness::machine::Machine;
use perf_harness::vectorized::build_kernel_vectorized;

fn fixture_path(name: &str) -> String {
    format!("{}/tests/fixtures/{name}.json", env!("CARGO_MANIFEST_DIR"))
}

fn run_vectorized_kernel(fixture: &Fixture, pipeline_width: usize) -> Machine {
    let params = &fixture.params;
    let program = build_kernel_vectorized(params.batch_size, params.rounds, pipeline_width);
    let mut machine = Machine::new(fixture.mem_in.clone(), program);
    machine.enable_debug = false; // this kernel doesn't emit debug slots (see module docs)
    machine.run(); // header-load pause
    machine.run(); // run to completion
    machine
}

#[test]
fn small_fixture_pipeline_width_1() {
    let fixture = Fixture::load(fixture_path("small"));
    let machine = run_vectorized_kernel(&fixture, 1);
    assert_eq!(machine.mem, fixture.mem_out);
}

#[test]
fn small_fixture_pipeline_width_6() {
    let fixture = Fixture::load(fixture_path("small"));
    let machine = run_vectorized_kernel(&fixture, 6);
    assert_eq!(machine.mem, fixture.mem_out);
}

#[test]
fn baseline_fixture_pipeline_width_1() {
    let fixture = Fixture::load(fixture_path("baseline"));
    let machine = run_vectorized_kernel(&fixture, 1);
    assert_eq!(machine.mem, fixture.mem_out);
    println!("pipeline_width=1: {} cycles", machine.cycle);
}

#[test]
fn baseline_fixture_pipeline_width_6() {
    let fixture = Fixture::load(fixture_path("baseline"));
    let machine = run_vectorized_kernel(&fixture, 6);
    assert_eq!(machine.mem, fixture.mem_out);
    println!("pipeline_width=6: {} cycles", machine.cycle);
}
