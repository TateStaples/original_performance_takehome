"""P3-A: optimizer over the SERVING design space, scored by simultaneous floors.

Structural facts used (each derived, see research/strains/p3a/STATE.md):

  T1  serving one group-round at level d costs exactly 2^d - 1 two-way ops,
      and EVERY one of them is independently placeable on flow (vselect) or
      valu (multiply_add), given 2^d precomputed broadcast vectors.
      Proof: a node combining constant subtables A (bit=0) and B (bit=1) is
      either vselect(b, B[q], A[q]) or madd(b, (B-A)[q], A[q]); both children
      are again tournaments over CONSTANT tables of size 2^(d-1).  Hence no
      interior node ever needs a runtime subtract.
  T2  conditions are the raw parity bits (exact 0/1) if they are retained
      per level instead of packed into a position accumulator -> the mask
      extractions and the lagged position folds both vanish; the position is
      instead built by Horner ONLY at a gather boundary (d madds for d bits).
  T3  the gather-address recurrence is 1 madd + one 2-way constant choice
      (flow vselect or 1 valu op) per gathered group-round.

Usage: python3 tools/p3a_opt.py
"""

from __future__ import annotations

# measured on the shipped 1006 kernel (tools/p3a_mech.py)
HASH_CORE = 5280      # vec-ops, incl. 352 elided ^C5 (primed levels {5,6}+tables)
FOLDIN = 512
PARITY = 448
SETUP_VEC_MIN = 70    # 48 broadcast vectors + 12 priming vxors + ~10 scalar-eq
SETUP_VEC_SHIPPED = 83
SETUP_LOAD = 60
SETUP_FLOW_MIN = 2    # pause only; the 20 add_imm move to alu (2.5 vec-eq)
ADDIMM_ALU_VEC = 3    # 20 alu slots ~ 2.5 vec-op equivalents, rounded up
GR = {d: (64 if d <= 4 else 32) for d in range(11)}
VALUE_GR = sum(GR[d] for d in range(1, 11))   # 448


def profile(s: int) -> dict[int, int]:
    out, left = {}, s
    for L in range(1, 11):
        take = min(GR[L], left)
        if take:
            out[L] = take
            left -= take
        if not left:
            break
    return out


def evaluate(C: int, s: int, setup_vec: int = SETUP_VEC_MIN,
             setup_flow: int = SETUP_FLOW_MIN, store_bcast: bool = True):
    prof = profile(s)
    g = VALUE_GR - s
    folds = sum(n * (2 ** L - 1) for L, n in prof.items())
    n4 = prof.get(4, 0)
    # one exit per group per epoch-0 (mandatory), plus each round-15 L4
    # group-round left unserved (its address must be built at round 14).
    exits = 32 + max(0, 32 - n4)
    # exit = d madds instead of the steady 1 madd (d = 3 or 4 bits)
    idx_valu = g + 2 * exits
    idx_sel = g                       # 2-way constant choice, flow-eligible

    loads = 8 * g + SETUP_LOAD
    if loads > 2 * C:
        return None
    # spend leftover load slots on store-engine table broadcasts (8 scalar
    # stores + 1 vload replace 1 valu vbroadcast); capped by the 48 vectors.
    k = min(48, 2 * C - loads) if store_bcast else 0
    loads += k
    stores = 78 + 8 * k

    flow_avail = C - setup_flow
    items = folds + idx_sel
    on_flow = min(items, flow_avail)
    valu_extra = items - on_flow

    vec = (HASH_CORE + FOLDIN + PARITY + idx_valu + setup_vec - k
           + ADDIMM_ALU_VEC + valu_extra)
    lane = 8 * vec
    flow = setup_flow + on_flow
    return dict(C=C, s=s, g=g, folds=folds, exits=exits, k=k,
                lane=lane, loads=loads, flow=flow, stores=stores,
                f_av=lane / 60.0, f_ld=loads / 2.0, f_fl=float(flow),
                ok=(lane <= 60 * C and loads <= 2 * C and flow <= C))


def row(r):
    return (f"  C={r['C']} s={r['s']:>3} g={r['g']:>3} folds={r['folds']:>4}"
            f" | alu+valu {r['lane']:>6} load {r['loads']:>5} flow {r['flow']:>4}"
            f" store {r['stores']:>5}"
            f" | floors {r['f_av']:7.1f} /{r['f_ld']:7.1f} /{r['f_fl']:7.1f}"
            f" | {'PASS' if r['ok'] else 'fail'}")


def main() -> None:
    print("== best serving design vs cycle target (T1+T2+T3, min setup) ==")
    best = None
    for C in range(900, 1010):
        cands = [evaluate(C, s) for s in range(190, 320)]
        cands = [c for c in cands if c and c["ok"]]
        if cands:
            b = min(cands, key=lambda c: c["lane"])
            if best is None:
                best = b
            if C <= 950 or C % 10 == 0:
                print(row(b))
    print("\nMINIMUM FEASIBLE CYCLE FLOOR:", best["C"] if best else "none")
    print(row(best))

    print("\n== sensitivity: which assumption is load-bearing at C=940 ==")
    variants = [
        ("baseline (T1+T2+T3, setup 70, add_imm->alu, store-bcast)", {}),
        ("shipped setup cost 83", dict(setup_vec=SETUP_VEC_SHIPPED)),
        ("add_imm stays on flow (setup_flow=22)", dict(setup_flow=22)),
        ("no store-engine broadcast", dict(store_bcast=False)),
        ("T1 off: interior nodes cost 2 valu (shipped spelling)", None),
    ]
    for name, kw in variants:
        if kw is None:
            # re-price interiors at 2 valu ops when they land on valu
            best2 = None
            for s in range(190, 320):
                r = evaluate(940, s)
                if r is None:
                    continue
                prof = profile(s)
                inter = sum(n * (2 ** (L - 1) - 1) for L, n in prof.items())
                leaves = r["folds"] - inter
                flow_avail = 940 - SETUP_FLOW_MIN
                x_i = min(inter, flow_avail)
                rem = flow_avail - x_i
                x_r = min(leaves + r["g"], rem)
                extra = 2 * (inter - x_i) + (leaves + r["g"] - x_r)
                lane = r["lane"] - 8 * (r["folds"] + r["g"] - min(r["folds"] + r["g"], flow_avail)) + 8 * extra
                ok = lane <= 60 * 940 and r["loads"] <= 1880
                if best2 is None or lane < best2[0]:
                    best2 = (lane, s, ok)
            print(f"  {name:<52} best alu+valu {best2[0]} "
                  f"({'PASS' if best2[2] else 'FAIL by %d' % (best2[0]-56400)})")
            continue
        cands = [evaluate(940, s, **kw) for s in range(190, 320)]
        cands = [c for c in cands if c]
        b = min(cands, key=lambda c: (not c["ok"], c["lane"]))
        print(f"  {name:<52} alu+valu {b['lane']} load {b['loads']} flow {b['flow']}"
              f"  {'PASS' if b['ok'] else 'FAIL'}")


if __name__ == "__main__":
    main()
