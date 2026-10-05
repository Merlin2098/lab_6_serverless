from __future__ import annotations

import codecs
import csv
import io
import random
import re
from datetime import date
from pathlib import Path

import pytest

from scripts.generate_orders import (
    COLUMNS,
    FAULTS,
    SAMPLES_DIR,
    build_rows,
    generate,
    main,
    render_csv,
    render_invalid_csv,
    taken_file_names,
    used_order_ids,
)
from src.lambdas.validator.app import validate_csv

REQUIRED = tuple(COLUMNS)
# orders_<date>_<6 hex>.csv  (the invalid one ends in _invalid)
NAME = re.compile(r"orders_(\d{4}_\d{2}_\d{2})_([0-9a-f]{6})(_invalid)?\.csv")


def dates(paths: list[Path]) -> list[str]:
    matches = [NAME.fullmatch(p.name) for p in paths]
    assert all(matches), [p.name for p in paths]
    return [m.group(1) for m in matches]


# Derived from the UTF-8 bytes so no invisible character is written in the source.
BOM = codecs.BOM_UTF8.decode("utf-8")


def parse(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


# --- rows -------------------------------------------------------------------


def test_columns_match_the_contract_and_the_lambda_default() -> None:
    assert COLUMNS == ("order_id", "customer_id", "amount", "status")


def test_build_rows_returns_the_requested_count_with_consecutive_ids() -> None:
    rows = build_rows(random.Random(1), count=5, first_order_id=3001)
    assert [r["order_id"] for r in rows] == [3001, 3002, 3003, 3004, 3005]


def test_build_rows_values_follow_the_contract() -> None:
    for row in build_rows(random.Random(2), count=200, first_order_id=1):
        assert row["customer_id"].startswith("C") and len(row["customer_id"]) == 4
        assert row["status"] in {"COMPLETED", "CANCELLED"}
        assert 5 <= row["amount"] <= 500
        assert row["amount"].as_tuple().exponent == -2  # two decimals


def test_same_seed_gives_the_same_rows() -> None:
    first = build_rows(random.Random(7), count=20, first_order_id=1)
    second = build_rows(random.Random(7), count=20, first_order_id=1)
    assert first == second


# --- valid csv --------------------------------------------------------------


def test_render_csv_has_header_lf_endings_and_no_bom() -> None:
    text = render_csv(build_rows(random.Random(3), count=2, first_order_id=1))
    assert text.splitlines()[0] == "order_id,customer_id,amount,status"
    assert "\r" not in text and text.endswith("\n")
    assert not text.startswith(BOM)


def test_a_generated_valid_csv_passes_the_lambda_validation() -> None:
    text = render_csv(build_rows(random.Random(4), count=15, first_order_id=1))
    result = validate_csv("raw/orders_2026_10_07.csv", text, REQUIRED)
    assert result.valid is True and result.records == 15


# --- invalid csv ------------------------------------------------------------


@pytest.mark.parametrize(
    ("fault", "reason"),
    [
        ("amount", "invalid_amount"),
        ("missing-column", "missing_columns"),
        ("empty", "empty_file"),
        ("no-rows", "no_data_rows"),
    ],
)
def test_each_fault_is_rejected_by_the_lambda_for_that_reason(
    fault: str, reason: str
) -> None:
    rows = build_rows(random.Random(5), count=4, first_order_id=1)
    text = render_invalid_csv(fault, rows)
    result = validate_csv("raw/orders_2026_10_07_invalid.csv", text, REQUIRED)
    assert result.valid is False
    assert result.reason is not None and result.reason.startswith(reason)


def test_there_is_a_test_for_every_fault() -> None:
    assert set(FAULTS) == {"amount", "missing-column", "empty", "no-rows"}


def test_unknown_fault_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown fault"):
        render_invalid_csv("nope", [])


# --- files ------------------------------------------------------------------


def test_generate_writes_one_file_per_consecutive_day(tmp_path: Path) -> None:
    paths = generate(
        tmp_path,
        files=3,
        rows=4,
        start=date(2026, 10, 7),
        seed=1,
        first_order_id=3001,
        avoid=(),
    )
    assert dates(paths) == ["2026_10_07", "2026_10_08", "2026_10_09"]
    assert len({p.name for p in paths}) == 3
    ids = [r["order_id"] for p in paths for r in parse(p.read_text(encoding="utf-8"))]
    assert ids == [str(n) for n in range(3001, 3013)]  # unique across files


def test_generate_with_a_fault_adds_one_extra_invalid_file(tmp_path: Path) -> None:
    paths = generate(
        tmp_path,
        files=2,
        rows=3,
        start=date(2026, 10, 7),
        seed=1,
        first_order_id=1,
        avoid=(),
        invalid="amount",
    )
    assert dates(paths) == ["2026_10_07", "2026_10_08", "2026_10_09"]
    assert paths[-1].name.endswith("_invalid.csv")
    assert not any(p.name.endswith("_invalid.csv") for p in paths[:-1])
    bad = validate_csv(
        f"raw/{paths[-1].name}", paths[-1].read_text(encoding="utf-8"), REQUIRED
    )
    assert bad.valid is False


def test_generate_creates_the_output_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out"
    generate(
        target,
        files=1,
        rows=1,
        start=date(2026, 10, 7),
        seed=1,
        first_order_id=1,
        avoid=(),
    )
    assert len(list(target.glob("orders_2026_10_07_*.csv"))) == 1


def test_generate_with_a_seed_is_reproducible(tmp_path: Path) -> None:
    kwargs = dict(
        files=1, rows=10, start=date(2026, 10, 7), seed=42, first_order_id=1, avoid=()
    )
    a = generate(tmp_path / "a", **kwargs)[0].read_bytes()
    b = generate(tmp_path / "b", **kwargs)[0].read_bytes()
    assert a == b


# --- cli --------------------------------------------------------------------


def test_main_writes_files_and_prints_the_upload_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["--out", str(tmp_path), "--rows", "3", "--date", "2026-10-07", "--seed", "1"]
    )
    out = capsys.readouterr().out
    assert code == 0
    (written,) = tmp_path.glob("orders_2026_10_07_*.csv")
    assert "make upload FILE=" in out and written.name in out


