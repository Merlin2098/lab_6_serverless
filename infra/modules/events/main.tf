locals {
  tags = merge(var.tags, { Component = "events" })
}

# prefix+suffix is S3-native-notification syntax (AND). In an EventBridge
# pattern the values of an array are OR, so a content filter needs `wildcard`.
locals {
  event_pattern = {
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [var.bucket_name] }
      object = { key = [{ wildcard = var.key_pattern }] }
    }
  }
}

resource "aws_cloudwatch_event_rule" "this" {
  name          = "${var.name}-raw-csv"
  description   = "Starts the pipeline when a CSV lands in raw/"
  event_pattern = jsonencode(local.event_pattern)
  tags          = local.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-events-to-sfn"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "start_execution" {
  statement {
    actions   = ["states:StartExecution"]
    resources = [var.state_machine_arn]
  }
}

resource "aws_iam_role_policy" "start_execution" {
  name   = "${var.name}-start-execution"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.start_execution.json
}

resource "aws_cloudwatch_event_target" "this" {
  rule     = aws_cloudwatch_event_rule.this.name
  arn      = var.state_machine_arn
  role_arn = aws_iam_role.this.arn
}
