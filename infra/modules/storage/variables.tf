variable "bucket_name" {
  description = "Name of the data bucket."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
