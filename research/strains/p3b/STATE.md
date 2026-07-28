---
title: "P3-B: the index + parity recurrence -- true cost, true floor"
date: 2026-07-28
type: research
status: final
task: "Establish the real per-group-round cost of index maintenance, prove or refute the charter's 2-vec-op/group-round floor, exploit unused ISA, and price the wrap."
links: ["[[research/RESEARCH.md#Phase-3-charter]]", "[[research/graveyard.md#G-21]]"]
---

# P3-B: index + parity recurrence

**Verdict in one line: the charter's index floor of 8,192 lane-ops is WRONG
(too high by 1,584). The true floor at today's serving policy is 6,608
lane-ops and we spend 7,184 -- the axis has 576 lane-ops of slack, not zero,
and the "any design of this shape floors at 911 cycles" line should read
884.5 (or 872.5 under a b=0 L4 policy).**

**Cross-axis addendum (section 9): P3-A's C9 -- "eliminate the `omf`
constant-select, floor 939 -> 920" -- is REFUTED. The op is fungible
flow-or-valu; the only representations that remove it (`idx+1`, `idx+3`)
replace it with a valu-ONLY address-recovery op. Exact tie at P3-A's
optimum, strictly worse everywhere else. The floor stays 939.**

Tools (all read-only, new, mine): `tools/p3b_attrib.py`,
`tools/p3b_onestep.py`, `tools/p3b_model.py`, `tools/p3b_omf.py`.

## 0. What G-21 held fixed (the frame I was asked to test one level coarser)

G-21 (research/graveyard.md:248) closed "index algebra" with an argument
that is **entirely about one madd's three operand slots**: it showed that
you cannot fold the position recurrence into a *hash* madd, because the
only parity-isolating multiplier mod 2^32 is 2^31 (parks parity at bit31,
unusable as an address addend). Its scope statement --
"Steady-gather floor is extract(1)+madd(1)+combine(1) per round; mainline
is already there" -- is a statement about **one gathered round**, held at
**uniform per-round cost across all 512 group-rounds**. It never asked
(a) how many group-rounds actually need an address, (b) whether the
combine can be made free, or (c) whether the wrap costs anything. All three
answers turn out to be favourable and none of them contradict G-21.

## 1. (a) MEASURED per-group-round cost, attributed op by op

`python3 tools/p3b_attrib.py` monkeypatches `ListScheduler.put` and
attributes every emitted slot to its perf_takehome.py line and to the
(level -> next level) transition of the enclosing `_round_stage_generator`
frame. Result (vec-op-equivalents; 8 alu slots counted as 1 vec-op):

| transition | group-rounds | alu+valu vec-ops | flow slots | per gr |
|---|---|---|---|---|
| L0 -> L1 | 64 | 64 | 0 | 1.00 |
| L1 -> L2 | 64 | 64 | 0 | 1.00 |
| L2 -> L3 | 64 | 90 | 0 | 1.41 |
| L3 -> L4 | 64 | 230 | 0 | 3.59 |
| L4 -> L5 | 32 | 130 | 6 | 4.06 |
| L5 -> L6 ... L9 -> L10 | 32 each | 64 each | 32 each | 2.00 |
| **L10 -> L0 (wrap)** | 32 | **0** | **0** | **0.00** |
| **round 15 (last)** | 32 | **0** | **0** | **0.00** |
| TOTAL | 512 | 898 (= 7,184 lane-ops) | 166 | 1.75 |

**Only 448 of 512 group-rounds emit any index work at all.** The charter's
`512 x 2` normalisation is wrong on both factors.

Op-by-op answers to the brief's questions:

* **What the `v&` is for.** `val & 1`, the parity extract, one per updating
  group-round. Four call sites, all the same lambda at
  perf_takehome.py:1607: line 1615 writes it straight into a tournament
  ring slot P0/P1/P2 (113 valu + 56 alu-spelled), 1617 seeds `st` at L0,
  1620 rides it on `nv` into the next tournament round, 1622 is the
  gathered-path parity (229 slots -- exactly the 229 gathered group-rounds).
  Total 441 valu + 56 alu = 3,528 + 56 lane-ops. This is 1 op/updating
  group-round and is at floor everywhere.
