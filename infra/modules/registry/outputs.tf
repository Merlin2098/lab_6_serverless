output "repository_url" {
  description = "Repository URL (without tag)."
  value       = aws_ecr_repository.this.repository_url
}

output "repository_arn" {
  description = "Repository ARN."
  value       = aws_ecr_repository.this.arn
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the repository)."
  value       = aws_ecr_repository.this.arn
}
