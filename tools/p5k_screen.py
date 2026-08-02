#!/usr/bin/env python3
"""P5-K queue builder + z3 screener.

--build : shapes JSON + ownership -> tools/p5k_queue.json
--screen: run cegis (p5d_cegis, unmodified) on QUEUED entries in rank
          order, N workers (default 3), results appended to a JSONL;
          --merge folds results back into the queue file.
Soundness: identical to P5-D CEGIS -- UNSAT on sample constraints =>
shape impossible for ANY constants; SAT verified outside z3 (2^20 + 10M);
TIMEOUT reported OPEN, never closed.
"""
import sys, os, json, time, argparse
from collections import Counter

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)

QUEUE = os.path.join(TOOLS, "p5k_queue.json")
SHAPES = os.path.join(TOOLS, "p5k_shapes_n9.json")
RESULTS = os.path.join(TOOLS, "p5k_screen_results.jsonl")


def ownership():
    from p5k_enum import normalize
    from p5d_cegis import delete_ops, REAL_11
    own = {}  # ops-json -> (status, owner, evidence)
    SW = [("madd", 0), ("shr", 1), ("xorc", 1), ("xor2", 2, 3),
          ("madd", 4), ("shr", 5), ("xorc", 5), ("xor2", 6, 7),
          ("madd", 8)]
    st, key, cops = normalize(SW)
    own[json.dumps([list(o) for o in cops])] = (
        "OWNED-P5I", "P5-I", "sandwich9: z3 timeout 424s+10800s; "
        "P5-I bit-serial/differential attack in progress")
    UNSAT = [(0, 1), (0, 2), (0, 4), (0, 5), (0, 8), (0, 9), (1, 3),
             (1, 4), (1, 5), (1, 7), (1, 8), (1, 9), (2, 8), (4, 8),
             (5, 8), (7, 8)]
    TIMEOUT = [(0, 7), (2, 3), (2, 4), (2, 5), (2, 7), (2, 9), (4, 6),
               (4, 7), (4, 9), (5, 7), (5, 9), (7, 9)]
    for dels, (stt, ownr) in ((UNSAT, ("CLOSED-P5D", "P5-D")),
                              (TIMEOUT, ("OWNED-P5J", "P5-J"))):
        for (i, j) in dels:
            for new_ops, desc in delete_ops(REAL_11, 1, {i, j}):
                if len(new_ops) != 9:
                    continue
                r = normalize(new_ops)
                if r[0] != "OK":
                    continue
                k = json.dumps([list(o) for o in r[2]])
                if k in own and own[k][0] == "CLOSED-P5D":
                    continue  # UNSAT beats OPEN
                ev = f"deletion del={{{i},{j}}} of REAL_11 ({desc})"
                if stt == "CLOSED-P5D":
                    ev += "; z3 UNSAT at full constant freedom (p5d)"
                else:
                    ev += "; z3 TIMEOUT 120s (p5d), P5-J solving"
                own[k] = (stt, ownr, ev)
    return own


