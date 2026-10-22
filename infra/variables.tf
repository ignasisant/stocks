# --- Provider credentials ------------------------------------------------------

variable "cloudflare_api_token" {
  description = "Cloudflare API token with Account > Workers R2 Storage: Edit AND Account > Account API Tokens: Edit (the latter to mint the bucket-scoped S3 token). Dashboard -> My Profile -> API Tokens."
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account id (dashboard sidebar, or any zone's overview page)."
  type        = string
}

variable "github_token" {
  description = "GitHub PAT with repo + secrets scope (classic: repo; fine-grained: Secrets read/write on the repo)."
  type        = string
  sensitive   = true
}

variable "github_owner" {
  description = "GitHub owner of the repository."
  type        = string
  default     = "ignasisant"
}

variable "github_repo" {
  description = "Repository name (no owner prefix)."
  type        = string
  default     = "stocks"
}

# --- R2 -------------------------------------------------------------------------

variable "r2_bucket_name" {
  description = "R2 bucket holding user data dirs + static/logos restore dir."
  type        = string
  default     = "aguait-user-data"
}

variable "r2_location" {
  description = "R2 location hint. WEUR = Western Europe."
  type        = string
  default     = "WEUR"
}

# --- Google Cloud: the scheduled jobs beside the Cloud Run service ---------------

variable "gcp_project" {
  description = "Google Cloud project of the Cloud Run service (scripts/deploy.sh's STOCKS_GCP_PROJECT)."
  type        = string
  default     = "topstocks-507209"
}

variable "gcp_region" {
  description = "Region of the service, the cron job and the Cloud Scheduler jobs."
  type        = string
  default     = "europe-west1"
}

variable "cloud_run_service" {
  description = "Name of the production Cloud Run service; the cron job runs its image, environment and identity."
  type        = string
  default     = "topstocks"
}

variable "cron_job" {
  description = "Name of the Cloud Run job that writes the Today page's market read. scripts/deploy.sh and `stocks logs` know it by this name (STOCKS_GCP_JOB)."
  type        = string
  default     = "topstocks-cron"
}

# --- Notification secrets --------------------------------------------------------

variable "telegram_bot_token" {
  description = "Telegram bot token from @BotFather. Never configure a webhook on this bot — the Profile linking flow polls getUpdates."
  type        = string
  sensitive   = true
}

variable "app_public_url" {
  description = "Optional. The app's public origin (e.g. https://topstocks.example) — lets notifications link back into it. Empty = secret not created, messages ship link-free."
  type        = string
  default     = ""
}

variable "api_token" {
  description = "Optional. Must equal the app's [api] token — lets the warm-up (the Cloud Scheduler job in cron.tf, and warm.yml by hand) POST /api/v1/warm; needs app_public_url too. Empty = no warm-up."
  type        = string
  sensitive   = true
  default     = ""
}

variable "chat_enc_key" {
  description = "Optional. Fernet key, must equal the app's [chat] enc_key — lets the digest use BYOK LLM keys. Empty = secret not created."
  type        = string
  sensitive   = true
  default     = ""
}

variable "free_llm_groq" {
  description = "Optional. Groq API key for the free-chain digest highlight. Empty = secret not created."
  type        = string
  sensitive   = true
  default     = ""
}

variable "free_llm_cerebras" {
  description = "Optional. Cerebras API key for the free-chain digest highlight. Empty = secret not created."
  type        = string
  sensitive   = true
  default     = ""
}

variable "free_llm_openrouter" {
  description = "Optional. OpenRouter API key for the free-chain digest highlight. Empty = secret not created."
  type        = string
  sensitive   = true
  default     = ""
}
