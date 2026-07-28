"""H-059: run the shared ring audit (tools/audit_ring_windows.py) against a
plan artifact's SHIPPED literals.

audit_ring_windows takes --set overrides on the command line, which cannot
carry a full emission_plan; this feeds it the artifact's config
programmatically instead.  The audit itself is imported and called, never
modified.

Usage: python3 tools/h059_audit.py tools/h059_best_plan_1045.json
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import audit_ring_windows as AU  # noqa: E402
import f37_lib as F  # noqa: E402


def main() -> None:
    path = sys.argv[1]
    order, mix = F.load_point(path)
    # audit_ring_windows.CONFIG is its pinned baseline; replace it with the
    # artifact's own mix so the audit sees the SHIPPED literals.
    AU.CONFIG = dict(mix, emission_plan=order, lazy_val_loads=True,
                     debug_compares=False)
    sys.argv = [sys.argv[0]]
    AU.main()


if __name__ == "__main__":
    main()
