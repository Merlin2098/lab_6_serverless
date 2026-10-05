# Thin wrapper over the explicit commands of the lab (Docker/ECR, AWS CLI).
# Every recipe echoes the real command before running it; nothing is hidden.
# Run `make help` for the target list.
#
# Terraform is NOT wrapped here: run `terraform -chdir=infra ...` yourself
# (init, plan, apply, destroy, output). See docs/deploy/guia_deploy.md.
#
# Requires GNU Make and Git Bash. Credentials come from the environment or
# `aws configure` (never from this file).
#
# Values that depend on the deployed stack are read (read-only) from the
# Terraform outputs (infra/outputs.tf) and can be overridden on the command line:
#   ecr_repository_url, bucket_name, crawler_name, glue_database_name,
#   athena_workgroup, state_machine_arn
#
# Troubleshooting: if Terraform fails talking to the AWS provider with
# "x509: certificate signed by unknown authority" (local plugin handshake, seen
# on some Windows setups), run `export TF_DISABLE_PLUGIN_TLS=1` in your shell
# first. It only disables TLS on the loopback link between terraform and its
# own provider process.

SHELL := bash
.DEFAULT_GOAL := help

# --- Configuration ----------------------------------------------------------
PYTHON           ?= python
TF               ?= terraform -chdir=infra
REGION           ?= $(or $(AWS_DEFAULT_REGION),us-east-1)

PYTHON_VERSION   ?= 3.13
PLATFORM         ?= linux/amd64
IMAGE_NAME       ?= validator
DOCKERFILE       ?= docker/validator/Dockerfile
LAMBDA_SRC       ?= src/lambdas/validator/app.py
LOCAL_PORT       ?= 9000

# TAG has no default on purpose: the ECR repository is tag-immutable, so each
# image change needs a new tag (make image-publish TAG=1.0.1). Never "latest".
TAG              ?=

# Lazily evaluated (recursive `?=`): Terraform is only queried when used.
# `terraform output -raw` prints a warning on stdout (exit 0) when the stack is
# not applied, so read -json and keep only real string values.
tfout            = $(shell $(TF) output -no-color -json $(1) 2>/dev/null | sed -n 's/^"\(.*\)"$$/\1/p')
REPO_URI         ?= $(call tfout,ecr_repository_url)
BUCKET           ?= $(call tfout,bucket_name)
CRAWLER          ?= $(call tfout,crawler_name)
GLUE_DB          ?= $(call tfout,glue_database_name)
ATHENA_WORKGROUP ?= $(call tfout,athena_workgroup)
STATE_MACHINE_ARN ?= $(call tfout,state_machine_arn)

REGISTRY          = $(firstword $(subst /, ,$(REPO_URI)))
REPO_NAME         = $(patsubst $(REGISTRY)/%,%,$(REPO_URI))

# upload
FILE             ?=
PREFIX           ?= raw/

# local-invoke
PAYLOAD          ?= {}

# athena-query
ATHENA_SQL       ?= SELECT status, COUNT(*) AS filas, SUM(amount) AS total FROM $(GLUE_DB).orders GROUP BY status

.PHONY: help preflight \
        ecr-login docker-build docker-push image-publish ecr-digest \
        docker-run-local local-invoke \
        smoke e2e executions \
        gen-orders upload upload-generated crawler-start crawler-status athena-query \
        test lint \
        require-tag require-repo require-lambda-src require-crawler require-athena

# --- Help -------------------------------------------------------------------
help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

preflight: ## Check docker daemon, AWS CLI, Terraform and AWS credentials
	docker version --format 'docker server {{.Server.Version}}'
	aws --version
	terraform version
	aws sts get-caller-identity --region $(REGION)

# --- Lambda package / container image ---------------------------------------
require-tag:
	@test -n "$(TAG)" || { echo "TAG is required (immutable tags), e.g. make $(firstword $(MAKECMDGOALS)) TAG=1.0.0"; exit 1; }

require-repo:
	@test -n "$(REPO_URI)" || { echo "REPO_URI is empty: apply the stack first (output ecr_repository_url) or pass REPO_URI=..."; exit 1; }

require-crawler:
	@test -n "$(CRAWLER)" || { echo "CRAWLER is empty: apply the stack first (output crawler_name) or pass CRAWLER=..."; exit 1; }

require-athena:
	@test -n "$(ATHENA_WORKGROUP)" -a -n "$(GLUE_DB)" || { echo "ATHENA_WORKGROUP/GLUE_DB empty: apply the stack first (outputs athena_workgroup, glue_database_name) or pass them"; exit 1; }

require-lambda-src:
	@test -f "$(LAMBDA_SRC)" || { echo "Missing $(LAMBDA_SRC): the validator handler is not implemented yet"; exit 1; }

ecr-login: require-repo ## docker login to ECR (token valid 12 hours)
	aws ecr get-login-password --region $(REGION) | docker login --username AWS --password-stdin $(REGISTRY)

docker-build: require-tag require-lambda-src ## Build the image (TAG=x.y.z)
	docker build --platform $(PLATFORM) --provenance=false --build-arg PYTHON_VERSION=$(PYTHON_VERSION) -f $(DOCKERFILE) -t $(IMAGE_NAME):$(TAG) .

docker-push: require-tag require-repo ecr-login ## Tag and push the image to ECR (TAG=x.y.z)
	docker tag $(IMAGE_NAME):$(TAG) $(REPO_URI):$(TAG)
	docker push $(REPO_URI):$(TAG)

