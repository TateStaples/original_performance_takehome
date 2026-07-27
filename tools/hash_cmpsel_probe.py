"""H-038: compare/select 1-op re-derivation probe over the fused-hash trace DAG.

Extends tools/hash_relation_probe.py (H-036, family (b): "delete a node whose
consumers re-derive their outputs in 1 op") to the ONE vocabulary that probe —
and every other closed search (G-10 fusion/MITM, H-025 CEGIS/MITM) —
excluded: the machine's compare ops `<` and `==` (alu/valu, result 1/0) and
the flow engine's `select(cond, a, b)`.

What is enumerated (complete within this family):
  * lt(a, b), eq(a, b) over all ordered trace-node pairs: only relevant if
    some trace node were 0/1-valued on all samples — none is (checked and
    reported), so these are structurally dead for node re-derivation; they
    are still enumerated rather than assumed away.
  * select(c, a, b) over all trace-node triples (c any node, a != b): the
    target node must equal a whenever c != 0 and b whenever c == 0.
  * select(c, a, K) / select(c, K, a) with the constant arm K solved from
    samples on which the untaken/taken branch condition holds. On random
    32-bit samples every trace node is nonzero on every sample with
    overwhelming probability, making cond == 0 branches empty; the probe
    measures and reports this instead of assuming it.
  * lt/eq against a solved constant threshold: only meaningful for 0/1
    targets — no trace node qualifies (reported).

Anything surviving N=64 structured+random samples would be bulk-verified on
2**22 random inputs and then need a 2**32 exhaustive or algebraic argument
(hash inputs are arbitrary 32-bit words). Coverage statement: this closes
1-op compare/select re-derivations over this trace-node set; longer
compare/select programs are the Rust fusion_search --cmpsel suite's space.

Run: .venv/bin/python tools/hash_cmpsel_probe.py
"""

import random

M = (1 << 32) - 1
N = 64  # samples

# fused-hash constants (perf_takehome.py _fused_hash_constants)
C0 = 0x7ED55D16
C1 = 0xC761C23C
C2 = 0x165667B1
C3 = 0xD3A2646C
C4 = 0xFD7046C5
C5 = 0xB55A4F09
AP = (C2 + C3) & M
AQ = (C2 << 9) & M


def trace(x: int, nv2: int) -> dict[str, int]:
    """Two chained fused-hash rounds; nv2 is round 2's (val^node) xor mask."""
    t: dict[str, int] = {"x": x, "nv2": nv2}

    def one_round(a: int, pre: str) -> int:
        a1 = (a * 4097 + C0) & M
        t[pre + "a1"] = a1
        t[pre + "t1"] = a1 >> 19
        t[pre + "u1"] = a1 ^ C1
        a2 = t[pre + "u1"] ^ t[pre + "t1"]
        t[pre + "a2"] = a2
        p = (a2 * 33 + AP) & M
        q = (a2 * 16896 + AQ) & M
        t[pre + "p"] = p
        t[pre + "q"] = q
        a3 = p ^ q
        t[pre + "a3"] = a3
        a4 = (a3 * 9 + C4) & M
        t[pre + "a4"] = a4
        t[pre + "t5"] = a4 >> 16
        t[pre + "w5"] = a4 ^ C5
        val = t[pre + "w5"] ^ t[pre + "t5"]
        t[pre + "val"] = val
        return val

    v1 = one_round(x, "")
    t["x2"] = v1 ^ nv2
    one_round(t["x2"], "B")
    return t