* **Idx's 343 madd slots.** Two populations: (i) perf_takehome.py:1656, 166
  slots = the steady gather advance `gaddr' = 2*gaddr + (omf +/- par)`, one
  per gathered group-round at L5..L10 (+6 at L4->L5); (ii) `race_idx_madd`
  (perf_takehome.py:869), 133 valu slots + 44 alu-spelled copies = the
  position-accumulator folds `p := 2p+b` and the accumulator-exit
  reconstruction at L2..L5.
* **Routing's 504 madd slots (4,032 lane-ops) are NOT address arithmetic.**
  They are *tournament table selects spelled as madds* -- `race_sel` /
  `race_leaf` / `dual_fold` emit `cond*diff + lo` when the scheduler's race
  puts the select on valu instead of the 1-slot flow engine (call sites
  perf_takehome.py:1456/1474-1477/1486-1489/1539-1545). The charter's
  framing of them as index spend is a misattribution; they belong to the
  serving axis (P3-A/P3-C).
* **The `v-` (512 + 96 lane-ops).** perf_takehome.py:1631, the `+/- par`
  combine on the accumulator-exit path (`gaddr = -2p' + K -/+ par`), plus
  `race_sel`'s `diff = hi - lo` when a select is spelled as a madd.
* **The 816 Idx alu lane-ops.** 352 `<<` + 216 `+` + 192 `-` = 44
  alu-spelled madds (`race_idx_madd`'s `enc_a`: shift then add/sub, 16 alu
  slots per group-round) plus 56 alu-spelled parity `&`. The alu spelling
  costs **2x lane-ops** (16 vs 8) for the same work -- see C1 below.

## 2. (b) FLOOR VERDICT

### Lemma 1 (parity-only ops) -- mechanically established

`tools/p3b_onestep.py` part 1 searched 12 opcodes x 502 constants x 2
operand orders = 12,048 forms for ops whose output depends on `val` only
through bit0. Exactly five families survive and distinguish the parities:

| form | output |
|---|---|
| `val & 1` | {0, 1} |
| `val % 2` | {0, 1} |
| `val * 0x80000000` | {0, 2^31} |
| `val << 31` | {0, 2^31} |
| **`val \| 0xFFFFFFFE`** | {0xFFFFFFFE, 0xFFFFFFFF} = **p - 2** |

The last one is new to this repo (`v|` has never been used). It is the only
one that comes with a *free additive bias*. Any single op that reads `val`
and feeds an exact memory address must be one of these, because two vals of
equal parity must produce the same address.

### Lemma 2 (no one-op advance) -- mechanically established

`tools/p3b_onestep.py` part 2 enumerated **1,548,224 structural forms** --
every opcode and `multiply_add`, every operand assignment over
{A (live address), val, K (solved constant)} -- against
`A' = 2A - 6 + (val & 1)` on 204 (A, val) samples. **0 solutions.**
So a gathered group-round costs **>= 2 alu/valu ops**: one to materialise
parity, one to combine it into the address.

The flow-engine escape is also closed: `A' in {2A-6, 2A-5}` is only two
values, so a vselect *could* produce it free -- but both arms would have to
be live, and manufacturing `2A-6` is itself the madd. `flow add_imm` is
scalar (8 flow slots/group-round x 448 = 3,584 >> 940 budget).

### Lemma 3 (the -6 bias is already free)

Affine reparametrisation: carry `S = idx + b`. Then `S' = 2S + (1 - b + p)`
for every `b`, so the advance is always one madd; the addend is one of two
compile-time constants selected by `p`. The shipped kernel does exactly
this with a **flow vselect between `one_minus_fp_vec` and `two_minus_fp_vec`**
(perf_takehome.py:1650-1656) -- **the address bias costs 0 alu/valu lane-ops
today**, only 1 flow slot per gathered group-round (166 total, and flow has
143 slots of headroom at 940).
The load address must be exactly `idx + 7`, and `A = S - b + 7` is free only
for `b = 7`, i.e. **carrying the address itself is the unique zero-extra-op
affine representation.** Hence:

