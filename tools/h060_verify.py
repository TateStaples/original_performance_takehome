"""H-060 verification: the vec_partition knobs are inert when unset.

Compares dev.py's build against a pristine copy of dev.py from `main`
(module-loaded under a different name), instruction stream + scratch
bookkeeping, at the 1006 frontier and a few other configs.

Usage: python3 tools/h060_verify.py [--ref PATH_TO_MAIN_DEV_PY]
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h060_common as C  # noqa: E402
from run_variant import SHAPE  # noqa: E402


def load_ref(path: str) -> Any:
    spec = importlib.util.spec_from_file_location("dev_ref", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dev_ref"] = mod
    spec.loader.exec_module(mod)
    return mod


def build_with(mod: Any, cfg: dict[str, Any]) -> tuple[Any, int, dict]:
    kb = mod.KernelBuilder()
    kb.build_kernel_scheduled(**dict(SHAPE, **cfg))
    return kb.instrs, kb.scratch_next_addr, dict(kb.scratch_debug)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="")
    args = ap.parse_args()

    ref_path = args.ref
    tmp = None
    if not ref_path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
        tmp.write(subprocess.run(["git", "show", "main:dev.py"], cwd=REPO_ROOT,
                                 capture_output=True, text=True,
                                 check=True).stdout)
        tmp.close()
        ref_path = tmp.name
    ref = load_ref(ref_path)
    import dev

    cases: list[tuple[str, dict[str, Any]]] = [
        ("frontier (flags absent)", {}),
        ("frontier + inert knobs", {"vec_partition_plan": (),
                                    "vec_tie_offload": 0,
                                    "vec_tie_phase": 0,
                                    "vec_reclaim_margin": -1}),
        ("no rings", {"parity_ring": False, "parity_ring_plan": ()}),
        ("no rings, l4_gmin (9,30)", {"parity_ring": False,
                                      "parity_ring_plan": (),
                                      "l4_gmin": (9, 30)}),
        ("hash1_avec_race", {"hash1_avec_race": True}),
        ("tie_break vec_valu", {"tie_break": ("fold_flow", "vec_valu")}),
    ]
    ok = True
    for name, ov in cases:
        cfg = C.frontier(**ov)
        rcfg = {k: v for k, v in cfg.items()
                if not k.startswith("vec_partition") and not k.startswith("vec_tie")
                and k != "vec_reclaim_margin"}
        a = build_with(ref, rcfg)
        b = build_with(dev, cfg)
        same = a[0] == b[0] and a[1] == b[1] and a[2] == b[2]
        ok &= same
        print(f"{'OK ' if same else 'MISMATCH'} {name}: "
              f"ref {len(a[0])} bundles / scratch {a[1]} vs "
              f"dev {len(b[0])} bundles / scratch {b[1]}")

    # The partition must be able to REPRODUCE the race exactly: an explicit
    # per-site plan read off the raced build replays it bit-for-bit.
    import h060_race as R
    R.LOG.clear()
    orig = dev.KernelBuilder._sched_vec
    dev.KernelBuilder._sched_vec = R.logging_sched_vec  # type: ignore
    try:
        C.build(C.frontier())
    finally:
        dev.KernelBuilder._sched_vec = orig  # type: ignore
    plan = tuple((r[0], "a" if r[5] == "alu" else "v") for r in R.LOG)
    b = build_with(dev, C.frontier(vec_partition_plan=plan))
    a = build_with(ref, C.frontier())
    same = a[0] == b[0]
    ok &= same
    print(f"{'OK ' if same else 'MISMATCH'} replay: full per-site plan "
          f"({len(plan)} sites) reproduces the race -> "
          f"{len(b[0])} bundles (ref {len(a[0])})")

    if tmp:
        os.unlink(tmp.name)
    print("ALL OK" if ok else "FAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
