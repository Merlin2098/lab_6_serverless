locals {
  tags = merge(var.tags, { Component = "registry" })
}

resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE" # every image change needs a new tag
  force_delete         = true        # lab: lets `terraform destroy` remove a repo that holds images
  tags                 = local.tags
}

# Lets the Lambda service pull the image (spec section 13).
data "aws_iam_policy_document" "lambda_pull" {
  statement {
    sid    = "LambdaECRImageRetrievalPolicy"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
  }
}

resource "aws_ecr_repository_policy" "lambda_pull" {
  repository = aws_ecr_repository.this.name
  policy     = data.aws_iam_policy_document.lambda_pull.json
}