* **1-based / `idx+1` (`M' = 2M + p`, constant-free):** saves the flow
  vselect but the load needs `M + 6` -> +1 valu op per gathered
  group-round. **+1,280 lane-ops / -166 flow. REFUTED.**
* **`idx+3` with `p - 2` from `val | 0xFFFFFFFE`** (`S' = 2S + (val|0xFFFFFFFE)`,
  exact, no select at all): identical trade. **+1,280 / -166. REFUTED**
  -- but this is the right spelling if flow ever becomes the binding engine.
* **level-offset split** (`idx = 2^d - 1 + off`, `off' = 2off + p`):
  substituting the level constant `6 + 2^d` gives back `A' = 2A - 6 + p`
  identically. It is the same recurrence in different letters. **0 delta.**
* **redundant `U = 2A - 6` carried alongside:** the select becomes free but
  `U' = 2A' - 4` is another madd. **+1,280 / -160 flow. REFUTED.**
* **advance by memory table in `extra_room`:** replaces the madd with a load
  -> +8 load slots per gathered group-round = **+1,280 load slots** on an
  engine already 12 slots OVER the 940 budget (1,892 vs 1,880). **REFUTED
  quantitatively.**
* **delayed/lagged normalisation:** already exploited maximally -- see below.

### The floor, correctly normalised

Combining: a transition costs 1 op (parity) if its successor is served by a
tournament, 2 ops if its successor gathers from an already-packed
predecessor, `k` ops if it must pack `k-1` loose bits, and **0 ops if its
successor is level 0 (the wrap) or if it is the last round.**

```
floor = 448 extracts
      + 3 madds x (L4 gathers: 9 in epoch 1 + 30 in epoch 2)
      + 4 madds x 23 (epoch-1 groups served at L4, pack 5 loose bits)
      + 1 madd  x 9  (epoch-1 groups already packed at L4)
      + 1 madd  x 160 (steady gather L5->L6 .. L9->L10)
      = 826 vec-ops = 6,608 lane-ops        [today's l4_gmin = (9,30)]
      = 736 vec-ops = 5,888 lane-ops        [if epoch-2 L4 gathers go to 0]
```

**VERDICT: the 2-vec-op/group-round claim is PROVED for gathered-successor
transitions (Lemmas 1+2) and REFUTED for tournament-served transitions,
where the floor is 1 op (parity bit only, no accumulate -- the shipped
kernel already runs L0->L1 and L1->L2 at exactly 1.00/gr via the parity
ring). The aggregate "8,192 lane-ops" is therefore a 24% over-estimate.**

Caveat on the per-row split: L4->L5 measures 130 against a modelled floor of
133 (-3). The line-based attribution smears a few packing madds between the
L3->L4 and L4->L5 rows (`race_idx_madd` is called from both the state-update
tail and the lagged `fold_position` inside the serving block), so trust the
TOTAL row, not individual rows, to about +/-5 vec-ops.

Measured 7,184 vs floor 6,608 = **576 lane-ops of slack**, of which 352 is
the deliberate alu-spelling of 44 madds (a scheduling race that trades
census for realized cycles -- see G-36) and ~224 is genuine accumulator
slop at L2->L4. **The index axis is 92% of the way to its own floor.**

Why the shipped kernel packs the position instead of keeping all bits
loose: the loose-bit ring needs one live vector per outstanding bit per
group. The ring covers 3 bits; going to 5 needs +2 vectors x 32 groups =
+512 scratch words and `scratch_next_addr` is 1533/1536. Under LOOP.md 0b
(idealized machine, infinite scratch) that is admissible; on the real
machine it is the reason the accumulator exists. **The packed accumulator
is a scratch optimisation, not an op optimisation.**

## 3. (c) Unused ISA

