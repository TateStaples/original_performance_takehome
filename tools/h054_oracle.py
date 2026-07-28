"""H-054 x H-053: free-slot oracle specialised to the SELECT class.

G-26's oracle (tools/free_slot_oracle.py) has classes for vec/madd/bcast/
gather but not for the tournament/fold SELECTS, which are the whole subject
of H-054. This routes exactly those ops to the 64-wide `debug` engine
(dependency edges and the 1-cycle write latency preserved, slot cost zero),
so it upper-bounds ANY migration/respelling of the select class -- including
mechanisms that do not exist, like an infinitely wide flow engine.

Classes:
  sel        every multi-encoding race site that has a pure-flow spelling
             (the 395 "flow-capable" sites) -- free
  sel_lost   only the sites greedy routed OFF flow (the 159 the hypothesis
             wants to migrate) -- free
  vselect    every emitted vselect op, however spelled -- free
  race       every multi-encoding race site (flow-capable or not) -- free

Programs are NOT correct; cycles only.

Usage: python3 tools/h054_oracle.py [--class sel] [--bias N]
"""
from __future__ import annotations

import argparse
import json
import sys

import dev
import h054_common as C
from dev import KernelBuilder, ListScheduler

_orig_emit_any = ListScheduler.emit_any
_orig_emit = ListScheduler.emit


def measure_free(op_class: str, **extra) -> tuple[int, int]:
    state = {"freed": 0}
    # pass 1 (only needed for sel_lost): which sites does greedy lose?
    lost: set[int] = set()
    if op_class == "sel_lost":
        import h054_diag as D
        kwargs = C.frontier_kwargs(**extra)
        kwargs.pop("flow_spelling_plan", None)
        D.build(kwargs, {}, logging=True)
        lost = {r["site"] for r in D.RACE_LOG
                if r["site"] is not None and r["site"] >= 0
                and r["flow_idx"] is not None and r["chosen"] != r["flow_idx"]}

    def free_emit_any(self, encodings):
        encodings = list(encodings)
        if len(encodings) > 1:
            is_flow_site = any(all(e == "flow" for e, *_ in enc)
                               for enc in encodings)
            key = (self.flow_site_idx if is_flow_site
                   else -(self.aux_site_idx + 1))
            hit = (op_class == "race"
                   or (op_class == "sel" and is_flow_site)
                   or (op_class == "sel_lost" and is_flow_site and key in lost))
            if hit:
                # consume the site counter exactly as the real path would
                if is_flow_site:
                    self.flow_site_idx += 1
                else:
                    self.aux_site_idx += 1
                enc = encodings[0]
                state["freed"] += 1
                return _orig_emit_any(self, [[("debug", slot, reads, writes)
                                              for _e, slot, reads, writes in enc]])
        return _orig_emit_any(self, encodings)

    def free_emit(self, engine, slot, reads=(), writes=(), mem_read=False,
                  mem_write=False, min_cycle=0, ignore_mem_read_hazard=False,
                  ignore_mem_write_hazard=False):
        if op_class == "vselect" and slot and slot[0] in ("vselect", "select"):
            engine = "debug"
            state["freed"] += 1
        return _orig_emit(self, engine, slot, reads, writes, mem_read,
                          mem_write, min_cycle, ignore_mem_read_hazard,
                          ignore_mem_write_hazard)

    if op_class == "vselect":
        ListScheduler.emit = free_emit          # type: ignore[method-assign]
    elif op_class != "none":
        ListScheduler.emit_any = free_emit_any  # type: ignore[method-assign]
    # `vselect` must also catch the ones emit_any places
    if op_class == "vselect":
        def sel_emit_any(self, encodings):
            encodings = list(encodings)
            if len(encodings) > 1:
                if any(all(e == "flow" for e, *_ in enc) for enc in encodings):
                    self.flow_site_idx += 1
                else:
                    self.aux_site_idx += 1
                enc = next((e for e in encodings
                            if all(x == "flow" for x, *_ in e)), encodings[0])
                state["freed"] += 1
                return _orig_emit_any(self, [[("debug", slot, reads, writes)
                                              for _e, slot, reads, writes in enc]])
            return _orig_emit_any(self, encodings)
        ListScheduler.emit_any = sel_emit_any   # type: ignore[method-assign]
    try:
        kb = KernelBuilder()
        kb.build_kernel_scheduled(C.SHAPE["batch_size"], C.SHAPE["rounds"],
                                  C.SHAPE["forest_height"],
                                  **C.frontier_kwargs(**extra))
    finally:
        ListScheduler.emit_any = _orig_emit_any  # type: ignore[method-assign]
        ListScheduler.emit = _orig_emit          # type: ignore[method-assign]
    cycles = sum(1 for b in kb.instrs if any(e != "debug" for e in b))
    return cycles, state["freed"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bias", type=int, default=0)
    args = ap.parse_args()
    extra = {"flow_race_bias": args.bias} if args.bias else {}
    base, _ = measure_free("none", **extra)
    print(f"baseline (bias={args.bias}): {base}")
    for cls in ("sel", "sel_lost", "vselect", "race"):
        c, n = measure_free(cls, **extra)
        print(json.dumps({"class": cls, "freed": n, "cycles": c,
                          "delta": c - base}), flush=True)


if __name__ == "__main__":
    main()