def build():
    with open(SHAPES) as f:
        data = json.load(f)
    own = ownership()
    n_owned = Counter()
    entries = []
    KEEP = 3000
    total_materialized = len(data["shapes"])
    for e in data["shapes"]:
        k = json.dumps(e["ops"])
        if k in own:
            stt, ownr, ev = own[k]
            e["status"], e["owner"], e["evidence"] = stt, ownr, ev
            n_owned[stt] += 1
            entries.append(e)
        elif e["rank"] < KEEP:
            e["status"], e["owner"], e["evidence"] = "QUEUED", "P5-K", ""
            entries.append(e)
    present = {json.dumps(e["ops"]) for e in entries}
    missing = [k for k in own if k not in present]
    for k in missing:  # owned shapes cut off by stratum caps: force-include
        stt, ownr, ev = own[k]
        entries.append({"ops": json.loads(k), "rank": -1, "stratum": None,
                        "feat": None, "score": None, "status": stt,
                        "owner": ownr,
                        "evidence": ev + " [not in materialized head: "
                        "stratum capped]"})
    meta = {
        "date": "2026-08-02", "task": "P5-K 9-op shape completeness",
        "vocabulary": "madd/shr/xorc/xor2 (p5d_cegis semantics)",
        "funnel": {"raw_typed_sequences": 514896782400,
                   "valid_sequences_dp": 1150842615,
                   "after_K1_shr2_dp": 555652601,
                   "after_final_not_shr_dp": 522151181},
        "materialized_strata": data["strata"],
        "totals": data["totals"],
        "total_materialized_shapes": total_materialized,
        "queue_head_size": KEEP,
        "owned_counts": dict(n_owned),
        "owned_forced_in": missing,
        "note": ("entries ranked by structural closeness to the real "
                 "11-op form; statuses: QUEUED (undecided, P5-K), "
                 "SCREEN-UNSAT (closed here), SCREEN-TIMEOUT (open), "
                 "SAT-CANDIDATE (!!), CLOSED-P5D, OWNED-P5I, OWNED-P5J")}
    with open(QUEUE, "w") as f:
        json.dump({"meta": meta, "entries": entries}, f)
    print(f"queue built: {len(entries)} entries; owned={dict(n_owned)}; "
          f"owned-but-missing-from-strata={len(missing)}")
    for k in missing:
        print("  MISSING:", own[k][0], k)


def _worker(job):
    rank, ops_l, timeout_s = job
    from p5d_cegis import cegis, myhash
    ops = [tuple(o) for o in ops_l]
    t0 = time.time()
    verdict, detail = cegis(ops, 1, myhash, f"rank{rank}",
                            solver_timeout_s=timeout_s)
    return {"rank": rank, "ops": ops_l, "verdict": verdict,
            "detail": detail, "secs": round(time.time() - t0, 1)}


def screen(limit, timeout_s, workers):
    import multiprocessing as mp
    with open(QUEUE) as f:
        q = json.load(f)
    done = set()
    if os.path.exists(RESULTS):
        with open(RESULTS) as f:
            for line in f:
                done.add(json.loads(line)["rank"])
    jobs = [(e["rank"], e["ops"], timeout_s)
            for e in sorted(q["entries"], key=lambda e: e["rank"])
            if e["status"] == "QUEUED" and e["rank"] not in done][:limit]
    print(f"screening {len(jobs)} shapes, {workers} workers, "
          f"{timeout_s}s z3 budget each", flush=True)
    ctx = mp.get_context("spawn")
    with ctx.Pool(workers) as pool:
        for res in pool.imap_unordered(_worker, jobs):
            with open(RESULTS, "a") as f:
                f.write(json.dumps(res) + "\n")
            print(f"  rank={res['rank']} {res['verdict']} "
                  f"({res['secs']}s) {res['detail']}", flush=True)
            if res["verdict"] == "FOUND":
                print("!!! SAT-CANDIDATE — validate immediately", flush=True)


def merge():
    with open(QUEUE) as f:
        q = json.load(f)
    res = {}
    with open(RESULTS) as f:
        for line in f:
            r = json.loads(line)
            res[r["rank"]] = r
    n = Counter()
    for e in q["entries"]:
        r = res.get(e["rank"])
        if not r or e["status"] != "QUEUED":
            continue
        v = r["verdict"]
        e["status"] = {"UNSAT": "SCREEN-UNSAT", "TIMEOUT": "SCREEN-TIMEOUT",
                       "FOUND": "SAT-CANDIDATE",
                       "GAVE_UP": "SCREEN-TIMEOUT"}[v]
        e["evidence"] = f"p5k z3 {v} ({r['detail']}; {r['secs']}s)"
        n[e["status"]] += 1
    with open(QUEUE, "w") as f:
        json.dump(q, f)
    print("merged:", dict(n))
    print("status totals:", dict(Counter(e["status"] for e in q["entries"])))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--screen", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    if a.build:
        build()
    if a.screen:
        screen(a.limit, a.timeout, a.workers)
    if a.merge:
        merge()
