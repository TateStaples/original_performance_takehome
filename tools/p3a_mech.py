"""P3-A: mechanism-level census of the shipped 1006 kernel.

Builds on tools/p3a_attrib.py's call-site capture and folds every placed slot
into one of the mechanisms the Phase-3 charter's budget chain names:

  hash / foldin        -- the fixed 11-op hash + the node_val fold-in xor
  idx.parity           -- parity extract  (vl & 1)
  idx.addr             -- gather-address recurrence (madd 2*g+omf, omf select)
  idx.exit             -- epoch-exit gaddr reconstruction from position
  pos.fold             -- position accumulator p := 2p+b  (tournament support)
  pos.seed             -- ringed L2 position seed
  cond.mask            -- condition extraction from the position accumulator
  tourn.L1/L2/L3       -- broadcast-table folds for served levels 1..3
  tourn.L4             -- the level-4 pair machinery (W folds, U combines)
  setup                -- everything emitted outside the round loop
  gather               -- load slots

Usage: python3 tools/p3a_mech.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import p3a_attrib as A  # noqa: E402
from problem import VLEN  # noqa: E402
import perf_takehome as P  # noqa: E402

# line -> mechanism, keyed on the *_round_stage_generator* frame line when the
# emit happened inside the round loop, else on the outer builder line.
GEN = {
    1575: "hash.foldin",
    **{l: "hash.core" for l in (1576, 1578, 1579, 1580, 1582, 1583, 1584,
                                1586, 1587, 1589, 1590)},
    1615: "idx.parity", 1617: "idx.parity", 1620: "idx.parity",
    1622: "idx.parity",
    1655: "idx.addr", 1656: "idx.addr",
    1627: "idx.exit", 1631: "idx.exit",
    1446: "tourn.L1",
    1453: "tourn.L2", 1454: "tourn.L2", 1455: "tourn.L2", 1459: "tourn.L2",
    1464: "tourn.L2", 1465: "tourn.L2", 1466: "tourn.L2",
    1456: "pos.seed",
    1460: "pos.fold", 1473: "pos.fold", 1485: "pos.fold", 1515: "pos.fold",
    1534: "pos.fold",
    1483: "cond.mask", 1484: "cond.mask",
    1474: "tourn.L3", 1475: "tourn.L3", 1476: "tourn.L3", 1477: "tourn.L3",
    1478: "tourn.L3", 1479: "tourn.L3", 1480: "tourn.L3",
    1486: "tourn.L3", 1487: "tourn.L3", 1488: "tourn.L3", 1489: "tourn.L3",
    1490: "tourn.L3", 1491: "tourn.L3", 1492: "tourn.L3",
    1531: "cond.mask", 1550: "cond.mask", 1557: "cond.mask",
    **{l: "tourn.L4" for l in (1502, 1505, 1508, 1511, 1516, 1535, 1536, 1537,
                               1538, 1539, 1540, 1541, 1542, 1543, 1544, 1545,
                               1546, 1552, 1553, 1559)},
    1670: "gather.load",
    1564: "debug", 1593: "debug",
}


def mech(chain: tuple[str, ...]) -> str:
    for site in chain:
        fn, _, ln = site.rpartition(":")
        if fn == "_round_stage_generator":
            return GEN.get(int(ln), f"UNMAPPED:{ln}")
    return "setup"


def main() -> None:
    kb = P.KernelBuilder()
    kb.build_kernel(forest_height=10, n_nodes=2047, batch_size=256, rounds=16)
    print(f"cycles {len(kb.instrs)}")

    av: Counter[str] = Counter()      # alu+valu lane-ops
    slots: Counter[tuple[str, str]] = Counter()   # (mech, engine) -> slots
    for chain, engine, op, r, l, g in A.records:
        m = mech(chain)
        slots[(m, engine)] += 1
        if engine == "alu":
            av[m] += 1
        elif engine == "valu":
            av[m] += VLEN

    order = sorted(av, key=lambda m: -av[m])
    print(f"\n{'mechanism':<16}{'alu+valu':>10}{'alu sl':>8}{'valu sl':>9}"
          f"{'flow':>7}{'load':>7}{'store':>7}")
    tot = 0
    for m in order:
        tot += av[m]
        print(f"{m:<16}{av[m]:>10}{slots[(m,'alu')]:>8}{slots[(m,'valu')]:>9}"
              f"{slots[(m,'flow')]:>7}{slots[(m,'load')]:>7}{slots[(m,'store')]:>7}")
    for m in sorted(set(k[0] for k in slots) - set(order)):
        print(f"{m:<16}{0:>10}{0:>8}{0:>9}"
              f"{slots[(m,'flow')]:>7}{slots[(m,'load')]:>7}{slots[(m,'store')]:>7}")
    print(f"{'TOTAL':<16}{tot:>10}")

    # roll-ups the charter cares about
    hashv = av["hash.core"] + av["hash.foldin"]
    idxmin = 2 * 512 * VLEN
    nonhash = tot - hashv
    print(f"\nhash          {hashv}")
    print(f"non-hash      {nonhash}")
    print(f"idx-minimum   {idxmin}  (2 vec-ops x 512 group-rounds x 8)")
    print(f"BUDGET LINE   {nonhash - idxmin}  (target <= 1744)")

    # tournament-support subtotal (what the charter calls 'support arithmetic')
    support = sum(av[m] for m in av if m.startswith(("pos.", "cond.", "tourn.")))
    print(f"tournament support+folds {support} lane-ops "
          f"({support // VLEN} vec-op equivalents)")


if __name__ == "__main__":
    main()
