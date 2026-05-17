variable "project_id" {
  description = "GCP project ID where everything is deployed."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run Job, Artifact Registry, Scheduler."
  type        = string
  default     = "asia-northeast1"
}

variable "name_prefix" {
  description = "Prefix applied to all created resource names."
  type        = string
  default     = "gcdocs-collector"
}

variable "bucket_location" {
  description = "Location of the state/snapshots bucket (region or multi-region)."
  type        = string
  default     = "ASIA-NORTHEAST1"
}

variable "bucket_name" {
  description = "Override bucket name. If empty, derived from name_prefix + project_id."
  type        = string
  default     = ""
}

variable "image_uri" {
  description = "Fully qualified container image for the Cloud Run Job (Artifact Registry)."
  type        = string
}

variable "schedule_morning_cron" {
  description = "Cron for the morning run, in Asia/Tokyo."
  type        = string
  default     = "0 3 * * *"
}

variable "schedule_evening_cron" {
  description = "Cron for the evening run, in Asia/Tokyo."
  type        = string
  default     = "0 19 * * *"
}

variable "schedule_time_zone" {
  description = "Time zone for both schedules."
  type        = string
  default     = "Asia/Tokyo"
}

variable "job_timeout_seconds" {
  description = "Cloud Run Job task timeout."
  type        = number
  default     = 3600
}

variable "job_cpu" {
  type    = string
  default = "1"
}

variable "job_memory" {
  type    = string
  default = "1Gi"
}

variable "job_max_retries" {
  type    = number
  default = 1
}
