variable "name" {
  description = "ECR repository name."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