# ECR is tag-immutable, so pushing the same tag twice fails: publish only when missing.
image-publish: require-tag require-repo ## Build and push TAG unless it is already in ECR
	@if aws ecr describe-images --region $(REGION) --repository-name $(REPO_NAME) --image-ids imageTag=$(TAG) >/dev/null 2>&1; then \
	  echo "Image $(REPO_URI):$(TAG) is already in ECR: skipping build and push."; \
	  echo "If you changed the Lambda code, it was NOT published: use a NEW tag, e.g. make image-publish TAG=<new> && terraform -chdir=infra apply -var image_tag=<new>"; \
	else \
	  $(MAKE) docker-build docker-push TAG=$(TAG); \
	fi

ecr-digest: require-tag require-repo ## Show the digest of a pushed tag (tag vs digest)
	aws ecr describe-images --region $(REGION) --repository-name $(REPO_NAME) --image-ids imageTag=$(TAG) --query 'imageDetails[0].[imageTags[0],imageDigest]' --output text

docker-run-local: require-tag ## Run the image locally with the Lambda emulator on localhost (LOCAL_PORT)
	docker run --rm -p $(LOCAL_PORT):8080 $(IMAGE_NAME):$(TAG)

local-invoke: ## POST PAYLOAD to the local emulator (run docker-run-local first)
	curl -s -XPOST "http://localhost:$(LOCAL_PORT)/2015-03-31/functions/function/invocations" -d '$(PAYLOAD)'; echo

# --- Lab flow ---------------------------------------------------------------
smoke: ## Upload the valid (F1) and the invalid sample to raw/
	$(MAKE) upload FILE=data/samples/orders_2026_10_04.csv
	$(MAKE) upload FILE=data/samples/orders_invalid.csv

e2e: ## End-to-end check of the deployed stack with boto3 (takes a few minutes)
	uv run python scripts/check_deployed_pipeline.py

executions: ## Last 10 executions of the state machine
	@test -n "$(STATE_MACHINE_ARN)" || { echo "STATE_MACHINE_ARN is empty: apply the stack first (output state_machine_arn)"; exit 1; }
	aws stepfunctions list-executions --region $(REGION) --state-machine-arn $(STATE_MACHINE_ARN) --max-items 10 --query 'executions[*].[name,status,startDate]' --output table

# --- Pipeline use and verification ------------------------------------------
# No arguments: the script picks free dates and order_ids by itself. For other
# sizes or an invalid file, run it directly: python scripts/generate_orders.py --help
gen-orders: ## Generate new order CSVs in data/generated/ (unique names, never overwrites an earlier upload)
	uv run python scripts/generate_orders.py

upload: ## Upload FILE to s3://BUCKET/PREFIX (default raw/)
	@test -n "$(FILE)" || { echo "FILE is required, e.g. make upload FILE=data/orders_2026_10_04.csv"; exit 1; }
	@test -n "$(BUCKET)" || { echo "BUCKET is empty: apply the stack first (output bucket_name) or pass BUCKET=..."; exit 1; }
	aws s3 cp "$(FILE)" "s3://$(BUCKET)/$(PREFIX)" --region $(REGION)

upload-generated: ## Upload every CSV in data/generated/ to s3://BUCKET/PREFIX (default raw/)
	@test -n "$(BUCKET)" || { echo "BUCKET is empty: apply the stack first (output bucket_name) or pass BUCKET=..."; exit 1; }
	@ls data/generated/*.csv >/dev/null 2>&1 || { echo "No CSV in data/generated/: run 'make gen-orders' first"; exit 1; }
	aws s3 cp data/generated "s3://$(BUCKET)/$(PREFIX)" --recursive --exclude "*" --include "*.csv" --region $(REGION)

crawler-start: require-crawler ## Start the Glue crawler
	aws glue start-crawler --name $(CRAWLER) --region $(REGION)

crawler-status: require-crawler ## Show the crawler state (wait for READY)
	aws glue get-crawler --name $(CRAWLER) --region $(REGION) --query 'Crawler.State' --output text

athena-query: require-athena ## Run ATHENA_SQL in the lab workgroup and print the result
	qid=$$(aws athena start-query-execution --region $(REGION) --work-group "$(ATHENA_WORKGROUP)" --query-string "$(ATHENA_SQL)" --query QueryExecutionId --output text) || exit 1; \
	echo "QueryExecutionId: $$qid"; \
	while :; do \
	  state=$$(aws athena get-query-execution --region $(REGION) --query-execution-id $$qid --query QueryExecution.Status.State --output text); \
	  echo "state: $$state"; \
	  case $$state in QUEUED|RUNNING) sleep 2;; *) break;; esac; \
	done; \
	test "$$state" = SUCCEEDED || { aws athena get-query-execution --region $(REGION) --query-execution-id $$qid --query QueryExecution.Status.StateChangeReason --output text; exit 1; }; \
	aws athena get-query-results --region $(REGION) --query-execution-id $$qid --query 'ResultSet.Rows[*].Data[*].VarCharValue' --output text

# --- Quality ----------------------------------------------------------------
test: ## Run pytest (non-cloud tests, in the uv environment)
	uv run python scripts/testing/run_pytest.py

lint: ## Run ruff check (ruff lives in the uv environment)
	uv run python scripts/testing/run_ruff_check.py
