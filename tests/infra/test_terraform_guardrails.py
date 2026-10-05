from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
MODULES = INFRA / "modules"
EXPECTED_MODULES = {
    "storage",
    "registry",
    "compute",
    "orchestration",
    "events",
    "catalog",
}
TF_FILES = sorted(INFRA.rglob("*.tf"))


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def module_text(name: str) -> str:
    return "\n".join(text(p) for p in sorted((MODULES / name).glob("*.tf")))


def test_expected_modules_exist_and_expose_resource_arn() -> None:
    assert {p.name for p in MODULES.iterdir() if p.is_dir()} == EXPECTED_MODULES
    for name in EXPECTED_MODULES:
        assert 'output "resource_arn"' in text(MODULES / name / "outputs.tf"), name


def test_no_wildcard_iam_actions() -> None:
    for path in TF_FILES:
        for match in re.finditer(r"actions\s*=\s*\[([^\]]*)\]", text(path)):
            assert '"*"' not in match.group(1), f"wildcard action in {path}"


def test_wildcard_resource_is_only_the_step_functions_log_delivery() -> None:
    allowed = MODULES / "orchestration" / "main.tf"
    for path in TF_FILES:
        if re.search(r'resources\s*=\s*\["\*"\]', text(path)):
            assert path == allowed, f"unexpected Resource * in {path}"


def test_every_declared_log_group_has_retention() -> None:
    blocks = []
    for path in TF_FILES:
        blocks += re.findall(
            r'resource "aws_cloudwatch_log_group" "[^"]+" \{(.*?)\n\}',
            text(path),
            re.DOTALL,
        )
    assert len(blocks) == 2  # lambda + step functions
    for body in blocks:
        assert "retention_in_days" in body


def test_log_groups_use_stack_specific_names_and_never_the_shared_glue_one() -> None:
    assert '"/aws/lambda/${var.name}"' in module_text("compute")
    assert '"/aws/vendedlogs/states/${var.name}"' in module_text("orchestration")
    assert not any(
        re.search(r'name\s*=\s*"/aws-glue/crawlers', text(p)) for p in TF_FILES
    )


def test_ecr_is_immutable_and_force_deletable() -> None:
    registry = module_text("registry")
    assert 'image_tag_mutability = "IMMUTABLE"' in registry
    assert re.search(r"force_delete\s*=\s*true", registry)


def test_lambda_runs_from_an_x86_image() -> None:
    compute = module_text("compute")
    assert re.search(r'package_type\s*=\s*"Image"', compute)
    assert '["x86_64"]' in compute


def test_fault_injection_removes_only_the_put_statement() -> None:
    compute = module_text("compute")
    assert 'dynamic "statement"' in compute
    assert "var.inject_fault ? [] : [1]" in compute
    assert "s3:PutObject" in compute


def test_event_rule_uses_wildcard_not_prefix_suffix() -> None:
    events = module_text("events")
    assert "wildcard" in events
    assert '"raw/*.csv"' in events
    # Comments may mention prefix/suffix; the pattern itself must not use them as keys.
    assert not re.search(r"\b(prefix|suffix)\s*=", events)


def test_s3_buckets_are_private_and_without_versioning() -> None:
    for name in ("storage", "catalog"):
        body = module_text(name)
        assert re.search(r"block_public_policy\s*=\s*true", body)
        assert "aws_s3_bucket_versioning" not in body


def test_budget_guardrail_is_opt_in() -> None:
    variables = text(INFRA / "variables.tf")
    match = re.search(
        r'variable "enable_budget_guardrail" \{.*?default\s*=\s*(\w+)',
        variables,
        re.DOTALL,
    )
    assert match and match.group(1) == "false"


# --- destroy safety and lab-specific tags -------------------------------------

DESTROY_FLAGS = {
    "aws_s3_bucket": ("force_destroy", 2),  # data bucket + Athena results bucket
    "aws_athena_workgroup": ("force_destroy", 1),
    "aws_ecr_repository": ("force_delete", 1),
}
TAGGABLE_MODULE_RESOURCES = [
    "aws_s3_bucket",
    "aws_ecr_repository",
    "aws_cloudwatch_log_group",
    "aws_iam_role",
    "aws_lambda_function",
    "aws_sfn_state_machine",
    "aws_cloudwatch_event_rule",
    "aws_glue_catalog_database",
    "aws_glue_crawler",
    "aws_athena_workgroup",
]
LAB_TAG_KEYS = {
    "Project",
    "Course",
    "Session",
    "Lab",
    "Environment",
    "Owner",
    "ManagedBy",
    "CostCenter",
}
TEMPLATE_DEFAULTS = {"engineering", "data-engineering"}


def resource_blocks(resource_type: str, files: list[Path] = TF_FILES) -> list[str]:
    pattern = rf'resource "{resource_type}" "[^"]+" \{{(.*?)\n\}}'
    return [
        body for path in files for body in re.findall(pattern, text(path), re.DOTALL)
    ]


def variable_default(name: str) -> str:
    match = re.search(
        rf'variable "{name}" \{{.*?default\s*=\s*"([^"]*)"',
        text(INFRA / "variables.tf"),
        re.DOTALL,
    )
    assert match, name
    return match.group(1)


def test_everything_that_can_block_destroy_forces_it() -> None:
    for resource_type, (flag, expected_count) in DESTROY_FLAGS.items():
        blocks = resource_blocks(resource_type)
        assert len(blocks) == expected_count, resource_type
        for body in blocks:
            assert re.search(rf"{flag}\s*=\s*true", body), f"{resource_type}: {flag}"


def test_common_tags_identify_this_lab() -> None:
    main = text(INFRA / "main.tf")
    block = re.search(r"common_tags = merge\((.*?)\n  \)", main, re.DOTALL)
    assert block
    assert LAB_TAG_KEYS <= set(re.findall(r"^\s+(\w+)\s+=", block.group(1), re.M))
    assert 'Course      = "aws-data-engineer"' in main
    assert 'Lab         = "serverless-orchestration-containers"' in main
    assert 'Session     = "06"' in main


def test_tag_defaults_are_not_the_generic_template_values() -> None:
    assert variable_default("cost_center") not in TEMPLATE_DEFAULTS
    assert variable_default("owner") not in TEMPLATE_DEFAULTS
    assert "s6" in variable_default("cost_center")


def test_every_module_adds_a_component_tag() -> None:
    for name in EXPECTED_MODULES:
        body = text(MODULES / name / "main.tf")
        assert re.search(rf'Component\s*=\s*"{name}"', body), name


def test_module_resources_use_the_component_tags() -> None:
    module_files = sorted(MODULES.rglob("main.tf"))
    for resource_type in TAGGABLE_MODULE_RESOURCES:
        blocks = resource_blocks(resource_type, module_files)
        assert blocks, resource_type
        for body in blocks:
            assert re.search(r"\btags\s*=\s*local\.tags", body), resource_type


def test_state_machine_may_only_start_the_lab_crawler() -> None:
    orchestration = module_text("orchestration")
    statement = re.search(
        r'data "aws_iam_policy_document" "start_crawler" \{(.*?)\n\}',
        orchestration,
        re.DOTALL,
    )
    assert statement, "missing start_crawler policy"
    assert '"glue:StartCrawler"' in statement.group(1)
    assert "resources = [var.crawler_arn]" in statement.group(1)
    assert "crawler_arn" in text(INFRA / "main.tf")
