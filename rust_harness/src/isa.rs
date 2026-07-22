//! Typed instruction set for the VLIW/SIMD simulator described in
//! `docs/isa.md`. This mirrors `problem.py`'s `Machine` 1:1 in semantics,
//! but replaces Python's untyped `dict[Engine, list[tuple]]` bundles with
//! Rust enums/structs so that most ways of misusing the ISA (wrong operand
//! count, mixing up a scratch address with a literal, overfilling an
//! engine's slots) are caught by the compiler instead of by a runtime
//! assertion deep in a 150,000-cycle simulation.

use serde::{Deserialize, Serialize};

pub const VLEN: usize = 8;
pub const N_CORES: usize = 1;
pub const SCRATCH_SIZE: usize = 1536;

pub mod slot_limits {
    pub const ALU: usize = 12;
    pub const VALU: usize = 6;
    pub const LOAD: usize = 2;
    pub const STORE: usize = 2;
    pub const FLOW: usize = 1;
    pub const DEBUG: usize = 64;
}

/// An address into a core's scratch space (`SCRATCH_SIZE` words). Distinct
/// from a raw `u32` value/literal so the two can't be swapped by accident —
/// e.g. `("const", dest, val)` takes a `Scratch` destination and a `u32`
/// literal, and those two parameters can no longer be transposed without a
/// type error.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct Scratch(pub u16);

impl Scratch {
    /// Address of lane `i` of a vector value based at `self` (must be `VLEN`
    /// contiguous scratch slots per the ISA's vector-addressing rule).
    pub fn lane(self, i: usize) -> Scratch {
        Scratch(self.0 + i as u16)
    }
}

impl std::ops::Add<u16> for Scratch {
    type Output = Scratch;
    fn add(self, rhs: u16) -> Scratch {
        Scratch(self.0 + rhs)
    }
}

/// Scalar ALU / VALU opcode. Semantics match `Machine.alu` in `problem.py`
/// exactly, including 32-bit wraparound (every result is taken mod 2**32,
/// matching Python's arbitrary-precision-then-truncate behavior — see
/// `AluOp::apply`).
#[derive(Copy, Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub enum AluOp {
    Add,
    Sub,
    Mul,
    FloorDiv,
    CDiv,
    Xor,
    And,
    Or,
    Shl,
    Shr,
    Mod,
    Lt,
    Eq,
}

impl AluOp {
    /// `a OP b`, matching `Machine.alu`'s semantics bit-for-bit, including
    /// Python's floored (not truncated) modulo/subtraction wraparound and
    /// its tolerance for shift amounts >= 32 (Python has arbitrary-precision
    /// ints; a left shift by >= 32 just moves everything out of the final
    /// `% 2**32` window, i.e. the result is 0).
    pub fn apply(self, a: u32, b: u32) -> u32 {
        const MOD: i64 = 1i64 << 32;
        let wrap = |x: i64| x.rem_euclid(MOD) as u32;
        match self {
            AluOp::Add => wrap(a as i64 + b as i64),
            AluOp::Sub => wrap(a as i64 - b as i64),
            // u32*u32 can reach ~2^64, which overflows the i64 `wrap` helper
            // (panics in debug). Python's arbitrary-precision `(a*b) % 2**32`
            // never does; `wrapping_mul` keeps the low 32 bits and is
            // bit-identical to that. The real hash only ever multiplies by
            // small constants, but the minimality search in problem.rs probes
            // large*large, so this must be overflow-safe.
            AluOp::Mul => a.wrapping_mul(b),
            AluOp::FloorDiv => {
                assert!(b != 0, "alu FloorDiv by zero (a={a}, b={b})");
                a / b
            }
            AluOp::CDiv => {
                assert!(b != 0, "alu CDiv by zero (a={a}, b={b})");
                let a = a as u64;
                let b = b as u64;
                a.div_ceil(b) as u32
            }
            AluOp::Xor => a ^ b,
            AluOp::And => a & b,
            AluOp::Or => a | b,
            AluOp::Shl => {
                if b >= 32 {
                    0
                } else {
                    wrap((a as i64) << b)
                }
            }
            AluOp::Shr => {
                if b >= 32 {
                    0
                } else {
                    a >> b
                }
            }
            AluOp::Mod => {
                assert!(b != 0, "alu Mod by zero (a={a}, b={b})");
                a % b
            }
            AluOp::Lt => (a < b) as u32,
            AluOp::Eq => (a == b) as u32,
        }
    }
}

/// One `alu` engine slot: `dest = a1 OP a2`.
#[derive(Copy, Clone, Debug, Serialize, Deserialize)]
pub struct AluSlot {
    pub op: AluOp,
    pub dest: Scratch,
    pub a1: Scratch,
    pub a2: Scratch,
}