| op | verdict |
|---|---|
| `v\|` | **useful**: `val \| 0xFFFFFFFE` = `p - 2` in one op, the only parity form with a free additive bias. Enables a select-free advance if the state is biased to `idx+3`. Trades 166 flow slots for 1,280 lane-ops -> currently a loss. |
| `v%` | `val % 2` = p. Exactly equivalent to `v& 1`. No gain. |
| `v*` | `val * 2^31` = p at bit31. G-21's dead end, re-confirmed. |
| `v<`, `v==` | produce 0/1 but test magnitude/equality, never parity: 0 of 992 `==` forms and 0 of 2 `<` forms are parity-only. Useless for the recurrence. Note the *pipelined* kernel does use `<` for a wraparound compare (perf_takehome.py:1950) -- the scheduled kernel doesn't need it (see wrap, below). |
| `v//` | `val // 2^31` = bit31, not bit0. Useless. |
| `v<<` | `val << 31` = p at bit31. Same dead end. |
| `flow add_imm` | scalar, 1 slot: 8 slots per group-round -> 3,584 flow slots vs a 940 budget. Useless at vector width. |
| `flow select` (scalar) | same 8x problem. |
| `load const` / `load_offset` | `load_offset(dest, addr, off)` offsets the *scratch* indices, not the memory address (problem.py:299-303). **There is no base+displacement addressing mode**, which is precisely G-21's `reopen-if` condition -- still not met. |
| polluted-consumer question | **No.** Both consumers require cleanliness: the madd addend must be exact (it is added to an address), and a vselect condition must be nonzero-iff-odd, which `val` raw is not. The only pollution-tolerant form is `val * 2^31` / `val << 31` (nonzero iff odd) -- still 1 op, so no saving. |

## 4. (d) The wrap

**Current cost: exactly ZERO alu/valu/flow/load ops. Floor: zero. Closed.**

The kernel aligns round r to level `r mod 11` (perf_takehome.py:682), so the
wrap fires deterministically at r=10 for every walker simultaneously.
`_round_stage_generator` returns early at perf_takehome.py:1604-1605
(`if next_level == 0: return`) -- no compare, no select, and **not even a
parity extract**, because round 10's parity is discarded. Verified by
attribution: no L10 -> L0 row exists and exactly 448 = 512 - 32 (wrap) - 32
(last round) group-rounds emit index work. Line 541 of perf_takehome.py
states the invariant: "NO wraparound compare/select".
For contrast, the non-graded `build_kernel_pipelined` path pays a `v<` plus
a select per group-round (perf_takehome.py:1943-1950) -- 2 vec-ops -- which
is what the wrap costs if rounds are not level-aligned. The scheduled
kernel's alignment is worth 512 x 2 x 8 = 8,192 lane-ops and is already banked.

## 5. CENSUS DELTAS (`python3 tools/p3b_model.py`)

Baseline 59,489 alu+valu lane-ops / 1,892 load slots / 797 flow slots;
capacity at 940 = 56,400 / 1,880 / 940.

| candidate | alu+valu | load | flow | result |
|---|---|---|---|---|
| C0 shipped 1006 | +0 | +0 | +0 | 59,489/1,892/797 |
| C1 force all idx madds onto valu (undo the alu race) | **-352** | +0 | +0 | 59,137/1,892/797 |
| C2 carry `idx+1` (`M'=2M+p`) | +1,280 | +0 | -166 | refuted |
| C3 carry `idx+3`, parity `val\|0xFFFFFFFE` | +1,280 | +0 | -166 | refuted |
| C4 level-offset split | +0 | +0 | +0 | identity |
| C5 redundant `U = 2A-6` | +1,280 | +0 | -160 | refuted |
| C6 advance via mem table | -1,280 | **+1,280** | +0 | refuted (load engine already over budget) |
| C7 drop epoch-2 L4 gathers (**index side only**) | -720 | -240 | +0 | serving cost not modelled -- P3-A/P3-C |
| C8 C1 + C7 + close the L2..L4 slop (**index side only**) | -1,088 | -240 | +0 | optimistic bound |

