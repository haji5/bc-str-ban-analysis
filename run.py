"""Cross-platform task runner mirroring the Makefile (for machines without GNU make).

    python run.py all            # data -> sql -> model -> plots -> test
    python run.py data --offline # never touch the network
"""
from __future__ import annotations

import os
import subprocess
import sys

TARGETS = {
    "data": [["-m", "src.ingest"]],
    "sql": [["-m", "src.database"]],
    "model": [["-m", "src.models"], ["-m", "src.plots"]],
    "plots": [["-m", "src.plots"]],
    "test": [["-m", "pytest"]],
    "app": [["-m", "streamlit", "run", "app/app.py"]],
    "app-data": [["-m", "src.database", "--export-app"]],
    "site": [["scripts/export_dashboard.py"]],
}
TARGETS["all"] = TARGETS["data"] + TARGETS["sql"] + TARGETS["model"] + TARGETS["test"]


def main() -> int:
    args = sys.argv[1:] or ["all"]
    if "--offline" in args:
        os.environ["STR_OFFLINE"] = "1"
        args.remove("--offline")
    for target in args:
        if target == "install":
            steps = [["-m", "pip", "install", "-e", ".[dev]"]]
        elif target not in TARGETS:
            print(f"unknown target {target!r}; choose from install, {', '.join(TARGETS)}")
            return 2
        else:
            steps = TARGETS[target]
        for step in steps:
            print(f"\n==> [{target}] python {' '.join(step)}", flush=True)
            rc = subprocess.call([sys.executable, *step])
            if rc:
                return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
