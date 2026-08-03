"""P7-C: audit the DECLARED reads/writes/mem flags of every scheduled op
against the true read/write sets implied by problem.py's handlers.

Over-declaration  => conservatism (spurious RAW/WAR/WAW edges).
Under-declaration => unsoundness (the schedule is correct by luck).

Uses ListScheduler.trace (dev.py:119-125), which records every put() as
(cycle, engine, tag, slot, reads, writes, mem_read, mem_write).
"""
from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dev  # noqa: E402
import h060_common as C  # noqa: E402
from problem import VLEN  # noqa: E402


def V(a):
    return set(range(a, a + VLEN))


def truth(engine, slot):
    """Return (reads, writes, mem_read, mem_write) per problem.py."""
    op = slot[0]
    if engine == "alu":
        _, dest, a1, a2 = slot
        return {a1, a2}, {dest}, False, False
    if engine == "valu":
        if op == "vbroadcast":
            _, dest, src = slot
            return {src}, V(dest), False, False
        if op == "multiply_add":
            _, dest, a, b, c = slot
            return V(a) | V(b) | V(c), V(dest), False, False
        _, dest, a1, a2 = slot
        return V(a1) | V(a2), V(dest), False, False
    if engine == "load":
        if op == "load":
            _, dest, addr = slot
            return {addr}, {dest}, True, False
        if op == "load_offset":
            _, dest, addr, off = slot
            return {addr + off}, {dest + off}, True, False
        if op == "vload":
            _, dest, addr = slot
            return {addr}, V(dest), True, False
        if op == "const":
            _, dest, _val = slot
            return set(), {dest}, False, False
    if engine == "store":
        if op == "store":
            _, addr, src = slot
            return {addr, src}, set(), False, True
        if op == "vstore":
            _, addr, src = slot
            return {addr} | V(src), set(), False, True
    if engine == "flow":
        if op == "select":
            _, dest, cond, a, b = slot
            return {cond, a, b}, {dest}, False, False
        if op == "add_imm":
            _, dest, a, _imm = slot
            return {a}, {dest}, False, False
        if op == "vselect":
            _, dest, cond, a, b = slot
            return V(cond) | V(a) | V(b), V(dest), False, False
        if op in ("halt", "pause"):
            return set(), set(), False, False
        if op == "coreid":
            return set(), {slot[1]}, False, False
        if op == "trace_write":
            return {slot[1]}, set(), False, False
        if op in ("cond_jump", "cond_jump_rel"):
            return {slot[1]}, set(), False, False
        if op == "jump":
            return set(), set(), False, False
        if op == "jump_indirect":
            return {slot[1]}, set(), False, False
    raise NotImplementedError((engine, slot))


def main() -> None:
    # dev.py:1729 does `scheduler.trace = getattr(self, "sched_trace", None)`,
    # so the trace is turned on from the KernelBuilder side.
    from run_variant import SHAPE
    cfg = C.frontier()
    kb = dev.KernelBuilder()
    kb.sched_trace = []
    kb.build_kernel_scheduled(**dict(SHAPE, **cfg))
    prog = kb.instrs
    traces = [type("T", (), {"trace": kb.sched_trace})()]

    over_r: Counter = Counter()
    under_r: Counter = Counter()
    over_w: Counter = Counter()
    under_w: Counter = Counter()
    memflag: Counter = Counter()
    total: Counter = Counter()
    examples: dict = {}
    n = 0
    for sch in traces:
        for (cycle, engine, tag, slot, reads, writes, mr, mw) in (sch.trace or []):
            n += 1
            tr, tw, tmr, tmw = truth(engine, slot)
            dr, dw = set(reads), set(writes)
            key = f"{engine}:{slot[0]}"
            total[key] += 1
            if dr - tr:
                over_r[key] += len(dr - tr)
                examples.setdefault("over_r:" + key, (slot, sorted(dr - tr)[:6]))
            if tr - dr:
                under_r[key] += len(tr - dr)
                examples.setdefault("under_r:" + key, (slot, sorted(tr - dr)[:6]))
            if dw - tw:
                over_w[key] += len(dw - tw)
                examples.setdefault("over_w:" + key, (slot, sorted(dw - tw)[:6]))
            if tw - dw:
                under_w[key] += len(tw - dw)
                examples.setdefault("under_w:" + key, (slot, sorted(tw - dw)[:6]))
            if bool(mr) != tmr:
                memflag[f"{key}:mem_read decl={bool(mr)} true={tmr}"] += 1
            if bool(mw) != tmw:
                memflag[f"{key}:mem_write decl={bool(mw)} true={tmw}"] += 1

    print(f"schedulers={len(traces)} traced_puts={n} bundles={len(prog)}")
    print("op census:", dict(total))
    for name, c in (("OVER-declared reads", over_r), ("UNDER-declared reads", under_r),
                    ("OVER-declared writes", over_w), ("UNDER-declared writes", under_w),
                    ("mem-flag mismatches", memflag)):
        print(f"-- {name}: {dict(c) if c else 'NONE'}")
    for k, v in sorted(examples.items()):
        print("   eg", k, v)


if __name__ == "__main__":
    main()
