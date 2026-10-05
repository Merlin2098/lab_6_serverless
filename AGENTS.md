# AGENTS.md

## Purpose

This file defines the working contract for AI agents in the current project.
It is intentionally project-name agnostic so it remains valid when copied into
or used to bootstrap another repository.

Agents should first inspect the repository and its active capabilities before
assuming a language, cloud provider, framework, or infrastructure stack.
Typical supported work may include:

* Python data jobs and helpers
* SQL transformations
* Terraform infrastructure
* Application and frontend code
* Config-driven workflows
* Lightweight testing and packaging workflows

---

## Operating Behaviour

When assisting in a project that contains this guidance:

* Understand the objective and current repository shape before acting
* Search for existing implementations before proposing new files; prefer
  modifying or extending existing code over creating new files or parallel
  structures — only create new files when no equivalent exists or the user
  explicitly requests it
* Apply the conventions and policies below as guidance, not as rigid rules
* Prefer simple, explicit changes over frameworks or abstractions
* Validate the result against the principles and policies in this file
* For AWS/Terraform reference material (service behavior, resource syntax,
  current limits), consult the AWS Documentation and Terraform MCP servers
  live rather than relying on local guidance files — this file states the
  project's own conventions, not a mirror of vendor docs

The agent must not:

* create orchestration frameworks, skill composition systems, or meta-systems
* introduce hidden framework-like behavior
* maintain a local library of guidance files that duplicates what an MCP
  server already provides live

---

## Execution Rules

Use explicit project commands only.

Preferred workflow:

* run scripts directly with `python scripts/<script>.py`
* use Git Bash as the default terminal; use the documented wrapper flow under `scripts/python/`
* run Terraform commands directly and intentionally from `infra/`

Do not introduce hidden automation.

---

## Package Manager Awareness

Projects using this guidance use [`uv`](https://docs.astral.sh/uv/) with
`pyproject.toml` for Python dependency management.

Inspect `pyproject.toml` (`[project.dependencies]` and the `dev`
`[dependency-groups]` entry) to resolve active dependencies. Use `uv sync` to
create/update `.venv` and install everything (add `--no-group dev` to skip
development tooling). AWS Lambda/Glue jobs that need an isolated dependency
set get their own `requirements-<job>.txt`, generated from `pyproject.toml`
via `uv export` rather than hand-maintained pip installs.

---

## Approval Boundaries

### Never without approval

* `terraform apply`
* `terraform destroy`
* modify infrastructure state
* overwrite data or generated artifacts intentionally owned by users

### Ask before

* IAM changes
* Terraform module changes
* paid AWS services or production-grade infrastructure defaults
* data contract updates
* budget limit or alert email changes
* CloudWatch log group deletion or retention reduction

---

## Principles

* separation of concerns across infra, code, and config
* SQL separate from Python
* config-driven pipelines
* contracts-first validation
* prefer simple over complex
* keep workflows explicit and reproducible

---

## Governance

### Spec before code (advisory)

Before implementing a significant feature or architectural change, a spec is
desirable. For small tasks, quick fixes, or exploratory work where the scope
is clear, a spec is optional. If a task looks significant and no spec exists,
mention it once and offer to create one — do not block the work.

### ADR before architecture change (required)

Any decision that changes the overall architecture (adding a new service,
replacing a technology, changing a data contract) must be recorded in an ADR
under `docs/internal/adr/` before implementation begins. Use the standard ADR
format: title, status, context, decision, consequences.

### Configuration over hardcoding (required)

Values that differ between environments (URLs, bucket names, credentials,
feature flags, thresholds) must live in configuration files or environment
variables, never hardcoded in source. Applies to Python, SQL, Terraform
variable defaults, and CI/CD workflows.

### Security by default (required)

Every new resource, endpoint, or data store must be private and
least-privilege from day one. Security must not be retrofitted.

* S3 buckets: block public access, use OAC for CloudFront
* IAM: explicit deny on unused actions; no wildcard resources in production
* APIs: authentication required; no unauthenticated endpoints without
  explicit justification
* Secrets: never in source code; use environment variables or AWS Secrets
  Manager
* Database: no direct production access; changes through migrations only

### Never send sensitive files to external services (required)

Never pass credentials, keys, or secrets to external APIs, compression
tools, or any third-party service boundary. This includes `.env` files and
variants, private key files (`.pem`, `.key`, `.p12`, `.pfx`, `.asc`, `.gpg`),
files named `credentials`/`secrets`/`passwords`, and content from
`~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`, `~/.docker`. Refuse and explain
the risk if a task would require sending this content to an external
service.

### Prefer the simplest working solution (advisory)

Before writing new code, adding a dependency, or introducing an abstraction,
climb this ladder and stop at the first rung that holds:

1. Does this need to exist at all? (YAGNI)
2. Does the stdlib do it?
3. Does a native platform feature cover it?
4. Does an already-installed dependency solve it?
5. Can it be one line?
6. Only then: the minimum code that works.

Apply it silently; only surface the reasoning if a simplification was
non-obvious or an alternative was skipped. Never simplify away input
validation at trust boundaries, error handling that prevents data loss,
security controls, or mandatory tags/log retention (see AWS/Terraform
guardrails below). A deliberate shortcut with a known ceiling gets a
`# debt:` comment naming the ceiling and upgrade trigger.

### AWS/Terraform operational guardrails (required)

Applies to any project using AWS and/or Terraform.

The agent MUST:

* declare `aws_cloudwatch_log_group` explicitly for every service that
  produces logs, and set `retention_in_days` on every log group — never omit
  it
* gate `aws_budgets_budget` behind `enable_budget_guardrail` (default
  `false`); opt-in for student/demo deployments, enabled explicitly for real
  or long-lived environments
* apply a common tag set (including `CostCenter`) to every resource
* expose `log_group_name`, `log_group_arn`, and `resource_arn` as outputs in
  every module
* generate `tests/aws/` Python/boto3 validation tests when deploying AWS
  infrastructure
* validate IAM roles before applying infrastructure changes

The agent MUST NOT:

* delete or overwrite `terraform.tfstate`
* enable S3 versioning by default — only when explicitly requested and
  justified
* assume implicit IAM permissions — all permissions must be declared in
  Terraform
* create resources without mandatory tags
* omit `retention_in_days` on CloudWatch log groups

### IAM cross-module placement rule (required)

When a resource in module A requires a permission whose target ARN is only
known inside module B, declare the `aws_iam_role_policy` in module B (where
the ARN is available), not in module A. Placing it in module A would require
passing the ARN back and creates a circular dependency.

**Canonical example — Lambda DLQ:** the `aws_sqs_queue` (DLQ) lives in the
`lambda` module. AWS validates `sqs:SendMessage` on that ARN at function
creation time. Therefore the inline policy granting `sqs:SendMessage` must be
declared in the `lambda` module, attached to the execution role name received
as a variable — not in the `iam` module.

---

## Philosophy

Simple. Explicit. Reproducible.

AI is a helper for the current project, not the system itself.
