//! Typed port of `KernelBuilder` from `perf_takehome.py`. `build_kernel_naive`
//! is a line-for-line port of the shipped Python baseline — a known-good,
//! cross-validated (see `tests/matches_python_baseline.rs`) starting point
//! to optimize from using the typed API instead of hand-written tuples.

use crate::isa::{
    AluOp, AluSlot, Bundle, CapacityError, DebugSlot, FlowSlot, LoadSlot, Program, Scratch,
    StoreSlot,
};
use crate::problem::HASH_STAGES;
use std::collections::HashMap;

pub struct Builder {
    pub program: Program,
    scratch_ptr: u16,
    const_map: HashMap<u32, Scratch>,
    named: HashMap<&'static str, Scratch>,
}

impl Builder {
    pub fn new() -> Self {
        Builder {
            program: Vec::new(),
            scratch_ptr: 0,
            const_map: HashMap::new(),
            named: HashMap::new(),
        }
    }

    pub fn named(&self, name: &str) -> Scratch {
        *self
            .named
            .get(name)
            .unwrap_or_else(|| panic!("no scratch slot named {name:?}"))
    }

    pub fn alloc_scratch(&mut self, len: u16) -> Scratch {
        let addr = Scratch(self.scratch_ptr);
        self.scratch_ptr += len;
        assert!(
            (self.scratch_ptr as usize) <= crate::isa::SCRATCH_SIZE,
            "out of scratch space (wanted {len} more, have {} of {})",
            self.scratch_ptr,
            crate::isa::SCRATCH_SIZE
        );
        addr
    }

    pub fn alloc_named(&mut self, name: &'static str, len: u16) -> Scratch {
        let addr = self.alloc_scratch(len);
        self.named.insert(name, addr);
        addr
    }

    /// Memoized constant load: emits a `load::Const` bundle the first time
    /// `val` is requested and reuses the same scratch slot afterward — same
    /// behavior (and same "hoists to wherever it's first requested at
    /// build-time" quirk) as `KernelBuilder.scratch_const` in Python; see
    /// `docs/problem.md` §3 for why that matters for cycle counts.
    pub fn scratch_const(&mut self, val: u32) -> Scratch {
        if let Some(&s) = self.const_map.get(&val) {
            return s;
        }
        let s = self.alloc_scratch(1);
        self.push_load_single(LoadSlot::Const { dest: s, val });
        self.const_map.insert(val, s);
        s
    }

    // --- single-slot-per-bundle helpers (mirrors KernelBuilder.add/build) ---

    pub fn push_alu_single(&mut self, slot: AluSlot) {
        self.program.push(Bundle {
            alu: vec![slot],
            ..Default::default()
        });
    }
    pub fn push_load_single(&mut self, slot: LoadSlot) {
        self.program.push(Bundle {
            load: vec![slot],
            ..Default::default()
        });
    }
    pub fn push_store_single(&mut self, slot: StoreSlot) {
        self.program.push(Bundle {
            store: vec![slot],
            ..Default::default()
        });
    }
    pub fn push_flow_single(&mut self, slot: FlowSlot) {
        self.program.push(Bundle {
            flow: vec![slot],
            ..Default::default()
        });
    }
    pub fn push_debug_single(&mut self, slot: DebugSlot) {
        self.program.push(Bundle {
            debug: vec![slot],
            ..Default::default()
        });
    }

    /// Push a hand-packed bundle (multiple slots, possibly across several
    /// engines) — this is the escape hatch for actually using the VLIW/SIMD
    /// width instead of one-slot-per-cycle. Fails at build time (not deep in
    /// a simulation run) if any engine's slot limit is exceeded.
    pub fn push_bundle(&mut self, bundle: Bundle) -> Result<(), CapacityError> {
        bundle.validate()?;
        self.program.push(bundle);
        Ok(())
    }
}

impl Default for Builder {
    fn default() -> Self {
        Self::new()
    }
}

