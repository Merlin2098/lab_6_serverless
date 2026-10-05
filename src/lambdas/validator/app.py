"""Validator Lambda for the S6 serverless lab.

Receives the EventBridge "Object Created" event (forwarded as-is by Step
Functions), validates the CSV under raw/ and, if valid, writes it to
processed/orders/ under the SAME file name, so reprocessing a file never
duplicates data.

Validation problems are returned as {"valid": False, ...} (the Choice state
decides). Unexpected errors (e.g. AccessDenied on PutObject) are NOT caught on
purpose: they propagate so Step Functions' Catch stores them in $.error.

Keep this file self-contained: the container image copies only app.py.
"""

from __future__ import annotations

import codecs
import csv
import io
import logging
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from posixpath import basename

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_PROCESSED_PREFIX = "processed/orders/"
DEFAULT_REQUIRED_COLUMNS = "order_id,customer_id,amount,status"
# Derived from the UTF-8 bytes so no invisible character is ever written in the source.
BOM = codecs.BOM_UTF8.decode("utf-8")


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    records: int = 0
    reason: str | None = None


def _processed_prefix() -> str:
    return os.environ.get("PROCESSED_PREFIX", DEFAULT_PROCESSED_PREFIX)


def _required_columns() -> tuple[str, ...]:
    raw = os.environ.get("REQUIRED_COLUMNS", DEFAULT_REQUIRED_COLUMNS)
    return tuple(column.strip() for column in raw.split(",") if column.strip())


@lru_cache(maxsize=1)
def _s3():
    return boto3.client("s3")


def _invalid(reason: str) -> ValidationResult:
    return ValidationResult(valid=False, reason=reason)


def _is_numeric(value: str | None) -> bool:
    # Decimal also accepts "NaN", "Infinity" and "1_000"; Athena would not.
    if value is None or "_" in value:
        return False
    try:
        return Decimal(value.strip()).is_finite()
    except InvalidOperation:
        return False


def validate_csv(
    key: str, text: str, required_columns: tuple[str, ...]
) -> ValidationResult:
    """Pure validation (no I/O). First failing rule wins."""
    if not key.lower().endswith(".csv"):
        return _invalid("invalid_extension")
    text = text.lstrip(BOM)
    if not text.strip():
        return _invalid("empty_file")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    missing = [column for column in required_columns if column not in fieldnames]
    if missing:
        return _invalid("missing_columns: " + ", ".join(missing))

    rows = list(reader)
    if not rows:
        return _invalid("no_data_rows")
    for number, row in enumerate(rows, start=1):
        if not _is_numeric(row.get("amount")):
            return _invalid(f"invalid_amount: row {number}")
    return ValidationResult(valid=True, records=len(rows))


def handler(event: dict, context: object) -> dict:
    bucket = event["detail"]["bucket"]["name"]
    # EventBridge delivers the key as-is (S3 notifications URL-encode it; this does not).
    key = event["detail"]["object"]["key"]

    s3 = _s3()
    raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    try:
        text = raw.decode("utf-8-sig")  # also drops a leading BOM
    except UnicodeDecodeError:
        logger.info("s3://%s/%s is not valid UTF-8", bucket, key)
        return {"valid": False, "reason": "invalid_encoding"}

    result = validate_csv(key, text, _required_columns())
    if not result.valid:
        logger.info("s3://%s/%s rejected: %s", bucket, key, result.reason)
        return {"valid": False, "reason": result.reason}

    # debt: reads the whole file in memory; fine for small CSVs, revisit for
    # files of hundreds of MB (use streaming / Glue instead).
    output_key = _processed_prefix() + basename(key)
    s3.put_object(
        Bucket=bucket,
        Key=output_key,
        Body=text.encode(
            "utf-8"
        ),  # normalized: no BOM, so the Crawler reads clean headers
        ContentType="text/csv",
    )
    logger.info(
        "s3://%s/%s -> %s (%d records)", bucket, key, output_key, result.records
    )
    return {"valid": True, "records": result.records, "output": output_key}