@pytest.mark.parametrize(
    "argv",
    [["--rows", "0"], ["--files", "0"], ["--date", "07/10/2026"], ["--invalid", "x"]],
)
def test_main_rejects_bad_arguments(argv: list[str], tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--out", str(tmp_path), *argv])
    assert exc.value.code == 2


# --- no collision with the samples -----------------------------------------


def write_sample(folder: Path, name: str, ids: list[int]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{n},C001,10.00,COMPLETED\n" for n in ids)
    (folder / name).write_text("order_id,customer_id,amount,status\n" + body)


def test_used_order_ids_and_file_names_are_read_from_the_folders(
    tmp_path: Path,
) -> None:
    write_sample(tmp_path, "orders_2026_10_04.csv", [1001, 1002])
    write_sample(tmp_path, "orders_invalid.csv", [2001])
    (tmp_path / "prueba.csv").write_text("")  # empty file: ignored, no crash
    assert used_order_ids(tmp_path, tmp_path / "missing") == {1001, 1002, 2001}
    assert "orders_2026_10_04.csv" in taken_file_names(tmp_path)


def test_the_real_samples_are_what_the_default_avoids() -> None:
    assert SAMPLES_DIR.name == "samples" and SAMPLES_DIR.is_dir()
    assert {1001, 2001} <= used_order_ids(SAMPLES_DIR)


def test_a_generated_name_is_never_a_sample_name_even_on_the_same_date(
    tmp_path: Path,
) -> None:
    samples = tmp_path / "samples"
    write_sample(samples, "orders_2026_10_04.csv", [1001])
    paths = generate(
        tmp_path / "out",
        files=1,
        rows=2,
        start=date(2026, 10, 4),
        seed=1,
        first_order_id=None,
        avoid=(samples,),
    )
    assert paths[0].name != "orders_2026_10_04.csv"
    assert dates(paths) == ["2026_10_04"]


def test_two_runs_on_the_same_date_write_different_files(tmp_path: Path) -> None:
    # Same seed on purpose: even then the names must differ (no overwrite in S3).
    kwargs = dict(
        files=1,
        rows=2,
        start=date(2026, 10, 7),
        seed=1,
        first_order_id=None,
        avoid=(),
    )
    first = generate(tmp_path, **kwargs)
    second = generate(tmp_path, **kwargs)
    assert first[0].name != second[0].name
    assert len(list(tmp_path.glob("*.csv"))) == 2


def test_unseeded_runs_get_different_suffixes(tmp_path: Path) -> None:
    names = {
        generate(
            tmp_path / str(n),
            files=1,
            rows=1,
            start=date(2026, 10, 7),
            seed=None,
            first_order_id=1,
            avoid=(),
        )[0].name
        for n in range(8)
    }
    assert len(names) == 8


def test_new_order_ids_start_above_every_existing_one(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    write_sample(samples, "orders_2026_10_04.csv", [1001, 7000])
    paths = generate(
        tmp_path / "out",
        files=1,
        rows=3,
        start=date(2026, 10, 7),
        seed=1,
        first_order_id=None,
        avoid=(samples,),
        clock=lambda: 1.0,  # 1000 ms: below the ids in use, so the bump decides
    )
    ids = [int(r["order_id"]) for r in parse(paths[0].read_text(encoding="utf-8"))]
    assert ids == [7001, 7002, 7003]


def test_default_first_id_comes_from_the_clock_in_milliseconds(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    write_sample(samples, "orders_2026_10_04.csv", [1001])
    paths = generate(
        tmp_path / "out",
        files=1,
        rows=1,
        start=date(2026, 10, 7),
        seed=1,
        first_order_id=None,
        avoid=(samples,),
        clock=lambda: 1_790_000_000.123,
    )
    assert parse(paths[0].read_text(encoding="utf-8"))[0]["order_id"] == "1790000000123"


def test_ids_from_different_moments_never_overlap_even_without_local_files(
    tmp_path: Path,
) -> None:
    # Fresh folders each time (as if data/generated/ had been deleted): the clock
    # alone keeps ids apart, as long as runs are more than `rows` ms apart.
    def ids_at(moment: float, folder: str) -> set[int]:
        (path,) = generate(
            tmp_path / folder,
            files=1,
            rows=50,
            start=date(2026, 10, 7),
            seed=1,
            first_order_id=None,
            avoid=(),
            clock=lambda: moment,
        )
        return {int(r["order_id"]) for r in parse(path.read_text(encoding="utf-8"))}

    assert ids_at(1_790_000_000.0, "a").isdisjoint(ids_at(1_790_000_005.0, "b"))


def test_the_clock_start_is_still_bumped_above_ids_already_in_data(
    tmp_path: Path,
) -> None:
    samples = tmp_path / "samples"
    write_sample(samples, "orders_2026_10_04.csv", [9_999_999_999_999])
    (path,) = generate(
        tmp_path / "out",
        files=1,
        rows=1,
        start=date(2026, 10, 7),
        seed=1,
        first_order_id=None,
        avoid=(samples,),
        clock=lambda: 1.0,
    )
    assert parse(path.read_text(encoding="utf-8"))[0]["order_id"] == "10000000000000"


def test_running_twice_never_overwrites_nor_repeats_ids(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    write_sample(samples, "orders_2026_10_04.csv", [1001])
    kwargs = dict(
        files=1,
        rows=3,
        start=date(2026, 10, 7),
        seed=1,
        first_order_id=None,
        avoid=(samples,),
    )
    first = generate(tmp_path / "out", **kwargs)
    second = generate(tmp_path / "out", **kwargs)
    assert first[0] != second[0]
    ids = [
        r["order_id"]
        for p in (*first, *second)
        for r in parse(p.read_text(encoding="utf-8"))
    ]
    assert len(ids) == len(set(ids)) == 6


def test_an_explicit_order_id_that_collides_is_refused(tmp_path: Path) -> None:
    samples = tmp_path / "samples"
    write_sample(samples, "orders_2026_10_04.csv", [1001, 1002])
    with pytest.raises(ValueError, match="already used"):
        generate(
            tmp_path / "out",
            files=1,
            rows=1,
            start=date(2026, 10, 7),
            seed=1,
            first_order_id=1002,
            avoid=(samples,),
        )


def test_main_defaults_never_reuse_a_sample_name_or_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Start on the date of an existing sample: it must move to the next free day.
    assert main(["--out", str(tmp_path), "--date", "2026-10-04", "--seed", "1"]) == 0
    capsys.readouterr()
    (written,) = tmp_path.glob("*.csv")
    assert written.name not in taken_file_names(SAMPLES_DIR)
    new_ids = used_order_ids(tmp_path)
    assert new_ids and new_ids.isdisjoint(used_order_ids(SAMPLES_DIR))
