# End-to-end check of the deployed S6 lab, using the AWS SDK for Python (boto3).
#
# Uploads the sample files (plus a few throwaway ones) to the deployed bucket and
# verifies, step by step, that every service does its part:
#   S3 -> EventBridge -> Step Functions -> Lambda -> S3, then
#   Glue Crawler -> Data Catalog -> Athena.
#
# Usage:  uv run python scripts/check_deployed_pipeline.py [--skip-catalog] [--keep]
#         (or: make e2e)
# Needs the stack deployed (values come from `terraform output`) and AWS
# credentials in the environment or in .env.credentials.
#
# Throwaway objects (raw/e2e_<run id>_*, otra/e2e_<run id>_*) and the outputs
# they produce are deleted at the end unless --keep is given. The three valid
# samples keep their fixed keys, so re-running never changes the Athena result.
from __future__ import annotations

import argparse
import codecs
import json
import subprocess
import sys
import time
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = REPO_ROOT / "data" / "samples"
PROCESSED_PREFIX = "processed/orders/"
VALID_SAMPLES = (
    "orders_2026_10_04.csv",
    "orders_2026_10_05.csv",
    "orders_2026_10_06.csv",
)
EXPECTED_TOTALS = {
    "COMPLETED": (6, Decimal("1290.75")),
    "CANCELLED": (1, Decimal("99.90")),
}
EXPECTED_COLUMNS = ["order_id", "customer_id", "amount", "status"]
REQUIRED_OUTPUTS = (
    "bucket_name",
    "state_machine_arn",
    "lambda_function_name",
    "crawler_name",
    "glue_database_name",
    "athena_workgroup",
)
BOM = codecs.BOM_UTF8

EXECUTION_TIMEOUT_SECONDS = 240  # S3 -> EventBridge propagation can take minutes
QUIET_WINDOW_SECONDS = 30  # how long to watch for executions that must NOT happen
CRAWLER_TIMEOUT_SECONDS = 600
ATHENA_TIMEOUT_SECONDS = 120
POLL_SECONDS = 5


# --- test cases -------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    label: str
    key: str
    expect: str  # "succeeded" | "invalid" | "none" (no execution at all)
    source: Path | None = None
    data: bytes | None = None
    output_key: str | None = None
    cleanup: bool = False  # delete the output at the end (throwaway keys only)

    def body(self) -> bytes:
        if self.data is not None:
            return self.data
        assert self.source is not None
        return self.source.read_bytes()

    @property
    def throwaway(self) -> bool:
        return "e2e_" in self.key


def build_cases(run_id: str) -> list[Case]:
    cases = [
        Case(
            label=f"valid sample {name}",
            key=f"raw/{name}",
            expect="succeeded",
            source=SAMPLES / name,
            output_key=PROCESSED_PREFIX + name,
        )
        for name in VALID_SAMPLES
    ]
    tag = f"e2e_{run_id}"
    valid = (SAMPLES / "orders_2026_10_04.csv").read_bytes()
    spaced = f"{tag}_with space.csv"
    bom = f"{tag}_bom.csv"
    cases += [
        Case(
            "key with spaces",
            f"raw/{spaced}",
            "succeeded",
            data=valid,
            output_key=PROCESSED_PREFIX + spaced,
            cleanup=True,
        ),
        Case(
            "file saved with BOM",
            f"raw/{bom}",
            "succeeded",
            data=BOM + valid,
            output_key=PROCESSED_PREFIX + bom,
            cleanup=True,
        ),
        Case(
            "invalid amount",
            f"raw/{tag}_orders_invalid.csv",
            "invalid",
            source=SAMPLES / "orders_invalid.csv",
        ),
        Case(
            "missing column",
            f"raw/{tag}_prueba_invalida.csv",
            "invalid",
            source=SAMPLES / "prueba_invalida.csv",
        ),
        Case(
            "empty csv",
            f"raw/{tag}_prueba.csv",
            "invalid",
            source=SAMPLES / "prueba.csv",
        ),
        Case(
            "json inside raw/",
            f"raw/{tag}_prueba.json",
            "none",
            source=SAMPLES / "prueba.json",
        ),
        Case(
            "csv outside raw/",
            f"otra/{tag}_prueba.csv",
            "none",
            source=SAMPLES / "prueba.csv",
        ),
        Case(
            "uppercase .CSV (rule is case-sensitive)",
            f"raw/{tag}_UPPER.CSV",
            "none",
            data=valid,
        ),
    ]
    return cases


# --- pure helpers (unit tested) ---------------------------------------------


