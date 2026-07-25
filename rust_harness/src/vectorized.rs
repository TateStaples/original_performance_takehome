//! The "basic optimizations" pass: vectorize the per-round update across
//! the batch dimension with `valu` (8 walkers per vector register), and
//! optionally interleave `pipeline_width` independent groups' instruction
//! streams so valu's 6 slots/cycle actually get filled -- a single group's
//! own dependency chain never offers more than 2 independent valu ops at
//! once (see the hash-stage comment below), so packing needs more than one
//! group in flight. `pipeline_width=1` is the vectorize-only version;
//! `pipeline_width=6` is the packing sweet spot (see WAVE note below) and
//! is what "efficiently pipelining" refers to. See rust_harness/README.md
//! and docs/problem.md for the write-up, and stats::analyze to check the
//! theory below against what actually got emitted.
//!
//! Design notes (see docs/problem.md for the algorithm, docs/isa.md for
//! the ISA):
//! - idx/val stay resident in scratch as one 8-wide vector register per
//!   group of 8 walkers, for that group's *entire* 16-round lifetime --
//!   memory is only touched once at the very start (vload) and once at the
//!   very end (vstore) per group, unlike the naive baseline, which
//!   round-trips through memory every single round for every walker.
//! - node_val's lookup (`mem[forest_values_p + idx[lane]]`) is a gather:
//!   each of the 8 lanes needs a different address, and this ISA has no
//!   vector gather instruction (only contiguous vload/vstore) -- so this
//!   step is unavoidably 8 scalar `load`s per group per round. With
//!   `load`'s 2-slot/cycle limit, that's (batch_size/VLEN) * rounds * 8 / 2
//!   -- a hard lower bound no matter how well everything else packs.
//! - the branch `1 if val % 2 == 0 else 2` is replaced with the equivalent
//!   pure arithmetic `(val % 2) + 1` (no comparison/select needed): one
//!   fewer op, and one less demand on the single-slot `flow` engine. Only
//!   the tree-wraparound check genuinely needs a select.
//! - WAVE: a group's hash stage offers exactly 2 mutually-independent valu
//!   ops at a time (the op1/op3 half-stages; the combine step depends on
//!   both, so it can't join them in the same bundle) but every *other*
//!   phase (addr, xor, mod, etc.) offers only 1 valu op per group. `valu`
//!   has 6 slots/cycle, and 6 is a multiple of both 1 and 2 -- so a wave of
//!   6 groups fills every phase's valu bundles at (close to) 100%, which is
//!   why `pipeline_width=6` is the sweet spot rather than some other width.

use crate::builder::Builder;
use crate::isa::{
    slot_limits, AluOp, AluSlot, Bundle, FlowSlot, LoadSlot, Program, Scratch, StoreSlot, ValuSlot,
    VLEN,
};
use crate::problem::HASH_STAGES;

/// Greedily packs slots into bundles: keeps appending to the bundle
/// currently being built until an engine's slot limit would be exceeded,
/// then flushes and starts a new one. Safe to use freely *within* a set of
/// mutually-independent ops; `barrier()` must be called before pushing
/// anything that depends on a value written by an already-pushed op, since
/// bundle-local writes only become visible after the whole bundle commits
/// (see docs/isa.md §2) -- every phase below calls `barrier()` right after
/// itself for exactly this reason.
struct Packer {
    program: Program,
    current_bundle: Bundle,
}

impl Packer {
    fn new() -> Self {
        Packer {
            program: Vec::new(),
            current_bundle: Bundle::default(),
        }
    }

    fn barrier(&mut self) {
        if !self.current_bundle.is_empty() {
            self.program.push(std::mem::take(&mut self.current_bundle));
        }
    }

