#!/usr/bin/env python3
"""P5-A: realized cost of the with-indices writeback tail, by injection.

Design (research/strains/p5a/STATE.md section 1): per group g,
    p_g  = v&(val_g, one_vec)          (parity of post-hash round-15 value)
    pb_g = v-(p_g, twelve_vec)         (bias; const vec from 1 vbroadcast)
    f_g  = madd(gaddr_g, two_vec, pb_g)  -> final level-5 index vector
    vstore(addr_g, f_g)                (addr_g = inp_indices_p + 8g, alu add)
32 groups: +96 valu vec-ops, +1 vbroadcast, +32 alu, +32 vstores.

Method: backtrack_sched.capture() the mainline-equivalent dev build, append
the tail ops in emission order, rebuild the hazard DAG, offline greedy, and
compare non-empty cycle counts. Timing-exact modelling notes:
  * p_g reads the REAL val_g words -> RAW edge from the group's final
    round-15 hash op (the true binding input).
  * gaddr_g / pos_g reads are OMITTED: their producers are strictly earlier
    than val_g's (round-15 loads feed the round-15 hash), so the edge can
    never bind; values-wrong-timing-right is fine for a cost model.
  * temps live on the group's st_g vector (dead after round 15; WAW/WAR
    edges against its real last writer/readers are kept, honestly).
  * addr scalars write fake words (real impl: 32 dead scalar-pool words;
    reads non-binding — base scalar + cached g*8 consts exist from setup).

Usage: python3 tools/p5a_tail.py [--recapture]
"""

from __future__ import annotations

import os
import pickle
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.environ.get(
    "P5A_SCRATCH",
    "/private/tmp/claude-501/-Users-tatestaples-Code-original-performance-takehome/"
    "3c5b1f32-7f70-46d9-9d31-685ca3585579/scratchpad")
os.environ.setdefault("H51_SCRATCH", SCRATCH)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import backtrack_sched as B  # noqa: E402

CACHE = os.path.join(SCRATCH, "p5a_capture.pkl")


def get_capture():
    if os.path.exists(CACHE) and "--recapture" not in sys.argv:
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    data = B.capture()
    os.makedirs(SCRATCH, exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(data, f)
    return data


def vec_groups(scratch_debug, base):
    """All 8-word vectors whose name starts with `base`, sorted by addr."""
    out = []
    for addr, (name, length) in scratch_debug.items():
        stripped = name.rstrip("0123456789")
        if stripped == base and length == 8:
            out.append(addr)
    return sorted(out)


def main() -> None:
    data = get_capture()
    ops = list(data["ops"])
    pw = data["pair_writes"]
    sd = data["scratch_debug"]

    preds, floors = B.build_model(ops, pw)
    place0, n0 = B.greedy_schedule(ops, preds, floors)
    print(f"baseline: captured {data['n_cycles']} cycles, "
          f"offline greedy {n0} non-empty cycles, {len(ops)} ops")

    vals = vec_groups(sd, "val")
    sts = vec_groups(sd, "st") or vec_groups(sd, "nv")
    ones = vec_groups(sd, "one_vec")
    twos = vec_groups(sd, "two_vec")
    print(f"found: val x{len(vals)}, temp(st/nv) x{len(sts)}, "
          f"one_vec x{len(ones)}, two_vec x{len(twos)}")
    assert len(vals) >= 32 and len(sts) >= 32, "scratch name bases changed"
    one_words = tuple(range(ones[0], ones[0] + 8)) if ones else ()
    two_words = tuple(range(twos[0], twos[0] + 8)) if twos else ()

    # context: when do the val vectors receive their final write?
    val_words = {w for a in vals[:32] for w in range(a, a + 8)}
    last_val_cycle = 0
    for i, op in enumerate(ops):
        if any(w in val_words for w in op[3]):
            last_val_cycle = max(last_val_cycle, place0[i])
    print(f"last val write at greedy cycle {last_val_cycle} of {n0}")

    # copy mem-hazard flags from an existing result vstore
    vst = next(op for op in reversed(ops) if op[0] == "store")
    _, _, _, _, mr, mw, ig_mr, ig_mw, _, _, _ = vst
    print(f"vstore flags copied: mem_write={mw} ig_mr={ig_mr} ig_mw={ig_mw}")

    FAKE = 100_000            # model-only addresses (see docstring)
    tail = []

    def add(engine, name, reads, writes, mem_write=False):
        tail.append((engine, (name,), tuple(reads), tuple(writes),
                     False, mem_write, ig_mr if mem_write else False,
                     ig_mw if mem_write else False, 0, 0, f"p5a_{name}"))

    cvec = tuple(range(FAKE, FAKE + 8))
    add("valu", "vbroadcast", (), cvec)                      # twelve_vec
    for g in range(32):
        vg = tuple(range(vals[g], vals[g] + 8))
        tg = tuple(range(sts[g], sts[g] + 8))
        add("valu", "v&", vg + one_words, tg)                # p
        add("valu", "v-", tg + cvec, tg)                     # pb
        add("valu", "multiply_add", tg + two_words, tg)      # final (gaddr
        #                                   read omitted: never binding)
        aw = (FAKE + 100 + g,)
        add("alu", "+", (), aw)                              # addr scalar
        add("store", "vstore", aw + tg, (), mem_write=True)

    ext = ops + tail
    preds1, floors1 = B.build_model(ext, pw)
    place1, n1 = B.greedy_schedule(ext, preds1, floors1)
    print(f"\nextended: {len(ext)} ops -> {n1} non-empty cycles")
    print(f"REALIZED TAIL DELTA (greedy, this schedule class): "
          f"{n1 - n0} cycles")
    tail_cycles = sorted(place1[len(ops) + i] for i in range(len(tail)))
    print(f"tail ops placed in cycles {tail_cycles[0]}..{tail_cycles[-1]}; "
          f"baseline end {n0 - 1}, extended end {max(place1)}")
    # census restatement
    print("\ncensus delta: valu +97 vec-ops (+776 lane-ops), alu +32, "
          "load +0..1, store +32, flow 0  => +13.5 cycles of 60/cyc floor")


if __name__ == "__main__":
    main()