/// One `valu` engine slot (8-wide, `VLEN` contiguous scratch slots per
/// operand).
#[derive(Copy, Clone, Debug, Serialize, Deserialize)]
pub enum ValuSlot {
    /// Lanewise `alu` op over 8 contiguous elements.
    Op {
        op: AluOp,
        dest: Scratch,
        a1: Scratch,
        a2: Scratch,
    },
    /// Splat a scalar into all 8 lanes.
    Broadcast { dest: Scratch, src: Scratch },
    /// Fused multiply-add, lanewise: `dest[i] = a[i]*b[i] + c[i]`.
    MultiplyAdd {
        dest: Scratch,
        a: Scratch,
        b: Scratch,
        c: Scratch,
    },
}

/// One `load` engine slot.
#[derive(Copy, Clone, Debug, Serialize, Deserialize)]
pub enum LoadSlot {
    /// `dest = mem[scratch[addr]]`.
    Load { dest: Scratch, addr: Scratch },
    /// `dest+offset = mem[scratch[addr+offset]]` — for treating a vector
    /// dest/addr pair as one block while indexing lanes individually.
    LoadOffset {
        dest: Scratch,
        addr: Scratch,
        offset: u16,
    },
    /// `dest[0..VLEN] = mem[scratch[addr] .. +VLEN]` (`addr` is scalar).
    VLoad { dest: Scratch, addr: Scratch },
    /// `dest = val` — the only way to get a literal into scratch.
    Const { dest: Scratch, val: u32 },
}

/// One `store` engine slot.
#[derive(Copy, Clone, Debug, Serialize, Deserialize)]
pub enum StoreSlot {
    /// `mem[scratch[addr]] = scratch[src]`.
    Store { addr: Scratch, src: Scratch },
    /// `mem[scratch[addr] .. +VLEN] = scratch[src .. +VLEN]` (`addr` is scalar).
    VStore { addr: Scratch, src: Scratch },
}

/// One `flow` engine slot. Only one of these is allowed per cycle
/// (`slot_limits::FLOW == 1`) — it's the tightest engine in the ISA.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum FlowSlot {
    /// `dest = a if cond != 0 else b` — branchless scalar mux.
    Select {
        dest: Scratch,
        cond: Scratch,
        a: Scratch,
        b: Scratch,
    },
    /// Same, 8-wide lanewise.
    VSelect {
        dest: Scratch,
        cond: Scratch,
        a: Scratch,
        b: Scratch,
    },
    /// `dest = a + imm` — add a literal without a separate `const` load.
    AddImm {
        dest: Scratch,
        a: Scratch,
        imm: u32,
    },
    Halt,
    /// Pause this core (used to sync with a reference kernel's `yield`
    /// points for step-by-step debugging).
    Pause,
    TraceWrite {
        val: Scratch,
    },
    Jump {
        addr: usize,
    },
    /// Computed jump: `pc = scratch[addr]`.
    JumpIndirect {
        addr: Scratch,
    },
    CondJump {
        cond: Scratch,
        addr: usize,
    },
    CondJumpRel {
        cond: Scratch,
        offset: isize,
    },
    CoreId {
        dest: Scratch,
    },
}

/// One `debug` engine slot. Free (never advances the cycle counter) and
/// ignored entirely when grading — but a live correctness check while
/// developing, if a value trace is loaded into the `Machine` (see
/// `machine::Machine::with_trace`).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum DebugSlot {
    /// Assert `scratch[loc] == trace[key]`.
    Compare { loc: Scratch, key: String },
    /// Assert `scratch[loc..loc+VLEN] == [trace[k] for k in keys]`.
    VCompare { loc: Scratch, keys: Vec<String> },
    /// No-op annotation (shows up as a label in a trace viewer).
    Comment { text: String },
}

/// One instruction bundle: every filled slot across every engine fires in
/// the same simulated cycle. Using one `Vec` per engine (rather than a
/// `HashMap<Engine, Vec<Slot>>` as in Python) means the compiler enforces
/// which slot types are legal on which engine — there's no runtime "unknown
/// op for this engine" case to hit.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Bundle {
    pub alu: Vec<AluSlot>,
    pub valu: Vec<ValuSlot>,
    pub load: Vec<LoadSlot>,
    pub store: Vec<StoreSlot>,
    pub flow: Vec<FlowSlot>,
    pub debug: Vec<DebugSlot>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct CapacityError {
    pub engine: &'static str,
    pub limit: usize,
}

impl std::fmt::Display for CapacityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{} engine is full (limit {} slots/cycle)",
            self.engine, self.limit
        )
    }
}
impl std::error::Error for CapacityError {}

impl Bundle {
    pub fn is_empty(&self) -> bool {
        self.alu.is_empty()
            && self.valu.is_empty()
            && self.load.is_empty()
            && self.store.is_empty()
            && self.flow.is_empty()
            && self.debug.is_empty()
    }

    /// True if this bundle has at least one non-`debug` slot — matches
    /// `Machine.run`'s rule for whether a bundle costs a simulated cycle.
    pub fn costs_a_cycle(&self) -> bool {
        !(self.alu.is_empty()
            && self.valu.is_empty()
            && self.load.is_empty()
            && self.store.is_empty()
            && self.flow.is_empty())
    }