def main() -> None:
    rng = random.Random(0x1B038)
    xs = [0, 1, M, 0x80000000, 0xAAAAAAAA, 0x55555555, C0, C5] + [
        rng.getrandbits(32) for _ in range(N - 8)
    ]
    nvs = [rng.getrandbits(32) for _ in range(N)]
    traces = [trace(x, nv) for x, nv in zip(xs, nvs)]
    names = list(traces[0].keys())
    cols = {n: [t[n] for t in traces] for n in names}

    # --- structural preconditions, measured not assumed ---
    bool_nodes = [n for n in names if all(v <= 1 for v in cols[n])]
    zero_hits = {n: sum(1 for v in cols[n] if v == 0) for n in names}
    nodes_with_zero = {n: k for n, k in zero_hits.items() if k > 0}
    print(f"trace nodes: {len(names)}; samples: N={N} (8 structured + {N - 8} random)")
    print(f"0/1-valued nodes (compare-target candidates): {bool_nodes or 'NONE'}")
    print(f"nodes ever equal to 0 on a sample (live select cond==0 branches): {nodes_with_zero or 'NONE'}")

    hits: list[str] = []
    n_checked = 0

    def check(vname: str, desc: str, fn) -> None:
        vcol = cols[vname]
        for i in range(N):
            if fn(traces[i]) != vcol[i]:
                return
        hits.append(f"{vname} = {desc}")

    for vname in names:
        if vname in ("x", "nv2"):
            continue
        vcol = cols[vname]
        srcs = [n for n in names if n != vname]

        # --- lt/eq over node pairs (both orders; eq symmetric) ---
        for a in srcs:
            for b in srcs:
                if a == b:
                    continue
                n_checked += 1
                check(vname, f"lt({a}, {b})", lambda t, a=a, b=b: 1 if t[a] < t[b] else 0)
                if a < b:
                    n_checked += 1
                    check(vname, f"eq({a}, {b})", lambda t, a=a, b=b: 1 if t[a] == t[b] else 0)

        # --- lt/eq vs solved constant (only 0/1 targets can match) ---
        if vname in bool_nodes:
            for a in srcs:
                ones = [traces[i][a] for i in range(N) if vcol[i] == 1]
                zeros_v = [traces[i][a] for i in range(N) if vcol[i] == 0]
                if ones:
                    c = max(ones) + 1
                    n_checked += 1
                    check(vname, f"lt({a}, {c:#x})", lambda t, a=a, c=c: 1 if t[a] < c else 0)
                    c = min(ones)
                    n_checked += 1
                    check(vname, f"lt({c:#x}, {a})", lambda t, a=a, c=c: 1 if c < t[a] else 0)
                    c = ones[0]
                    n_checked += 1
                    check(vname, f"eq({a}, {c:#x})", lambda t, a=a, c=c: 1 if t[a] == c else 0)
                if zeros_v:
                    c = max(zeros_v)
                    n_checked += 1
                    check(vname, f"lt({c:#x}, {a})[z]", lambda t, a=a, c=c: 1 if c < t[a] else 0)

        # --- select(c, a, b) over node triples ---
        for c in srcs:
            ccol = cols[c]
            for a in srcs:
                for b in srcs:
                    if a == b:
                        continue
                    n_checked += 1
                    check(
                        vname,
                        f"select({c}, {a}, {b})",
                        lambda t, c=c, a=a, b=b: t[a] if t[c] != 0 else t[b],
                    )

        # --- select with one solved constant arm ---
        for c in srcs:
            ccol = cols[c]
            zero_idx = [i for i in range(N) if ccol[i] == 0]
            nz_idx = [i for i in range(N) if ccol[i] != 0]
            for a in srcs:
                # select(c, a, K): K solved from a cond==0 sample (else the
                # form is sample-indistinguishable from plain `a`, i.e. dead).
                if zero_idx:
                    K = vcol[zero_idx[0]]
                    n_checked += 1
                    check(
                        vname,
                        f"select({c}, {a}, {K:#x})",
                        lambda t, c=c, a=a, K=K: t[a] if t[c] != 0 else K,
                    )
                # select(c, K, a): K solved from a cond!=0 sample.
                if nz_idx:
                    K = vcol[nz_idx[0]]
                    n_checked += 1
                    check(
                        vname,
                        f"select({c}, {K:#x}, {a})",
                        lambda t, c=c, a=a, K=K: K if t[c] != 0 else t[a],
                    )

    print(f"checked {n_checked} candidate 1-op compare/select derivations")

    # A hit of the form select(c, K, a) where c is nonzero on ALL samples is
    # sample-indistinguishable from the constant K (dead, not a re-derivation);
    # classify hits that survive.
    novel = []
    for h in hits:
        vname, rhs = h.split(" = ", 1)
        if rhs.startswith("select("):
            cond = rhs.split("(", 1)[1].split(",")[0]
            if cond in cols and all(v != 0 for v in cols[cond]):
                # cond never 0 on samples: form equals its taken arm on every
                # sample; only counts if the arm itself is a novel relation,
                # which the pair/triple enumeration reports separately.
                novel.append(h + "   [degenerate: cond nonzero on all samples]")
                continue
        novel.append(h)
    print(f"hits: {len(hits)}")
    if not hits:
        print("  (none) — no 1-op compare/select re-derivation exists over this node set at N=64")
    for h in novel:
        print(" ", h)


if __name__ == "__main__":
    main()
