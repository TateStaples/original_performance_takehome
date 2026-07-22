//! Converts a typed `Program` into the exact JSON shape that corresponds to
//! `KernelBuilder.instrs` in `perf_takehome.py` — a list of bundles, each a
//! JSON object keyed by engine name (only engines with at least one slot
//! present, matching how `KernelBuilder.add`/`build` construct bundles) to
//! an array of Python-tuple-shaped arrays (op code first, matching
//! `problem.py`'s slot tuples exactly).
//!
//! `debug` slots are intentionally dropped here: `tests/submission_tests.py`
//! (the actual grader) runs with `enable_debug = False`, and cycle counts
//! never depend on them (see docs/isa.md §2), so there is nothing to lose by
//! omitting them from the bridge. Fine-grained per-step checking during
//! development is `debug::Compare` against a fixture's trace *within Rust*
//! (see `machine::Machine::with_trace`) — that's the fast loop this harness
//! is for. `tools/load_rust_kernel.py` is the Python-side counterpart that
//! reads this JSON back into a real `KernelBuilder`.

use crate::isa::{AluOp, AluSlot, Bundle, FlowSlot, LoadSlot, Program, StoreSlot, ValuSlot};
use serde_json::{json, Map, Value};

fn alu_op_str(op: AluOp) -> &'static str {
    match op {
        AluOp::Add => "+",
        AluOp::Sub => "-",
        AluOp::Mul => "*",
        AluOp::FloorDiv => "//",
        AluOp::CDiv => "cdiv",
        AluOp::Xor => "^",
        AluOp::And => "&",
        AluOp::Or => "|",
        AluOp::Shl => "<<",
        AluOp::Shr => ">>",
        AluOp::Mod => "%",
        AluOp::Lt => "<",
        AluOp::Eq => "==",
    }
}

fn alu_slot_json(s: &AluSlot) -> Value {
    json!([alu_op_str(s.op), s.dest.0, s.a1.0, s.a2.0])
}

fn valu_slot_json(s: &ValuSlot) -> Value {
    match s {
        ValuSlot::Op { op, dest, a1, a2 } => json!([alu_op_str(*op), dest.0, a1.0, a2.0]),
        ValuSlot::Broadcast { dest, src } => json!(["vbroadcast", dest.0, src.0]),
        ValuSlot::MultiplyAdd { dest, a, b, c } => json!(["multiply_add", dest.0, a.0, b.0, c.0]),
    }
}

fn load_slot_json(s: &LoadSlot) -> Value {
    match s {
        LoadSlot::Load { dest, addr } => json!(["load", dest.0, addr.0]),
        LoadSlot::LoadOffset { dest, addr, offset } => {
            json!(["load_offset", dest.0, addr.0, offset])
        }
        LoadSlot::VLoad { dest, addr } => json!(["vload", dest.0, addr.0]),
        LoadSlot::Const { dest, val } => json!(["const", dest.0, val]),
    }
}

fn store_slot_json(s: &StoreSlot) -> Value {
    match s {
        StoreSlot::Store { addr, src } => json!(["store", addr.0, src.0]),
        StoreSlot::VStore { addr, src } => json!(["vstore", addr.0, src.0]),
    }
}

fn flow_slot_json(s: &FlowSlot) -> Value {
    match s {
        FlowSlot::Select { dest, cond, a, b } => json!(["select", dest.0, cond.0, a.0, b.0]),
        FlowSlot::VSelect { dest, cond, a, b } => json!(["vselect", dest.0, cond.0, a.0, b.0]),
        FlowSlot::AddImm { dest, a, imm } => json!(["add_imm", dest.0, a.0, imm]),
        FlowSlot::Halt => json!(["halt"]),
        FlowSlot::Pause => json!(["pause"]),
        FlowSlot::TraceWrite { val } => json!(["trace_write", val.0]),
        FlowSlot::Jump { addr } => json!(["jump", addr]),
        FlowSlot::JumpIndirect { addr } => json!(["jump_indirect", addr.0]),
        FlowSlot::CondJump { cond, addr } => json!(["cond_jump", cond.0, addr]),
        FlowSlot::CondJumpRel { cond, offset } => json!(["cond_jump_rel", cond.0, offset]),
        FlowSlot::CoreId { dest } => json!(["coreid", dest.0]),
    }
}

pub fn bundle_to_python_json(b: &Bundle) -> Value {
    let mut map = Map::new();
    if !b.alu.is_empty() {
        map.insert(
            "alu".into(),
            Value::Array(b.alu.iter().map(alu_slot_json).collect()),
        );
    }
    if !b.valu.is_empty() {
        map.insert(
            "valu".into(),
            Value::Array(b.valu.iter().map(valu_slot_json).collect()),
        );
    }
    if !b.load.is_empty() {
        map.insert(
            "load".into(),
            Value::Array(b.load.iter().map(load_slot_json).collect()),
        );
    }
    if !b.store.is_empty() {
        map.insert(
            "store".into(),
            Value::Array(b.store.iter().map(store_slot_json).collect()),
        );
    }
    if !b.flow.is_empty() {
        map.insert(
            "flow".into(),
            Value::Array(b.flow.iter().map(flow_slot_json).collect()),
        );
    }
    Value::Object(map)
}

pub fn program_to_python_json(program: &Program) -> Value {
    // Bundles that were purely `debug` (or genuinely empty) contribute
    // nothing on the Python side — no cycle, no scratch/mem effect — so
    // they're dropped rather than emitted as noisy empty `{}` bundles.
    Value::Array(
        program
            .iter()
            .filter(|b| b.costs_a_cycle())
            .map(bundle_to_python_json)
            .collect(),
    )
}
