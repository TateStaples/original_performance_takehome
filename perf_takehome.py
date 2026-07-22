"""
# Anthropic's Original Performance Engineering Take-home (Release version)

Copyright Anthropic PBC 2026. Permission is granted to modify and use, but not
to publish or redistribute your solutions so it's hard to find spoilers.

# Task

- Optimize the kernel (in KernelBuilder.build_kernel) as much as possible in the
  available time, as measured by test_kernel_cycles on a frozen separate copy
  of the simulator.

Validate your results using `python tests/submission_tests.py` without modifying
anything in the tests/ folder.

We recommend you look through problem.py next.
"""

from collections import defaultdict
import random
import unittest

from problem import (
    Engine,
    DebugInfo,
    SLOT_LIMITS,
    VLEN,
    N_CORES,
    SCRATCH_SIZE,
    Machine,
    Tree,
    Input,
    HASH_STAGES,
    reference_kernel,
    build_mem_image,
    reference_kernel2,
)


class KernelBuilder:
    def __init__(self):
        self.instrs = []
        self.scratch = {}
        self.scratch_debug = {}
        self.scratch_ptr = 0
        self.const_map = {}
        self._current = {}  # bundle being greedily packed by _pack/_flush

    def debug_info(self):
        return DebugInfo(scratch_map=self.scratch_debug)

    def build(self, slots: list[tuple[Engine, tuple]], vliw: bool = False):
        # Simple slot packing that just uses one slot per instruction bundle
        instrs = []
        for engine, slot in slots:
            instrs.append({engine: [slot]})
        return instrs

    def add(self, engine, slot):
        self.instrs.append({engine: [slot]})

    def _pack(self, engine, slot):
        """
        Greedily append `slot` to the bundle currently being built, filling
        up to SLOT_LIMITS[engine] slots on that engine before starting a new
        bundle. Safe to call freely for mutually-independent ops; call
        _flush() before pushing anything that depends on a value one of
        those ops just wrote, since a bundle's writes only become visible
        after the whole bundle commits (see docs/isa.md).
        """
        bucket = self._current.setdefault(engine, [])
        if len(bucket) >= SLOT_LIMITS[engine]:
            self._flush()
            bucket = self._current.setdefault(engine, [])
        bucket.append(slot)

    def _flush(self):
        if self._current:
            self.instrs.append(self._current)
            self._current = {}

    def alloc_scratch(self, name=None, length=1):
        addr = self.scratch_ptr
        if name is not None:
            self.scratch[name] = addr
            self.scratch_debug[addr] = (name, length)
        self.scratch_ptr += length
        assert self.scratch_ptr <= SCRATCH_SIZE, "Out of scratch space"
        return addr

    def scratch_const(self, val, name=None):
        if val not in self.const_map:
            addr = self.alloc_scratch(name)
            self.add("load", ("const", addr, val))
            self.const_map[val] = addr
        return self.const_map[val]

    def build_kernel(
        self, forest_height: int, n_nodes: int, batch_size: int, rounds: int
    ):
        self.build_kernel_vectorized(batch_size, rounds, pipeline_width=1)

    def build_kernel_vectorized(self, batch_size: int, rounds: int, pipeline_width: int = 6):
        """
        Vectorized + pipelined kernel: processes VLEN=8 walkers per `valu`
        register instead of one scalar walker at a time, and keeps idx/val
        resident in scratch for a group's entire round-lifetime -- memory is
        only touched once at the very start (vload) and once at the very
        end (vstore) per group, unlike a round-major scan that round-trips
        through memory every round for every walker.

        `pipeline_width` groups' independent instruction streams are
        interleaved so valu's 6 slots/cycle actually get filled: a single
        group's own hash-stage dependency chain (op1/op3 are independent,
        but the combine step needs both, so it can't join them in the same
        bundle -- see docs/isa.md) only ever offers 2 independent valu ops
        at a time, and every other phase (addr, xor, mod, ...) offers only
        1 -- so a wave of pipeline_width=6 groups fills every phase's valu
        bundles at (close to) 100%, since 6 is a multiple of both 1 and 2.
        pipeline_width=1 gives the vectorize-only version (valu is used,
        but its slots mostly aren't filled).

        node_val's lookup (`mem[forest_values_p + idx[lane]]`) is a
        data-dependent gather -- there's no vector gather instruction in
        this ISA, only contiguous vload/vstore -- so it's unavoidably 8
        scalar loads per group per round; with `load`'s 2-slot/cycle limit
        that makes it the dominant, hardest-to-remove cost once everything
        else is packed (confirmed via rust_harness's usage-stats tool).

        This was prototyped, correctness-checked against Python-exported
        fixtures, and profiled in rust_harness/src/vectorized.rs before
        being ported here -- see that file and rust_harness/README.md for
        the fuller write-up, and docs/problem.md for the algorithm this
        implements.
        """
        assert batch_size % VLEN == 0, f"batch_size must be a multiple of VLEN={VLEN}"
        n_groups = batch_size // VLEN

        # Only the 4 header fields this kernel actually reads (see
        # docs/problem.md §2.5 for the fixed 7-word header layout).
        header_fields = {"n_nodes": 1, "forest_values_p": 4, "inp_indices_p": 5, "inp_values_p": 6}
        addr_tmp_scalar = self.alloc_scratch("header_addr_tmp")
        for name, header_index in header_fields.items():
            self.alloc_scratch(name)
            self.add("load", ("const", addr_tmp_scalar, header_index))
            self.add("load", ("load", self.scratch[name], addr_tmp_scalar))

        # Matches reference_kernel2's first yield.
        self.add("flow", ("pause",))

        # Broadcast every constant this kernel needs into an 8-wide vector,
        # exactly once; every group/round below only *reads* these.
        def broadcast(src):
            dest = self.alloc_scratch(length=VLEN)
            self._pack("valu", ("vbroadcast", dest, src))
            return dest

        zero_const = self.scratch_const(0)
        one_const = self.scratch_const(1)
        two_const = self.scratch_const(2)
        zero_vec = broadcast(zero_const)
        one_vec = broadcast(one_const)
        two_vec = broadcast(two_const)
        forest_values_p_vec = broadcast(self.scratch["forest_values_p"])
        n_nodes_vec = broadcast(self.scratch["n_nodes"])

        hash_const_vecs = [
            (broadcast(self.scratch_const(val1)), broadcast(self.scratch_const(val3)))
            for (_, val1, _, _, val3) in HASH_STAGES
        ]
        self._flush()

        # One persistent 8-wide vector register per group, alive for the
        # group's entire 16-round lifetime.
        idx_vecs = [self.alloc_scratch(length=VLEN) for _ in range(n_groups)]
        val_vecs = [self.alloc_scratch(length=VLEN) for _ in range(n_groups)]

        # Per-pipeline-slot scratch temporaries, reused wave to wave.
        def temp_pool():
            return [self.alloc_scratch(length=VLEN) for _ in range(pipeline_width)]

        addr_tmp = temp_pool()
        node_val_tmp = temp_pool()
        hash_tmp1 = temp_pool()
        hash_tmp2 = temp_pool()
        offset_tmp = temp_pool()
        next_idx_tmp = temp_pool()
        cmp_tmp = temp_pool()

        def group_addrs(base):
            # addr[g] = base + g*VLEN, computed as one packed batch (up to
            # SLOT_LIMITS["alu"]/cycle) rather than one bundle per group.
            addrs = []
            for g in range(n_groups):
                dest = self.alloc_scratch()
                offset_const = self.scratch_const(g * VLEN)
                self._pack("alu", ("+", dest, base, offset_const))
                addrs.append(dest)
            self._flush()
            return addrs

        # Load every group's starting idx/val once.
        idx_addrs = group_addrs(self.scratch["inp_indices_p"])
        val_addrs = group_addrs(self.scratch["inp_values_p"])
        for g in range(n_groups):
            self._pack("load", ("vload", idx_vecs[g], idx_addrs[g]))
            self._pack("load", ("vload", val_vecs[g], val_addrs[g]))
        self._flush()

        for _round in range(rounds):
            wave_start = 0
            while wave_start < n_groups:
                wave = list(range(wave_start, min(wave_start + pipeline_width, n_groups)))
                wave_start += pipeline_width

                # addr[g] = idx[g] + forest_values_p (all 8 lanes' gather addresses in one valu op)
                for slot, g in enumerate(wave):
                    self._pack("valu", ("+", addr_tmp[slot], idx_vecs[g], forest_values_p_vec))
                self._flush()

                # gather node_val -- unavoidably scalar, see docstring above
                for slot in range(len(wave)):
                    for lane in range(VLEN):
                        self._pack("load", ("load", node_val_tmp[slot] + lane, addr_tmp[slot] + lane))
                self._flush()

                # val ^= node_val
                for slot, g in enumerate(wave):
                    self._pack("valu", ("^", val_vecs[g], val_vecs[g], node_val_tmp[slot]))
                self._flush()

                # 6-stage hash, vectorized
                for stage_idx, (op1, _, op2, op3, _) in enumerate(HASH_STAGES):
                    c1_vec, c3_vec = hash_const_vecs[stage_idx]
                    for slot, g in enumerate(wave):
                        self._pack("valu", (op1, hash_tmp1[slot], val_vecs[g], c1_vec))
                        self._pack("valu", (op3, hash_tmp2[slot], val_vecs[g], c3_vec))
                    self._flush()
                    for slot, g in enumerate(wave):
                        self._pack("valu", (op2, val_vecs[g], hash_tmp1[slot], hash_tmp2[slot]))
                    self._flush()

                # offset = (val % 2) + 1 -- replaces the naive mod+eq+select
                for slot, g in enumerate(wave):
                    self._pack("valu", ("%", offset_tmp[slot], val_vecs[g], two_vec))
                self._flush()
                for slot in range(len(wave)):
                    self._pack("valu", ("+", offset_tmp[slot], offset_tmp[slot], one_vec))
                self._flush()

                # next_idx = idx*2 + offset
                for slot, g in enumerate(wave):
                    self._pack("valu", ("*", next_idx_tmp[slot], idx_vecs[g], two_vec))
                self._flush()
                for slot in range(len(wave)):
                    self._pack("valu", ("+", next_idx_tmp[slot], next_idx_tmp[slot], offset_tmp[slot]))
                self._flush()

                # wraparound: idx = (next_idx < n_nodes) ? next_idx : 0 -- the one genuine select
                for slot in range(len(wave)):
                    self._pack("valu", ("<", cmp_tmp[slot], next_idx_tmp[slot], n_nodes_vec))
                self._flush()
                for slot, g in enumerate(wave):
                    self._pack("flow", ("vselect", idx_vecs[g], cmp_tmp[slot], next_idx_tmp[slot], zero_vec))
                self._flush()

        # Store every group's final idx/val once, at the same addresses
        # computed for the initial load (nothing writes those pointer
        # registers in between, so there's no need to recompute them).
        for g in range(n_groups):
            self._pack("store", ("vstore", idx_addrs[g], idx_vecs[g]))
            self._pack("store", ("vstore", val_addrs[g], val_vecs[g]))
        self._flush()

        # Matches reference_kernel2's second yield.
        self.add("flow", ("pause",))