    /// Validate against `slot_limits` — the same check `Machine::step`
    /// performs at run time, exposed here so a `Program` can fail fast at
    /// build time instead of mid-simulation.
    pub fn validate(&self) -> Result<(), CapacityError> {
        macro_rules! check {
            ($field:expr, $name:expr, $limit:expr) => {
                if $field.len() > $limit {
                    return Err(CapacityError {
                        engine: $name,
                        limit: $limit,
                    });
                }
            };
        }
        check!(self.alu, "alu", slot_limits::ALU);
        check!(self.valu, "valu", slot_limits::VALU);
        check!(self.load, "load", slot_limits::LOAD);
        check!(self.store, "store", slot_limits::STORE);
        check!(self.flow, "flow", slot_limits::FLOW);
        check!(self.debug, "debug", slot_limits::DEBUG);
        Ok(())
    }

    pub fn push_alu(&mut self, slot: AluSlot) -> Result<(), CapacityError> {
        if self.alu.len() >= slot_limits::ALU {
            return Err(CapacityError {
                engine: "alu",
                limit: slot_limits::ALU,
            });
        }
        self.alu.push(slot);
        Ok(())
    }
    pub fn push_valu(&mut self, slot: ValuSlot) -> Result<(), CapacityError> {
        if self.valu.len() >= slot_limits::VALU {
            return Err(CapacityError {
                engine: "valu",
                limit: slot_limits::VALU,
            });
        }
        self.valu.push(slot);
        Ok(())
    }
    pub fn push_load(&mut self, slot: LoadSlot) -> Result<(), CapacityError> {
        if self.load.len() >= slot_limits::LOAD {
            return Err(CapacityError {
                engine: "load",
                limit: slot_limits::LOAD,
            });
        }
        self.load.push(slot);
        Ok(())
    }
    pub fn push_store(&mut self, slot: StoreSlot) -> Result<(), CapacityError> {
        if self.store.len() >= slot_limits::STORE {
            return Err(CapacityError {
                engine: "store",
                limit: slot_limits::STORE,
            });
        }
        self.store.push(slot);
        Ok(())
    }
    pub fn push_flow(&mut self, slot: FlowSlot) -> Result<(), CapacityError> {
        if self.flow.len() >= slot_limits::FLOW {
            return Err(CapacityError {
                engine: "flow",
                limit: slot_limits::FLOW,
            });
        }
        self.flow.push(slot);
        Ok(())
    }
    pub fn push_debug(&mut self, slot: DebugSlot) -> Result<(), CapacityError> {
        if self.debug.len() >= slot_limits::DEBUG {
            return Err(CapacityError {
                engine: "debug",
                limit: slot_limits::DEBUG,
            });
        }
        self.debug.push(slot);
        Ok(())
    }
}

/// A whole program: an ordered list of bundles.
pub type Program = Vec<Bundle>;

#[cfg(test)]
mod tests {
    use super::*;

    // Cross-checked against Python: `(a - b) % 2**32` for a < b wraps like
    // 32-bit two's complement, via floored (not truncated) modulo.
    #[test]
    fn sub_wraps_like_python_mod() {
        assert_eq!(AluOp::Sub.apply(0, 1), 0xFFFF_FFFF);
        assert_eq!(AluOp::Sub.apply(5, 5), 0);
    }

    #[test]
    fn mul_wraps_at_32_bits() {
        // 0xFFFFFFFF * 2 = 0x1_FFFFFFFE -> truncated to 0xFFFFFFFE
        assert_eq!(AluOp::Mul.apply(0xFFFF_FFFF, 2), 0xFFFF_FFFE);
    }

    #[test]
    fn shift_by_32_or_more_is_zero() {
        // Python: (a << 32) % 2**32 == 0 for any a in [0, 2**32).
        assert_eq!(AluOp::Shl.apply(1, 32), 0);
        assert_eq!(AluOp::Shl.apply(0xFFFF_FFFF, 40), 0);
        assert_eq!(AluOp::Shr.apply(0xFFFF_FFFF, 32), 0);
    }

    #[test]
    fn floor_div_and_cdiv() {
        assert_eq!(AluOp::FloorDiv.apply(7, 2), 3);
        assert_eq!(AluOp::CDiv.apply(7, 2), 4);
        assert_eq!(AluOp::CDiv.apply(8, 2), 4);
    }

    #[test]
    fn lt_and_eq_are_boolean_ints() {
        assert_eq!(AluOp::Lt.apply(3, 5), 1);
        assert_eq!(AluOp::Lt.apply(5, 3), 0);
        assert_eq!(AluOp::Eq.apply(5, 5), 1);
    }

    #[test]
    fn bundle_capacity_is_enforced_at_push_time() {
        let mut b = Bundle::default();
        for _ in 0..slot_limits::FLOW {
            b.push_flow(FlowSlot::Halt).unwrap();
        }
        let err = b.push_flow(FlowSlot::Halt).unwrap_err();
        assert_eq!(err.engine, "flow");
    }
}
