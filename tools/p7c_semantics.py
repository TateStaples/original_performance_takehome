"""P7-C: EMPIRICAL confirmation of the machine's true bundle semantics.

Runs tiny hand-written programs on the real problem.py Machine to verify
each dependency class's true minimum separation, instead of only reading
the source.
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from problem import Machine, DebugInfo, N_CORES  # noqa: E402

DI = DebugInfo(scratch_map={})


def run(prog, mem=None, scratch_init=None):
    m = Machine(mem or [0] * 64, prog, DI, n_cores=N_CORES)
    m.enable_pause = False
    m.enable_debug = False
    if scratch_init:
        for a, v in scratch_init.items():
            m.cores[0].scratch[a] = v
    m.run()
    return m


def main() -> None:
    # 1. RAW scratch needs 1 cycle: same-cycle read sees the OLD value.
    m = run([{"load": [("const", 0, 7)], "alu": [("+", 1, 0, 0)]}],
            scratch_init={0: 3})
    print(f"RAW same-cycle: s1={m.cores[0].scratch[1]} "
          f"(3+3=6 => reads OLD; 7+7=14 => reads NEW)")

    # 2. WAR scratch is 0: writer in the same cycle does not clobber the read.
    m = run([{"alu": [("+", 1, 0, 0), ("+", 0, 2, 2)]}],
            scratch_init={0: 5, 2: 100})
    print(f"WAR same-cycle: s1={m.cores[0].scratch[1]} (10 => reader saw old 5)"
          f"  s0={m.cores[0].scratch[0]} (200)")

    # 3. WAW scratch same cycle, SAME engine: later slot wins?
    m = run([{"alu": [("+", 5, 1, 1), ("+", 5, 2, 2)]}],
            scratch_init={1: 10, 2: 20})
    print(f"WAW same engine: s5={m.cores[0].scratch[5]} "
          f"(40 => LATER slot wins, 20 => earlier)")

    # 4. WAW same cycle, DIFFERENT engines -- which engine wins?
    #    Build the bundle with 'alu' inserted first, then 'flow'.
    b = {}
    b["alu"] = [("+", 5, 1, 1)]     # -> 20
    b["flow"] = [("add_imm", 5, 2, 0)]   # -> 20? use distinct values
    m = run([{"alu": [("+", 5, 1, 1)], "flow": [("add_imm", 5, 2, 7)]}],
            scratch_init={1: 10, 2: 100})
    print(f"WAW alu-then-flow(dict order): s5={m.cores[0].scratch[5]} "
          f"(20 => alu won, 107 => flow won)")
    b2 = {}
    b2["flow"] = [("add_imm", 5, 2, 7)]
    b2["alu"] = [("+", 5, 1, 1)]
    m = run([b2], scratch_init={1: 10, 2: 100})
    print(f"WAW flow-then-alu(dict order): s5={m.cores[0].scratch[5]} "
          f"(20 => alu won, 107 => flow won)")

    # 5. mem RAW: store then same-cycle load sees OLD memory.
    mem = [0] * 64
    mem[30] = 999
    m = run([{"store": [("store", 0, 1)], "load": [("load", 2, 0)]}],
            mem=mem, scratch_init={0: 30, 1: 42})
    print(f"mem RAW same-cycle: s2={m.cores[0].scratch[2]} "
          f"(999 => load saw OLD mem)  mem[30]={m.mem[30]} (42)")

    # 6. mem WAR: load then same-cycle store to the same address.
    mem = [0] * 64
    mem[30] = 999
    m = run([{"load": [("load", 2, 0)], "store": [("store", 0, 1)]}],
            mem=mem, scratch_init={0: 30, 1: 42})
    print(f"mem WAR same-cycle: s2={m.cores[0].scratch[2]} (999) "
          f"mem[30]={m.mem[30]} (42)")

    # 7. empty / debug-only bundles are FREE (run() only counts non-debug)
    m = run([{}, {"alu": [("+", 1, 0, 0)]}, {}, {}])
    print(f"empty bundles: program len 4 -> machine.cycle={m.cycle} "
          f"(1 => empty bundles are free)")


if __name__ == "__main__":
    main()