BASELINE = 147734

def do_kernel_test(
    forest_height: int,
    rounds: int,
    batch_size: int,
    seed: int = 123,
    trace: bool = False,
    prints: bool = False,
):
    print(f"{forest_height=}, {rounds=}, {batch_size=}")
    random.seed(seed)
    forest = Tree.generate(forest_height)
    inp = Input.generate(forest, batch_size, rounds)
    mem = build_mem_image(forest, inp)

    kb = KernelBuilder()
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), rounds)
    # print(kb.instrs)

    value_trace = {}
    machine = Machine(
        mem,
        kb.instrs,
        kb.debug_info(),
        n_cores=N_CORES,
        value_trace=value_trace,
        trace=trace,
    )
    machine.prints = prints
    for i, ref_mem in enumerate(reference_kernel2(mem, value_trace)):
        machine.run()
        inp_values_p = ref_mem[6]
        if prints:
            print(machine.mem[inp_values_p : inp_values_p + len(inp.values)])
            print(ref_mem[inp_values_p : inp_values_p + len(inp.values)])
        assert (
            machine.mem[inp_values_p : inp_values_p + len(inp.values)]
            == ref_mem[inp_values_p : inp_values_p + len(inp.values)]
        ), f"Incorrect result on round {i}"
        inp_indices_p = ref_mem[5]
        if prints:
            print(machine.mem[inp_indices_p : inp_indices_p + len(inp.indices)])
            print(ref_mem[inp_indices_p : inp_indices_p + len(inp.indices)])
        # Updating these in memory isn't required, but you can enable this check for debugging
        # assert machine.mem[inp_indices_p:inp_indices_p+len(inp.indices)] == ref_mem[inp_indices_p:inp_indices_p+len(inp.indices)]

    print("CYCLES: ", machine.cycle)
    print("Speedup over baseline: ", BASELINE / machine.cycle)
    return machine.cycle


