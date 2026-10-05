from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_ruff_wrappers_smoke() -> None:
    check_result = subprocess.run(
        [
            sys.executable,
            "scripts/testing/run_ruff_check.py",
            "tests/lambdas/test_validator.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    format_result = subprocess.run(
        [
            sys.executable,
            "scripts/testing/run_ruff_format.py",
            "--check",
            "tests/lambdas/test_validator.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert check_result.returncode == 0, check_result.stderr
    assert format_result.returncode == 0, format_result.stderr


def test_pytest_wrapper_smoke() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/testing/run_pytest.py", "--version"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "pytest" in result.stdout.lower()


def test_pytest_wrapper_treats_no_tests_as_success(tmp_path: Path) -> None:
    _write(
        tmp_path / "requirements.txt",
        "",
    )

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/testing/run_pytest.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "No tests were collected" in result.stdout
