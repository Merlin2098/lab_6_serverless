"""Cloud tests for the deployed S6 stack (need credentials and the deployed stack).

Run with: python scripts/testing/run_cloud_tests.py
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.cloud


def _aws_session():
    # Imported lazily: aws_session needs python-dotenv, which is only in the uv
    # environment. This keeps `make test` collectable without it. Importing it
    # also loads .env.credentials, so it must happen before checking the env.
    pytest.importorskip("dotenv")
    import aws_session

    return aws_session


def get_client(service: str):
    return _aws_session().get_client(service)


REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "data" / "samples"
EXECUTION_TIMEOUT_SECONDS = 240  # S3 -> EventBridge propagation can take minutes
POLL_SECONDS = 5


@pytest.fixture(scope="module")
def outputs() -> dict[str, str]:
    _aws_session()  # loads .env.credentials into the environment
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        pytest.skip("AWS credentials not configured")
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
        data = {}
    if "state_machine_arn" not in data:
        pytest.skip("stack not deployed (see docs/deploy/guia_deploy.md)")
    return {name: item["value"] for name, item in data.items()}


def wait_for_execution(sfn, arn: str, key: str, started_after: datetime) -> dict:
    deadline = time.monotonic() + EXECUTION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        for item in sfn.list_executions(stateMachineArn=arn, maxResults=20)[
            "executions"
        ]:
            if item["startDate"] < started_after:
                continue
            detail = sfn.describe_execution(executionArn=item["executionArn"])
            if key in detail["input"] and detail["status"] != "RUNNING":
                return detail
        time.sleep(POLL_SECONDS)
    pytest.fail(f"no finished execution for {key} within {EXECUTION_TIMEOUT_SECONDS}s")


def object_exists(s3, bucket: str, key: str) -> bool:
    return s3.list_objects_v2(Bucket=bucket, Prefix=key).get("KeyCount", 0) > 0


# --- structure --------------------------------------------------------------


def test_bucket_sends_events_to_eventbridge(outputs) -> None:
    config = get_client("s3").get_bucket_notification_configuration(
        Bucket=outputs["bucket_name"]
    )
    assert "EventBridgeConfiguration" in config


def test_rule_only_matches_csv_files_in_raw(outputs) -> None:
    rule = get_client("events").describe_rule(Name=outputs["event_rule_name"])
    pattern = json.loads(rule["EventPattern"])
    assert pattern["detail"]["object"]["key"] == [{"wildcard": "raw/*.csv"}]


def test_lambda_is_an_x86_container_image(outputs) -> None:
    config = get_client("lambda").get_function_configuration(
        FunctionName=outputs["lambda_function_name"]
    )
    assert config["PackageType"] == "Image"
    assert config["Architectures"] == ["x86_64"]


def test_state_machine_has_retry_and_catch(outputs) -> None:
    sfn = get_client("stepfunctions")
    definition = json.loads(
        sfn.describe_state_machine(stateMachineArn=outputs["state_machine_arn"])[
            "definition"
        ]
    )
    validate = definition["States"]["Validate"]
    assert validate["Retry"] and validate["Catch"]


def test_log_groups_have_retention(outputs) -> None:
    logs = get_client("logs")
    for name in (outputs["log_group_name"], outputs["state_machine_log_group_name"]):
        groups = logs.describe_log_groups(logGroupNamePrefix=name)["logGroups"]
        group = next(g for g in groups if g["logGroupName"] == name)
        assert group.get("retentionInDays"), name


# --- end to end -------------------------------------------------------------


def test_valid_file_succeeds_and_is_written_to_processed(outputs) -> None:
    s3, sfn = get_client("s3"), get_client("stepfunctions")
    bucket = outputs["bucket_name"]
    started = datetime.now(timezone.utc)

    # Same key every time: reprocessing is idempotent and never adds rows.
    s3.upload_file(
        str(SAMPLES / "orders_2026_10_04.csv"), bucket, "raw/orders_2026_10_04.csv"
    )
    detail = wait_for_execution(
        sfn, outputs["state_machine_arn"], "orders_2026_10_04.csv", started
    )

    assert detail["status"] == "SUCCEEDED"
    assert object_exists(s3, bucket, "processed/orders/orders_2026_10_04.csv")


def test_invalid_file_fails_with_invalid_file_and_writes_nothing(outputs) -> None:
    s3, sfn = get_client("s3"), get_client("stepfunctions")
    bucket = outputs["bucket_name"]
    # Unique name: never pollutes the table.
    name = f"e2e_{uuid.uuid4().hex[:8]}_orders_invalid.csv"
    started = datetime.now(timezone.utc)

    s3.upload_file(str(SAMPLES / "orders_invalid.csv"), bucket, f"raw/{name}")
    detail = wait_for_execution(sfn, outputs["state_machine_arn"], name, started)

    assert detail["status"] == "FAILED"
    assert detail["error"] == "InvalidFile"
    assert not object_exists(s3, bucket, f"processed/orders/{name}")
    s3.delete_object(Bucket=bucket, Key=f"raw/{name}")


# --- spec section 8: outputs, deployed IAM, Athena result ---------------------

EXPECTED_OUTPUTS = {
    "ecr_repository_url",
    "bucket_name",
    "crawler_name",
    "glue_database_name",
    "athena_workgroup",
    "state_machine_arn",
    "state_machine_log_group_name",
    "lambda_function_name",
    "event_rule_name",
    "log_group_name",
    "log_group_arn",
}
CRAWLER_TIMEOUT_SECONDS = 600
ATHENA_TIMEOUT_SECONDS = 120


def test_all_documented_outputs_exist(outputs) -> None:
    assert EXPECTED_OUTPUTS <= set(outputs)
    assert all(outputs[name] for name in EXPECTED_OUTPUTS)


def role_name(arn: str) -> str:
    return arn.rsplit("/", 1)[-1]


def inline_policy_actions(iam, name: str) -> list[str]:
    actions: list[str] = []
    for policy_name in iam.list_role_policies(RoleName=name)["PolicyNames"]:
        document = iam.get_role_policy(RoleName=name, PolicyName=policy_name)[
            "PolicyDocument"
        ]
        statements = document["Statement"]
        if isinstance(statements, dict):
            statements = [statements]
        for statement in statements:
            action = statement.get("Action", [])
            actions += [action] if isinstance(action, str) else list(action)
    return actions


def test_deployed_roles_have_no_wildcard_actions(outputs) -> None:
    iam = get_client("iam")
    lambda_role = get_client("lambda").get_function_configuration(
        FunctionName=outputs["lambda_function_name"]
    )["Role"]
    sfn_role = get_client("stepfunctions").describe_state_machine(
        stateMachineArn=outputs["state_machine_arn"]
    )["roleArn"]
    events_role = get_client("events").list_targets_by_rule(
        Rule=outputs["event_rule_name"]
    )["Targets"][0]["RoleArn"]
    crawler_role = get_client("glue").get_crawler(Name=outputs["crawler_name"])[
        "Crawler"
    ]["Role"]

    for arn in (lambda_role, sfn_role, events_role, crawler_role):
        actions = inline_policy_actions(iam, role_name(arn))
        assert actions, arn
        assert "*" not in actions, arn


def wait_for_crawler(glue, name: str) -> None:
    time.sleep(10)  # give a just-started crawler time to leave READY
    deadline = time.monotonic() + CRAWLER_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        crawler = glue.get_crawler(Name=name)["Crawler"]
        if crawler["State"] == "READY":
            assert crawler["LastCrawl"]["Status"] == "SUCCEEDED"
            return
        time.sleep(POLL_SECONDS)
    pytest.fail(f"crawler {name} not READY within {CRAWLER_TIMEOUT_SECONDS}s")


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
            return [[cell.get("VarCharValue", "") for cell in r["Data"]] for r in rows]
        if status["State"] in ("FAILED", "CANCELLED"):
            pytest.fail(
                f"athena query {status['State']}: {status.get('StateChangeReason')}"
            )
        time.sleep(2)
    pytest.fail("athena query timed out")


def test_athena_matches_the_expected_totals(outputs) -> None:
    s3, sfn = get_client("s3"), get_client("stepfunctions")
    glue, athena = get_client("glue"), get_client("athena")
    bucket = outputs["bucket_name"]
    names = ["orders_2026_10_04.csv", "orders_2026_10_05.csv", "orders_2026_10_06.csv"]
    started = datetime.now(timezone.utc)

    # Fixed keys: idempotent, so repeated runs never change the totals.
    for name in names:
        s3.upload_file(str(SAMPLES / name), bucket, f"raw/{name}")
    for name in names:
        detail = wait_for_execution(sfn, outputs["state_machine_arn"], name, started)
        assert detail["status"] == "SUCCEEDED", name

    try:
        glue.start_crawler(Name=outputs["crawler_name"])
    except glue.exceptions.CrawlerRunningException:
        pass
    wait_for_crawler(glue, outputs["crawler_name"])

    sql = (
        "SELECT status, COUNT(*) AS filas, ROUND(SUM(amount), 2) AS total "
        f"FROM {outputs['glue_database_name']}.orders GROUP BY status"
    )
    rows = run_athena(athena, outputs["athena_workgroup"], sql)[1:]  # drop header
    result = {
        status: (int(count), round(float(total), 2)) for status, count, total in rows
    }

    assert result == {"COMPLETED": (6, 1290.75), "CANCELLED": (1, 99.9)}
