variable "name" {
  description = "Lambda function name (also used for the log group and role)."
  type        = string
}

variable "image_uri" {
  description = "Full image URI including tag, e.g. <repo-url>:1.0.0."
  type        = string
}

variable "bucket_arn" {
  description = "ARN of the data bucket the function reads from and writes to."
  type        = string
}

variable "raw_prefix" {
  description = "Input prefix the function may read (s3:GetObject)."
  type        = string
}

variable "processed_prefix" {
  description = "Output prefix the function may write (s3:PutObject)."
  type        = string
}

variable "required_columns" {
  description = "CSV columns the validator requires."
  type        = list(string)
  default     = ["order_id", "customer_id", "amount", "status"]
}

variable "inject_fault" {
  description = "When true, the role loses s3:PutObject on the processed prefix (troubleshooting scenario)."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
}

variable "memory_size" {
  description = "Lambda memory in MB."
  type        = number
  default     = 256
}

variable "timeout" {
  description = "Lambda timeout in seconds."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
