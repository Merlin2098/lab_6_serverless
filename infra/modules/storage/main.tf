locals {
  tags = merge(var.tags, { Component = "storage" })
}

resource "aws_s3_bucket" "this" {
  bucket        = var.bucket_name
  force_destroy = true # lab: lets `terraform destroy` empty the bucket
  tags          = local.tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Sends "Object Created" events to the default EventBridge bus. It takes a few
# minutes to become effective after apply.
resource "aws_s3_bucket_notification" "this" {
  bucket      = aws_s3_bucket.this.id
  eventbridge = true
}
