//! Break down the arithmetic work by *purpose* (hash / index / routing),
//! per engine. Answers "what is the ALU actually computing" -- how much of
//! the scalar-ALU-kind work is the hash vs. the index recurrence vs. getting
//! the tree value to the walker.
//!
//! Counts are on the DAG itself (node kind x category), independent of the
//! schedule: an `Alu(_)` node is one scalar-ALU-kind op (it runs on the alu
//! engine, or batches 8-wide onto valu -- either way it's alu-shaped work);
//! `MultiplyAdd` is valu-only; `Flow` is a select. Load/Store are memory.
//!
//! Usage: cargo run --release --bin breakdown -- <forest_height> <batch_size> <rounds> [threshold] [algebraic|flow]

use perf_harness::dag::{
    build_problem_dag, build_problem_dag_butterfly, build_problem_dag_idxlite,
    build_problem_dag_smart_tuned, Dag, NodeCategory, NodeKind, SelectImpl,
};
use perf_harness::schedule::{peak_register_pressure, schedule, SchedulerConfig};
use std::env;

const CATEGORIES: [NodeCategory; 5] = [
    NodeCategory::Hash,
    NodeCategory::Idx,
    NodeCategory::Routing,
    NodeCategory::Setup,
    NodeCategory::Store,
];

fn engine_class(node_kind: NodeKind) -> Option<&'static str> {
    match node_kind {
        NodeKind::Alu(_) => Some("alu-kind"),
        NodeKind::MultiplyAdd => Some("valu madd"),
        NodeKind::Flow => Some("flow"),
        NodeKind::ContiguousLoad | NodeKind::GatherLoad => Some("load"),
        NodeKind::Store => Some("store"),
        NodeKind::Free => None,
    }
}