**No candidate clears 940. The index axis cannot get there alone and never
could -- but it is not the closed axis the charter assumed.**

## 6. The corrected budget chain (the deliverable for the charter)

| idx floor used | non-hash-non-idx budget @940 | current spend on that pool | required cut |
|---|---|---|---|
| charter's 8,192 | 1,744 | 4,833 | -3,089 (**-64%**) |
| P3-B 6,608 (today's policy) | 3,328 | 6,417 | -3,089 (**-48%**) |
| P3-B 5,888 (b=0 policy) | 4,048 | 7,137 | -3,089 (**-43%**) |

The absolute cut is invariant (3,089 lane-ops) -- but the charter's "-64%"
is measured against a pool that was 1,584 lane-ops too small, and ~576-1,296
of the cut is now known to be available **on the index axis itself**, which
the charter listed as at-floor. The design-floor line should read:

* `(46,464 + 6,608)/60 = 884.5 cycles` at today's serving policy, or
* `(46,464 + 5,888)/60 = 872.5 cycles` if the epoch-2 L4 gathers go away,

not 911. That is 26-38 cycles of headroom the charter had written off.

## 7. Dead ends explored (all negative, all costed)

* fold the recurrence into a hash madd -- G-21, re-confirmed by Lemma 1.
* any affine rebias of the carried state -- Lemma 3, all +1,280 lane-ops.
* redundant/two-word state -- always one extra maintenance op.
* pack the L4 base address through the existing tournament select tree
  instead of Horner madds: 15 vselects per group-round x 32 = 480 flow
  slots vs 143 slots of flow headroom at 940. Refuted.
* memory-table advance and any "second load per lane" scheme: the load
  engine is the one engine already over the 940 budget (1,892 vs 1,880).

## 9. CROSS-AXIS: can the `omf` constant-select be eliminated? (answers P3-A C9)

**VERDICT: IMPOSSIBLE to eliminate for free; every alternative representation
is WEAKLY DOMINATED by the shipped spelling, with an EXACT TIE at P3-A's
saturated optimum. The achievable floor stays 939. C9 (920) is not a valid
design.** Tool: `python3 tools/p3b_omf.py` (imports `tools/p3a_model.py`
unmodified).

### Lemma 1, strengthened to all 2^32 constants (was: 502 sampled)

For each opcode the "output depends on val only through bit0" condition is
decidable in closed form, so the sampled search of section 2 is exhaustive:

| op | parity-only iff | output as a function of p |
|---|---|---|
| `val & k` | `k & ~1 == 0`, i.e. k in {0,1} | `p` |
| `val \| k` | `~k & ~1 == 0`, i.e. k in {0xFFFFFFFE, 0xFFFFFFFF} | `p - 2` |
| `val * k` | `2k = 0 mod 2^32`, i.e. k in {0, 2^31} | `p * 2^31` |
| `val << k` | `k >= 31` | `p * 2^31` (k=31), else 0 |
| `val % k` | `k == 2` | `p` |
| `^ + - // >> < ==`, and any form with val as the *right* operand of a shift/div/mod | never (bit1 of val survives, or the result is magnitude-driven) | -- |

**Theorem (one-op addend set).** The complete set of values a single ISA op
can produce from `val` while depending on it only through parity is
`{p + c : c in {0, -2}}` union `{p * 2^31}`. **The parity always enters with
coefficient +1** -- no op yields `-p`, so complement/negated representations
are closed too.

### Consequence for the addend

Carrying `S = idx + b` gives `S' = 2S + (1 - b + p)`, so the addend is
`p + (1-b)`. It is a one-op parity form only for `b = 1` (addend `p`) or
`b = 3` (addend `p - 2`, the `val | 0xFFFFFFFE` form). The load needs
`mem[scratch[addr]]` with **no displacement** (problem.py:294-303), so the
scratch word read must equal `idx + 7` exactly: `b = 7`, whose addend is
`p - 6`, and `-6 not in {0, -2}`. **The three constraints -- one-op addend,
exact loadability, and `forest_values_p == 7` -- are jointly unsatisfiable.**

### Per-level re-bias (P3-A's explicit question)

Let `b_d` vary by level (`level(r) = r mod 11` is compile-time). Then
`addend = p + (1 - 2*b_d + b_{d+1})`, free iff `b_{d+1} = 2*b_d - 1` or
`2*b_d - 3`. But every gathered level pins `b_d = 7`, forcing
`b_{d+1} = 13 or 11`, neither of which is 7. Levels 5..10 gather
consecutively, so all five 5->6..9->10 transitions are pinned.
**Per-level re-bias buys nothing.** The one boundary where `b` IS free --
entering a gathered level from a served one -- is already exploited: that is
the Horner exit, and it needs no `omf` select of its own... except that the
residual constant there is +38 (= 7 + 31), and the free per-stage injections
are only 0 or -2 (contributions -32,-16,-8,-4,-2, all non-positive), so the
Horner exit **also** pays exactly one "parity + constant" fungible op.
**P3-A's count of `idx_selects = g = 227` is therefore correct, not an
over-count** -- I tried to shave it and failed.

### The corrected trade (this is where P3-A's model goes wrong)

The `omf` op is not special: it is a two-way choice between two live
vectors, so by P3-A's own T1 it is **fungible** -- 1 flow slot, or 1 valu
`madd(par, one_vec, omf_vec)` = 8 lane-ops. "Eliminating" it via `S = idx+3`
does not delete an op; it **replaces one FLOW-ELIGIBLE op with one
VALU-ONLY op** (`A = S + 4`; flow cannot add -- `vselect` only chooses
between live vectors and `add_imm` is scalar, problem.py:328-333).

Dominance, for any design and any C. With `rem` = flow slots left after the
interior selects and `L` = leaf selects:

```
shipped   valu cost from the save-1 pool = max(0, L + g - rem)
S = idx+3 valu cost                      = g + max(0, L - rem)
L >= rem : both = L + g - rem                      EXACT TIE
L <  rem : shipped = max(0, L+g-rem) <= g          shipped STRICTLY WINS
```

At P3-A's optimum (`s=221`, `g=227`, `L=680`, `inter=459`, `SETUP_FLOW=2`,
C=940): `rem = 479 < L`, so it is the tie case, and the two censuses are
**bit-identical**:

