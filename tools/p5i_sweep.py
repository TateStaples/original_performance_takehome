#!/usr/bin/env python3
"""P5-I: checkpointed z3 sweep over the sandwich9 pairs still open after
the theory kills (see research/strains/p5i/STATE.md secs. 1-3, 6).

Open set = {s1+s2 == 32, s1 in 1..17} + {s1+s2 >= 33} minus pairs already
checkpointed as REFUTED/FOUND in STATE.md. OPEN checkpoints are retried
only when --retry-open is given (escalation pass with a bigger budget).

Usage: python3 tools/p5i_sweep.py [--rung-timeout 25] [--wall-budget 400]
                                  [--retry-open] [--order s2|L|revL]
Appends one CHECKPOINT line per decided pair to STATE.md (crash-safe).
"""
import argparse
import re
import time

from p5i_z3pair import decide_pair, myhash

STATE = "/Users/tatestaples/Code/original_performance_takehome/research/strains/p5i/STATE.md"


def open_pairs():
    out = []
    for s1 in range(1, 32):
        for s2 in range(1, 32):
            L = s1 + s2
            if L == 32 and 1 <= s1 <= 17:
                out.append((s1, s2))
            elif L >= 33:
                out.append((s1, s2))
    return out


def done_pairs(retry_open):
    done = {}
    with open(STATE) as f:
        for line in f:
            m = re.match(r"CHECKPOINT pair=\((\d+),(\d+)\) verdict=(\w+)", line)
            if m:
                done[(int(m.group(1)), int(m.group(2)))] = m.group(3)
    if retry_open:
        return {p for p, v in done.items() if v in ("REFUTED", "FOUND")}
    return set(done)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rung-timeout", type=int, default=25)
    ap.add_argument("--wall-budget", type=int, default=400)
    ap.add_argument("--retry-open", action="store_true")
    ap.add_argument("--order", default="shell", choices=["s2", "L", "revL", "shell"])
    a = ap.parse_args()

    todo = [p for p in open_pairs() if p not in done_pairs(a.retry_open)]
    if a.order == "s2":
        todo.sort(key=lambda p: (p[1], p[0]))
    elif a.order == "L":
        todo.sort(key=lambda p: (p[0] + p[1], p[0]))
    elif a.order == "revL":
        todo.sort(key=lambda p: (-(p[0] + p[1]), p[0]))
    else:
        # measured difficulty: extreme shifts easy, middle band hard
        todo.sort(key=lambda p: (min(p[0], 32 - p[0]) + min(p[1], 32 - p[1]), p))

    t0 = time.time()
    n = 0
    for (s1, s2) in todo:
        if time.time() - t0 > a.wall_budget:
            break
        v, d = decide_pair(s1, s2, myhash, a.rung_timeout, verbose=False)
        line = f"CHECKPOINT pair=({s1},{s2}) verdict={v} {d} rt={a.rung_timeout}s"
        with open(STATE, "a") as f:
            f.write(line + "\n")
        print(line, flush=True)
        n += 1
    remaining = len(todo) - n
    print(f"SLICE DONE: {n} pairs decided this slice, {remaining} still queued, "
          f"wall={time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