def rows_to_totals(rows: list[list[str]]) -> dict[str, tuple[int, Decimal]]:
    """Athena result rows (header first) -> {status: (rows, total amount)}."""
    return {status: (int(count), Decimal(total)) for status, count, total in rows[1:]}


def compare_totals(actual: dict[str, tuple[int, Decimal]]) -> tuple[bool, str]:
    def show(value: tuple[int, Decimal] | None) -> str:
        if value is None:
            return "missing"
        return f"{value[0]} rows / {value[1].quantize(Decimal('0.01'))}"

    problems = []
    for status in sorted(set(EXPECTED_TOTALS) | set(actual)):
        want, got = EXPECTED_TOTALS.get(status), actual.get(status)
        if want != got:
            problems.append(f"{status}: expected {show(want)}, got {show(got)}")
    if problems:
        return False, "; ".join(problems)
    return True, ", ".join(f"{s} {show(v)}" for s, v in sorted(EXPECTED_TOTALS.items()))


@dataclass
class Report:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, passed, detail))
        print(self._line(name, passed, detail), flush=True)

    @staticmethod
    def _line(name: str, passed: bool, detail: str) -> str:
        suffix = f" - {detail}" if detail else ""
        return f"  {'PASS' if passed else 'FAIL'}  {name}{suffix}"

    @property
    def ok(self) -> bool:
        return all(passed for _, passed, _ in self.checks)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def summary(self) -> str:
        passed = sum(1 for _, ok, _ in self.checks if ok)
        return f"{passed} passed, {len(self.checks) - passed} failed"

    def render(self) -> str:
        lines = [self._line(*check) for check in self.checks]
        return "\n".join([*lines, f"\n{self.summary()}"])


# --- AWS access -------------------------------------------------------------