/// Port of `KernelBuilder.build_hash`: emits the 6 `myhash` stages as
/// scalar `alu` ops (plus matching `debug::Compare`s), each stage being
/// `val = (val OP1 val1) OP2 (val OP3 val3)`.
pub fn build_hash(
    b: &mut Builder,
    val_addr: Scratch,
    tmp1: Scratch,
    tmp2: Scratch,
    round: u32,
    i: u32,
) {
    for (hi, &(op1, val1, op2, op3, val3)) in HASH_STAGES.iter().enumerate() {
        let c1 = b.scratch_const(val1);
        let c3 = b.scratch_const(val3);
        b.push_alu_single(AluSlot {
            op: op1,
            dest: tmp1,
            a1: val_addr,
            a2: c1,
        });
        b.push_alu_single(AluSlot {
            op: op3,
            dest: tmp2,
            a1: val_addr,
            a2: c3,
        });
        b.push_alu_single(AluSlot {
            op: op2,
            dest: val_addr,
            a1: tmp1,
            a2: tmp2,
        });
        b.push_debug_single(DebugSlot::Compare {
            loc: val_addr,
            key: format!("{round}|{i}|hash_stage|{hi}"),
        });
    }
}

/// Line-for-line port of the shipped `KernelBuilder.build_kernel` baseline:
/// fully scalar, one slot per bundle, no packing, no `valu`. `forest_height`
/// and `n_nodes` are accepted for signature parity with the Python original
/// but — like the Python original — are unused in the body itself; only
/// `scratch["n_nodes"]` (the *runtime* value loaded from the memory header)
/// is actually consulted, in the tree-wraparound check.
///
/// This is meant to be forked, not called directly forever: it's the
/// cross-validated (see the `matches_python_baseline` integration test)
/// starting point to optimize from with the typed API in this module.
pub fn build_kernel_naive(
    _forest_height: u32,
    _n_nodes: u32,
    batch_size: u32,
    rounds: u32,
) -> Program {
    let mut b = Builder::new();

    let tmp1 = b.alloc_named("tmp1", 1);
    let tmp2 = b.alloc_named("tmp2", 1);
    let tmp3 = b.alloc_named("tmp3", 1);

    // Read the 7-word memory header (see docs/problem.md §2.5) into named
    // scratch slots — their *addresses* (0..6) are known at build time,
    // their *values* only at run time.
    let init_vars: [&'static str; 7] = [
        "rounds",
        "n_nodes",
        "batch_size",
        "forest_height",
        "forest_values_p",
        "inp_indices_p",
        "inp_values_p",
    ];
    for name in init_vars {
        b.alloc_named(name, 1);
    }
    for (i, name) in init_vars.iter().enumerate() {
        b.push_load_single(LoadSlot::Const {
            dest: tmp1,
            val: i as u32,
        });
        b.push_load_single(LoadSlot::Load {
            dest: b.named(name),
            addr: tmp1,
        });
    }

    let zero_const = b.scratch_const(0);
    let one_const = b.scratch_const(1);
    let two_const = b.scratch_const(2);

    // Matches reference_kernel2's first `yield` (right after the header is
    // conceptually available) — see docs/problem.md §4.
    b.push_flow_single(FlowSlot::Pause);
    b.push_debug_single(DebugSlot::Comment {
        text: "Starting loop".into(),
    });

    let tmp_idx = b.alloc_named("tmp_idx", 1);
    let tmp_val = b.alloc_named("tmp_val", 1);
    let tmp_node_val = b.alloc_named("tmp_node_val", 1);
    let tmp_addr = b.alloc_named("tmp_addr", 1);

    let inp_indices_p = b.named("inp_indices_p");
    let inp_values_p = b.named("inp_values_p");
    let forest_values_p = b.named("forest_values_p");
    let n_nodes_rt = b.named("n_nodes");

    for round in 0..rounds {
        for i in 0..batch_size {
            let i_const = b.scratch_const(i);

            // idx = mem[inp_indices_p + i]
            b.push_alu_single(AluSlot {
                op: AluOp::Add,
                dest: tmp_addr,
                a1: inp_indices_p,
                a2: i_const,
            });
            b.push_load_single(LoadSlot::Load {
                dest: tmp_idx,
                addr: tmp_addr,
            });
            b.push_debug_single(DebugSlot::Compare {
                loc: tmp_idx,
                key: format!("{round}|{i}|idx"),
            });

            // val = mem[inp_values_p + i]
            b.push_alu_single(AluSlot {
                op: AluOp::Add,
                dest: tmp_addr,
                a1: inp_values_p,
                a2: i_const,
            });
            b.push_load_single(LoadSlot::Load {
                dest: tmp_val,
                addr: tmp_addr,
            });
            b.push_debug_single(DebugSlot::Compare {
                loc: tmp_val,
                key: format!("{round}|{i}|val"),
            });

            // node_val = mem[forest_values_p + idx]
            b.push_alu_single(AluSlot {
                op: AluOp::Add,
                dest: tmp_addr,
                a1: forest_values_p,
                a2: tmp_idx,
            });
            b.push_load_single(LoadSlot::Load {
                dest: tmp_node_val,
                addr: tmp_addr,
            });
            b.push_debug_single(DebugSlot::Compare {
                loc: tmp_node_val,
                key: format!("{round}|{i}|node_val"),
            });

            // val = myhash(val ^ node_val)
            b.push_alu_single(AluSlot {
                op: AluOp::Xor,
                dest: tmp_val,
                a1: tmp_val,
                a2: tmp_node_val,
            });
            build_hash(&mut b, tmp_val, tmp1, tmp2, round, i);
            b.push_debug_single(DebugSlot::Compare {
                loc: tmp_val,
                key: format!("{round}|{i}|hashed_val"),
            });

            // idx = 2*idx + (1 if val % 2 == 0 else 2)
            b.push_alu_single(AluSlot {
                op: AluOp::Mod,
                dest: tmp1,
                a1: tmp_val,
                a2: two_const,
            });
            b.push_alu_single(AluSlot {
                op: AluOp::Eq,
                dest: tmp1,
                a1: tmp1,
                a2: zero_const,
            });
            b.push_flow_single(FlowSlot::Select {
                dest: tmp3,
                cond: tmp1,
                a: one_const,
                b: two_const,
            });
            b.push_alu_single(AluSlot {
                op: AluOp::Mul,
                dest: tmp_idx,
                a1: tmp_idx,
                a2: two_const,
            });
            b.push_alu_single(AluSlot {
                op: AluOp::Add,
                dest: tmp_idx,
                a1: tmp_idx,
                a2: tmp3,
            });
            b.push_debug_single(DebugSlot::Compare {
                loc: tmp_idx,
                key: format!("{round}|{i}|next_idx"),
            });

            // idx = 0 if idx >= n_nodes else idx
            b.push_alu_single(AluSlot {
                op: AluOp::Lt,
                dest: tmp1,
                a1: tmp_idx,
                a2: n_nodes_rt,
            });
            b.push_flow_single(FlowSlot::Select {
                dest: tmp_idx,
                cond: tmp1,
                a: tmp_idx,
                b: zero_const,
            });
            b.push_debug_single(DebugSlot::Compare {
                loc: tmp_idx,
                key: format!("{round}|{i}|wrapped_idx"),
            });

            // mem[inp_indices_p + i] = idx
            b.push_alu_single(AluSlot {
                op: AluOp::Add,
                dest: tmp_addr,
                a1: inp_indices_p,
                a2: i_const,
            });
            b.push_store_single(StoreSlot::Store {
                addr: tmp_addr,
                src: tmp_idx,
            });

            // mem[inp_values_p + i] = val
            b.push_alu_single(AluSlot {
                op: AluOp::Add,
                dest: tmp_addr,
                a1: inp_values_p,
                a2: i_const,
            });
            b.push_store_single(StoreSlot::Store {
                addr: tmp_addr,
                src: tmp_val,
            });
        }
    }

    // Matches reference_kernel2's second `yield`.
    b.push_flow_single(FlowSlot::Pause);

    b.program
}
