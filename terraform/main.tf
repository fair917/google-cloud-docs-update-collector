locals {
  bucket_name      = var.bucket_name != "" ? var.bucket_name : "${var.name_prefix}-${var.project_id}"
  job_name         = "${var.name_prefix}-job"
  job_sa_id        = "${var.name_prefix}-job-sa"
  scheduler_sa_id  = "${var.name_prefix}-sched-sa"
  ar_repo_name     = "${var.name_prefix}-docker"
  job_resource_url = "projects/${var.project_id}/locations/${var.region}/jobs/${local.job_name}"
}

# ---- Required APIs ----------------------------------------------------------

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# ---- Artifact Registry (Docker) --------------------------------------------

resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = local.ar_repo_name
  format        = "DOCKER"
  description   = "Container images for ${var.name_prefix}"
  depends_on    = [google_project_service.apis]
}

# ---- GCS bucket -------------------------------------------------------------

resource "google_storage_bucket" "state" {
  name                        = local.bucket_name
  location                    = var.bucket_location
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age                = 90
      with_state         = "ARCHIVED"
      matches_prefix     = ["snapshots/", "diffs/"]
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

# ---- Service accounts -------------------------------------------------------

resource "google_service_account" "job" {
  account_id   = local.job_sa_id
  display_name = "${var.name_prefix} Cloud Run Job runtime SA"
}

resource "google_service_account" "scheduler" {
  account_id   = local.scheduler_sa_id
  display_name = "${var.name_prefix} Cloud Scheduler invoker SA"
}

resource "google_storage_bucket_iam_member" "job_object_admin" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.job.email}"
}

# Scheduler needs to invoke the Job. roles/run.invoker grants jobs.run.
resource "google_project_iam_member" "scheduler_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

# ---- Cloud Run Job ----------------------------------------------------------

resource "google_cloud_run_v2_job" "collector" {
  name     = local.job_name
  location = var.region

  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account       = google_service_account.job.email
      timeout               = "${var.job_timeout_seconds}s"
      max_retries           = var.job_max_retries

      containers {
        image = var.image_uri

        env {
          name  = "GCDOCS__BUCKET"
          value = google_storage_bucket.state.name
        }
        env {
          name  = "LOG_LEVEL"
          value = "INFO"
        }

        resources {
          limits = {
            cpu    = var.job_cpu
            memory = var.job_memory
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_storage_bucket_iam_member.job_object_admin,
  ]
}

# ---- Cloud Scheduler (twice daily) ------------------------------------------

resource "google_cloud_scheduler_job" "morning" {
  name      = "${var.name_prefix}-morning"
  region    = var.region
  schedule  = var.schedule_morning_cron
  time_zone = var.schedule_time_zone

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/v2/${local.job_resource_url}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_cloud_run_v2_job.collector]
}

resource "google_cloud_scheduler_job" "evening" {
  name      = "${var.name_prefix}-evening"
  region    = var.region
  schedule  = var.schedule_evening_cron
  time_zone = var.schedule_time_zone

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/v2/${local.job_resource_url}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_cloud_run_v2_job.collector]
}
