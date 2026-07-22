//! Fast, strongly-typed development harness for `perf_takehome.py`'s
//! kernel-building task. See `README.md` in this directory for the
//! intended workflow, and `docs/isa.md` / `docs/problem.md` at the repo
//! root for the specs this is a port of.

pub mod bridge;
pub mod builder;
pub mod fixtures;
pub mod isa;
pub mod machine;
pub mod problem;
pub mod stats;
pub mod vectorized;