class Tests(unittest.TestCase):
    def test_ref_kernels(self):
        """
        Test the reference kernels against each other
        """
        random.seed(123)
        for i in range(10):
            f = Tree.generate(4)
            inp = Input.generate(f, 10, 6)
            mem = build_mem_image(f, inp)
            reference_kernel(f, inp)
            for _ in reference_kernel2(mem, {}):
                pass
            assert inp.indices == mem[mem[5] : mem[5] + len(inp.indices)]
            assert inp.values == mem[mem[6] : mem[6] + len(inp.values)]

    def test_kernel_trace(self):
        # Full-scale example for performance testing
        do_kernel_test(10, 16, 256, trace=True, prints=False)

    # Passing this test is not required for submission, see submission_tests.py for the actual correctness test
    # You can uncomment this if you think it might help you debug
    # def test_kernel_correctness(self):
    #     for batch in range(1, 3):
    #         for forest_height in range(3):
    #             do_kernel_test(
    #                 forest_height + 2, forest_height + 4, batch * 16 * VLEN * N_CORES
    #             )

    def test_kernel_cycles(self):
        do_kernel_test(10, 16, 256)


# To run all the tests:
#    python perf_takehome.py
# To run a specific test:
#    python perf_takehome.py Tests.test_kernel_cycles
# To view a hot-reloading trace of all the instructions:  **Recommended debug loop**
# NOTE: The trace hot-reloading only works in Chrome. In the worst case if things aren't working, drag trace.json onto https://ui.perfetto.dev/
#    python perf_takehome.py Tests.test_kernel_trace
# Then run `python watch_trace.py` in another tab, it'll open a browser tab, then click "Open Perfetto"
# You can then keep that open and re-run the test to see a new trace.

# To run the proper checks to see which thresholds you pass:
#    python tests/submission_tests.py

if __name__ == "__main__":
    unittest.main()