def terraform_outputs() -> dict[str, str]:
    result = subprocess.run(
        ["terraform", "-chdir=infra", "output", "-no-color", "-json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return {name: item["value"] for name, item in data.items()}


def get_clients() -> dict[str, object]:
    # aws_session loads .env.credentials and applies the repo's SSL workaround.
    # aws_session disables TLS verification (Python 3.14 SSL workaround); hide
    # the resulting per-request warning so it does not bury the report.
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    sys.path.insert(0, str(REPO_ROOT / "tests" / "aws"))
    from aws_session import get_client

    return {
        name: get_client(name) for name in ("s3", "stepfunctions", "glue", "athena")
    }


class ExecutionWatcher:
    """Finds the Step Functions executions started after `since`, by object key."""

    def __init__(self, sfn, state_machine_arn: str, since: datetime):
        self.sfn, self.arn, self.since = sfn, state_machine_arn, since
        self.details: dict[str, dict] = {}

    def refresh(self) -> None:
        listing = self.sfn.list_executions(stateMachineArn=self.arn, maxResults=100)
        for item in listing["executions"]:
            if item["startDate"] < self.since:
                continue
            known = self.details.get(item["executionArn"])
            if known and known["status"] != "RUNNING":
                continue
            self.details[item["executionArn"]] = self.sfn.describe_execution(
                executionArn=item["executionArn"]
            )

    def for_key(self, key: str) -> list[dict]:
        found = []
        for detail in self.details.values():
            try:
                event = json.loads(detail["input"])
                if event["detail"]["object"]["key"] == key:
                    found.append(detail)
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        return found

    def finished(self, key: str) -> dict | None:
        for detail in self.for_key(key):
            if detail["status"] != "RUNNING":
                return detail
        return None

    def wait_for(
        self, keys: list[str], timeout: int = EXECUTION_TIMEOUT_SECONDS
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.refresh()
            if all(self.finished(key) for key in keys):
                return
            time.sleep(POLL_SECONDS)


def list_processed(s3, bucket: str) -> set[str]:
    keys: set[str] = set()
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=PROCESSED_PREFIX
    ):
        keys |= {item["Key"] for item in page.get("Contents", [])}
    return keys


def read_object(s3, bucket: str, key: str) -> bytes | None:
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except s3.exceptions.NoSuchKey:
        return None


def run_athena(athena, workgroup: str, sql: str) -> list[list[str]]:
    query_id = athena.start_query_execution(QueryString=sql, WorkGroup=workgroup)[
        "QueryExecutionId"
    ]
    deadline = time.monotonic() + ATHENA_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = athena.get_query_execution(QueryExecutionId=query_id)[
            "QueryExecution"
        ]["Status"]
        if status["State"] == "SUCCEEDED":
            rows = athena.get_query_results(QueryExecutionId=query_id)["ResultSet"][
                "Rows"
            ]
            return [
                [cell.get("VarCharValue", "") for cell in row["Data"]] for row in rows
            ]
        if status["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"{status['State']}: {status.get('StateChangeReason')}")
        time.sleep(2)
    raise RuntimeError("Athena query timed out")


# --- stages -----------------------------------------------------------------


def crawler_started(output: str | None) -> bool:
    """True if a finished execution went through the StartCrawler state."""
    try:
        return "crawler" in json.loads(output or "")
    except (TypeError, json.JSONDecodeError):
        return False


def check_crawler_started(
    cases: list[Case], watcher: ExecutionWatcher, report: Report
) -> None:
    missing = []
    for case in cases:
        if case.expect != "succeeded":
            continue
        done = watcher.finished(case.key)
        if (
            done
            and done["status"] == "SUCCEEDED"
            and not crawler_started(done.get("output"))
        ):
            missing.append(case.key)
    report.add(
        "every successful execution started the Glue crawler (StartCrawler)",
        not missing,
        "all successful executions passed through StartCrawler"
        if not missing
        else f"no crawler result in the output of: {', '.join(missing)}",
    )


def evaluate_case(
    case: Case, watcher: ExecutionWatcher, s3, bucket: str, report: Report
):
    executions = watcher.for_key(case.key)
    if case.expect == "none":
        report.add(
            f"{case.label}: does not start the pipeline",
            not executions,
            f"{len(executions)} unexpected execution(s) for {case.key}"
            if executions
            else case.key,
        )
        return

    done = watcher.finished(case.key)
    if done is None:
        report.add(
            f"{case.label}: pipeline finished",
            False,
            f"no finished execution for {case.key} within {EXECUTION_TIMEOUT_SECONDS}s",
        )
        return

    if case.expect == "succeeded":
        output = read_object(s3, bucket, case.output_key)
        ok = done["status"] == "SUCCEEDED" and output is not None
        detail = (
            case.output_key
            if ok
            else (
                f"status={done['status']} error={done.get('error')} "
                "(AccessDenied in the Lambda logs? check inject_fault)"
                if done["status"] != "SUCCEEDED"
                else f"{case.output_key} was not written"
            )
        )
        report.add(f"{case.label}: SUCCEEDED and written to processed/", ok, detail)
        if ok and case.label == "file saved with BOM":
            clean = output == (SAMPLES / "orders_2026_10_04.csv").read_bytes()
            report.add(
                "BOM is removed from the output",
                clean,
                "output has no BOM" if clean else f"starts with {output[:3]!r}",
            )
        return

    output_written = bool(
        list_prefix(s3, bucket, f"{PROCESSED_PREFIX}{Path(case.key).name}")
    )
    ok = (
        done["status"] == "FAILED"
        and done.get("error") == "InvalidFile"
        and not output_written
    )
    report.add(
        f"{case.label}: FAILED with InvalidFile and writes nothing",
        ok,
        "InvalidFile, no output"
        if ok
        else f"status={done['status']} error={done.get('error')} output_written={output_written}",
    )


def list_prefix(s3, bucket: str, prefix: str) -> list[str]:
    return [
        item["Key"]
        for item in s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
    ]


def check_idempotency(s3, sfn, outputs: dict[str, str], report: Report) -> None:
    bucket, arn = outputs["bucket_name"], outputs["state_machine_arn"]
    name = VALID_SAMPLES[0]
    before = list_processed(s3, bucket)
    since = datetime.now(timezone.utc)
    s3.put_object(Bucket=bucket, Key=f"raw/{name}", Body=(SAMPLES / name).read_bytes())
    watcher = ExecutionWatcher(sfn, arn, since)
    watcher.wait_for([f"raw/{name}"])
    done = watcher.finished(f"raw/{name}")
    after = list_processed(s3, bucket)
    same_content = (
        read_object(s3, bucket, PROCESSED_PREFIX + name)
        == (SAMPLES / name).read_bytes()
    )
    ok = (
        bool(done)
        and done["status"] == "SUCCEEDED"
        and before == after
        and same_content
    )
    report.add(
        "re-uploading a file reprocesses it without duplicating data",
        ok,
        f"{len(after)} object(s) in processed/, same keys and content"
        if ok
        else f"status={done and done['status']} keys_equal={before == after} same_content={same_content}",
    )


def cleanup(s3, bucket: str, cases: list[Case]) -> None:
    keys = [c.key for c in cases if c.throwaway]
    keys += [c.output_key for c in cases if c.cleanup and c.output_key]
    for start in range(0, len(keys), 1000):
        s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in keys[start : start + 1000]]},
        )
    print(f"  cleaned up {len(keys)} throwaway object(s)", flush=True)


