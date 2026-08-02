#!/usr/bin/env python3
"""P6-D: EXTENDED transfer test for p5i sec.9's differential-count theorem.

Two changes vs tools/p5i3_transfer.py:

 (E1) the K2 madd (the single madd between c and shr B's input) may be EVEN.
      p5i3_transfer's abstract interpreter mapped even-madd(('E',{H,U}|{U}))
      to ('C',0) -- lossy, because in fact  e* - e = sg*K2*2^u  EXACTLY (the
      K2*2^(w-1) term vanishes mod 2^w for even K2), which is the SAME 'S'
      invariant the odd case has, minus a term that is invisible below bit w-1.
      So the state is ('S', {}), and shr B still yields ('D',0).
      The COUNT differs: see p6d_algebra.py THEOREM P6D-1,
          M_even = 2^(w-t) * q            (vs  M_odd = 2^(w-t)(q-1)+2^(w+1-s2) n_1)
      and both satisfy  N == 0 mod 2^(w+1-s2).

 (E2) T6b (shr-B's input slot must be a DAG cut, forcing K2 odd) is therefore
      DROPPED.  Its only job was to pin K2's parity; both parities are now
      covered.  T6a (x -> c bijective) is NOT droppable -- the count is a count
      over c -- and is re-checked PER PARITY ASSIGNMENT (an even madd inside
      c's cone destroys bijectivity).

Verdict model per (shape, s1, s2):  the shape+shifts can realise myhash's
bit-0 differential count only if SOME parity assignment of the madds admits it.
 * a parity assignment whose abstract output state is CONSTANT gives
   N in {0, 2^w} != N_myhash -> refuted;
 * an ODD-K2 assignment is filtered by p5i3_arith (sec.9 + sec.12);
 * an EVEN-K2 assignment is alive iff t >= 15 (P6D-3).
"""
import json
import sys
from collections import defaultdict

sys.path.insert(0, "tools")
import p5i3_transfer as T

ZERO = ("E", frozenset())


def _run2(ops, a_idx, b_idx, even=frozenset()):
    """like p5i3_transfer._run but with the EVEN-K2 'S' rule (E1).
    returns (state, c_slot, k2_idx, dup)."""
    st = {0: ("E", frozenset(["H"]))}
    c_slot = None
    k2_idx = None
    dup = False
    for k, op in enumerate(ops):
        out = k + 1
        kind = op[0]
        if kind in ("madd", "xorc", "shr"):
            s = st[op[1]]
            if s == ZERO:
                st[out] = ZERO
                continue
        if kind == "madd":
            ev = k in even
            if s[0] == "E" and s[1] == frozenset(["H"]):
                # K*2^(w-1) = 2^(w-1) (K odd) or 0 (K even)
                st[out] = ZERO if ev else ("E", frozenset(["H"]))
            elif s[0] == "E" and s[1] in (frozenset(["H", "U"]),
                                          frozenset(["U"])):
                # e* - e = [2^(w-1) +] sg*K*2^u exactly, EITHER parity (E1)
                if c_slot is not None:
                    dup = True
                c_slot = op[1]
                k2_idx = k
                st[out] = ("S", frozenset())
            elif s[0] == "E":
                st[out] = ("C", 0)
            elif s[0] in ("C", "D"):
                st[out] = ("C", 0) if ev else (s[0], s[1])
            else:
                st[out] = "TOP"
        elif kind == "xorc":
            st[out] = s
        elif kind == "shr":
            if k == a_idx:
                if s[0] == "E" and s[1] == frozenset(["H"]):
                    st[out] = ("E", frozenset(["U"]))
                elif s[0] in ("E", "S"):
                    st[out] = ("C", 0)
                else:
                    st[out] = "TOP"
            elif k == b_idx:
                if s[0] == "S":
                    st[out] = ("D", 0)
                elif s[0] == "E":
                    st[out] = ("C", 0)
                else:
                    st[out] = "TOP"
            else:
                st[out] = "TOP"
        elif kind == "xor2":
            sa, sb = st[op[1]], st[op[2]]
            if sa == ZERO:
                st[out] = sb
            elif sb == ZERO:
                st[out] = sa
            elif sa[0] == "E" and sb[0] == "E":
                st[out] = ("E", sa[1] ^ sb[1])
            elif sa[0] == "S" and sb[0] == "E":
                st[out] = ("S", sa[1] ^ sb[1])
            elif sb[0] == "S" and sa[0] == "E":
                st[out] = ("S", sb[1] ^ sa[1])
            else:
                da, db = T.d0(sa), T.d0(sb)
                if da is None or db is None:
                    st[out] = "TOP"
                else:
                    st[out] = (("D", da[0] ^ db[0]) if (da[1] ^ db[1])
                               else ("C", da[0] ^ db[0]))
        else:
            st[out] = "TOP"
    return st[len(ops)], c_slot, k2_idx, dup


