# DriftGuard – AWS Cloud Example
# ─────────────────────────────────────────────────────────
# Demonstrates drift detection on real AWS resources.
# Prerequisites: AWS CLI configured, valid credentials.

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state with locking (recommended for cloud)
  backend "s3" {
    bucket         = "driftguard-tfstate"
    key            = "demo/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "driftguard-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project    = "DriftGuard"
      ManagedBy  = "terraform"
      Env        = var.environment
    }
  }
}

# ── Variables ──────────────────────────────────────────────
variable "aws_region" {
  default = "us-east-1"
}

variable "environment" {
  default = "dev"
}

# ── S3 bucket (easy to mutate for drift demo) ─────────────
resource "aws_s3_bucket" "demo" {
  bucket = "driftguard-demo-${var.environment}"

  tags = {
    Name = "driftguard-demo"
    env  = var.environment
  }
}

resource "aws_s3_bucket_versioning" "demo" {
  bucket = aws_s3_bucket.demo.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ── Security group (high-risk resource for classification) ─
resource "aws_security_group" "demo" {
  name        = "driftguard-demo-sg"
  description = "DriftGuard demo security group"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "driftguard-demo-sg"
    env  = var.environment
  }
}

# ── Outputs ────────────────────────────────────────────────
output "bucket_name" {
  value = aws_s3_bucket.demo.bucket
}

output "security_group_id" {
  value = aws_security_group.demo.id
}
