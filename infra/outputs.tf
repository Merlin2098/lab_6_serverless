output "bucket_name" {
  description = "Data bucket (raw/ input, processed/ output)."
  value       = module.storage.bucket_name
}

output "ecr_repository_url" {
  description = "ECR repository URL for the validator image."
  value       = module.registry.repository_url
}

output "budget_name" {
  description = "AWS Budget name for monthly cost governance. Empty string when enable_budget_guardrail is false."
  value       = var.enable_budget_guardrail ? aws_budgets_budget.monthly[0].name : ""
}

output "budget_alert_sns_arn" {
  description = "SNS topic ARN for budget alerts. Empty string when the guardrail is disabled or no alert email is configured."
  value       = var.enable_budget_guardrail && var.budget_alert_email != "" ? aws_sns_topic.budget_alerts[0].arn : ""
}

output "lambda_function_name" {
  description = "Validator Lambda name."
  value       = module.compute.function_name
}

output "log_group_name" {
  description = "CloudWatch log group name of the validator Lambda."
  value       = module.compute.log_group_name
}

output "log_group_arn" {
  description = "CloudWatch log group ARN of the validator Lambda."
  value       = module.compute.log_group_arn
}

output "state_machine_arn" {
  description = "Pipeline state machine ARN."
  value       = module.orchestration.state_machine_arn
}

output "state_machine_log_group_name" {
  description = "CloudWatch log group name of the state machine."
  value       = module.orchestration.log_group_name
}

output "event_rule_name" {
  description = "EventBridge rule that starts the pipeline."
  value       = module.events.rule_name
}

output "crawler_name" {
  description = "Glue crawler that catalogs processed/orders/."
  value       = module.catalog.crawler_name
}

output "glue_database_name" {
  description = "Glue Data Catalog database."
  value       = module.catalog.database_name
}

output "athena_workgroup" {
  description = "Athena workgroup for the lab."
  value       = module.catalog.workgroup_name
}