def check_catalog(
    clients: dict[str, object], outputs: dict[str, str], report: Report
) -> None:
    glue, athena = clients["glue"], clients["athena"]
    crawler, database = outputs["crawler_name"], outputs["glue_database_name"]

    print("  making sure the crawler has run (can take a few minutes)...", flush=True)
    try:
        glue.start_crawler(Name=crawler)
    except glue.exceptions.CrawlerRunningException:
        pass
    time.sleep(10)  # let a just-started crawler leave READY
    deadline = time.monotonic() + CRAWLER_TIMEOUT_SECONDS
    state = last = None
    while time.monotonic() < deadline:
        data = glue.get_crawler(Name=crawler)["Crawler"]
        state, last = data["State"], data.get("LastCrawl", {})
        if state == "READY":
            break
        time.sleep(POLL_SECONDS)
    report.add(
        "Glue Crawler finishes",
        state == "READY" and last.get("Status") == "SUCCEEDED",
        f"state={state} lastCrawl={last.get('Status')}",
    )

    try:
        table = glue.get_table(DatabaseName=database, Name="orders")["Table"]
    except glue.exceptions.EntityNotFoundException:
        report.add(
            "Data Catalog table orders exists", False, f"{database}.orders not found"
        )
        return
    columns = {c["Name"]: c["Type"] for c in table["StorageDescriptor"]["Columns"]}
    location = table["StorageDescriptor"]["Location"]
    report.add(
        "Data Catalog table has the contract columns",
        list(columns) == EXPECTED_COLUMNS,
        ", ".join(f"{k}:{v}" for k, v in columns.items()),
    )
    report.add(
        "Data Catalog table points at processed/orders/",
        location.endswith(PROCESSED_PREFIX),
        location,
    )

    sql = (
        "SELECT status, COUNT(*) AS filas, ROUND(SUM(amount), 2) AS total "
        f"FROM {database}.orders GROUP BY status"
    )
    try:
        totals = rows_to_totals(run_athena(athena, outputs["athena_workgroup"], sql))
    except (RuntimeError, ValueError) as error:
        report.add("Athena returns the expected totals", False, str(error))
        return
    ok, detail = compare_totals(totals)
    report.add("Athena returns the expected totals", ok, detail)


# --- main -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end check of the deployed S6 lab."
    )
    parser.add_argument(
        "--skip-catalog",
        action="store_true",
        help="skip the Crawler / Data Catalog / Athena stage",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="do not delete the throwaway objects at the end",
    )
    args = parser.parse_args(argv)

    outputs = terraform_outputs()
    missing = [name for name in REQUIRED_OUTPUTS if not outputs.get(name)]
    if missing:
        print(
            f"Stack not deployed or outputs missing: {', '.join(missing)}. Deploy it first (see docs/deploy/guia_deploy.md)."
        )
        return 2

    clients = get_clients()
    s3, sfn = clients["s3"], clients["stepfunctions"]
    bucket, arn = outputs["bucket_name"], outputs["state_machine_arn"]
    cases = build_cases(uuid.uuid4().hex[:8])
    report = Report()

    print(
        f"Stack: bucket={bucket}\n       state machine={arn.rsplit(':', 1)[-1]}\n",
        flush=True,
    )
    print("1/4 Uploading files...", flush=True)
    since = datetime.now(timezone.utc)
    for case in cases:
        s3.put_object(Bucket=bucket, Key=case.key, Body=case.body())
    watcher = ExecutionWatcher(sfn, arn, since)

    try:
        print("2/4 Waiting for Step Functions...", flush=True)
        watcher.wait_for([c.key for c in cases if c.expect != "none"])
        time.sleep(QUIET_WINDOW_SECONDS)  # files that must NOT trigger anything
        watcher.refresh()
        for case in cases:
            evaluate_case(case, watcher, s3, bucket, report)
        check_crawler_started(cases, watcher, report)

        print("3/4 Idempotency...", flush=True)
        check_idempotency(s3, sfn, outputs, report)
    finally:
        if not args.keep:
            cleanup(s3, bucket, cases)

    if args.skip_catalog:
        print("4/4 Catalog stage skipped.", flush=True)
    else:
        print("4/4 Glue Crawler -> Data Catalog -> Athena...", flush=True)
        check_catalog(clients, outputs, report)

    # The checks were already printed live; only repeat what failed.
    print("\n" + "=" * 60 + f"\n{report.summary()}")
    for name, passed, detail in report.checks:
        if not passed:
            print(f"  FAILED: {name} - {detail}")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
