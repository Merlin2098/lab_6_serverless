# Validator Lambda as a container image.
# Build context is the repo root (see `make docker-build`); the dockerignore
# next to this file whitelists only the handler.
#
# The Lambda base image already ships the Runtime Interface Client and boto3,
# so no requirements.txt is needed. Add one here if the handler gains
# dependencies (e.g. pyarrow for the E6 Parquet extension).
#
# PYTHON_VERSION must be a runtime currently supported by Lambda. Check the
# Lambda runtimes list before the session; override with
# `make docker-build PYTHON_VERSION=...`.
ARG PYTHON_VERSION=3.13
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION}

COPY src/lambdas/validator/app.py ${LAMBDA_TASK_ROOT}/

CMD ["app.handler"]
