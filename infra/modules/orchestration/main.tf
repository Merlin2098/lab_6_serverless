locals {
  tags = merge(var.tags, { Component = "orchestration" })
}

# The /aws/vendedlogs/states/ prefix is the one recommended for Step Functions
# log groups (keeps the log-delivery resource policy small).
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/vendedlogs/states/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-sfn"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "invoke_lambda" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [var.lambda_arn]
  }
}

resource "aws_iam_role_policy" "invoke_lambda" {
  name   = "${var.name}-invoke-lambda"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.invoke_lambda.json
}

# StartCrawler state: the state machine may start this one crawler and nothing else.
data "aws_iam_policy_document" "start_crawler" {
  statement {
    actions   = ["glue:StartCrawler"]
    resources = [var.crawler_arn]
  }
}

resource "aws_iam_role_policy" "start_crawler" {
  name   = "${var.name}-start-crawler"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.start_crawler.json
}

# The CloudWatch Logs log-delivery APIs do not support resource-level
# permissions, so Resource "*" is required here (and only here).
data "aws_iam_policy_document" "log_delivery" {
  statement {
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "log_delivery" {
  name   = "${var.name}-log-delivery"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.log_delivery.json
}

resource "aws_sfn_state_machine" "this" {
  name     = var.name
  role_arn = aws_iam_role.this.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/pipeline.asl.json.tftpl", {
    lambda_arn   = var.lambda_arn
    crawler_name = var.crawler_name
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.this.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  depends_on = [
    aws_iam_role_policy.invoke_lambda,
    aws_iam_role_policy.start_crawler,
    aws_iam_role_policy.log_delivery,
  ]

  tags = local.tags
}
