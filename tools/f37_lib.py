"""F-37: multi-move (k-entry simultaneous displacement) helpers.

Single-entry displacements at the 1006 plan are provably empty (G-30 /
f18_exhaust1: 25,550 moves, zero below 1006).  Any remaining order win must
be a strictly PAIRED escape, and G-30's round-window productivity map says
it must live in rounds 12-15.

Move representation
-------------------
A move is `(src, anchor)` in BASE-index space:

    src     base index of the entry being displaced
    anchor  base index of the entry it must land immediately BEFORE,
            or `END` (= n) for "append at the very end"

This is a re-coordinatisation of f18_exhaust1's `(i, j)` reinsertion that
COMPOSES: k moves with pairwise-distinct `src` and with no `anchor` inside
the moved set are applied by deleting all k entries at once and re-inserting
each before its (still present) anchor.  For k = 1 it reproduces
`q.insert(j, q.pop(i))` exactly.

Nothing here modifies a shared tool; `emission_order_search` and
`audit_ring_windows` (via `f34_lib`) are imported and called.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Iterable, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import emission_order_search as eos  # noqa: E402
import f34_lib as L  # noqa: E402

ROUNDS, N_GROUPS = eos.ROUNDS, eos.N_GROUPS
END = -1  # sentinel anchor: append at the end


def load_point(path: str) -> tuple[tuple, dict[str, Any]]:
    """(order, mix) from an artifact with a `params.mix` block."""
    return L.load_json_point(path)


def valid(p: Sequence[tuple[int, int]]) -> bool:
    nr = [0] * N_GROUPS
    for r, g in p:
        if nr[g] != r:
            return False
        nr[g] += 1
    return all(v == ROUNDS for v in nr)


def positions(p: Sequence[tuple[int, int]]) -> list[list[int]]:
    d: list[list[int]] = [[] for _ in range(N_GROUPS)]
    for i, (_, g) in enumerate(p):
        d[g].append(i)
    return d


def enumerate_moves(plan: Sequence[tuple[int, int]],
                    rounds: Iterable[int] | None = None
                    ) -> list[tuple[int, int]]:
    """Every valid single displacement `(src, anchor)`.

    `rounds` restricts the SOURCE entry's round (F-37 uses {12..15}); the
    destination interval is the entry's maximal feasible interval, bounded
    only by its own group's round-neighbours, i.e. unbounded radius --
    identical coverage to f18_exhaust1.enumerate_moves.
    """
    n = len(plan)
    pos = positions(plan)
    rs = None if rounds is None else set(rounds)
    out: list[tuple[int, int]] = []
    for i, (r, g) in enumerate(plan):
        if rs is not None and r not in rs:
            continue
        gp = pos[g]
        lo = gp[r - 1] + 1 if r > 0 else 0
        hi = gp[r + 1] - 1 if r + 1 < ROUNDS else n - 1
        for t in range(lo, hi + 1):
            if t == i:
                continue
            j = t - 1 if t > i else t          # f18 (i, j) reinsertion index
            if j == i:
                continue
            # anchor = element of (base minus i) sitting at index j
            anchor = END if j >= n - 1 else (j if j < i else j + 1)
            out.append((i, anchor))
    return out


def apply_moves(plan: Sequence[tuple[int, int]],
                moves: Sequence[tuple[int, int]],
                resolve: bool = False) -> tuple | None:
    """Apply k simultaneous displacements; None if the set is ill-formed.

    An anchor that is itself displaced by another member of the set has no
    surviving landing site.  Default is to reject the set (`None`);
    `resolve=True` instead slides the anchor forward to the next entry that
    survives, i.e. "land where that entry used to be" -- which is what the
    composite of the two intended displacements actually means.
    """
    n = len(plan)
    srcs = [s for s, _ in moves]
    if len(set(srcs)) != len(srcs):
        return None
    moved = set(srcs)
    ins: dict[int, list[int]] = {}
    for s, a in moves:
        if a in moved:                 # anchor swept away by another move
            if not resolve:
                return None
            b = a
            while b != END and b in moved:
                b += 1
                if b >= n:
                    b = END
            a = b
        ins.setdefault(a, []).append(s)
    for v in ins.values():
        v.sort()
    out: list[tuple[int, int]] = []
    for idx, e in enumerate(plan):
        if idx in moved:
            continue
        for s in ins.get(idx, ()):
            out.append(plan[s])
        out.append(e)
    for s in ins.get(END, ()):
        out.append(plan[s])
    if len(out) != len(plan):
        return None
    return tuple(out)


def span(n: int, mv: tuple[int, int]) -> tuple[int, int]:
    """Base-index interval a single move perturbs."""
    s, a = mv
    p = n if a == END else a
    return (s, p - 1) if s < p else (p, s)


def overlap(n: int, m1: tuple[int, int], m2: tuple[int, int]) -> bool:
    a0, a1 = span(n, m1)
    b0, b1 = span(n, m2)
    return a0 <= b1 and b0 <= a1


def moved_groups(plan: Sequence[tuple[int, int]],
                 mv: tuple[int, int]) -> int:
    return plan[mv[0]][1]
