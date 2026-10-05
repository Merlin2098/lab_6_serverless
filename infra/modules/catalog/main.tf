locals {
  tags = merge(var.tags, { Component = "catalog" })
}

# --- Data Catalog + Crawler -------------------------------------------------
# No log group is declared for the crawler on purpose: Glue crawlers write to
# the shared /aws-glue/crawlers group (name not configurable). See ADR 0001.

resource "aws_glue_catalog_database" "this" {
  name = var.database_name
  tags = local.tags
}

resource "aws_glue_classifier" "orders_csv" {
  name = "${var.name}-orders-csv"

  csv_classifier {
    contains_header = "PRESENT"
    delimiter       = ","
    quote_symbol    = "\""
  }
}

data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "crawler" {
  name               = "${var.name}-crawler"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "glue_service_role" {
  role       = aws_iam_role.crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

data "aws_iam_policy_document" "crawler_s3" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${var.bucket_arn}/${var.processed_prefix}*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.processed_prefix}*"]
    }
  }
}

resource "aws_iam_role_policy" "crawler_s3" {
  name   = "${var.name}-crawler-s3"
  role   = aws_iam_role.crawler.id
  policy = data.aws_iam_policy_document.crawler_s3.json
}

# No schedule: the state machine starts it after every valid file (StartCrawler
# state); `make crawler-start` still works to run it by hand.
resource "aws_glue_crawler" "this" {
  name          = "${var.name}-orders"
  database_name = aws_glue_catalog_database.this.name
  role          = aws_iam_role.crawler.arn
  classifiers   = [aws_glue_classifier.orders_csv.name]

  s3_target {
    path = "s3://${var.bucket_name}/${var.processed_prefix}"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  depends_on = [
    aws_iam_role_policy_attachment.glue_service_role,
    aws_iam_role_policy.crawler_s3,
  ]

  tags = local.tags
}

# --- Athena -----------------------------------------------------------------

resource "aws_s3_bucket" "results" {
  bucket        = var.results_bucket_name
  force_destroy = true # lab: lets `terraform destroy` empty the bucket
  tags          = local.tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "results" {
  bucket = aws_s3_bucket.results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_athena_workgroup" "this" {
  name          = "${var.name}-wg"
  force_destroy = true
  tags          = local.tags

  configuration {
    enforce_workgroup_configuration = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.results.bucket}/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
