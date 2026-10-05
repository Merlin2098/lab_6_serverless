from __future__ import annotations

import json
from pathlib import Path

from src.lambdas.validator.app import DEFAULT_REQUIRED_COLUMNS

CONTRACT = (
    Path(__file__).resolve().parents[2] / "src" / "contracts" / "orders_contract.json"
)


def load_contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_contract_columns_match_the_validator_required_columns() -> None:
    columns = [column["name"] for column in load_contract()["columns"]]
    assert columns == DEFAULT_REQUIRED_COLUMNS.split(",")


def test_contract_describes_the_lab_dataset() -> None:
    contract = load_contract()
    assert contract["dataset"] == "s6_lab_db.orders"
    assert contract["primary_key"] == ["order_id"]


def test_contract_columns_are_not_nullable() -> None:
    # The validator rejects empty values in amount and requires every column.
    assert all(column["nullable"] is False for column in load_contract()["columns"])
