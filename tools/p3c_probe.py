"""P3-C: empirical marginal-cost probe for the design-space cost model.

Builds `dev.KernelBuilder.build_kernel_scheduled` at a family of serving
configurations and reports, for each, the raw per-engine census
(alu+valu lane-ops / load slots / flow slots / store slots) plus the
served/gathered group-round split.  Differences between rows give the
MARGINAL census cost of serving one more group-round at a given level,
which is what `p3c_design_cost.py` needs as its coefficients.

Read-only: imports dev.py, modifies nothing.

Usage (repo root):  python3 tools/p3c_probe.py [config-name ...]
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from problem import VLEN  # noqa: E402
import dev  # noqa: E402

FOREST_HEIGHT = 10
BATCH_SIZE = 256
ROUNDS = 16
N_GROUPS = BATCH_SIZE // VLEN
PERIOD = FOREST_HEIGHT + 1

BASE = dict(
    alu_offload=True,
    parity_conds=True,
    c5_prexored_value_domain=True,
    auto_raced_first_fold_levels=(1, 2),
    pair_tournament_second_fold_race=True,
    pair_tournament_first_fold_race=3,
    idx_recurrence_race=True,
    derive_consts=True,
    alu_val_addrs=True,
    c5_primed_gather_levels=(5,),
    store_pair=True,
    reverse_newest_parity_fold=(15,),
    newest_parity_last_leaf_diff_tables=True,
    temp_and_cond_pool_sizes=(16, 4),
)


def census(kb) -> dict:
    """Per-engine slot/lane-op census of a built kernel."""
    ops: Counter[tuple[str, str]] = Counter()
    for bundle in kb.instrs:
        for engine, slots in bundle.items():
            if engine == "debug":
                continue
            for slot in slots:
                ops[(engine, slot[0])] += 1
    lane = 0
    loads = flows = stores = 0
    madd_lane = 0
    for (engine, op), n in ops.items():
        if engine == "alu":
            lane += n
            if op == "multiply_add":
                madd_lane += n
        elif engine == "valu":
            if op in ("pause", "add_imm"):
                lane += n
            else:
                lane += VLEN * n
                if op == "multiply_add":
                    madd_lane += VLEN * n
        elif engine == "load":
            loads += n
        elif engine == "store":
            stores += n
        elif engine == "flow":
            flows += n
    n_gather = ops[("load", "load")]
    return dict(
        cycles=len(kb.instrs),
        lane=lane,
        madd_lane=madd_lane,
        load=loads,
        flow=flows,
        store=stores,
        vselect=ops[("flow", "vselect")],
        gather_loads=n_gather,
        gathered_gr=n_gather // VLEN,
        scratch=kb.scratch_next_addr,
        ops=ops,
    )


def build(**kw):
    kb = dev.KernelBuilder()
    cfg = dict(BASE)
    cfg.update(kw)
    kb.build_kernel_scheduled(BATCH_SIZE, ROUNDS, FOREST_HEIGHT, **cfg)
    return kb


CONFIGS = {
    # name: kwargs
    "T3_g12_30":  dict(tournament_levels=(1, 2, 3), l4_gmin=(12, 30)),
    "T3_g16_30":  dict(tournament_levels=(1, 2, 3), l4_gmin=(16, 30)),
    "T3_g20_30":  dict(tournament_levels=(1, 2, 3), l4_gmin=(20, 30)),
    "T3_g26_30":  dict(tournament_levels=(1, 2, 3), l4_gmin=(26, 30)),
    "T3_g30_30":  dict(tournament_levels=(1, 2, 3), l4_gmin=(30, 30)),
    "T3_g6_31":   dict(tournament_levels=(1, 2, 3), l4_gmin=(6, 31)),
    "T2_g30_30":  dict(tournament_levels=(1, 2), l4_gmin=(30, 30),
                       auto_raced_first_fold_levels=(1, 2),
                       c5_primed_gather_levels=(),
                       pair_tournament_first_fold_race=(),
                       pair_tournament_second_fold_race=False),
    "T4_g30_30":  dict(tournament_levels=(1, 2, 3, 4), l4_gmin=(30, 30),
                       c5_primed_gather_levels=(),
                       pair_tournament_first_fold_race=(),
                       pair_tournament_second_fold_race=False,
                       reverse_newest_parity_fold=(),
                       newest_parity_last_leaf_diff_tables=False),
    "T5_g30_30":  dict(tournament_levels=(1, 2, 3, 4, 5), l4_gmin=(30, 30),
                       c5_primed_gather_levels=(),
                       pair_tournament_first_fold_race=(),
                       pair_tournament_second_fold_race=False,
                       reverse_newest_parity_fold=(),
                       newest_parity_last_leaf_diff_tables=False),
}


def main() -> None:
    want = sys.argv[1:] or list(CONFIGS)
    rows = []
    for name in want:
        kw = CONFIGS[name]
        t0 = time.time()
        try:
            c = census(build(**kw))
        except Exception as e:  # noqa: BLE001
            print(f"{name:<12} FAILED {type(e).__name__}: {str(e)[:150]}")
            continue
        c["name"] = name
        c["secs"] = time.time() - t0
        rows.append(c)
        print(f"{name:<12} cyc={c['cycles']:<5} lane={c['lane']:<7} "
              f"madd_lane={c['madd_lane']:<6} load={c['load']:<5} "
              f"flow={c['flow']:<5} vsel={c['vselect']:<5} "
              f"gath_gr={c['gathered_gr']:<4} scratch={c['scratch']:<5} "
              f"({c['secs']:.1f}s)")
        sys.stdout.flush()
    print()
    for c in rows:
        print(f"-- {c['name']} op detail")
        for (e, o), n in sorted(c["ops"].items()):
            print(f"     {e:<6}{o:<16}{n:>7}")


if __name__ == "__main__":
    main()
