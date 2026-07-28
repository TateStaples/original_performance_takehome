"""H-063: free-slot oracle specialised to the SETUP phase / table construction.

`tools/free_slot_oracle.py` classes are op-shaped (bcast / vec / madd /
gather).  H-063 direction A needs a PHASE-shaped class: "everything the
builder emits before the group loop starts" (scheduler.tag is None), and
sub-classes of that -- the level-table bulk vloads, their ^C5 priming, the
scalar pair diffs, and the vbroadcast splats that replicate table words
into lanes.

Same mechanism as free_slot_oracle: reroute the chosen ops to the `debug`
engine (64 slots/cycle, and a bundle holding only debug slots costs no
cycle).  Dependency edges and write latency are preserved, only the slot
cost disappears.  Resulting programs are NOT correct -- cycles only.

Classes
  setup       every op with scheduler.tag is None
  tables      lv vloads + lv ^C5 prime + pair diffs + table vbroadcasts
  tbl_bcast   only the table vbroadcasts (the lane-replication step)
  tbl_alu     only the scalar pair diffs
  lv_load     only the 4 level-table bulk vloads
  setup_valu  every setup op on valu
  setup_alu   every setup op on alu
  finstore    the final result vstores (drain audit, direction C)

Usage (repo root):
  python3 tools/h063_oracle.py                # all classes at the 1006 config
  python3 tools/h063_oracle.py tables setup
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dev  # noqa: E402
import h061_common as C  # noqa: E402

CLASSES = ("setup", "tables", "tbl_bcast", "tbl_alu", "lv_load",
           "setup_valu", "setup_alu", "setup_load", "setup_flow",
           "setup_valload", "setup_const", "finstore",
           "win_valu", "win_alu", "win_any")

# window used by the win_* classes (see main(); `window=LO,HI` on argv)
WINDOW = [29, 65]


def measure_free(op_class: str, kw: dict[str, Any]) -> tuple[int, int]:
    state = {"freed": 0, "lv": None}
    orig_emit = dev.ListScheduler.emit
    orig_alloc = dev.KernelBuilder.alloc_scratch

    def alloc(self, name=None, length=1):
        addr = orig_alloc(self, name, length)
        if name == "lv":
            state["lv"] = (addr, addr + length)
        return addr

    def in_lv(addrs) -> bool:
        lv = state["lv"]
        if lv is None:
            return False
        return any(lv[0] <= a < lv[1] for a in addrs)

    def free_emit(self, engine, slot, reads=(), writes=(), mem_read=False,
                  mem_write=False, min_cycle=0, ignore_mem_read_hazard=False,
                  ignore_mem_write_hazard=False):
        setup = self.tag is None
        op = slot[0]
        hit = False
        if op_class == "setup":
            hit = setup
        elif op_class == "setup_valu":
            hit = setup and engine == "valu"
        elif op_class == "setup_alu":
            hit = setup and engine == "alu"
        elif op_class == "lv_load":
            hit = setup and op == "vload" and in_lv(writes)
        elif op_class == "tbl_bcast":
            hit = setup and op == "vbroadcast"
        elif op_class == "tbl_alu":
            hit = setup and engine == "alu" and op == "-" and in_lv(reads)
        elif op_class == "tables":
            hit = setup and (
                op == "vbroadcast"
                or (op == "vload" and in_lv(writes))
                or (engine == "valu" and op == "^" and in_lv(writes))
                or (engine == "alu" and op == "-" and in_lv(reads))
            )
        elif op_class.startswith("win_"):
            # PHASE-LOCAL relaxation: free the ops the greedy would place
            # inside WINDOW, on the named engine.  `self.ready`/`find_free`
            # reproduce the placement decision exactly, so this prices "what
            # is the compute saturating this window worth?" without moving
            # anything else.
            eng = op_class[4:]
            if engine == eng or eng == "any":
                c = self.find_free(engine, self.ready(
                    reads, writes, mem_read, mem_write, min_cycle,
                    ignore_mem_read_hazard, ignore_mem_write_hazard))
                hit = WINDOW[0] <= c < WINDOW[1]
        elif op_class == "setup_load":
            hit = setup and engine == "load"
        elif op_class == "setup_flow":
            hit = setup and engine == "flow"
        elif op_class == "setup_valload":
            hit = setup and op == "vload" and not in_lv(writes)
        elif op_class == "setup_const":
            hit = setup and op == "const"
        elif op_class == "finstore":
            hit = op == "vstore" and not setup
        if hit:
            state["freed"] += 1
            engine = "debug"
        return orig_emit(self, engine, slot, reads, writes, mem_read, mem_write,
                         min_cycle, ignore_mem_read_hazard,
                         ignore_mem_write_hazard)

    dev.ListScheduler.emit = free_emit          # type: ignore[method-assign]
    dev.KernelBuilder.alloc_scratch = alloc     # type: ignore[method-assign]
    try:
        kb = dev.KernelBuilder()
        kb.build_kernel_scheduled(*C.SHAPE, **kw)
    finally:
        dev.ListScheduler.emit = orig_emit          # type: ignore[method-assign]
        dev.KernelBuilder.alloc_scratch = orig_alloc  # type: ignore[method-assign]
    cycles = sum(1 for b in kb.instrs if any(e != "debug" for e in b))
    return cycles, state["freed"]


def main() -> None:
    args = sys.argv[1:]
    if args and args[0].startswith("window="):
        lo, hi = args[0].split("=", 1)[1].split(",")
        WINDOW[0], WINDOW[1] = int(lo), int(hi)
        args = args[1:]
    wanted = args or list(CLASSES)
    print(json.dumps({"window": list(WINDOW)}))
    kw = C.kwargs()
    base, _ = measure_free("none", kw)
    print(json.dumps({"class": "baseline", "cycles": base}))
    for cl in wanted:
        cyc, freed = measure_free(cl, kw)
        print(json.dumps({"class": cl, "freed": freed, "cycles": cyc,
                          "delta": cyc - base}), flush=True)


if __name__ == "__main__":
    main()
