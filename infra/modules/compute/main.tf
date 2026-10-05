locals {
  tags = merge(var.tags, { Component = "compute" })
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-exec"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "logs" {
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "${var.name}-logs"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.logs.json
}

# Read raw/*; write processed/orders/*. With inject_fault the write statement
# is omitted: the Lambda then fails with AccessDenied on PutObject, which is the
# Troubleshoot scenario (diagnose in $.error and CloudWatch, then `-var inject_fault=false`).
data "aws_iam_policy_document" "s3_access" {
  statement {
    sid       = "ReadRaw"
    actions   = ["s3:GetObject"]
    resources = ["${var.bucket_arn}/${var.raw_prefix}*"]
  }

  dynamic "statement" {
    for_each = var.inject_fault ? [] : [1]

    content {
      sid       = "WriteProcessed"
      actions   = ["s3:PutObject"]
      resources = ["${var.bucket_arn}/${var.processed_prefix}*"]
    }
  }
}

resource "aws_iam_role_policy" "s3_access" {
  name   = "${var.name}-s3-access"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.s3_access.json
}

resource "aws_lambda_function" "this" {
  function_name = var.name
  role          = aws_iam_role.this.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["x86_64"]
  memory_size   = var.memory_size
  timeout       = var.timeout

  environment {
    variables = {
      PROCESSED_PREFIX = var.processed_prefix
      REQUIRED_COLUMNS = join(",", var.required_columns)
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.this,
    aws_iam_role_policy.logs,
    aws_iam_role_policy.s3_access,
  ]

  tags = local.tags
}