def cone_madds(ops, slot, acc=None):
    """madd op indices inside the cone feeding `slot`."""
    if acc is None:
        acc = set()
    if slot == 0:
        return acc
    op = ops[slot - 1]
    if op[0] == "madd":
        acc.add(slot - 1)
    for a in op[1:]:
        cone_madds(ops, a, acc)
    return acc


def extended_transfer(ops):
    """returns (a_idx,b_idx,c_slot,k2_idx,modes) or None.
    modes: set of 'odd'/'even' -- the K2 parities the shape can realise."""
    shrs = [k for k, o in enumerate(ops) if o[0] == "shr"]
    if len(shrs) != 2:
        return None
    madds = [k for k, o in enumerate(ops) if o[0] == "madd"]
    for a_idx, b_idx in ((shrs[0], shrs[1]), (shrs[1], shrs[0])):
        st, c, k2, dup = _run2(ops, a_idx, b_idx)
        if dup or c is None or not (isinstance(st, tuple) and st[0] == "D"):
            continue
        if not T.bijective_cone(ops, c):
            continue                      # T6a, all-odd baseline
        ccone = cone_madds(ops, c)
        modes = set()
        bad = False
        for m in range(1 << len(madds)):
            ev = frozenset(o for i, o in enumerate(madds) if (m >> i) & 1)
            st2, c2, k22, dup2 = _run2(ops, a_idx, b_idx, ev)
            if dup2:
                bad = True
                break
            if isinstance(st2, tuple) and st2[0] == "D":
                # the count model applies -> needs x->c bijective for THIS ev
                if c2 != c or (ccone & ev):
                    bad = True
                    break
                modes.add("even" if k22 in ev else "odd")
                continue
            d = T.d0(st2)
            if d is None or d[1] != 0:     # not a constant differential
                bad = True
                break
        if bad:
            continue
        return (a_idx, b_idx, c, k2, modes)
    return None


# ------------------------------------------------------------- verdicts ----
def odd_alive_grid(jmax=12):
    """ALIVE(s1,s2) for the ODD-K2 model over 1<=s1,s2<=30, t>=1 (sec.9+12)."""
    import p5i3_arith as AR
    alive = set()
    for s1 in range(1, 31):
        for s2 in range(1, 31):
            if s1 + s2 - 31 < 1:
                continue
            if 33 - s2 > 18:               # sec.9 divisibility mass kill
                continue
            a, _ = AR.decide_pair(s1, s2, jmax=jmax)
            if a:
                alive.add((s1, s2))
    return alive


def even_alive_grid():
    """ALIVE(s1,s2) for the EVEN-K2 model (P6D-3: t >= 15)."""
    return {(s1, s2) for s1 in range(1, 31) for s2 in range(1, 31)
            if s1 + s2 - 31 >= 15}


def main():
    q = json.load(open("tools/p5k_queue.json"))
    ent = q["entries"]
    oddA = odd_alive_grid()
    evenA = even_alive_grid()
    print("ODD-K2 alive over the 435-pair t>=1 grid : %d" % len(oddA))
    print("EVEN-K2 alive (t>=15)                    : %d" % len(evenA))
    print("union                                    : %d" % len(oddA | evenA))
    print("even-only (NEW open, cost of dropping T6b): %d" % len(evenA - oddA))

    stats = defaultdict(int)
    rows = []
    for e in ent:
        ops = [tuple(o) for o in e["ops"]]
        old = T.shape_transfers(ops)
        new = extended_transfer(ops)
        key = ("OLD-Y" if old else "OLD-N") + "/" + ("NEW-Y" if new else "NEW-N")
        stats[key] += 1
        if new:
            rows.append((e, new))
    for k in sorted(stats):
        print("  %-14s %d" % (k, stats[k]))
    modes = defaultdict(int)
    for e, r in rows:
        modes["+".join(sorted(r[4]))] += 1
    print("  modes:", dict(modes))
    json.dump([{"rank": e["rank"], "ops": e["ops"], "modes": sorted(r[4]),
                "a": r[0], "b": r[1], "c": r[2], "k2": r[3]}
               for e, r in rows],
              open("/tmp/p6d_transfer.json", "w"))
    print("wrote /tmp/p6d_transfer.json  (%d shapes)" % len(rows))


if __name__ == "__main__":
    main()
