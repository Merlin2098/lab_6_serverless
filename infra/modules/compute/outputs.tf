output "function_arn" {
  description = "Validator Lambda ARN."
  value       = aws_lambda_function.this.arn
}

output "function_name" {
  description = "Validator Lambda name."
  value       = aws_lambda_function.this.function_name
}

output "role_arn" {
  description = "Lambda execution role ARN."
  value       = aws_iam_role.this.arn
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the function)."
  value       = aws_lambda_function.this.arn
}

output "log_group_name" {
  description = "CloudWatch log group name of the function."
  value       = aws_cloudwatch_log_group.this.name
}

output "log_group_arn" {
  description = "CloudWatch log group ARN of the function."
  value       = aws_cloudwatch_log_group.this.arn
}
