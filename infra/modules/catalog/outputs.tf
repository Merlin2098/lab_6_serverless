output "crawler_name" {
  description = "Glue crawler name."
  value       = aws_glue_crawler.this.name
}

output "database_name" {
  description = "Glue Data Catalog database name."
  value       = aws_glue_catalog_database.this.name
}

output "workgroup_name" {
  description = "Athena workgroup name."
  value       = aws_athena_workgroup.this.name
}

output "results_bucket_name" {
  description = "Athena results bucket name."
  value       = aws_s3_bucket.results.bucket
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the crawler)."
  value       = aws_glue_crawler.this.arn
}
