# DriftGuard – Local Demo (Docker Provider)
# ──────────────────────────────────────────
# This creates a simple Docker container that you can mutate
# manually to simulate infrastructure drift.

terraform {
  required_version = ">= 1.0"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

# ── Docker image ──────────────────────────────────────────────
resource "docker_image" "nginx" {
  name         = "nginx:alpine"
  keep_locally = true
}

# ── Docker container ──────────────────────────────────────────
resource "docker_container" "demo" {
  image = docker_image.nginx.image_id
  name  = "driftguard_demo"

  ports {
    internal = 80
    external = 8080
  }

  env = [
    "ENV=dev",
    "MANAGED_BY=driftguard",
  ]

  labels {
    label = "env"
    value = "dev"
  }

  labels {
    label = "managed_by"
    value = "driftguard"
  }
}
