//! Loader for JSON fixtures exported from the real Python `problem.py` by
//! `tools/export_fixtures.py` — this is how the Rust harness gets access to
//! bit-for-bit the same workload (and, optionally, the same per-step value
//! trace) that `tests/submission_tests.py` actually grades against, without
//! reimplementing Python's `random` module.

use serde::Deserialize;
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Clone, Deserialize)]
pub struct Params {
    pub forest_height: u32,
    pub n_nodes: u32,
    pub batch_size: u32,
    pub rounds: u32,
    pub seed: u64,
}

#[derive(Debug, Deserialize)]
pub struct Fixture {
    pub params: Params,
    pub mem_in: Vec<u32>,
    pub mem_out: Vec<u32>,
    /// Keyed exactly like `problem::reference_run`'s output:
    /// `"{round}|{i}|{field}"`, plus `"{round}|{i}|hash_stage|{hi}"`.
    #[serde(default)]
    pub trace: HashMap<String, u32>,
}

impl Fixture {
    pub fn load<P: AsRef<Path>>(path: P) -> Fixture {
        let json_text = std::fs::read_to_string(path.as_ref())
            .unwrap_or_else(|e| panic!("reading fixture {:?}: {e}", path.as_ref()));
        serde_json::from_str(&json_text)
            .unwrap_or_else(|e| panic!("parsing fixture {:?}: {e}", path.as_ref()))
    }
}
