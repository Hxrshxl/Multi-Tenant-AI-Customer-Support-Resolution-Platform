#!/usr/bin/env python
"""Run every local quality check in one command.

    python scripts/check.py           # lint, format check, types, tests
    python scripts/check.py --fix     # auto-fix lint and formatting first

Cross-platform by design: this is the single entry point referenced by the
README and, later, by CI (KAN-61), so Windows and Linux run exactly the same
checks.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

PY = sys.executable


@dataclass(frozen=True)
class Check:
    name: str
    command: list[str]


CHECKS: list[Check] = [
    Check("ruff lint", [PY, "-m", "ruff", "check", "."]),
    Check("ruff format", [PY, "-m", "ruff", "format", "--check", "."]),
    Check("mypy", [PY, "-m", "mypy"]),
    Check("pytest", [PY, "-m", "pytest"]),
]

FIXES: list[Check] = [
    Check("ruff lint --fix", [PY, "-m", "ruff", "check", ".", "--fix"]),
    Check("ruff format", [PY, "-m", "ruff", "format", "."]),
]


def run(check: Check) -> bool:
    print(f"\n=== {check.name} ===", flush=True)
    return subprocess.run(check.command, check=False).returncode == 0


def main() -> int:
    if "--fix" in sys.argv:
        for fix in FIXES:
            run(fix)

    failed = [check.name for check in CHECKS if not run(check)]

    print("\n" + "=" * 40)
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