    fn alu(&mut self, slot: AluSlot) {
        if self.current_bundle.alu.len() >= slot_limits::ALU {
            self.barrier();
        }
        self.current_bundle.alu.push(slot);
    }
    fn valu(&mut self, slot: ValuSlot) {
        if self.current_bundle.valu.len() >= slot_limits::VALU {
            self.barrier();
        }
        self.current_bundle.valu.push(slot);
    }
    fn load(&mut self, slot: LoadSlot) {
        if self.current_bundle.load.len() >= slot_limits::LOAD {
            self.barrier();
        }
        self.current_bundle.load.push(slot);
    }
    fn store(&mut self, slot: StoreSlot) {
        if self.current_bundle.store.len() >= slot_limits::STORE {
            self.barrier();
        }
        self.current_bundle.store.push(slot);
    }
    fn flow(&mut self, slot: FlowSlot) {
        if self.current_bundle.flow.len() >= slot_limits::FLOW {
            self.barrier();
        }
        self.current_bundle.flow.push(slot);
    }

    fn finish(mut self) -> Program {
        self.barrier();
        self.program
    }
}

pub fn build_kernel_vectorized(batch_size: u32, rounds: u32, pipeline_width: usize) -> Program {
    assert_eq!(
        batch_size % VLEN as u32,
        0,
        "batch_size must be a multiple of VLEN={VLEN} for this kernel"
    );
    assert!(pipeline_width >= 1);
    let group_count = (batch_size / VLEN as u32) as usize;

    let mut builder = Builder::new();

    // Only the 4 header fields this kernel actually reads (see
    // docs/problem.md §2.5 for the fixed 7-word header layout).
    let n_nodes_scalar = load_header_field(&mut builder, "n_nodes", 1);
    let forest_values_p_scalar = load_header_field(&mut builder, "forest_values_p", 4);
    let inp_indices_p_scalar = load_header_field(&mut builder, "inp_indices_p", 5);
    let inp_values_p_scalar = load_header_field(&mut builder, "inp_values_p", 6);

    builder.push_flow_single(FlowSlot::Pause);

    let mut packer = Packer::new();

    // Broadcast every constant this kernel needs into an 8-wide vector,
    // exactly once, up front; every group/round below only *reads* these.
    let zero_scalar = builder.scratch_const(0);
    let one_scalar = builder.scratch_const(1);
    let two_scalar = builder.scratch_const(2);
    let zero_vec = broadcast(&mut builder, &mut packer, zero_scalar);
    let one_vec = broadcast(&mut builder, &mut packer, one_scalar);
    let two_vec = broadcast(&mut builder, &mut packer, two_scalar);
    let forest_values_p_vec = broadcast(&mut builder, &mut packer, forest_values_p_scalar);
    let n_nodes_vec = broadcast(&mut builder, &mut packer, n_nodes_scalar);

    let hash_const_vecs: Vec<(Scratch, Scratch)> = HASH_STAGES
        .iter()
        .map(|&(_, val1, _, _, val3)| {
            let val1_const = builder.scratch_const(val1);
            let val3_const = builder.scratch_const(val3);
            (
                broadcast(&mut builder, &mut packer, val1_const),
                broadcast(&mut builder, &mut packer, val3_const),
            )
        })
        .collect();
    packer.barrier();

    // One persistent 8-wide vector register per group, alive for the
    // group's entire 16-round lifetime.
    let idx_vecs: Vec<Scratch> = (0..group_count)
        .map(|_| builder.alloc_scratch(VLEN as u16))
        .collect();
    let val_vecs: Vec<Scratch> = (0..group_count)
        .map(|_| builder.alloc_scratch(VLEN as u16))
        .collect();

    // Per-pipeline-slot scratch temporaries, reused wave to wave.
    let addr_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| builder.alloc_scratch(VLEN as u16))
        .collect();
    let node_val_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| builder.alloc_scratch(VLEN as u16))
        .collect();
    let hash_tmp1: Vec<Scratch> = (0..pipeline_width)
        .map(|_| builder.alloc_scratch(VLEN as u16))
        .collect();
    let hash_tmp2: Vec<Scratch> = (0..pipeline_width)
        .map(|_| builder.alloc_scratch(VLEN as u16))
        .collect();
    let offset_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| builder.alloc_scratch(VLEN as u16))
        .collect();
    let next_idx_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| builder.alloc_scratch(VLEN as u16))
        .collect();
    let cmp_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| builder.alloc_scratch(VLEN as u16))
        .collect();

    // Load every group's starting idx/val once. Addresses are computed in
    // one packed batch (up to 12/cycle on alu) rather than one-at-a-time,
    // since stats::analyze on an earlier version of this function showed
    // these as unpacked single-op bundles -- a real, easily-fixed miss.
    let idx_addrs = group_addrs(&mut builder, &mut packer, inp_indices_p_scalar, group_count);
    let val_addrs = group_addrs(&mut builder, &mut packer, inp_values_p_scalar, group_count);
    for group in 0..group_count {
        packer.load(LoadSlot::VLoad {
            dest: idx_vecs[group],
            addr: idx_addrs[group],
        });
        packer.load(LoadSlot::VLoad {
            dest: val_vecs[group],
            addr: val_addrs[group],
        });
    }
    packer.barrier();

    for _round in 0..rounds {
        let mut wave_start = 0;
        while wave_start < group_count {
            let wave_end = (wave_start + pipeline_width).min(group_count);
            let wave: Vec<usize> = (wave_start..wave_end).collect();
            wave_start = wave_end;

            // addr[group] = idx[group] + forest_values_p (all 8 lanes' gather addresses in one valu op)
            for (pipeline_slot, &group) in wave.iter().enumerate() {
                packer.valu(ValuSlot::Op {
                    op: AluOp::Add,
                    dest: addr_tmp[pipeline_slot],
                    a1: idx_vecs[group],
                    a2: forest_values_p_vec,
                });
            }
            packer.barrier();

            // gather node_val -- unavoidably scalar, see module docs
            for (pipeline_slot, _) in wave.iter().enumerate() {
                for lane in 0..VLEN {
                    packer.load(LoadSlot::Load {
                        dest: node_val_tmp[pipeline_slot].lane(lane),
                        addr: addr_tmp[pipeline_slot].lane(lane),
                    });
                }
            }
            packer.barrier();

            // val ^= node_val
            for (pipeline_slot, &group) in wave.iter().enumerate() {
                packer.valu(ValuSlot::Op {
                    op: AluOp::Xor,
                    dest: val_vecs[group],
                    a1: val_vecs[group],
                    a2: node_val_tmp[pipeline_slot],
                });
            }
            packer.barrier();

            // 6-stage hash, vectorized
            for (stage_idx, &(op1, _, op2, op3, _)) in HASH_STAGES.iter().enumerate() {
                let (val1_const_vec, val3_const_vec) = hash_const_vecs[stage_idx];
                for (pipeline_slot, &group) in wave.iter().enumerate() {
                    packer.valu(ValuSlot::Op {
                        op: op1,
                        dest: hash_tmp1[pipeline_slot],
                        a1: val_vecs[group],
                        a2: val1_const_vec,
                    });
                    packer.valu(ValuSlot::Op {
                        op: op3,
                        dest: hash_tmp2[pipeline_slot],
                        a1: val_vecs[group],
                        a2: val3_const_vec,
                    });
                }
                packer.barrier();
                for (pipeline_slot, &group) in wave.iter().enumerate() {
                    packer.valu(ValuSlot::Op {
                        op: op2,
                        dest: val_vecs[group],
                        a1: hash_tmp1[pipeline_slot],
                        a2: hash_tmp2[pipeline_slot],
                    });
                }
                packer.barrier();
            }

            // offset = (val % 2) + 1 -- replaces the naive mod+eq+select
            for (pipeline_slot, &group) in wave.iter().enumerate() {
                packer.valu(ValuSlot::Op {
                    op: AluOp::Mod,
                    dest: offset_tmp[pipeline_slot],
                    a1: val_vecs[group],
                    a2: two_vec,
                });
            }
            packer.barrier();
            for (pipeline_slot, _) in wave.iter().enumerate() {
                packer.valu(ValuSlot::Op {
                    op: AluOp::Add,
                    dest: offset_tmp[pipeline_slot],
                    a1: offset_tmp[pipeline_slot],
                    a2: one_vec,
                });
            }
            packer.barrier();

            // next_idx = idx*2 + offset
            for (pipeline_slot, &group) in wave.iter().enumerate() {
                packer.valu(ValuSlot::Op {
                    op: AluOp::Mul,
                    dest: next_idx_tmp[pipeline_slot],
                    a1: idx_vecs[group],
                    a2: two_vec,
                });
            }
            packer.barrier();
            for (pipeline_slot, _) in wave.iter().enumerate() {
                packer.valu(ValuSlot::Op {
                    op: AluOp::Add,
                    dest: next_idx_tmp[pipeline_slot],
                    a1: next_idx_tmp[pipeline_slot],
                    a2: offset_tmp[pipeline_slot],
                });
            }
            packer.barrier();

            // wraparound: idx = (next_idx < n_nodes) ? next_idx : 0 -- the one genuine select
            for (pipeline_slot, _) in wave.iter().enumerate() {
                packer.valu(ValuSlot::Op {
                    op: AluOp::Lt,
                    dest: cmp_tmp[pipeline_slot],
                    a1: next_idx_tmp[pipeline_slot],
                    a2: n_nodes_vec,
                });
            }
            packer.barrier();
            for (pipeline_slot, &group) in wave.iter().enumerate() {
                packer.flow(FlowSlot::VSelect {
                    dest: idx_vecs[group],
                    cond: cmp_tmp[pipeline_slot],
                    a: next_idx_tmp[pipeline_slot],
                    b: zero_vec,
                });
            }
            packer.barrier();
        }
    }

    // Store every group's final idx/val once, at the *same* addresses
    // computed for the initial load -- nothing writes inp_indices_p_scalar /
    // inp_values_p_scalar in between, so those registers are still valid and
    // there's no need to recompute them.
    for group in 0..group_count {
        packer.store(StoreSlot::VStore {
            addr: idx_addrs[group],
            src: idx_vecs[group],
        });
        packer.store(StoreSlot::VStore {
            addr: val_addrs[group],
            src: val_vecs[group],
        });
    }

    let mut program = builder.program;
    program.extend(packer.finish());
    program.push(Bundle {
        flow: vec![FlowSlot::Pause],
        ..Default::default()
    });
    program
}

fn load_header_field(builder: &mut Builder, name: &'static str, header_index: u32) -> Scratch {
    let dest = builder.alloc_named(name, 1);
    let addr = builder.scratch_const(header_index);
    builder.push_load_single(LoadSlot::Load { dest, addr });
    dest
}

fn broadcast(builder: &mut Builder, packer: &mut Packer, src: Scratch) -> Scratch {
    let dest = builder.alloc_scratch(VLEN as u16);
    packer.valu(ValuSlot::Broadcast { dest, src });
    dest
}

/// `addr[group] = base + group*VLEN` for every group, computed as one packed batch
/// (up to `slot_limits::ALU` per bundle) rather than one bundle per group.
fn group_addrs(
    builder: &mut Builder,
    packer: &mut Packer,
    base: Scratch,
    group_count: usize,
) -> Vec<Scratch> {
    let addrs: Vec<Scratch> = (0..group_count)
        .map(|group| {
            let dest = builder.alloc_scratch(1);
            let offset_const = builder.scratch_const((group * VLEN) as u32);
            packer.alu(AluSlot {
                op: AluOp::Add,
                dest,
                a1: base,
                a2: offset_const,
            });
            dest
        })
        .collect();
    packer.barrier();
    addrs
}
