variable "name" {
  description = "Name prefix for the crawler, role and Athena workgroup."
  type        = string
}

variable "bucket_name" {
  description = "Data bucket name."
  type        = string
}

variable "bucket_arn" {
  description = "Data bucket ARN."
  type        = string
}

variable "processed_prefix" {
  description = "Prefix the crawler scans (the table name is derived from its last folder, e.g. orders)."
  type        = string
}

variable "database_name" {
  description = "Glue Data Catalog database."
  type        = string
}

variable "results_bucket_name" {
  description = "Name of the Athena query results bucket."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
