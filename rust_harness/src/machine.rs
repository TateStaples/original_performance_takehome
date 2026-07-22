//! Simulator core, ported from `Machine` in `problem.py`. Semantics —
//! staged writes (a bundle's slots all read the start-of-cycle state; every
//! write lands only after the whole bundle has executed), the "a cycle only
//! counts if the bundle has a non-debug slot" rule, pause/halt — all match
//! the Python original; see `docs/isa.md` for the prose spec this mirrors.
//!
//! This only models a single core: `N_CORES = 1` is a fixed, intentional
//! property of this version of the take-home (see `docs/problem.md`), so
//! there's no value in carrying Python's now-vestigial multi-core loop.

use crate::isa::{AluSlot, Bundle, DebugSlot, FlowSlot, LoadSlot, Program, StoreSlot, ValuSlot, VLEN};
use std::collections::HashMap;

#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum CoreState {
    Running,
    Paused,
    Stopped,
}

pub struct Machine {
    pub mem: Vec<u32>,
    pub scratch: Vec<u32>,
    pub program: Program,
    pub pc: usize,
    pub cycle: u64,
    pub enable_pause: bool,
    pub enable_debug: bool,
    state: CoreState,
    trace: Option<HashMap<String, u32>>,
}

impl Machine {
    pub fn new(mem: Vec<u32>, program: Program) -> Self {
        Machine {
            mem,
            scratch: vec![0u32; crate::isa::SCRATCH_SIZE],
            program,
            pc: 0,
            cycle: 0,
            enable_pause: true,
            enable_debug: true,
            state: CoreState::Running,
            trace: None,
        }
    }

    /// Attach a value trace (round/element/field -> expected value) so
    /// `debug::Compare`/`VCompare` slots can assert against it, exactly like
    /// `reference_kernel2`'s `value_trace` does for the Python harness. See
    /// `tools/export_fixtures.py` for how a trace fixture is produced.
    pub fn with_trace(mut self, trace: HashMap<String, u32>) -> Self {
        self.trace = Some(trace);
        self
    }

    pub fn state(&self) -> CoreState {
        self.state
    }

    /// Run until the program halts, runs off the end, or pauses again.
    /// Resumes a paused machine, matching `Machine.run()` in Python.
    pub fn run(&mut self) {
        if self.state == CoreState::Paused {
            self.state = CoreState::Running;
        }
        // Temporarily move `program` out of `self` so `step` can take
        // `&mut self` without a borrow conflict against `self.program`.
        let program = std::mem::take(&mut self.program);
        while self.state == CoreState::Running {
            if self.pc >= program.len() {
                self.state = CoreState::Stopped;
                break;
            }
            let bundle = &program[self.pc];
            self.pc += 1;
            let costs_a_cycle = bundle.costs_a_cycle();
            self.step(bundle);
            if costs_a_cycle {
                self.cycle += 1;
            }
        }
        self.program = program;
    }

    fn step(&mut self, bundle: &Bundle) {
        bundle
            .validate()
            .unwrap_or_else(|e| panic!("{e} at pc={}", self.pc - 1));

        let mut scratch_write: HashMap<u16, u32> = HashMap::new();
        let mut mem_write: HashMap<u32, u32> = HashMap::new();

        for s in &bundle.alu {
            self.exec_alu(s, &mut scratch_write);
        }
        for s in &bundle.valu {
            self.exec_valu(s, &mut scratch_write);
        }
        for s in &bundle.load {
            self.exec_load(s, &mut scratch_write);
        }
        for s in &bundle.store {
            self.exec_store(s, &mut mem_write);
        }
        for s in &bundle.flow {
            self.exec_flow(s, &mut scratch_write);
        }
        if self.enable_debug {
            for s in &bundle.debug {
                self.exec_debug(s);
            }
        }

        for (addr, val) in scratch_write {
            self.scratch[addr as usize] = val;
        }
        for (addr, val) in mem_write {
            self.mem[addr as usize] = val;
        }
    }

    fn exec_alu(&self, s: &AluSlot, out: &mut HashMap<u16, u32>) {
        let a1 = self.scratch[s.a1.0 as usize];
        let a2 = self.scratch[s.a2.0 as usize];
        out.insert(s.dest.0, s.op.apply(a1, a2));
    }

    fn exec_valu(&self, s: &ValuSlot, out: &mut HashMap<u16, u32>) {
        match s {
            ValuSlot::Op { op, dest, a1, a2 } => {
                for i in 0..VLEN {
                    let x = self.scratch[(a1.0 as usize) + i];
                    let y = self.scratch[(a2.0 as usize) + i];
                    out.insert(dest.0 + i as u16, op.apply(x, y));
                }
            }
            ValuSlot::Broadcast { dest, src } => {
                let v = self.scratch[src.0 as usize];
                for i in 0..VLEN {
                    out.insert(dest.0 + i as u16, v);
                }
            }
            ValuSlot::MultiplyAdd { dest, a, b, c } => {
                for i in 0..VLEN {
                    let x = self.scratch[(a.0 as usize) + i] as u64;
                    let y = self.scratch[(b.0 as usize) + i] as u64;
                    let z = self.scratch[(c.0 as usize) + i] as u64;
                    let mul = (x * y) % (1u64 << 32);
                    let res = (mul + z) % (1u64 << 32);
                    out.insert(dest.0 + i as u16, res as u32);
                }
            }
        }
    }

