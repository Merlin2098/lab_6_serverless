from __future__ import annotations

import json
from pathlib import Path

import pytest

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "modules"
    / "orchestration"
    / "pipeline.asl.json.tftpl"
)
LAMBDA_ARN = "arn:aws:lambda:us-east-1:123456789012:function:s6-lab-dev-validator"
CRAWLER_NAME = "s6-lab-dev-orders"
RETRYABLE = {
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
}


@pytest.fixture(scope="module")
def asl() -> dict:
    text = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("${lambda_arn}", LAMBDA_ARN)
        .replace("${crawler_name}", CRAWLER_NAME)
    )
    return json.loads(text)


def test_starts_at_validate_and_invokes_the_lambda_with_the_whole_event(asl) -> None:
    assert asl["StartAt"] == "Validate"
    validate = asl["States"]["Validate"]
    assert validate["Resource"] == "arn:aws:states:::lambda:invoke"
    assert validate["Parameters"]["FunctionName"] == LAMBDA_ARN
    assert validate["Parameters"]["Payload.$"] == "$"
    assert validate["ResultPath"] == "$.validation"


def test_validate_retries_service_errors_with_backoff(asl) -> None:
    retry = asl["States"]["Validate"]["Retry"][0]
    assert set(retry["ErrorEquals"]) == RETRYABLE
    assert retry["IntervalSeconds"] == 2
    assert retry["MaxAttempts"] == 3
    assert retry["BackoffRate"] == 2.0


def test_validate_catches_everything_into_error_path(asl) -> None:
    catch = asl["States"]["Validate"]["Catch"][0]
    assert catch["ErrorEquals"] == ["States.ALL"]
    assert catch["ResultPath"] == "$.error"
    assert catch["Next"] == "HandleError"


def test_choice_routes_valid_results_to_success_and_defaults_to_invalid(asl) -> None:
    choice = asl["States"]["IsValid"]
    assert choice["Type"] == "Choice"
    rule = choice["Choices"][0]
    assert rule["Variable"] == "$.validation.Payload.valid"
    assert rule["BooleanEquals"] is True
    assert rule["Next"] == "StartCrawler"
    assert choice["Default"] == "InvalidFile"


def test_valid_files_start_the_crawler_with_the_sdk_integration(asl) -> None:
    start = asl["States"]["StartCrawler"]
    assert start["Type"] == "Task"
    # Direct AWS SDK integration (no Lambda): glue:StartCrawler.
    assert start["Resource"] == "arn:aws:states:::aws-sdk:glue:startCrawler"
    assert start["Parameters"] == {"Name": CRAWLER_NAME}
    assert start["ResultPath"] == "$.crawler"
    assert start["Next"] == "PipelineSucceeded"


def test_a_crawler_already_running_is_not_a_failure(asl) -> None:
    catches = {
        error: catch
        for catch in asl["States"]["StartCrawler"]["Catch"]
        for error in catch["ErrorEquals"]
    }
    running = catches["Glue.CrawlerRunningException"]
    assert running["Next"] == "PipelineSucceeded"
    assert running["ResultPath"] == "$.crawler"


def test_any_other_crawler_error_goes_to_the_error_path(asl) -> None:
    catch = asl["States"]["StartCrawler"]["Catch"][-1]  # most generic goes last
    assert catch["ErrorEquals"] == ["States.ALL"]
    assert catch["ResultPath"] == "$.error"
    assert catch["Next"] == "HandleError"


def test_invalid_files_never_start_the_crawler(asl) -> None:
    # The only way into StartCrawler is the valid branch of IsValid.
    entries = [
        name
        for name, state in asl["States"].items()
        if state.get("Next") == "StartCrawler"
        or any(c["Next"] == "StartCrawler" for c in state.get("Choices", []))
    ]
    assert entries == ["IsValid"]
    assert asl["States"]["IsValid"]["Default"] == "InvalidFile"


def test_terminal_states(asl) -> None:
    states = asl["States"]
    assert states["PipelineSucceeded"]["Type"] == "Succeed"
    assert states["InvalidFile"]["Type"] == "Fail"
    assert states["InvalidFile"]["Error"] == "InvalidFile"
    assert states["HandleError"]["Type"] == "Pass"
    assert states["HandleError"]["Next"] == "PipelineFailed"
    assert states["PipelineFailed"]["Type"] == "Fail"
    assert states["PipelineFailed"]["Error"] == "PipelineError"


def test_every_transition_targets_an_existing_state(asl) -> None:
    states = asl["States"]
    targets = [asl["StartAt"]]
    for state in states.values():
        targets += [state[key] for key in ("Next", "Default") if key in state]
        targets += [c["Next"] for c in state.get("Choices", [])]
        targets += [c["Next"] for c in state.get("Catch", [])]
    assert all(target in states for target in targets)