| design | alu+valu | load | flow | floors |
|---|---|---|---|---|
| C1* (omf on flow) | 56,272 | 1,880 | 940 | 937.9 / 940.0 / 940.0 |
| C9' (omf "eliminated", true cost) | **56,272** | **1,880** | **940** | **937.9 / 940.0 / 940.0** |

and at C=920 both give 56,432 lane-ops (needs 55,200) and 1,880 loads
(needs 1,840) -- **920 fails on two engines**, and buying the load slack
requires serving 5 more L4 group-rounds = +75 folds, which loses.

**So the coordinator's break-even intuition is right in arithmetic and wrong
in sign of conclusion: it is break-even, therefore not a win.** The 1,816
lane-ops freed on the fold side are exactly the 1,816 lane-ops spent on
address recovery. The reason it feels like a win is that the same 1,816
lane-ops can be spent WITHOUT changing the representation at all -- just
spell 227 `omf` selects as valu madds -- so the representation change is
doing no work.

### Practical consequence

The floor is **939**, realizing ~950-960 by P3-A's own regret caveat. There
is no 920 design on this axis. If more margin is needed it must come from
somewhere that removes COMPUTE, not from re-spelling the index recurrence.

## 10. What I did not do

* did not model the tournament/serving work that C7 would have to add
  (P3-A / P3-C boundary);
* did not attempt an implementation of anything (Phase 3 is theory-only);
* the ">= 4 madds to pack 5 loose bits" step is an argument from operand
  arity (each madd merges 2 runtime vectors), not a machine-checked
  enumeration -- it is the one soft joint in the floor. If a 3-op packing
  exists the floor drops another 32 vec-ops = 256 lane-ops.
