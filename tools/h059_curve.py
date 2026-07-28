"""H-059: the scratch-versus-parallelism trade curve.

Group liveness is a property of the EMISSION PLAN alone: group g's state
vectors are live from its round-0 emission to its round-15 emission, so a
diagonal whose lags satisfy

    lag(g + W) >= lag(g) + rounds

keeps at most W groups live at any diagonal step, and (crucially) makes
group g+W's registers reusable from group g's.  This module builds such
"rolling window" plans and measures them, so the cycle leg of the trade can
be priced BEFORE any allocator change (tools/h059_alias.py does the words
leg).

Usage:
  python3 tools/h059_curve.py curve            # W in {32,24,16,12,8,4}
  python3 tools/h059_curve.py base --w 16      # base-diagonal sweep at one W
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from typing import Any, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

from run_variant import measure  # noqa: E402

ROUNDS, N_GROUPS = 16, 32

# H-057 / 1006 mainline mix (everything except emission_plan).
MIX: dict[str, Any] = json.load(
    open(os.path.join(REPO_ROOT, "tools", "h057_best_plan_1006.json"))
)["params"]["mix"]


def _tuplify(v: Any) -> Any:
    if isinstance(v, list):
        return tuple(_tuplify(x) for x in v)
    return v


MIX = {k: _tuplify(v) for k, v in MIX.items()}

# Ring plans are ORDER-SPECIFIC (F-25 standing rule): the borrow windows are
# timed against the 1006 emission order, so carrying them onto any other
# order is unsound (measurably: out-of-range gathers).  Every H-059
# organization probe therefore runs RING-FREE; rings are re-mined from empty
# only on the point that is taken forward.
NORING: dict[str, Any] = {k: v for k, v in MIX.items()
                          if k not in ("parity_ring", "parity_ring_plan")}

# F-24's non-uniform diagonal (8 blocks of 4) -- the 1006 organization.
F24_LAGS = (0, 3, 6, 6, 10, 10, 13, 14)


def base_lags(w: int, spec: str) -> list[int]:
    """Per-group lag inside ONE window of w groups."""
    if spec == "f24":
        # compress F-24's 8-block diagonal onto w groups
        blocks = 8
        per = max(1, w // blocks)
        out = []
        for g in range(w):
            out.append(F24_LAGS[min(blocks - 1, g // per)])
        return out
    kind, _, rest = spec.partition(":")
    if kind == "even":
        nb, stag = (int(x) for x in rest.split(","))
        if w % nb:
            return []
        per = w // nb
        return [stag * (g // per) for g in range(w)]
    if kind == "flat":
        return [0] * w
    raise ValueError(spec)


def rolling_plan(w: int, spec: str = "f24", interleave: str = "zip",
                 rounds: int = ROUNDS, n_groups: int = N_GROUPS
                 ) -> tuple[Any, ...]:
    """Emission plan holding <= w groups live, windows offset by `rounds`."""
    b = base_lags(w, spec)
    if not b:
        return ()
    lag = {}
    for g in range(n_groups):
        lag[g] = (g // w) * rounds + b[g % w]
    n_steps = max(lag.values()) + rounds
    plan: list[Any] = []
    for step in range(n_steps):
        live = [g for g in range(n_groups) if 0 <= step - lag[g] < rounds]
        if not live:
            continue
        if interleave == "zip":
            # interleave across distinct lag values (the "wave" analogue)
            bylag: dict[int, list[int]] = {}
            for g in live:
                bylag.setdefault(lag[g], []).append(g)
            cols = [bylag[k] for k in sorted(bylag)]
            live = [g for tup in itertools.zip_longest(*cols) for g in tup
                    if g is not None]
        plan.extend((step - lag[g], g) for g in live)
    return tuple(plan)


def live_profile(plan: Sequence[Any], n_groups: int = N_GROUPS) -> tuple[int, list[int]]:
    """(peak simultaneous live groups, per-position live count)."""
    first: dict[int, int] = {}
    last: dict[int, int] = {}
    for i, e in enumerate(plan):
        members = e[1] if e and e[0] == "rr" else (e,)
        for _, g in members:
            first.setdefault(g, i)
            last[g] = i
    prof = []
    for i in range(len(plan)):
        prof.append(sum(1 for g in range(n_groups)
                        if first.get(g, 10**9) <= i <= last.get(g, -1)))
    return max(prof), prof


def reuse_ok(plan: Sequence[Any], w: int, n_groups: int = N_GROUPS) -> bool:
    """True iff group g+w's first emission strictly follows group g's last."""
    first: dict[int, int] = {}
    last: dict[int, int] = {}
    for i, e in enumerate(plan):
        members = e[1] if e and e[0] == "rr" else (e,)
        for _, g in members:
            first.setdefault(g, i)
            last[g] = i
    return all(first[g + w] > last[g] for g in range(n_groups - w))


def run(w: int, spec: str, interleave: str = "zip",
        extra: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = rolling_plan(w, spec, interleave)
    if not plan:
        return {"w": w, "spec": spec, "skip": True}
    peak, _ = live_profile(plan)
    ov = dict(NORING, emission_plan=plan)
    if extra:
        ov.update(extra)
    try:
        cyc, ok = measure(ov, seed=1)
    except Exception as exc:  # organization can trip config asserts
        return {"w": w, "spec": spec, "interleave": interleave,
                "error": f"{type(exc).__name__}: {exc}"[:160]}
    return {"w": w, "spec": spec, "interleave": interleave, "cycles": cyc,
            "correct": bool(ok), "peak_live": peak,
            "reuse_ok": reuse_ok(plan, w), "steps": len(plan)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["curve", "base"])
    ap.add_argument("--w", type=int, default=16)
    args = ap.parse_args()
    if args.mode == "curve":
        for w in (32, 24, 16, 12, 8, 4):
            for spec in ("f24", "even:4,3", "even:2,3", "flat"):
                for iv in ("zip", "block"):
                    r = run(w, spec, iv)
                    print(json.dumps(r), flush=True)
    else:
        w = args.w
        specs = ["f24", "flat"]
        for nb in (2, 3, 4, 6, 8):
            for stag in (1, 2, 3, 4, 5, 6):
                specs.append(f"even:{nb},{stag}")
        for spec in specs:
            for iv in ("zip", "block"):
                print(json.dumps(run(w, spec, iv)), flush=True)


# --------------------------------------------------------------------------
# arbitrary per-group base diagonal at one window size (search support)
# --------------------------------------------------------------------------
def rolling_plan_lags(w: int, b: Sequence[int], interleave: str = "zip",
                      rounds: int = ROUNDS, n_groups: int = N_GROUPS
                      ) -> tuple[Any, ...]:
    lag = {g: (g // w) * rounds + b[g % w] for g in range(n_groups)}
    n_steps = max(lag.values()) + rounds
    plan: list[Any] = []
    for step in range(n_steps):
        live = [g for g in range(n_groups) if 0 <= step - lag[g] < rounds]
        if not live:
            continue
        if interleave == "zip":
            bylag: dict[int, list[int]] = {}
            for g in live:
                bylag.setdefault(lag[g], []).append(g)
            cols = [bylag[k] for k in sorted(bylag)]
            live = [g for tup in itertools.zip_longest(*cols) for g in tup
                    if g is not None]
        plan.extend((step - lag[g], g) for g in live)
    return tuple(plan)


def eval_lags(w: int, b: Sequence[int], interleave: str = "zip",
              extra: dict[str, Any] | None = None) -> tuple[int, bool]:
    plan = rolling_plan_lags(w, b, interleave)
    ov = dict(NORING, emission_plan=plan)
    if extra:
        ov.update(extra)
    try:
        return measure(ov, seed=1)
    except Exception:
        return (10 ** 6, False)


if __name__ == "__main__":
    main()
