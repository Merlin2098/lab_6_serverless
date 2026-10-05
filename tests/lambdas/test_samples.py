from __future__ import annotations

import csv
import io
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from src.lambdas.validator.app import validate_csv

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
REQUIRED = ("order_id", "customer_id", "amount", "status")
VALID_FILES = [
    ("orders_2026_10_04.csv", 3),
    ("orders_2026_10_05.csv", 2),
    ("orders_2026_10_06.csv", 2),
]


def read(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(("name", "records"), VALID_FILES)
def test_valid_samples_pass_validation(name: str, records: int) -> None:
    result = validate_csv(f"raw/{name}", read(name), REQUIRED)
    assert result.valid is True
    assert result.records == records


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("orders_invalid.csv", "invalid_amount: row 1"),
        ("prueba_invalida.csv", "missing_columns: amount"),
        ("prueba.csv", "empty_file"),
    ],
)
def test_invalid_samples_are_rejected(name: str, reason: str) -> None:
    assert validate_csv(f"raw/{name}", read(name), REQUIRED).reason == reason


def test_json_sample_is_rejected_by_extension() -> None:
    result = validate_csv("raw/prueba.json", read("prueba.json"), REQUIRED)
    assert result.reason == "invalid_extension"


def test_valid_samples_add_up_to_the_expected_athena_result() -> None:
    totals: dict[str, list] = defaultdict(lambda: [0, Decimal("0")])
    for name, _ in VALID_FILES:
        for row in csv.DictReader(io.StringIO(read(name))):
            totals[row["status"]][0] += 1
            totals[row["status"]][1] += Decimal(row["amount"])

    assert {status: tuple(values) for status, values in totals.items()} == {
        "COMPLETED": (6, Decimal("1290.75")),
        "CANCELLED": (1, Decimal("99.90")),
    }
