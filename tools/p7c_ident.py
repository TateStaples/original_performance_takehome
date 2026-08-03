"""P7-C: is the truth-exact model BIT-IDENTICAL to the shipped model?

Builds the 1006 frontier under `base` and under the fully relaxed
(truth-exact + no-mem) model and hashes the emitted program, then
re-measures correctness over 10 seeds. Also does the same for two other
configs so the claim is not a single-point artifact.
"""
from __future__ import annotations

import hashlib
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dev  # noqa: E402
import h060_common as C  # noqa: E402
import p7c_relax as R  # noqa: E402


def digest(prog) -> str:
    h = hashlib.sha256()
    for instr in prog:
        h.update(repr(sorted((e, list(map(str, s))) for e, s in instr.items())).encode())
    return h.hexdigest()[:16]


CONFIGS = {
    "frontier1006": {},
    "no_store_pair": {"store_pair": False},
    "no_disjoint_region": {"store_disjoint_region": False},
}


def main() -> None:
    for name, over in CONFIGS.items():
        out = []
        for mode in ("base", "all"):
            dev.ListScheduler.ready = (R.ORIG if mode == "base"
                                       else R.make_ready(**R.MODES["all"]))  # type: ignore
            kb, prog = C.build(C.frontier(**over))
            out.append((mode, len(prog), digest(prog)))
        dev.ListScheduler.ready = R.ORIG  # type: ignore
        same = out[0][2] == out[1][2]
        print(f"{name:20s} base={out[0][1]} relaxed={out[1][1]} "
              f"identical={same} ({out[0][2]} vs {out[1][2]})")
        sys.stdout.flush()

    # 10-seed correctness of the relaxed build on the frontier
    dev.ListScheduler.ready = R.make_ready(**R.MODES["all"])  # type: ignore
    bad = []
    for seed in range(1, 11):
        cyc, ok = C.measure(C.frontier(), seed=seed)
        if not ok:
            bad.append(seed)
        print(f"  relaxed seed {seed}: {cyc} correct={ok}")
        sys.stdout.flush()
    dev.ListScheduler.ready = R.ORIG  # type: ignore
    print("10-seed relaxed failures:", bad or "none")


if __name__ == "__main__":
    main()
