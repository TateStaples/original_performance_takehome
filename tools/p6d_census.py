#!/usr/bin/env python3
"""P6-D step 0: reproduce P5-I3 sec.13's transfer tally with reasons, and dump
the two recovery buckets (251 cut-test failures, 73 even-K-branch failures)
with enough structure to see WHY each fails.

Read-only; prints a census.  tools/p5i3_transfer.py is imported verbatim.
"""
import json
import sys
from collections import defaultdict, Counter

sys.path.insert(0, "tools")
import p5i3_transfer as T


def census(queue="tools/p5k_queue.json"):
    q = json.load(open(queue))
    ent = q["entries"]
    buckets = defaultdict(list)
    for e in ent:
        ops = [tuple(o) for o in e["ops"]]
        nshr = sum(1 for o in ops if o[0] == "shr")
        if nshr != 2:
            buckets["nshr!=2"].append(e)
            continue
        why = set()
        r = T.shape_transfers(ops, why)
        if r:
            buckets["TRANSFER"].append((e, r))
            continue
        key = " + ".join(sorted(why)) if why else "(none)"
        buckets[key].append(e)
    return ent, buckets


def main():
    ent, buckets = census()
    print("queue entries:", len(ent))
    for k in sorted(buckets, key=lambda k: -len(buckets[k])):
        print("  %-60s %d" % (k, len(buckets[k])))

    # ---- detail on the two recovery buckets -------------------------------
    for key, label in ((
            "no-sandwich-pattern + shrB-not-a-cut", "CUT"), ):
        pass
    cutk = [k for k in buckets if "cut" in k]
    evenk = [k for k in buckets if "even" in k]
    print("\ncut-bucket keys:", cutk, "even-bucket keys:", evenk)

    for k in cutk + evenk:
        rows = buckets[k]
        print("\n=== %s : %d shapes ===" % (k, len(rows)))
        shp = Counter()
        for e in rows:
            ops = [tuple(o) for o in e["ops"]]
            shp[tuple(o[0] for o in ops)] += 1
        for s, n in shp.most_common(12):
            print("   %-56s %d" % (",".join(s), n))
        print("   sample ranks:", [e["rank"] for e in rows[:8]])
        print("   sample ops  :", rows[0]["ops"])


if __name__ == "__main__":
    main()
