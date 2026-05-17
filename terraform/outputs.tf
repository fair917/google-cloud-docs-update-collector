output "bucket_name" {
  value = google_storage_bucket.state.name
}

output "artifact_registry_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}

output "cloud_run_job_name" {
  value = google_cloud_run_v2_job.collector.name
}

output "job_service_account" {
  value = google_service_account.job.email
}

output "scheduler_service_account" {
  value = google_service_account.scheduler.email
}
