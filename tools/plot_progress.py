"""
Track and visualize kernel-optimization progress.

Cycle counts are never hand-typed: `--record` actually runs the real
grading path (KernelBuilder.build_kernel from perf_takehome.py against
tests/frozen_problem.py, exactly like tests/submission_tests.py does) and
records whatever it measures.

Usage (from the repo root):
    python tools/plot_progress.py
        Regenerate tools/progress.png from the existing log.

    python tools/plot_progress.py --record STEP LABEL NOTE
        Measure the *current* perf_takehome.py KernelBuilder against the
        real grading simulator, append a new entry to progress_log.json,
        and regenerate the PNG. Run this once per optimization step, after
        the step's own correctness tests already pass.

Requires matplotlib (pip install matplotlib) -- not otherwise a dependency
of this repo.
"""

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(TOOLS_DIR, "progress_log.json")
PNG_PATH = os.path.join(TOOLS_DIR, "progress.png")

# Benchmark thresholds from Readme.md / docs/problem.md, plotted as
# reference lines for context against past Claude models' scores.
REFERENCE_LINES = [
    (18532, "starter code (harder 2h take-home)"),
    (2164, "Opus 4, many hours"),
    (1790, "Opus 4.5, casual session"),
    (1579, "Opus 4.5, 2h harness"),
    (1548, "Sonnet 4.5, many hours"),
    (1487, "Opus 4.5, 11.5h harness"),
    (1363, "Opus 4.5, improved harness"),
]


def measure_cycles() -> int:
    """Actually run the real grading path -- KernelBuilder.build_kernel
    (perf_takehome.py) against the frozen simulator (tests/frozen_problem.py)
    -- and return the cycle count it measures. This is exactly what
    tests/submission_tests.py's SpeedTests check, just returned instead of
    asserted."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
    sys.path.insert(0, REPO_ROOT)
    import submission_tests

    return submission_tests.do_kernel_test(10, 16, 256)


def load_log():
    with open(LOG_PATH) as f:
        return json.load(f)


def save_log(entries):
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


def plot(entries):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    labels = [e["label"] for e in entries]
    cycles = [e["cycles"] for e in entries]

    fig, ax = plt.subplots(figsize=(max(9.0, 1.7 * len(entries) + 2), 6))
    colors = plt.cm.viridis_r([i / max(1, len(entries) - 1) for i in range(len(entries))])
    bars = ax.bar(range(len(entries)), cycles, color=colors, width=0.6, zorder=3)

    ax.set_yscale("log")
    ax.set_ylabel("cycles (log scale)")
    ax.set_xticks(range(len(entries)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_title(
        "perf_takehome kernel: cycles by optimization step\n"
        "measured against tests/frozen_problem.py "
        "(forest_height=10, rounds=16, batch_size=256)",
        fontsize=11,
    )
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.grid(axis="y", which="major", linestyle="-", alpha=0.25, zorder=0)
    ax.grid(axis="y", which="minor", linestyle=":", alpha=0.15, zorder=0)

    for rect, c in zip(bars, cycles):
        ax.annotate(
            f"{c:,}",
            (rect.get_x() + rect.get_width() / 2, rect.get_height()),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            fontweight="bold",
        )

    y_top = max(cycles) * 1.6
    for y, ref_label in REFERENCE_LINES:
        if y < y_top:
            ax.axhline(y, color="gray", linestyle="--", linewidth=0.8, alpha=0.6, zorder=1)
            ax.annotate(
                ref_label,
                (len(entries) - 0.45, y),
                fontsize=7,
                color="gray",
                va="bottom",
                ha="right",
            )
    ax.set_ylim(top=y_top)

    fig.tight_layout()
    fig.savefig(PNG_PATH, dpi=150)
    print(f"wrote {PNG_PATH}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--record",
        nargs=3,
        metavar=("STEP", "LABEL", "NOTE"),
        help="measure the current KernelBuilder against the real grader, append, and regenerate the PNG",
    )
    args = ap.parse_args()

    entries = load_log()

    if args.record:
        step, label, note = args.record
        # Shells vary on whether a quoted "\n" in an argument stays literal
        # backslash-n or becomes a real newline; normalize so the label
        # always renders as a line break in the chart either way.
        label = label.replace("\\n", "\n")
        cycles = measure_cycles()
        entries.append({"step": step, "label": label, "cycles": cycles, "note": note})
        save_log(entries)
        print(f"recorded {step!r}: {cycles:,} cycles")

    for e in entries:
        speedup = entries[0]["cycles"] / e["cycles"]
        print(f"  {e['step']:<24} {e['cycles']:>8,} cycles   ({speedup:5.2f}x vs baseline)")

    plot(entries)


if __name__ == "__main__":
    main()
