variable "name" {
  description = "Rule name prefix."
  type        = string
}

variable "bucket_name" {
  description = "Bucket whose Object Created events trigger the pipeline."
  type        = string
}

variable "state_machine_arn" {
  description = "State machine started by the rule."
  type        = string
}

variable "key_pattern" {
  description = "EventBridge wildcard on the object key. Only raw/*.csv fires the pipeline; processed/ never does (no recursive invocation)."
  type        = string
  default     = "raw/*.csv"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
