variable "project_name" {
  description = "Project name used in AWS resource naming."
  type        = string
  default     = "s6-lab"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"
}

variable "owner" {
  description = "Owner tag applied to all managed resources."
  type        = string
  default     = "datahackers-bootcamp-da"
}

variable "aws_region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "us-east-1"
}

variable "tags" {
  description = "Additional tags applied to all resources."
  type        = map(string)
  default     = {}
}

variable "cost_center" {
  description = "Cost center tag for budget allocation and cost reporting."
  type        = string
  default     = "s6-lab-serverless"
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days. Use 7 for demos and labs; set higher for production per compliance requirements."
  type        = number
  default     = 7
}

variable "glue_database_name" {
  description = "Glue Data Catalog database that holds the lab table."
  type        = string
  default     = "s6_lab_db"
}

variable "image_tag" {
  description = "Tag of the validator image in ECR. The repository is tag-immutable: use a new tag for every image change."
  type        = string
  default     = "1.0.0"
}

variable "inject_fault" {
  description = "Troubleshooting scenario: when true, the Lambda role loses s3:PutObject on the processed prefix."
  type        = bool
  default     = false
}

variable "enable_budget_guardrail" {
  description = "Whether to create the monthly AWS Budget (and its SNS alert topic, if an email is set). Off by default for student/demo use; enable for real deployments."
  type        = bool
  default     = false
}

variable "budget_limit_usd" {
  description = "Monthly AWS budget limit in USD. Alerts fire at 80% (actual) and 100% (forecasted). Only used when enable_budget_guardrail is true."
  type        = number
  default     = 25
}

variable "budget_alert_email" {
  description = "Email address for budget alerts. Leave empty to skip SNS subscription creation. Only used when enable_budget_guardrail is true."
  type        = string
  default     = ""
}
