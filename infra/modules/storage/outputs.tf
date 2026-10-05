output "bucket_name" {
  description = "Data bucket name."
  value       = aws_s3_bucket.this.bucket
}

output "bucket_arn" {
  description = "Data bucket ARN."
  value       = aws_s3_bucket.this.arn
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the bucket)."
  value       = aws_s3_bucket.this.arn
}
