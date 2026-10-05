output "state_machine_arn" {
  description = "State machine ARN."
  value       = aws_sfn_state_machine.this.arn
}

output "state_machine_name" {
  description = "State machine name."
  value       = aws_sfn_state_machine.this.name
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the state machine)."
  value       = aws_sfn_state_machine.this.arn
}

output "log_group_name" {
  description = "CloudWatch log group name of the state machine."
  value       = aws_cloudwatch_log_group.this.name
}

output "log_group_arn" {
  description = "CloudWatch log group ARN of the state machine."
  value       = aws_cloudwatch_log_group.this.arn
}
