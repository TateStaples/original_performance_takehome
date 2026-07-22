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
    current: Bundle,
}

impl Packer {
    fn new() -> Self {
        Packer {
            program: Vec::new(),
            current: Bundle::default(),
        }
    }

    fn barrier(&mut self) {
        if !self.current.is_empty() {
            self.program.push(std::mem::take(&mut self.current));
        }
    }

    fn alu(&mut self, slot: AluSlot) {
        if self.current.alu.len() >= slot_limits::ALU {
            self.barrier();
        }
        self.current.alu.push(slot);
    }
    fn valu(&mut self, slot: ValuSlot) {
        if self.current.valu.len() >= slot_limits::VALU {
            self.barrier();
        }
        self.current.valu.push(slot);
    }
    fn load(&mut self, slot: LoadSlot) {
        if self.current.load.len() >= slot_limits::LOAD {
            self.barrier();
        }
        self.current.load.push(slot);
    }
    fn store(&mut self, slot: StoreSlot) {
        if self.current.store.len() >= slot_limits::STORE {
            self.barrier();
        }
        self.current.store.push(slot);
    }
    fn flow(&mut self, slot: FlowSlot) {
        if self.current.flow.len() >= slot_limits::FLOW {
            self.barrier();
        }
        self.current.flow.push(slot);
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
    let n_groups = (batch_size / VLEN as u32) as usize;

    let mut b = Builder::new();

    // Only the 4 header fields this kernel actually reads (see
    // docs/problem.md §2.5 for the fixed 7-word header layout).
    let n_nodes_s = load_header_field(&mut b, "n_nodes", 1);
    let forest_values_p_s = load_header_field(&mut b, "forest_values_p", 4);
    let inp_indices_p_s = load_header_field(&mut b, "inp_indices_p", 5);
    let inp_values_p_s = load_header_field(&mut b, "inp_values_p", 6);

    b.push_flow_single(FlowSlot::Pause);

    let mut pk = Packer::new();

    // Broadcast every constant this kernel needs into an 8-wide vector,
    // exactly once, up front; every group/round below only *reads* these.
    let zero_s = b.scratch_const(0);
    let one_s = b.scratch_const(1);
    let two_s = b.scratch_const(2);
    let zero_vec = broadcast(&mut b, &mut pk, zero_s);
    let one_vec = broadcast(&mut b, &mut pk, one_s);
    let two_vec = broadcast(&mut b, &mut pk, two_s);
    let forest_values_p_vec = broadcast(&mut b, &mut pk, forest_values_p_s);
    let n_nodes_vec = broadcast(&mut b, &mut pk, n_nodes_s);

    let hash_const_vecs: Vec<(Scratch, Scratch)> = HASH_STAGES
        .iter()
        .map(|&(_, val1, _, _, val3)| {
            let c1 = b.scratch_const(val1);
            let c3 = b.scratch_const(val3);
            (
                broadcast(&mut b, &mut pk, c1),
                broadcast(&mut b, &mut pk, c3),
            )
        })
        .collect();
    pk.barrier();

    // One persistent 8-wide vector register per group, alive for the
    // group's entire 16-round lifetime.
    let idx_vecs: Vec<Scratch> = (0..n_groups)
        .map(|_| b.alloc_scratch(VLEN as u16))
        .collect();
    let val_vecs: Vec<Scratch> = (0..n_groups)
        .map(|_| b.alloc_scratch(VLEN as u16))
        .collect();

    // Per-pipeline-slot scratch temporaries, reused wave to wave.
    let addr_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| b.alloc_scratch(VLEN as u16))
        .collect();
    let node_val_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| b.alloc_scratch(VLEN as u16))
        .collect();
    let hash_tmp1: Vec<Scratch> = (0..pipeline_width)
        .map(|_| b.alloc_scratch(VLEN as u16))
        .collect();
    let hash_tmp2: Vec<Scratch> = (0..pipeline_width)
        .map(|_| b.alloc_scratch(VLEN as u16))
        .collect();
    let offset_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| b.alloc_scratch(VLEN as u16))
        .collect();
    let next_idx_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| b.alloc_scratch(VLEN as u16))
        .collect();
    let cmp_tmp: Vec<Scratch> = (0..pipeline_width)
        .map(|_| b.alloc_scratch(VLEN as u16))
        .collect();

    // Load every group's starting idx/val once. Addresses are computed in
    // one packed batch (up to 12/cycle on alu) rather than one-at-a-time,
    // since stats::analyze on an earlier version of this function showed
    // these as unpacked single-op bundles -- a real, easily-fixed miss.
    let idx_addrs = group_addrs(&mut b, &mut pk, inp_indices_p_s, n_groups);
    let val_addrs = group_addrs(&mut b, &mut pk, inp_values_p_s, n_groups);
    for g in 0..n_groups {
        pk.load(LoadSlot::VLoad {
            dest: idx_vecs[g],
            addr: idx_addrs[g],
        });
        pk.load(LoadSlot::VLoad {
            dest: val_vecs[g],
            addr: val_addrs[g],
        });
    }
    pk.barrier();

    for _round in 0..rounds {
        let mut wave_start = 0;
        while wave_start < n_groups {
            let wave_end = (wave_start + pipeline_width).min(n_groups);
            let wave: Vec<usize> = (wave_start..wave_end).collect();
            wave_start = wave_end;

            // addr[g] = idx[g] + forest_values_p (all 8 lanes' gather addresses in one valu op)
            for (slot, &g) in wave.iter().enumerate() {
                pk.valu(ValuSlot::Op {
                    op: AluOp::Add,
                    dest: addr_tmp[slot],
                    a1: idx_vecs[g],
                    a2: forest_values_p_vec,
                });
            }
            pk.barrier();

            // gather node_val -- unavoidably scalar, see module docs
            for (slot, _) in wave.iter().enumerate() {
                for lane in 0..VLEN {
                    pk.load(LoadSlot::Load {
                        dest: node_val_tmp[slot].lane(lane),
                        addr: addr_tmp[slot].lane(lane),
                    });
                }
            }
            pk.barrier();

            // val ^= node_val
            for (slot, &g) in wave.iter().enumerate() {
                pk.valu(ValuSlot::Op {
                    op: AluOp::Xor,
                    dest: val_vecs[g],
                    a1: val_vecs[g],
                    a2: node_val_tmp[slot],
                });
            }
            pk.barrier();

            // 6-stage hash, vectorized
            for (stage_idx, &(op1, _, op2, op3, _)) in HASH_STAGES.iter().enumerate() {
                let (c1_vec, c3_vec) = hash_const_vecs[stage_idx];
                for (slot, &g) in wave.iter().enumerate() {
                    pk.valu(ValuSlot::Op {
                        op: op1,
                        dest: hash_tmp1[slot],
                        a1: val_vecs[g],
                        a2: c1_vec,
                    });
                    pk.valu(ValuSlot::Op {
                        op: op3,
                        dest: hash_tmp2[slot],
                        a1: val_vecs[g],
                        a2: c3_vec,
                    });
                }
                pk.barrier();
                for (slot, &g) in wave.iter().enumerate() {
                    pk.valu(ValuSlot::Op {
                        op: op2,
                        dest: val_vecs[g],
                        a1: hash_tmp1[slot],
                        a2: hash_tmp2[slot],
                    });
                }
                pk.barrier();
            }

            // offset = (val % 2) + 1 -- replaces the naive mod+eq+select
            for (slot, &g) in wave.iter().enumerate() {
                pk.valu(ValuSlot::Op {
                    op: AluOp::Mod,
                    dest: offset_tmp[slot],
                    a1: val_vecs[g],
                    a2: two_vec,
                });
            }
            pk.barrier();
            for (slot, _) in wave.iter().enumerate() {
                pk.valu(ValuSlot::Op {
                    op: AluOp::Add,
                    dest: offset_tmp[slot],
                    a1: offset_tmp[slot],
                    a2: one_vec,
                });
            }
            pk.barrier();

            // next_idx = idx*2 + offset
            for (slot, &g) in wave.iter().enumerate() {
                pk.valu(ValuSlot::Op {
                    op: AluOp::Mul,
                    dest: next_idx_tmp[slot],
                    a1: idx_vecs[g],
                    a2: two_vec,
                });
            }
            pk.barrier();
            for (slot, _) in wave.iter().enumerate() {
                pk.valu(ValuSlot::Op {
                    op: AluOp::Add,
                    dest: next_idx_tmp[slot],
                    a1: next_idx_tmp[slot],
                    a2: offset_tmp[slot],
                });
            }
            pk.barrier();

            // wraparound: idx = (next_idx < n_nodes) ? next_idx : 0 -- the one genuine select
            for (slot, _) in wave.iter().enumerate() {
                pk.valu(ValuSlot::Op {
                    op: AluOp::Lt,
                    dest: cmp_tmp[slot],
                    a1: next_idx_tmp[slot],
                    a2: n_nodes_vec,
                });
            }
            pk.barrier();
            for (slot, &g) in wave.iter().enumerate() {
                pk.flow(FlowSlot::VSelect {
                    dest: idx_vecs[g],
                    cond: cmp_tmp[slot],
                    a: next_idx_tmp[slot],
                    b: zero_vec,
                });
            }
            pk.barrier();
        }
    }

    // Store every group's final idx/val once, at the *same* addresses
    // computed for the initial load -- nothing writes inp_indices_p_s /
    // inp_values_p_s in between, so those registers are still valid and
    // there's no need to recompute them.
    for g in 0..n_groups {
        pk.store(StoreSlot::VStore {
            addr: idx_addrs[g],
            src: idx_vecs[g],
        });
        pk.store(StoreSlot::VStore {
            addr: val_addrs[g],
            src: val_vecs[g],
        });
    }

    let mut program = b.program;
    program.extend(pk.finish());
    program.push(Bundle {
        flow: vec![FlowSlot::Pause],
        ..Default::default()
    });
    program
}

fn load_header_field(b: &mut Builder, name: &'static str, header_index: u32) -> Scratch {
    let dest = b.alloc_named(name, 1);
    let addr = b.scratch_const(header_index);
    b.push_load_single(LoadSlot::Load { dest, addr });
    dest
}

fn broadcast(b: &mut Builder, pk: &mut Packer, src: Scratch) -> Scratch {
    let dest = b.alloc_scratch(VLEN as u16);
    pk.valu(ValuSlot::Broadcast { dest, src });
    dest
}

/// `addr[g] = base + g*VLEN` for every group, computed as one packed batch
/// (up to `slot_limits::ALU` per bundle) rather than one bundle per group.
fn group_addrs(b: &mut Builder, pk: &mut Packer, base: Scratch, n_groups: usize) -> Vec<Scratch> {
    let addrs: Vec<Scratch> = (0..n_groups)
        .map(|g| {
            let dest = b.alloc_scratch(1);
            let offset_const = b.scratch_const((g * VLEN) as u32);
            pk.alu(AluSlot {
                op: AluOp::Add,
                dest,
                a1: base,
                a2: offset_const,
            });
            dest
        })
        .collect();
    pk.barrier();
    addrs
}
