from __future__ import annotations

import subprocess
import sys
from pathlib import Path


DEFAULT_TARGETS = ("src", "tests", "scripts")


def main(argv: list[str] | None = None) -> int:
    project_root = Path.cwd()
    args = list(argv or sys.argv[1:])

    if args:
        command = [sys.executable, "-m", "ruff", "format", *args]
    else:
        existing_targets = [
            target for target in DEFAULT_TARGETS if (project_root / target).exists()
        ]
        if not existing_targets:
            print("No Ruff targets found. Skipping format.")
            return 0
        command = [sys.executable, "-m", "ruff", "format", *existing_targets]

    result = subprocess.run(command, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
