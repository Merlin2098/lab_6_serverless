from __future__ import annotations

import codecs
from decimal import Decimal
from pathlib import Path

from scripts.check_deployed_pipeline import (
    SAMPLES,
    Report,
    build_cases,
    compare_totals,
    crawler_started,
    rows_to_totals,
)

RUN = "abc123"
BOM = codecs.BOM_UTF8


def by_key(cases):
    return {case.key: case for case in cases}


# --- cases ------------------------------------------------------------------


def test_the_three_valid_samples_must_succeed_and_land_in_processed() -> None:
    cases = by_key(build_cases(RUN))
    for name in (
        "orders_2026_10_04.csv",
        "orders_2026_10_05.csv",
        "orders_2026_10_06.csv",
    ):
        case = cases[f"raw/{name}"]
        assert case.expect == "succeeded"
        assert case.output_key == f"processed/orders/{name}"
        assert (
            case.cleanup is False
        )  # these rows are part of the expected Athena result


def test_files_that_must_not_trigger_the_pipeline() -> None:
    cases = by_key(build_cases(RUN))
    assert cases[f"raw/e2e_{RUN}_prueba.json"].expect == "none"
    assert cases[f"otra/e2e_{RUN}_prueba.csv"].expect == "none"
    # The rule is case-sensitive (spec fixes raw/*.csv).
    assert cases[f"raw/e2e_{RUN}_UPPER.CSV"].expect == "none"


def test_invalid_files_must_fail_validation_and_write_nothing() -> None:
    cases = by_key(build_cases(RUN))
    for name in ("orders_invalid", "prueba_invalida", "prueba"):
        case = cases[f"raw/e2e_{RUN}_{name}.csv"]
        assert case.expect == "invalid"
        assert case.output_key is None


def test_key_with_spaces_checks_the_eventbridge_key_encoding() -> None:
    case = by_key(build_cases(RUN))[f"raw/e2e_{RUN}_with space.csv"]
    assert case.expect == "succeeded"
    assert case.output_key == f"processed/orders/e2e_{RUN}_with space.csv"


def test_bom_case_uploads_a_real_bom_and_expects_a_clean_output() -> None:
    case = by_key(build_cases(RUN))[f"raw/e2e_{RUN}_bom.csv"]
    assert case.body().startswith(BOM)
    assert case.expect == "succeeded"


def test_every_case_that_writes_output_under_a_test_key_is_cleaned_up() -> None:
    for case in build_cases(RUN):
        if case.key.startswith("raw/e2e_") and case.expect == "succeeded":
            assert case.cleanup is True, case.key


def test_test_keys_are_unique_per_run() -> None:
    first = {c.key for c in build_cases("run1") if "e2e_" in c.key}
    second = {c.key for c in build_cases("run2") if "e2e_" in c.key}
    assert first and first.isdisjoint(second)


def test_sources_come_from_the_sample_files() -> None:
    for case in build_cases(RUN):
        body = case.body()
        assert isinstance(body, bytes)
    assert (SAMPLES / "orders_2026_10_04.csv").is_file()
    assert Path(SAMPLES).name == "samples"


# --- athena totals ----------------------------------------------------------

ATHENA_ROWS = [
    ["status", "filas", "total"],
    ["COMPLETED", "6", "1290.75"],
    ["CANCELLED", "1", "99.9"],
]


def test_rows_to_totals_skips_the_header_and_parses_numbers() -> None:
    assert rows_to_totals(ATHENA_ROWS) == {
        "COMPLETED": (6, Decimal("1290.75")),
        "CANCELLED": (1, Decimal("99.90")),
    }


def test_compare_totals_accepts_the_expected_result() -> None:
    ok, detail = compare_totals(rows_to_totals(ATHENA_ROWS))
    assert ok is True, detail


def test_compare_totals_reports_what_differs() -> None:
    wrong = rows_to_totals(
        [["status", "filas", "total"], ["COMPLETED", "7", "1300.00"]]
    )
    ok, detail = compare_totals(wrong)
    assert ok is False
    assert "COMPLETED" in detail and "CANCELLED" in detail


# --- report -----------------------------------------------------------------


def test_report_fails_if_any_check_fails() -> None:
    report = Report()
    report.add("first", True)
    assert report.ok is True and report.exit_code == 0
    report.add("second", False, "boom")
    assert report.ok is False and report.exit_code == 1


def test_report_renders_every_check_with_its_detail() -> None:
    report = Report()
    report.add("alpha", True, "fine")
    report.add("beta", False, "broke")
    text = report.render()
    assert "PASS" in text and "alpha" in text and "fine" in text
    assert "FAIL" in text and "beta" in text and "broke" in text
    assert "1 passed, 1 failed" in text


def test_report_summary_is_a_single_line_without_repeating_the_checks() -> None:
    report = Report()
    report.add("alpha", True)
    report.add("beta", False, "broke")
    assert report.summary() == "1 passed, 1 failed"


# --- crawler started by the state machine -----------------------------------


def test_crawler_started_when_the_execution_output_carries_the_crawler_result() -> None:
    output = '{"detail": {}, "validation": {}, "crawler": {"SdkHttpMetadata": {}}}'
    assert crawler_started(output) is True


def test_crawler_not_started_without_the_crawler_key_or_output() -> None:
    assert crawler_started('{"detail": {}, "validation": {}}') is False
    assert crawler_started(None) is False
    assert crawler_started("not json") is False
