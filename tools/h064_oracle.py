"""H-064: WINDOWED-CAPACITY oracle for the head ramp.

`tools/h063_oracle.py` prices op CLASSES (reroute to the free debug engine).
This one prices per-engine BANDWIDTH inside a cycle window, using the offline
greedy model in `tools/backtrack_sched.py` (which reproduces dev's greedy
bit-exactly -- see its `validate`).  That is the question the ramp poses:
cycles 0..30 run the load engine at 2/2 with nothing but SETUP loads, while
valu/alu idle at the very front because no input vector has arrived yet.

It also supports op-level floors (delay a set of ops) and op-level "free"
(zero slot cost) so a restructuring can be priced before it is written.

Usage (repo root):
  python3 tools/h064_oracle.py caps        # widen each engine over [0,K)
  python3 tools/h064_oracle.py headload    # load-engine width sweep, K sweep
  python3 tools/h064_oracle.py consts      # price the 6 hash-constant loads
  python3 tools/h064_oracle.py valchain    # price the va address chain depth
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from typing import Any, Iterable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import backtrack_sched as B  # noqa: E402
import h064_chain as H  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402


def greedy(ops, preds, floors, cap_win=None, free=frozenset(),
           extra_floors=None, lag_override=None, pin=None):
    """Emission-order earliest-feasible greedy, with:
       cap_win: {engine: (lo, hi, cap)} -- cap applies for lo <= c < hi
       free:    set of op indices that consume no slot
       extra_floors: {i: cycle}
       lag_override: {(i, j): lag} to shorten a specific edge
    Returns (place, n_nonempty_cycles)."""
    n = len(ops)
    place = [0] * n
    eng_idx = {e: k for k, e in enumerate(B.ENGINES)}
    caps = [SLOT_LIMITS[e] for e in B.ENGINES]
    win = {}
    for e, (lo, hi, cap) in (cap_win or {}).items():
        win[eng_idx[e]] = (lo, hi, cap)
    occ: list[list[int]] = []

    def cap_at(e, c):
        w = win.get(e)
        if w is not None and w[0] <= c < w[1]:
            return w[2]
        return caps[e]

    for i in range(n):
        if pin is not None and i in pin:
            place[i] = pin[i]
            while len(occ) <= place[i]:
                occ.append([0] * len(B.ENGINES))
            continue
        ready = floors[i]
        if extra_floors:
            ef = extra_floors.get(i)
            if ef is not None and ef > ready:
                ready = ef
        for j, lag in preds[i]:
            if lag_override is not None:
                lag = lag_override.get((i, j), lag)
            t = place[j] + lag
            if t > ready:
                ready = t
        if i in free:
            place[i] = ready
            while len(occ) <= ready:
                occ.append([0] * len(B.ENGINES))
            continue
        e = eng_idx[ops[i][0]]
        c = ready
        while True:
            while len(occ) <= c:
                occ.append([0] * len(B.ENGINES))
            if occ[c][e] < cap_at(e, c):
                break
            c += 1
        occ[c][e] += 1
        place[i] = c
    nonempty = sum(1 for row in occ if any(row))
    return place, nonempty


def base(ops, preds, floors):
    return greedy(ops, preds, floors)


def cmd_caps(ops, preds, floors, info):
    _, b = base(ops, preds, floors)
    print(f"baseline (offline greedy) = {b}")
    for e in ("load", "valu", "alu", "flow", "store"):
        for K in (8, 16, 31, 65):
            for cap in (SLOT_LIMITS[e] * 2, 64):
                _, c = greedy(ops, preds, floors, cap_win={e: (0, K, cap)})
                print(f"  {e:<5} cap {cap:<3} over [0,{K:<3}) -> {c:<5} "
                      f"delta {c - b:+d}")


def cmd_headload(ops, preds, floors, info):
    _, b = base(ops, preds, floors)
    print(f"baseline = {b}")
    print("load-engine width in the head window (the ramp's only saturated engine)")
    for K in (4, 8, 12, 16, 24, 31, 40, 65):
        row = []
        for cap in (3, 4, 6, 8, 64):
            _, c = greedy(ops, preds, floors, cap_win={"load": (0, K, cap)})
            row.append(f"cap{cap}={c}({c - b:+d})")
        print(f"  [0,{K:<3}) " + "  ".join(row))


def _setup_load_groups(ops, info):
    names, est, place = info["names"], info["est"], info["place"]
    groups: dict[str, list[int]] = {"const": [], "ptrload": [], "lv": [],
                                    "val": [], "other": []}
    for i, op in enumerate(ops):
        if op[0] != "load" or op[10] is not None:
            continue
        nm = H.opname(op)
        w = op[3][0] if op[3] else None
        wn = names.get(w, "")
        if nm == "const":
            groups["const"].append(i)
        elif nm == "vload" and wn.startswith("lv["):
            groups["lv"].append(i)
        elif nm == "vload" and wn.startswith("val"):
            groups["val"].append(i)
        elif nm == "load":
            groups["ptrload"].append(i)
        else:
            groups["other"].append(i)
    return groups


def cmd_consts(ops, preds, floors, info):
    _, b = base(ops, preds, floors)
    g = _setup_load_groups(ops, info)
    print(f"baseline = {b}")
    for k, v in g.items():
        print(f"  group {k:<8} n={len(v):<3} placed "
              f"{sorted(info['place'][i] for i in v)[:8]}...")
    for k, v in g.items():
        if not v:
            continue
        _, c = greedy(ops, preds, floors, free=frozenset(v))
        print(f"  free {k:<8} ({len(v):>2} loads) -> {c} ({c - b:+d})")
    # free only the 6 "big" hash constants (those whose const feeds a
    # vbroadcast of a named C*/a* vector)
    names = info["names"]
    big = []
    for i in g["const"]:
        w = ops[i][3][0]
        # find the consumer vbroadcast
        for j, op in enumerate(ops):
            if op[0] == "valu" and H.opname(op) == "vbroadcast" and op[2] and op[2][0] == w:
                nm = names.get(op[3][0], "")
                if nm.startswith(("C", "ap[", "aq[")):
                    big.append(i)
                break
    print(f"  big hash-const loads: {big}")
    if big:
        _, c = greedy(ops, preds, floors, free=frozenset(big))
        print(f"  free big consts ({len(big)}) -> {c} ({c - b:+d})")


def cmd_valchain(ops, preds, floors, info):
    """Price the va (value-address) chain: it is 4 serial +va_c32 chains of
    depth 11.  Simulate a fully-parallel version by zeroing the lag on the
    va->va edges (i.e. as if every va were computed from a base in 1 step)."""
    _, b = base(ops, preds, floors)
    names = info["names"]
    va = [i for i, op in enumerate(ops)
          if op[10] is None and op[3] and names.get(op[3][0], "").startswith("va")]
    print(f"baseline = {b};  {len(va)} va ops")
    vaset = set(va)
    lag0 = {}
    for i in va:
        for j, lag in preds[i]:
            if j in vaset:
                lag0[(i, j)] = 0
    _, c = greedy(ops, preds, floors, lag_override=lag0)
    print(f"  va chain collapsed to depth 1 -> {c} ({c - b:+d})")
    _, c = greedy(ops, preds, floors, free=frozenset(va))
    print(f"  va ops free (slots only)     -> {c} ({c - b:+d})")
    _, c = greedy(ops, preds, floors, free=frozenset(va), lag_override=lag0)
    print(f"  both                          -> {c} ({c - b:+d})")


def cmd_ceiling(ops, preds, floors, info):
    """THE CEILING for H-064: pretend the whole head setup phase is
    instantaneous -- zero slots AND every setup value already resident at
    cycle 0.  No physical restructuring can beat this, because reaching
    memory at all costs const(c0) -> load(c1) -> vload(c2) -> readable c3."""
    _, b = base(ops, preds, floors)
    place = info["place"]
    for cut in (16, 40, 65, 10**9):
        head = {i for i, op in enumerate(ops) if op[10] is None and place[i] < cut}
        pin = dict.fromkeys(head, 0)
        _, c = greedy(ops, preds, floors, free=head, pin=pin)
        print(f"  setup ops placed <{cut:<10} ({len(head):>3} ops) instantaneous "
              f"at cycle 0 -> {c} ({c - b:+d})")
    # softer: keep the slots, only collapse the chain (all setup at cycle 0)
    head = {i for i, op in enumerate(ops) if op[10] is None and place[i] < 40}
    _, c = greedy(ops, preds, floors, extra_floors=None,
                  lag_override={(i, j): 0 for i in range(len(ops))
                                for j, _ in preds[i] if j in head})
    print(f"  setup->* edges lag 0 (chain collapsed, slots kept) -> {c} ({c - b:+d})")
    # and: free the head setup slots but keep the chain
    _, c = greedy(ops, preds, floors, free=head)
    print(f"  head setup slot-free, chain kept -> {c} ({c - b:+d})")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "caps"
    data, ops, preds, floors = H.capture()
    names = H.names_of(data["scratch_debug"])
    est, tail, lst, slack, place, bind = H.analyse(data, ops, preds, floors)
    info = {"names": names, "est": est, "place": place, "slack": slack,
            "bind": bind, "data": data}
    pl, n = base(ops, preds, floors)
    assert n == data["n_cycles"], f"model {n} != real {data['n_cycles']}"
    assert pl == place, "offline greedy diverged from the real placement"
    print(f"# model validated: {n} cycles, {len(ops)} ops")
    {"caps": cmd_caps, "headload": cmd_headload, "consts": cmd_consts,
     "valchain": cmd_valchain, "ceiling": cmd_ceiling}[cmd](ops, preds, floors, info)


if __name__ == "__main__":
    main()
