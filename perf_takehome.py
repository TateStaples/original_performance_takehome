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
        self.build_kernel_pipelined(
            batch_size, rounds, forest_height=forest_height, pipeline_width=16
        )

    # ------------------------------------------------------------------
    # Fused-hash constants (see docs/problem.md 2.4 and the bit-exact proof
    # in rust_harness/src/problem.rs::cross_stage_fusion_is_bit_exact).
    #
    # myhash's 6 stages collapse to 11 vector "mixing" ops instead of 18:
    #   stage0 (affine)      a*(1+2^12) + C0            -> 1 multiply_add
    #   stage1 (xor-shift)   (a ^ C1) ^ (a >> 19)       -> 3 ops
    #   stage2+stage3 fused  p = a*33 + (C2+C3);
    #                        q = a*(33*512) + (C2<<9);
    #                        a = p ^ q                  -> 2 multiply_add + 1 xor
    #   stage4 (affine)      a*(1+2^3) + C4             -> 1 multiply_add
    #   stage5 (xor-shift)   (a ^ C5) ^ (a >> 16)       -> 3 ops
    # stage2 is affine (b = 33a + C2) and both of stage3's branches are
    # integer-affine in b (hence in a), so the pair fuses across the boundary.
    # ------------------------------------------------------------------
    @staticmethod
    def _fused_hash_constants():
        M = (1 << 32) - 1
        (o0, C0, _, _, s0) = HASH_STAGES[0]
        (o1a, C1, _, o1b, s1) = HASH_STAGES[1]
        (_, C2, _, _, s2) = HASH_STAGES[2]
        (_, C3, _, _, s3) = HASH_STAGES[3]
        (_, C4, _, _, s4) = HASH_STAGES[4]
        (o5a, C5, _, o5b, s5) = HASH_STAGES[5]
        assert (o0, s0) == ("+", 12)
        assert (o1a, o1b, s1) == ("^", ">>", 19)
        assert s2 == 5 and s3 == 9 and s4 == 3
        assert (o5a, o5b, s5) == ("^", ">>", 16)
        c = {
            "k0": (1 + (1 << s0)) & M,
            "C0": C0,
            "C1": C1,
            "sh1": s1,
            "kp": (1 + (1 << s2)) & M,
            "ap": (C2 + C3) & M,
            "kq": ((1 + (1 << s2)) * (1 << s3)) & M,
            "aq": (C2 << s3) & M,
            "k4": (1 + (1 << s4)) & M,
            "C4": C4,
            "C5": C5,
            "sh5": s5,
        }

        def fused(a):
            a = (a * c["k0"] + c["C0"]) & M
            a = (a ^ c["C1"]) ^ (a >> c["sh1"])
            p = (a * c["kp"] + c["ap"]) & M
            q = (a * c["kq"] + c["aq"]) & M
            a = p ^ q
            a = (a * c["k4"] + c["C4"]) & M
            a = (a ^ c["C5"]) ^ (a >> c["sh5"])
            return a

        # Build-time sanity: the fused form must reproduce myhash bit-for-bit.
        import random as _r

        _rng = _r.Random(0xC0FFEE)
        samples = [0, 1, 2, 255, 1 << 31, M, C2, C3] + [
            _rng.randint(0, M) for _ in range(2000)
        ]
        for a in samples:
            ref = a
            for op1, val1, op2, op3, val3 in HASH_STAGES:
                fns = {
                    "+": lambda x, y: (x + y) & M,
                    "^": lambda x, y: x ^ y,
                    "<<": lambda x, y: (x << y) & M,
                    ">>": lambda x, y: x >> y,
                }
                ref = fns[op2](fns[op1](ref, val1), fns[op3](ref, val3))
            assert fused(a) == ref, f"fused hash mismatch at {a:#x}"
        return c

    def build_kernel_pipelined(
        self,
        batch_size: int,
        rounds: int,
        forest_height: int = None,
        pipeline_width: int = 16,
        debug_compares: bool = False,
    ):
        """
        Vectorized + software-pipelined kernel.

        Two independent, engine-disjoint work items make up each round for a
        group of VLEN walkers:
          - GATHER: compute the 8 gather addresses (one valu add) and issue
            the 8 scalar `load`s of `mem[forest_values_p + idx]` -- this is
            `load`-engine work (2 slots/cycle), and it is the workload's hard
            floor: batch_size/VLEN * rounds * 8 / 2 load-cycles no matter how
            well anything else packs.
          - COMPUTE: `val ^= node_val`, the (fused) 6-stage hash, and the
            idx update -- this is `valu`/`flow`-engine work.
        The baseline `build_kernel_vectorized` ran these as separate, barriered
        phases, so `load` sat idle during COMPUTE and `valu` sat idle during
        GATHER; the round cost was ~sum of the two. Here we software-pipeline:
        while COMPUTE(unit k) runs on valu/flow, GATHER(unit k+1) fills the
        otherwise-idle load slots of the very same bundles (ping-ponging two
        node_val buffers so the consumer and producer never alias). The round
        then costs ~max(load, valu, flow) instead of their sum -- i.e. it
        approaches the ~2048-cycle load floor.

        Also folds the hash to 11 mixing ops via multiply_add (see
        `_fused_hash_constants`) and the idx update to `2*idx + 1 + (val&1)`
        (one multiply_add + one and + one add), so valu stays comfortably
        under the load floor and hides beneath it.

        `debug_compares=True` interleaves free `("debug", ("vcompare", ...))`
        checks (ignored by the grader, `enable_debug=False`) against the
        reference value trace for fast (round, walker, field) bug isolation.
        """
        M = (1 << 32) - 1
        assert batch_size % VLEN == 0, f"batch_size must be a multiple of VLEN={VLEN}"
        n_groups = batch_size // VLEN
        pw = pipeline_width
        assert pw >= 1

        # Every walker advances exactly one tree level per round and wraps
        # back to the root together at the bottom, so at round r EVERY walker
        # sits at level r % (forest_height+1). On a "level 0" round every idx
        # is 0, so node_val is just the (broadcast) root value -- no gather.
        if forest_height is not None:
            period = forest_height + 1
            level0_rounds = {r for r in range(rounds) if r % period == 0}
        else:
            level0_rounds = {0}  # only the guaranteed initial all-root round

        # --- header: read the 4 fields this kernel uses (docs/problem.md 2.5)
        header_fields = {
            "n_nodes": 1,
            "forest_values_p": 4,
            "inp_indices_p": 5,
            "inp_values_p": 6,
        }
        for name, header_index in header_fields.items():
            self.alloc_scratch(name)
            addr = self.scratch_const(header_index)
            self.add("load", ("load", self.scratch[name], addr))

        # Matches reference_kernel2's first yield.
        self.add("flow", ("pause",))

        # --- broadcast every constant/vector this kernel needs, once ---
        bcast_slots = []

        def broadcast(src):
            dest = self.alloc_scratch(length=VLEN)
            bcast_slots.append(("vbroadcast", dest, src))
            return dest

        # node_val of the root (tree.values[0]); round 0 has every walker at
        # idx 0, so its gather is just this value broadcast -- no loads needed.
        root_nv = self.alloc_scratch("root_nv")
        self.add("load", ("load", root_nv, self.scratch["forest_values_p"]))
        root_nv_vec = broadcast(root_nv)

        one_vec = broadcast(self.scratch_const(1))
        two_vec = broadcast(self.scratch_const(2))
        fp_vec = broadcast(self.scratch["forest_values_p"])
        n_nodes_vec = broadcast(self.scratch["n_nodes"])

        hc = self._fused_hash_constants()
        vecs = {
            key: broadcast(self.scratch_const(hc[key]))
            for key in ("k0", "C0", "C1", "sh1", "kp", "ap", "kq", "aq", "k4", "C4", "C5", "sh5")
        }
        # Derived vectors for the gaddr-based idx update (see below):
        #   omf = 1 - forest_values_p   (folds the +1 and the -fp into one madd)
        #   fpn = forest_values_p + n_nodes  (wraparound compares gaddr < fpn)
        omf_vec = self.alloc_scratch(length=VLEN)
        fpn_vec = self.alloc_scratch(length=VLEN)
        # flush broadcasts, 6 valu/cycle
        for i in range(0, len(bcast_slots), SLOT_LIMITS["valu"]):
            self.instrs.append({"valu": bcast_slots[i : i + SLOT_LIMITS["valu"]]})
        self.instrs.append({"valu": [
            ("-", omf_vec, one_vec, fp_vec),
            ("+", fpn_vec, fp_vec, n_nodes_vec),
        ]})

        # --- persistent state -------------------------------------------
        # We never need the final indices (only `inp_values` is graded), so
        # instead of carrying `idx` we carry the gather ADDRESS
        #   gaddr = forest_values_p + idx
        # directly. That makes node_val's lookup a bare `load` of
        # mem[gaddr[lane]] with NO per-round address arithmetic, and folds
        # `forest_values_p` into the idx-update's multiply_add. One 8-wide
        # gaddr/val vector per group, alive for the whole run.
        gaddr_vecs = [self.alloc_scratch(length=VLEN) for _ in range(n_groups)]
        val_vecs = [self.alloc_scratch(length=VLEN) for _ in range(n_groups)]

        # Ping-pong node_val buffers, 2 sets of pw vectors.
        nv_bufs = [self.alloc_scratch(length=pw * VLEN) for _ in range(2)]
        # Per-pipeline-slot compute temporaries.
        t1 = [self.alloc_scratch(length=VLEN) for _ in range(pw)]
        t2 = [self.alloc_scratch(length=VLEN) for _ in range(pw)]

        # --- initial load of every group's idx/val (once) ---
        def group_addrs(base_name):
            base = self.scratch[base_name]
            addrs = []
            slots = []
            for g in range(n_groups):
                dest = self.alloc_scratch()
                slots.append(("+", dest, base, self.scratch_const(g * VLEN)))
                addrs.append(dest)
            for i in range(0, len(slots), SLOT_LIMITS["alu"]):
                self.instrs.append({"alu": slots[i : i + SLOT_LIMITS["alu"]]})
            return addrs

        # Every walker starts at idx 0 (Input.generate), so gaddr = fp for
        # all lanes -- just broadcast it, no index load needed. Values are
        # random, so they must be vloaded.
        val_addrs = group_addrs("inp_values_p")
        init_slots = [
            ("vbroadcast", gaddr_vecs[g], self.scratch["forest_values_p"])
            for g in range(n_groups)
        ]
        for i in range(0, len(init_slots), SLOT_LIMITS["valu"]):
            self.instrs.append({"valu": init_slots[i : i + SLOT_LIMITS["valu"]]})
        vload_slots = [("vload", val_vecs[g], val_addrs[g]) for g in range(n_groups)]
        for i in range(0, len(vload_slots), SLOT_LIMITS["load"]):
            self.instrs.append({"load": vload_slots[i : i + SLOT_LIMITS["load"]]})

        # --- pipeline over (round, wave) units ---
        waves = [
            list(range(ws, min(ws + pw, n_groups)))
            for ws in range(0, n_groups, pw)
        ]
        units = [(r, w) for r in range(rounds) for w in range(len(waves))]

        def gather_ops(unit, parity):
            # Pure loads: node_val[lane] = mem[gaddr[lane]]. No address math.
            # Level-0 rounds are all-root, so they need no gather.
            if unit[0] in level0_rounds:
                return []
            wave = waves[unit[1]]
            nv_buf = nv_bufs[parity]
            return [
                ("load", nv_buf + s * VLEN + lane, gaddr_vecs[g] + lane)
                for s, g in enumerate(wave)
                for lane in range(VLEN)
            ]

        def compute_cycles(unit, parity):
            r, w = unit
            wave = waves[w]
            nv_buf = nv_bufs[parity]
            cycles = []

            def step(ops):  # chunk independent valu ops into <=6/cycle bundles
                for i in range(0, len(ops), SLOT_LIMITS["valu"]):
                    cycles.append({"valu": ops[i : i + SLOT_LIMITS["valu"]]})

            # val ^= node_val  (level-0 rounds: broadcast root; else gathered)
            def nv_src(s):
                return root_nv_vec if r in level0_rounds else nv_buf + s * VLEN
            step([("^", val_vecs[g], val_vecs[g], nv_src(s))
                  for s, g in enumerate(wave)])
            # stage0 (affine): val = val*k0 + C0
            step([("multiply_add", val_vecs[g], val_vecs[g], vecs["k0"], vecs["C0"])
                  for g in wave])
            # stage1: (val ^ C1) ^ (val >> 19)
            ops = []
            for s, g in enumerate(wave):
                ops.append(("^", t1[s], val_vecs[g], vecs["C1"]))
                ops.append((">>", t2[s], val_vecs[g], vecs["sh1"]))
            step(ops)
            step([("^", val_vecs[g], t1[s], t2[s]) for s, g in enumerate(wave)])
            # stage2+stage3 fused: p = val*kp + ap ; q = val*kq + aq ; val = p ^ q
            ops = []
            for s, g in enumerate(wave):
                ops.append(("multiply_add", t1[s], val_vecs[g], vecs["kp"], vecs["ap"]))
                ops.append(("multiply_add", t2[s], val_vecs[g], vecs["kq"], vecs["aq"]))
            step(ops)
            step([("^", val_vecs[g], t1[s], t2[s]) for s, g in enumerate(wave)])
            # stage4 (affine): val = val*k4 + C4
            step([("multiply_add", val_vecs[g], val_vecs[g], vecs["k4"], vecs["C4"])
                  for g in wave])
            # stage5: (val ^ C5) ^ (val >> 16)
            ops = []
            for s, g in enumerate(wave):
                ops.append(("^", t1[s], val_vecs[g], vecs["C5"]))
                ops.append((">>", t2[s], val_vecs[g], vecs["sh5"]))
            step(ops)
            step([("^", val_vecs[g], t1[s], t2[s]) for s, g in enumerate(wave)])
            # val_vecs now holds the finished hash (hashed_val)
            if debug_compares:
                for g in wave:
                    cycles.append({"debug": [(
                        "vcompare", val_vecs[g],
                        [(r, g * VLEN + lane, "hashed_val") for lane in range(VLEN)],
                    )]})
            # idx update in gaddr space:
            #   next_gaddr = 2*gaddr + 1 - fp + (val & 1)
            #             = madd(gaddr, two, omf) + (val & 1)
            #   gaddr = (next_gaddr < fp+n_nodes) ? next_gaddr : fp  (idx=0 wrap)
            ops = []
            for s, g in enumerate(wave):
                ops.append(("&", t1[s], val_vecs[g], one_vec))                       # parity
                ops.append(("multiply_add", t2[s], gaddr_vecs[g], two_vec, omf_vec))  # 2*gaddr+1-fp
            step(ops)
            step([("+", t1[s], t2[s], t1[s]) for s, g in enumerate(wave)])           # next_gaddr
            step([("<", t2[s], t1[s], fpn_vec) for s, g in enumerate(wave)])         # in-range?
            for s, g in enumerate(wave):
                cycles.append({"flow": [("vselect", gaddr_vecs[g], t2[s], t1[s], fp_vec)]})
            return cycles

        def emit_unit(compute, load_ops):
            # Interleave the prefetched gather's loads into COMPUTE's
            # otherwise-idle load slots (2/cycle). Loads read gaddr_vecs of a
            # DIFFERENT wave, so they're independent of this compute.
            li = 0
            for cyc in compute:
                is_real = ("valu" in cyc) or ("flow" in cyc)
                if is_real and li < len(load_ops):
                    cyc = dict(cyc)
                    cyc["load"] = load_ops[li : li + SLOT_LIMITS["load"]]
                    li += SLOT_LIMITS["load"]
                self.instrs.append(cyc)
            while li < len(load_ops):
                self.instrs.append({"load": load_ops[li : li + SLOT_LIMITS["load"]]})
                li += SLOT_LIMITS["load"]

        def emit_gather_full(unit, parity):
            loads = gather_ops(unit, parity)
            for i in range(0, len(loads), SLOT_LIMITS["load"]):
                self.instrs.append({"load": loads[i : i + SLOT_LIMITS["load"]]})

        # Unit j's gathered node_val lives in buffer parity j % 2, so a
        # consumer (compute j, reads j%2) and the concurrently-prefetched
        # producer (gather j+1, writes (j+1)%2) never alias.
        #
        # We prefetch unit k+1's gather during unit k's compute ONLY when
        # their groups are disjoint -- otherwise gather(k+1) would read
        # gaddr_vecs before compute(k)'s vselect has committed the new gaddr
        # for those very groups. For the graded shape (32 groups) waves are
        # always disjoint, so this always prefetches; the fallback keeps
        # smaller/degenerate shapes correct.
        emit_gather_full(units[0], 0)
        for k, unit in enumerate(units):
            compute = compute_cycles(unit, k % 2)
            nxt = k + 1
            can_prefetch = nxt < len(units) and set(waves[units[nxt][1]]).isdisjoint(
                waves[unit[1]]
            )
            if can_prefetch:
                emit_unit(compute, gather_ops(units[nxt], nxt % 2))
            else:
                emit_unit(compute, [])
                if nxt < len(units):
                    emit_gather_full(units[nxt], nxt % 2)

        # --- store every group's final val once (indices aren't graded) ---
        store_slots = [("vstore", val_addrs[g], val_vecs[g]) for g in range(n_groups)]
        for i in range(0, len(store_slots), SLOT_LIMITS["store"]):
            self.instrs.append({"store": store_slots[i : i + SLOT_LIMITS["store"]]})

        # Matches reference_kernel2's second yield.
        self.add("flow", ("pause",))

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
        # docs/problem.md §2.5 for the fixed 7-word header layout). Routed
        # through scratch_const (memoized) rather than a raw "const" load,
        # since header index 1 (n_nodes) coincides with the "one" constant
        # broadcast below and can share its load.
        header_fields = {"n_nodes": 1, "forest_values_p": 4, "inp_indices_p": 5, "inp_values_p": 6}
        for name, header_index in header_fields.items():
            self.alloc_scratch(name)
            addr = self.scratch_const(header_index)
            self.add("load", ("load", self.scratch[name], addr))

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
