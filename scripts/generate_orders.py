"""Generate order CSV files to feed the lab pipeline.

Valid files follow the contract in src/contracts/orders_contract.json
(order_id, customer_id, amount, status) and pass the validator Lambda.
`--invalid KIND` adds one extra file that the validator must reject, to see the
InvalidFile path of the state machine.

Standard library only. Usage:
  python scripts/generate_orders.py                      # 1 file, 10 rows, today
  python scripts/generate_orders.py --files 3 --rows 20  # 3 consecutive days
  python scripts/generate_orders.py --invalid amount     # + one bad file
  python scripts/generate_orders.py --seed 42            # same amounts/customers

Nothing here collides with data/samples/ (nor with earlier generated files):
file names end in a random suffix (orders_2026_10_07_a1b2c3.csv), so every run
is a different S3 key and never overwrites a sample or an earlier upload. The
first order_id is the clock in milliseconds (e.g. 1790000000123), so ids never
repeat across runs even if data/generated/ was deleted; --seed fixes amounts and
customers but not the ids (use --first-order-id for that).

Files go to data/generated/ (git-ignored). Upload them with
`make upload FILE=<path>` (or `make upload-generated`); that is what triggers
the pipeline.
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import time
from datetime import date, timedelta
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

COLUMNS = ("order_id", "customer_id", "amount", "status")
FAULTS = ("amount", "missing-column", "empty", "no-rows")

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = REPO_ROOT / "data" / "samples"
DEFAULT_OUT = Path("data/generated")
STATUSES = ("COMPLETED", "CANCELLED")
STATUS_WEIGHTS = (0.85, 0.15)
CUSTOMERS = 50


def build_rows(
    rng: random.Random, count: int, first_order_id: int
) -> list[dict[str, object]]:
    return [
        {
            "order_id": first_order_id + offset,
            "customer_id": f"C{rng.randint(1, CUSTOMERS):03d}",
            "amount": Decimal(rng.randint(500, 50000)).scaleb(-2),  # 2 decimals
            "status": rng.choices(STATUSES, weights=STATUS_WEIGHTS)[0],
        }
        for offset in range(count)
    ]


def _render(columns: tuple[str, ...], rows: list[dict[str, object]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def render_csv(rows: list[dict[str, object]]) -> str:
    return _render(COLUMNS, rows)


def render_invalid_csv(fault: str, rows: list[dict[str, object]]) -> str:
    """CSV the validator rejects, one reason per fault."""
    if fault == "amount":  # invalid_amount: row 1
        broken = [{**rows[0], "amount": "abc"}, *rows[1:]]
        return render_csv(broken)
    if fault == "missing-column":  # missing_columns: status
        return _render(COLUMNS[:-1], rows)
    if fault == "empty":  # empty_file
        return ""
    if fault == "no-rows":  # no_data_rows
        return render_csv([])
    raise ValueError(f"unknown fault: {fault!r} (choose from {', '.join(FAULTS)})")


def taken_file_names(*folders: Path) -> set[str]:
    return {
        p.name for folder in folders if folder.is_dir() for p in folder.glob("*.csv")
    }


def used_order_ids(*folders: Path) -> set[int]:
    """order_id values already present in the CSVs of these folders."""
    ids: set[int] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.glob("*.csv"):
            try:
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        value = (row.get("order_id") or "").strip()
                        if value.isdigit():
                            ids.add(int(value))
            except (OSError, UnicodeDecodeError, csv.Error):
                continue  # unreadable file: it cannot clash on ids we cannot read
    return ids


def _unique_name(rng: random.Random, day: date, taken: set[str], tail: str = "") -> str:
    """orders_<date>_<6 hex><tail>.csv, a name not seen in the scanned folders.

    The random suffix makes every run a different S3 key, so a new upload never
    overwrites an earlier one (the generator cannot see what is already in S3).
    """
    while True:
        name = f"orders_{day:%Y_%m_%d}_{rng.getrandbits(24):06x}{tail}.csv"
        if name not in taken:
            taken.add(name)
            return name


def generate(
    out_dir: Path,
    *,
    files: int,
    rows: int,
    start: date,
    seed: int | None,
    first_order_id: int | None,
    avoid: tuple[Path, ...] = (SAMPLES_DIR,),
    invalid: str | None = None,
    clock: Callable[[], float] = time.time,
) -> list[Path]:
    """Write `files` valid CSVs on consecutive days (+1 invalid one if asked).

    File names carry a random suffix and never repeat a name found in `avoid`
    or `out_dir`. Folders in `avoid` (and `out_dir`) are also scanned for
    order_ids. `first_order_id=None` starts at the clock in milliseconds (so ids
    never repeat across runs, even if data/generated/ was deleted), bumped above
    any id already found there.
    """
    rng = random.Random(seed)
    scanned = (*avoid, out_dir)
    taken = taken_file_names(*scanned)
    highest = max(used_order_ids(*scanned), default=0)
    if first_order_id is None:
        first_order_id = max(int(clock() * 1000), highest + 1)
    elif first_order_id <= highest:
        raise ValueError(
            f"order_id {first_order_id} is already used (highest in use: {highest}); "
            f"start at {highest + 1} or higher"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for index in range(files):
        name = _unique_name(rng, start + timedelta(days=index), taken)
        data = build_rows(rng, rows, first_order_id + index * rows)
        path = out_dir / name
        path.write_text(render_csv(data), encoding="utf-8", newline="")
        written.append(path)

    if invalid:
        name = _unique_name(rng, start + timedelta(days=files), taken, "_invalid")
        data = build_rows(rng, rows, first_order_id + files * rows)
        path = out_dir / name
        path.write_text(render_invalid_csv(invalid, data), encoding="utf-8", newline="")
        written.append(path)

    return written


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate order CSV files.")
    parser.add_argument(
        "--files", type=_positive, default=1, help="valid files (one per day)"
    )
    parser.add_argument("--rows", type=_positive, default=10, help="rows per file")
    parser.add_argument(
        "--date",
        type=_iso_date,
        default=date.today(),
        help="first file date, YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--first-order-id",
        type=_positive,
        help="order_id of the first row (default: current time in ms, above any id in data/)",
    )
    parser.add_argument(
        "--invalid", choices=FAULTS, help="also write one file the validator rejects"
    )
    parser.add_argument("--seed", type=int, help="make the output reproducible")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output folder (default {DEFAULT_OUT.as_posix()})",
    )
    args = parser.parse_args(argv)

    try:
        paths = generate(
            args.out,
            files=args.files,
            rows=args.rows,
            start=args.date,
            seed=args.seed,
            first_order_id=args.first_order_id,
            invalid=args.invalid,
        )
    except ValueError as error:
        parser.error(str(error))

    print(f"Wrote {len(paths)} file(s) to {args.out.as_posix()}/")
    for path in paths:
        print(f"  make upload FILE={path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
