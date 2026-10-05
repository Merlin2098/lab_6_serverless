variable "name" {
  description = "State machine name."
  type        = string
}

variable "lambda_arn" {
  description = "ARN of the Lambda invoked by the Validate state."
  type        = string
}

variable "crawler_name" {
  description = "Name of the Glue crawler started by the StartCrawler state."
  type        = string
}

variable "crawler_arn" {
  description = "ARN of that crawler (the only resource the state machine may start)."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