    fn exec_load(&self, s: &LoadSlot, out: &mut HashMap<u16, u32>) {
        match s {
            LoadSlot::Load { dest, addr } => {
                let a = self.scratch[addr.0 as usize];
                out.insert(dest.0, self.mem[a as usize]);
            }
            LoadSlot::LoadOffset { dest, addr, offset } => {
                let a = self.scratch[(addr.0 + offset) as usize];
                out.insert(dest.0 + offset, self.mem[a as usize]);
            }
            LoadSlot::VLoad { dest, addr } => {
                let base = self.scratch[addr.0 as usize];
                for i in 0..VLEN {
                    out.insert(dest.0 + i as u16, self.mem[base as usize + i]);
                }
            }
            LoadSlot::Const { dest, val } => {
                out.insert(dest.0, *val);
            }
        }
    }

    fn exec_store(&self, s: &StoreSlot, out: &mut HashMap<u32, u32>) {
        match s {
            StoreSlot::Store { addr, src } => {
                let a = self.scratch[addr.0 as usize];
                out.insert(a, self.scratch[src.0 as usize]);
            }
            StoreSlot::VStore { addr, src } => {
                let base = self.scratch[addr.0 as usize];
                for i in 0..VLEN {
                    out.insert(base + i as u32, self.scratch[(src.0 as usize) + i]);
                }
            }
        }
    }

    fn exec_flow(&mut self, s: &FlowSlot, out: &mut HashMap<u16, u32>) {
        match s {
            FlowSlot::Select { dest, cond, a, b } => {
                let v = if self.scratch[cond.0 as usize] != 0 {
                    self.scratch[a.0 as usize]
                } else {
                    self.scratch[b.0 as usize]
                };
                out.insert(dest.0, v);
            }
            FlowSlot::VSelect { dest, cond, a, b } => {
                for i in 0..VLEN {
                    let v = if self.scratch[(cond.0 as usize) + i] != 0 {
                        self.scratch[(a.0 as usize) + i]
                    } else {
                        self.scratch[(b.0 as usize) + i]
                    };
                    out.insert(dest.0 + i as u16, v);
                }
            }
            FlowSlot::AddImm { dest, a, imm } => {
                let v = ((self.scratch[a.0 as usize] as u64 + *imm as u64) % (1u64 << 32)) as u32;
                out.insert(dest.0, v);
            }
            FlowSlot::Halt => self.state = CoreState::Stopped,
            FlowSlot::Pause => {
                if self.enable_pause {
                    self.state = CoreState::Paused;
                }
            }
            FlowSlot::TraceWrite { .. } => {
                // Trace buffer isn't modeled — not needed for cycle-count or
                // memory-correctness checking, which is this harness's job.
            }
            FlowSlot::Jump { addr } => self.pc = *addr,
            FlowSlot::JumpIndirect { addr } => self.pc = self.scratch[addr.0 as usize] as usize,
            FlowSlot::CondJump { cond, addr } => {
                if self.scratch[cond.0 as usize] != 0 {
                    self.pc = *addr;
                }
            }
            FlowSlot::CondJumpRel { cond, offset } => {
                if self.scratch[cond.0 as usize] != 0 {
                    self.pc = (self.pc as isize + offset) as usize;
                }
            }
            FlowSlot::CoreId { dest } => {
                out.insert(dest.0, 0);
            }
        }
    }

    fn exec_debug(&self, s: &DebugSlot) {
        match s {
            DebugSlot::Compare { loc, key } => {
                let trace = self.trace.as_ref().unwrap_or_else(|| {
                    panic!("debug compare for {key:?} but no trace loaded (Machine::with_trace)")
                });
                let expected = *trace
                    .get(key)
                    .unwrap_or_else(|| panic!("no trace entry for key {key:?}"));
                let actual = self.scratch[loc.0 as usize];
                assert_eq!(
                    actual,
                    expected,
                    "compare failed for {key:?} at pc={} (loc={})",
                    self.pc - 1,
                    loc.0
                );
            }
            DebugSlot::VCompare { loc, keys } => {
                let trace = self.trace.as_ref().unwrap_or_else(|| {
                    panic!("debug vcompare for {keys:?} but no trace loaded (Machine::with_trace)")
                });
                for (i, key) in keys.iter().enumerate() {
                    let expected = *trace
                        .get(key)
                        .unwrap_or_else(|| panic!("no trace entry for key {key:?}"));
                    let actual = self.scratch[(loc.0 as usize) + i];
                    assert_eq!(
                        actual,
                        expected,
                        "vcompare failed for {key:?} (lane {i}) at pc={} (loc={})",
                        self.pc - 1,
                        loc.0
                    );
                }
            }
            DebugSlot::Comment { .. } => {}
        }
    }
}
