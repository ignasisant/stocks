# --- Scheduled work on Google Cloud ------------------------------------------------
#
# Two things used to run on GitHub's `schedule:` triggers: the Today page's
# shared market read (today.yml, `stocks today-market`) and the price warm-up
# (warm.yml, one POST to /api/v1/warm). GitHub runs a scheduled workflow when
# a runner is free, which for this repo meant two to five hours late every
# day — the 06:30 read landed at 11:00–12:15, so the page had no shared layer
# all morning and its first readers paid the rebuild. Cloud Scheduler fires on
# the minute, and at three jobs per billing account it costs nothing; the
# Cloud Run job it starts runs the service's own image inside the
# instance-based free tier (about a minute of one vCPU a day). The two
# workflows keep their workflow_dispatch as the manual fallback.
#
# Credentials: the google provider reads Application Default Credentials, or
# GOOGLE_OAUTH_ACCESS_TOKEN for a one-off apply — see README.md.

# The live service. The job runs its image, with its environment (the secrets
# file, EDGAR_USER_AGENT, the free-chain model) and under its identity, so the
# bucket, the secret and the free LLM keys reach the job without a second copy
# of any setting. scripts/deploy.sh moves the job to each image it promotes —
# and to the secret version it pins — so an apply afterwards finds nothing to
# change.
data "google_cloud_run_v2_service" "app" {
  name     = var.cloud_run_service
  location = var.gcp_region
  project  = var.gcp_project
}

locals {
  app_container = data.google_cloud_run_v2_service.app.template[0].containers[0]

  # The service's own markers: the commit stamp changes every deploy (the
  # image digest already says which build the job runs) and the boot warm-up
  # only means something to a server.
  service_only_env = ["STOCKS_COMMIT", "STOCKS_BOOT_WARM"]
  cron_env = [
    for e in local.app_container.env : e if !contains(local.service_only_env, e.name)
  ]
}

resource "google_project_service" "cloudscheduler" {
  project            = var.gcp_project
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

# The identity Cloud Scheduler presents to start the job: run.invoker on this
# one job and nothing else.
resource "google_service_account" "cron" {
  project      = var.gcp_project
  account_id   = var.cron_job
  display_name = "Cloud Scheduler trigger for the ${var.cron_job} job"
}

resource "google_cloud_run_v2_job" "cron" {
  name     = var.cron_job
  location = var.gcp_region
  project  = var.gcp_project

  template {
    task_count = 1

    template {
      service_account = data.google_cloud_run_v2_service.app.template[0].service_account
      # The read takes a minute or two; a stuck download must not hold the
      # instance (and the free tier) for longer than this.
      timeout     = "900s"
      max_retries = 1

      containers {
        image = local.app_container.image
        # The entrypoint (scripts/docker-entrypoint.sh) hands its arguments to
        # exec once the secrets file is written, so this runs the CLI in
        # place of the server.
        args = ["/app/.venv/bin/stocks", "today-market"]

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }

        dynamic "env" {
          for_each = local.cron_env
          content {
            name  = env.value.name
            value = env.value.value != "" ? env.value.value : null

            dynamic "value_source" {
              for_each = env.value.value_source
              content {
                secret_key_ref {
                  secret  = value_source.value.secret_key_ref[0].secret
                  version = value_source.value.secret_key_ref[0].version
                }
              }
            }
          }
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job_iam_member" "cron_invoker" {
  project  = var.gcp_project
  location = var.gcp_region
  name     = google_cloud_run_v2_job.cron.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cron.email}"
}

# The morning market read. Tuesday to Saturday, 06:30 UTC: each run reads the
# session that closed the evening before (Saturday's reads Friday's). FRED has
# posted the previous day's yields overnight and the crypto scan (03:30) is
# done. Starting the job is one API call that returns at once; the run itself
# is bounded by the job's own timeout.
resource "google_cloud_scheduler_job" "today_market" {
  project     = var.gcp_project
  region      = var.gcp_region
  name        = "${var.cron_job}-today-market"
  description = "Today page: the shared market read (stocks today-market)"

  schedule         = "30 6 * * 2-6"
  time_zone        = "Etc/UTC"
  attempt_deadline = "180s"

  retry_config {
    retry_count          = 1
    min_backoff_duration = "300s"
  }

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.gcp_project}/locations/${var.gcp_region}/jobs/${google_cloud_run_v2_job.cron.name}:run"

    oauth_token {
      service_account_email = google_service_account.cron.email
    }
  }

  depends_on = [
    google_project_service.cloudscheduler,
    google_cloud_run_v2_job_iam_member.cron_invoker,
  ]
}

# The price warm-up: the app refreshes, on the request's thread, the books
# read lately (api/warm.py, 240 s budget), so it stays an HTTP call to the
# service rather than a job of its own. Anchored to New York so the ticks
# after the US open and after each close keep their place across
# daylight-saving changes: 00:35 before the European open (the one that pays
# the day's chart rebase, with Yahoo quiet), 04:35 as Europe's morning
# readers arrive (the request log's one slow cluster a day sat four hours
# after the first tick, with every memo expired and the instance restarted
# since), 09:35 after the US open, 12:35 after the European close, 16:35
# after the US close. Saturday too: a weekend reader found the persisted
# memos past their grace and paid Friday's close over again. Needs the
# app's origin and its [api] token, like the warm.yml fallback.
resource "google_cloud_scheduler_job" "warm" {
  count = nonsensitive(var.api_token != "") && var.app_public_url != "" ? 1 : 0

  project     = var.gcp_project
  region      = var.gcp_region
  name        = "${var.cloud_run_service}-warm"
  description = "Price warm-up: POST /api/v1/warm for the books read lately"

  schedule         = "35 0,4,9,12,16 * * 1-6"
  time_zone        = "America/New_York"
  attempt_deadline = "300s"

  http_target {
    http_method = "POST"
    uri         = "${trimsuffix(var.app_public_url, "/")}/api/v1/warm"
    headers = {
      Authorization = "Bearer ${var.api_token}"
    }
  }

  depends_on = [google_project_service.cloudscheduler]
}
