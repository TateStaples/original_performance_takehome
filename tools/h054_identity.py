"""H-054: programmatic default-off bit-identity check.

Builds the kernel with the CURRENT dev.py and with the pre-H-054 dev.py
(git blob at BASE_REV) and asserts the emitted bundle lists are equal
object-for-object, on both the mainline config and the H-047 frontier.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

BASE_REV = os.environ.get("H054_BASE_REV", "bd27795")  # pre-H-054 (F-15 port)


def load_base_dev():
    blob = subprocess.run(["git", "-C", REPO_ROOT, "show", f"{BASE_REV}:dev.py"],
                          capture_output=True, check=True).stdout
    tmp = tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False)
    tmp.write(blob)
    tmp.close()
    spec = importlib.util.spec_from_file_location("dev_base", tmp.name)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    import dev
    import h054_common as C
    from run_variant import BASE_KWARGS, SHAPE
    base = load_base_dev()
    configs = [("mainline BASE_KWARGS", dict(BASE_KWARGS)),
               ("H-047 frontier", C.frontier_kwargs())]
    ok = True
    for name, kw in configs:
        outs = []
        for mod in (dev, base):
            kb = mod.KernelBuilder()
            kb.build_kernel_scheduled(SHAPE["batch_size"], SHAPE["rounds"],
                                      SHAPE["forest_height"], **kw)
            outs.append(kb.instrs)
        same = outs[0] == outs[1]
        ok &= same
        print(f"{name}: cycles {len(outs[0])} vs {len(outs[1])}  "
              f"bit-identical={same}")
    print("IDENTITY", "OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
