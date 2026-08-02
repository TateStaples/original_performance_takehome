#!/usr/bin/env python3
"""P5-I2: checkpointed sweep with the width-TRUNCATED encoder
(tools/p5i_z3pair2.py) over every sandwich9 pair still undecided.

todo = 482-pair z3 scope  minus  every pair with a REFUTED/FOUND
CHECKPOINT or CHECKPOINT2 line in STATE.md.  (v1-OPEN pairs are retried:
the truncated encoder is strictly stronger per second -- e.g. (28,14)
was v1-OPEN@25s and is v2-REFUTED in 11.9s.)

Appends one CHECKPOINT2 line per attempted pair, crash-safe.

Usage: python3 tools/p5i_sweep2.py [--rung-timeout 25] [--wall-budget 540]
                                   [--order shell|revshell] [--nrand 16]
"""
import argparse
import re
import time

from p5i_z3pair import myhash
from p5i_z3pair2 import decide_pair2

STATE = "/Users/tatestaples/Code/original_performance_takehome/research/strains/p5i/STATE.md"


def scope():
    out = []
    for s1 in range(1, 32):
        for s2 in range(1, 32):
            L = s1 + s2
            if (L == 32 and 1 <= s1 <= 17) or L >= 33:
                out.append((s1, s2))
    return out


def ledger():
    """(closed, v2_attempted) -- closed = REFUTED/FOUND by either encoder."""
    closed, v2 = set(), {}
    for line in open(STATE):
        m = re.match(r"CHECKPOINT2? pair=\((\d+),(\d+)\) verdict=(\w+)", line)
        if m:
            p = (int(m.group(1)), int(m.group(2)))
            if m.group(3) in ("REFUTED", "FOUND"):
                closed.add(p)
            if line.startswith("CHECKPOINT2"):
                v2[p] = m.group(3)
    return closed, v2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rung-timeout", type=int, default=25)
    ap.add_argument("--wall-budget", type=int, default=540)
    ap.add_argument("--order", default="shell", choices=["shell", "revshell"])
    ap.add_argument("--nrand", type=int, default=16)
    ap.add_argument("--redo-v2-open", action="store_true")
    a = ap.parse_args()

    closed, v2 = ledger()
    todo = [p for p in scope() if p not in closed
            and (a.redo_v2_open or p not in v2)]
    key = lambda p: (min(p[0], 32 - p[0]) + min(p[1], 32 - p[1]), p)  # noqa: E731
    todo.sort(key=key, reverse=(a.order == "revshell"))

    t0 = time.time()
    n = nref = 0
    for (s1, s2) in todo:
        if time.time() - t0 > a.wall_budget:
            break
        v, d = decide_pair2(s1, s2, myhash, a.rung_timeout, verbose=False)
        line = (f"CHECKPOINT2 pair=({s1},{s2}) verdict={v} {d} "
                f"rt={a.rung_timeout}s")
        with open(STATE, "a") as f:
            f.write(line + "\n")
        print(line, flush=True)
        n += 1
        nref += (v in ("REFUTED", "FOUND"))
    print(f"SLICE2 DONE: {n} attempted ({nref} closed), {len(todo)-n} queued, "
          f"wall={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
