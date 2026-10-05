data "aws_caller_identity" "current" {}

locals {
  name_prefix      = lower(replace("${var.project_name}-${var.environment}", "_", "-"))
  account_id       = data.aws_caller_identity.current.account_id
  raw_prefix       = "raw/"
  processed_prefix = "processed/orders/"
  common_tags = merge(
    var.tags,
    {
      Project     = var.project_name
      Course      = "aws-data-engineer"
      Session     = "06"
      Lab         = "serverless-orchestration-containers"
      Environment = var.environment
      Owner       = var.owner
      ManagedBy   = "Terraform"
      CostCenter  = var.cost_center
    }
  )
}

module "storage" {
  source      = "./modules/storage"
  bucket_name = "${local.name_prefix}-${local.account_id}-data"
  tags        = local.common_tags
}

module "registry" {
  source = "./modules/registry"
  name   = "${local.name_prefix}-validator"
  tags   = local.common_tags
}

module "compute" {
  source             = "./modules/compute"
  name               = "${local.name_prefix}-validator"
  image_uri          = "${module.registry.repository_url}:${var.image_tag}"
  bucket_arn         = module.storage.bucket_arn
  raw_prefix         = local.raw_prefix
  processed_prefix   = local.processed_prefix
  inject_fault       = var.inject_fault
  log_retention_days = var.log_retention_days
  tags               = local.common_tags
}

module "orchestration" {
  source             = "./modules/orchestration"
  name               = "${local.name_prefix}-pipeline"
  lambda_arn         = module.compute.function_arn
  crawler_name       = module.catalog.crawler_name
  crawler_arn        = module.catalog.resource_arn
  log_retention_days = var.log_retention_days
  tags               = local.common_tags
}

module "events" {
  source            = "./modules/events"
  name              = local.name_prefix
  bucket_name       = module.storage.bucket_name
  state_machine_arn = module.orchestration.state_machine_arn
  tags              = local.common_tags
}

module "catalog" {
  source              = "./modules/catalog"
  name                = local.name_prefix
  bucket_name         = module.storage.bucket_name
  bucket_arn          = module.storage.bucket_arn
  processed_prefix    = local.processed_prefix
  database_name       = var.glue_database_name
  results_bucket_name = "${local.name_prefix}-${local.account_id}-athena-results"
  tags                = local.common_tags
}
