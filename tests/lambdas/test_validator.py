from __future__ import annotations

import codecs
import io

import pytest
from botocore.exceptions import ClientError

from src.lambdas.validator import app
from src.lambdas.validator.app import ValidationResult, validate_csv

REQUIRED = ("order_id", "customer_id", "amount", "status")
HEADER = "order_id,customer_id,amount,status\n"
VALID = HEADER + "1001,C001,150.50,COMPLETED\n1002,C002,320.00,COMPLETED\n"


def check(key: str, text: str) -> ValidationResult:
    return validate_csv(key, text, REQUIRED)


# --- validate_csv -----------------------------------------------------------


def test_valid_file_counts_records() -> None:
    assert check("raw/orders.csv", VALID) == ValidationResult(valid=True, records=2)


def test_extension_check_is_case_insensitive() -> None:
    assert check("raw/ORDERS.CSV", VALID).valid is True


def test_rejects_non_csv_extension() -> None:
    result = check("raw/prueba.json", VALID)
    assert result == ValidationResult(valid=False, reason="invalid_extension")


@pytest.mark.parametrize("text", ["", "   \n\n"])
def test_rejects_empty_file(text: str) -> None:
    assert check("raw/a.csv", text).reason == "empty_file"


def test_rejects_header_only_file() -> None:
    # Review focus 3: only a header, no data rows.
    result = check("raw/a.csv", HEADER)
    assert result == ValidationResult(valid=False, reason="no_data_rows")


def test_rejects_missing_column() -> None:
    text = "order_id,customer_id,status\n3001,C200,COMPLETED\n"
    assert check("raw/a.csv", text).reason == "missing_columns: amount"


def test_rejects_non_numeric_amount_reporting_the_row() -> None:
    text = HEADER + "1001,C001,150.50,COMPLETED\n1002,C002,abc,COMPLETED\n"
    assert check("raw/a.csv", text).reason == "invalid_amount: row 2"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", "inf", "1_000", ""])
def test_rejects_amounts_decimal_accepts_but_athena_would_not(amount: str) -> None:
    # Review focus 5.
    text = HEADER + f"1001,C001,{amount},COMPLETED\n"
    assert check("raw/a.csv", text).reason == "invalid_amount: row 1"


def test_rejects_short_row_without_raising() -> None:
    # Review focus 4: fewer fields than the header.
    text = HEADER + "1001,C001\n"
    assert check("raw/a.csv", text).reason == "invalid_amount: row 1"


def test_accepts_amount_with_surrounding_spaces_and_negative_values() -> None:
    text = HEADER + "1001,C001, 10.5 ,COMPLETED\n1002,C002,-3,CANCELLED\n"
    assert check("raw/a.csv", text).valid is True


def test_accepts_text_that_still_carries_a_bom() -> None:
    # Review focus 1 (validation side).
    assert check("raw/a.csv", codecs.BOM_UTF8.decode("utf-8") + VALID).valid is True


# --- handler ----------------------------------------------------------------


class FakeS3:
    def __init__(self, objects: dict[str, bytes], put_error: Exception | None = None):
        self.objects = objects
        self.put_error = put_error
        self.puts: list[dict] = []

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, **kwargs) -> None:
        if self.put_error:
            raise self.put_error
        self.puts.append(kwargs)


def event(key: str, bucket: str = "lab-bucket") -> dict:
    return {"detail": {"bucket": {"name": bucket}, "object": {"key": key}}}


def install(monkeypatch: pytest.MonkeyPatch, fake: FakeS3) -> FakeS3:
    monkeypatch.setattr(app, "_s3", lambda: fake)
    return fake


def test_handler_writes_valid_file_with_the_same_name(monkeypatch) -> None:
    fake = install(monkeypatch, FakeS3({"raw/orders_2026_10_04.csv": VALID.encode()}))

    response = app.handler(event("raw/orders_2026_10_04.csv"), None)

    assert response == {
        "valid": True,
        "records": 2,
        "output": "processed/orders/orders_2026_10_04.csv",
    }
    assert len(fake.puts) == 1
    assert fake.puts[0]["Bucket"] == "lab-bucket"
    assert fake.puts[0]["Key"] == "processed/orders/orders_2026_10_04.csv"
    assert fake.puts[0]["Body"] == VALID.encode()


def test_handler_does_not_write_invalid_file(monkeypatch) -> None:
    fake = install(
        monkeypatch, FakeS3({"raw/bad.csv": (HEADER + "1,C,abc,X\n").encode()})
    )

    response = app.handler(event("raw/bad.csv"), None)

    assert response == {"valid": False, "reason": "invalid_amount: row 1"}
    assert fake.puts == []


def test_handler_flattens_nested_keys_to_the_base_name(monkeypatch) -> None:
    fake = install(monkeypatch, FakeS3({"raw/2026/10/a.csv": VALID.encode()}))

    response = app.handler(event("raw/2026/10/a.csv"), None)

    assert response["output"] == "processed/orders/a.csv"
    assert fake.puts[0]["Key"] == "processed/orders/a.csv"


def test_handler_keeps_spaces_and_special_characters_in_the_key(monkeypatch) -> None:
    # Review focus 2: EventBridge delivers the key without URL-encoding.
    key = "raw/orders 2026 10 (1).csv"
    fake = install(monkeypatch, FakeS3({key: VALID.encode()}))

    response = app.handler(event(key), None)

    assert response["output"] == "processed/orders/orders 2026 10 (1).csv"
    assert fake.puts[0]["Key"] == "processed/orders/orders 2026 10 (1).csv"


def test_handler_strips_the_bom_from_the_output(monkeypatch) -> None:
    # Review focus 1 (output side): a BOM would rename the first column.
    fake = install(monkeypatch, FakeS3({"raw/a.csv": b"\xef\xbb\xbf" + VALID.encode()}))

    response = app.handler(event("raw/a.csv"), None)

    assert response["valid"] is True
    assert fake.puts[0]["Body"] == VALID.encode()


def test_handler_rejects_files_that_are_not_utf8(monkeypatch) -> None:
    fake = install(monkeypatch, FakeS3({"raw/a.csv": b"\xff\xfe\x00\x01"}))

    response = app.handler(event("raw/a.csv"), None)

    assert response == {"valid": False, "reason": "invalid_encoding"}
    assert fake.puts == []


def test_handler_propagates_unexpected_errors_so_step_functions_can_catch_them(
    monkeypatch,
) -> None:
    denied = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "PutObject"
    )
    install(monkeypatch, FakeS3({"raw/a.csv": VALID.encode()}, put_error=denied))

    with pytest.raises(ClientError):
        app.handler(event("raw/a.csv"), None)


def test_handler_reads_configuration_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("PROCESSED_PREFIX", "out/")
    monkeypatch.setenv("REQUIRED_COLUMNS", "order_id,amount")
    text = "order_id,amount\n1,10.0\n"
    fake = install(monkeypatch, FakeS3({"raw/a.csv": text.encode()}))

    response = app.handler(event("raw/a.csv"), None)

    assert response == {"valid": True, "records": 1, "output": "out/a.csv"}
    assert fake.puts[0]["Key"] == "out/a.csv"
