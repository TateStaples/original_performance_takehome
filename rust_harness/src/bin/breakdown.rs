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
    build_problem_dag, build_problem_dag_smart_tuned, Dag, NodeCat, ResKind, SelectImpl,
};
use std::env;

const CATS: [NodeCat; 5] = [
    NodeCat::Hash,
    NodeCat::Idx,
    NodeCat::Routing,
    NodeCat::Setup,
    NodeCat::Store,
];

fn engine_class(k: ResKind) -> Option<&'static str> {
    match k {
        ResKind::Alu(_) => Some("alu-kind"),
        ResKind::MultiplyAdd => Some("valu madd"),
        ResKind::Flow => Some("flow"),
        ResKind::ContiguousLoad | ResKind::GatherLoad => Some("load"),
        ResKind::Store => Some("store"),
        ResKind::Free => None,
    }
}

fn report(label: &str, dag: &Dag) {
    // counts[category][engine_class]
    let classes = ["alu-kind", "valu madd", "flow", "load", "store"];
    let mut grid: Vec<Vec<u64>> = vec![vec![0u64; classes.len()]; CATS.len()];
    for (i, node) in dag.nodes.iter().enumerate() {
        let Some(cls) = engine_class(node.kind) else {
            continue;
        };
        let ci = CATS.iter().position(|c| *c == dag.category[i]).unwrap();
        let ei = classes.iter().position(|c| *c == cls).unwrap();
        grid[ci][ei] += 1;
    }

    println!("\n##### {label} #####");
    println!(
        "{:>8} {:>10} {:>10} {:>8} {:>9} {:>8}",
        "category", "alu-kind", "valu madd", "flow", "load", "store"
    );
    let mut col_tot = vec![0u64; classes.len()];
    for (ci, cat) in CATS.iter().enumerate() {
        println!(
            "{:>8} {:>10} {:>10} {:>8} {:>9} {:>8}",
            format!("{cat:?}"),
            grid[ci][0],
            grid[ci][1],
            grid[ci][2],
            grid[ci][3],
            grid[ci][4],
        );
        for e in 0..classes.len() {
            col_tot[e] += grid[ci][e];
        }
    }

    // The headline: how the alu-kind (scalar-ALU) work splits by purpose.
    let alu_total: u64 = col_tot[0];
    println!("\nalu-kind (scalar-ALU) work by purpose:");
    for (ci, cat) in CATS.iter().enumerate() {
        let n = grid[ci][0];
        if n == 0 {
            continue;
        }
        println!(
            "  {:>8}: {:>7}  ({:>5.1}%)",
            format!("{cat:?}"),
            n,
            100.0 * n as f64 / alu_total as f64
        );
    }
    // And the full arithmetic pool (alu-kind + valu madd + flow selects).
    let arith = col_tot[0] + col_tot[1] + col_tot[2];
    println!(
        "total alu-kind={} valu-madd={} flow={}  (arith pool={arith})",
        col_tot[0], col_tot[1], col_tot[2]
    );
    for (ci, cat) in CATS.iter().enumerate() {
        let n = grid[ci][0] + grid[ci][1] + grid[ci][2];
        if n == 0 {
            continue;
        }
        println!(
            "  arith {:>8}: {:>7}  ({:>5.1}%)",
            format!("{cat:?}"),
            n,
            100.0 * n as f64 / arith as f64
        );
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let fh: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(10);
    let bs: u32 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(256);
    let r: u32 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(16);
    let threshold: u32 = args.get(4).and_then(|s| s.parse().ok()).unwrap_or(4);
    let select = match args.get(5).map(|s| s.as_str()) {
        Some("flow") => SelectImpl::Flow,
        _ => SelectImpl::Algebraic,
    };

    report("plain (per-walker gather)", &build_problem_dag(fh, bs, r));
    report(
        &format!("smart (threshold={threshold}, {select:?})"),
        &build_problem_dag_smart_tuned(fh, bs, r, select, threshold),
    );
}