fn report(label: &str, dag: &Dag) {
    // counts[category][engine_class]
    let engine_class_labels = ["alu-kind", "valu madd", "flow", "load", "store"];
    let mut counts: Vec<Vec<u64>> = vec![vec![0u64; engine_class_labels.len()]; CATEGORIES.len()];
    for (i, node) in dag.nodes.iter().enumerate() {
        let Some(engine_class_label) = engine_class(node.kind) else {
            continue;
        };
        let category_index = CATEGORIES
            .iter()
            .position(|c| *c == dag.category[i])
            .unwrap();
        let engine_index = engine_class_labels
            .iter()
            .position(|c| *c == engine_class_label)
            .unwrap();
        counts[category_index][engine_index] += 1;
    }

    println!("\n##### {label} #####");
    println!(
        "{:>8} {:>10} {:>10} {:>8} {:>9} {:>8}",
        "category", "alu-kind", "valu madd", "flow", "load", "store"
    );
    let mut column_totals = vec![0u64; engine_class_labels.len()];
    for (category_index, category) in CATEGORIES.iter().enumerate() {
        println!(
            "{:>8} {:>10} {:>10} {:>8} {:>9} {:>8}",
            format!("{category:?}"),
            counts[category_index][0],
            counts[category_index][1],
            counts[category_index][2],
            counts[category_index][3],
            counts[category_index][4],
        );
        for engine_index in 0..engine_class_labels.len() {
            column_totals[engine_index] += counts[category_index][engine_index];
        }
    }

    // The headline: how the alu-kind (scalar-ALU) work splits by purpose.
    let alu_total: u64 = column_totals[0];
    println!("\nalu-kind (scalar-ALU) work by purpose:");
    for (category_index, category) in CATEGORIES.iter().enumerate() {
        let alu_kind_count = counts[category_index][0];
        if alu_kind_count == 0 {
            continue;
        }
        println!(
            "  {:>8}: {:>7}  ({:>5.1}%)",
            format!("{category:?}"),
            alu_kind_count,
            100.0 * alu_kind_count as f64 / alu_total as f64
        );
    }
    // And the full arithmetic pool (alu-kind + valu madd + flow selects).
    let arith_pool_total = column_totals[0] + column_totals[1] + column_totals[2];
    println!(
        "total alu-kind={} valu-madd={} flow={}  (arith pool={arith_pool_total})",
        column_totals[0], column_totals[1], column_totals[2]
    );
    for (category_index, category) in CATEGORIES.iter().enumerate() {
        let arith_count =
            counts[category_index][0] + counts[category_index][1] + counts[category_index][2];
        if arith_count == 0 {
            continue;
        }
        println!(
            "  arith {:>8}: {:>7}  ({:>5.1}%)",
            format!("{category:?}"),
            arith_count,
            100.0 * arith_count as f64 / arith_pool_total as f64
        );
    }

    // Analytical arithmetic floor: alu+valu can retire 60 lane-ops/cycle
    // (alu 12 + valu 6*8), and only alu-kind + valu-madd must use them (flow
    // ops go on the flow engine). Report the idx-only floor too.
    let alu_valu_ops = column_totals[0] + column_totals[1];
    let idx_alu_valu = counts[1][0] + counts[1][1]; // Idx row, alu-kind + madd
    println!(
        "arith floor (alu+valu ops / 60) ~= {} cyc;  idx-only ~= {} cyc;  flow ops = {}",
        alu_valu_ops.div_ceil(60),
        idx_alu_valu.div_ceil(48),
        column_totals[2],
    );

    // Actually schedule it (realistic, walker_window=16) for the real cycles.
    let schedule_result = schedule(
        dag,
        SchedulerConfig {
            gather_batchable: false,
            walker_window: Some(16),
        },
    );
    let (peak, _) = peak_register_pressure(dag, &schedule_result);
    let busy_pct = |busy_cycles: u64| 100.0 * busy_cycles as f64 / schedule_result.cycles as f64;
    println!(
        "scheduled: {} cyc  (alu {:.0}% valu {:.0}% flow {:.0}% load {:.0}%)  peak {} {}",
        schedule_result.cycles,
        busy_pct(schedule_result.alu.busy_cycles),
        busy_pct(schedule_result.valu.busy_cycles),
        busy_pct(schedule_result.flow.busy_cycles),
        busy_pct(schedule_result.load().busy_cycles),
        peak,
        if peak <= 1536 { "fits" } else { "OVER" },
    );
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let forest_height: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(10);
    let batch_size: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(256);
    let rounds: u32 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(16);
    let threshold: u32 = args.get(4).and_then(|s| s.parse().ok()).unwrap_or(4);
    let select = match args.get(5).map(|s| s.as_str()) {
        Some("flow") => SelectImpl::Flow,
        _ => SelectImpl::Algebraic,
    };

    report(
        "plain (per-walker gather)",
        &build_problem_dag(forest_height, batch_size, rounds),
    );
    report(
        &format!("smart (threshold={threshold}, {select:?})"),
        &build_problem_dag_smart_tuned(forest_height, batch_size, rounds, select, threshold),
    );
    report(
        &format!("idxlite (threshold={threshold}, {select:?}) -- idx recurrence elided"),
        &build_problem_dag_idxlite(forest_height, batch_size, rounds, select, threshold),
    );
    report(
        "butterfly -- all routing on flow, alu/valu = hash+parity only",
        &build_problem_dag_butterfly(forest_height, batch_size, rounds),
    );

    // idxlite reshapes liveness, so re-tune the walker window for realizability.
    println!("\n### idxlite window sweep (threshold={threshold}, {select:?}) ###");
    let idxlite = build_problem_dag_idxlite(forest_height, batch_size, rounds, select, threshold);
    for window in [4u32, 6, 8, 10, 12, 16] {
        let schedule_result = schedule(
            &idxlite,
            SchedulerConfig {
                gather_batchable: false,
                walker_window: Some(window),
            },
        );
        let (peak, _) = peak_register_pressure(&idxlite, &schedule_result);
        println!(
            "  window {window:>2}: {} cyc,  peak {} {}",
            schedule_result.cycles,
            peak,
            if peak <= 1536 { "fits" } else { "OVER" }
        );
    }
}
