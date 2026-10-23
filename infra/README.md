# infra/ — Terraform for the stocks repo

Manages the parts of the deployment that have Terraform providers:

| Piece | Managed here | Notes |
|---|---|---|
| Cloudflare R2 bucket | yes | persistent storage behind `stocks.storage` |
| GitHub Actions secrets | yes | everything `.github/workflows/notify.yml` reads; replaces `scripts/setup_notify_secrets.sh` |
| Cloud Run job `topstocks-cron` + Cloud Scheduler | yes | `cron.tf`: the Today page's market read (06:30 UTC, Tue–Sat), the price warm-up (four ticks a trading day, New York time) and the owner's usage digest (Monday 07:00 UTC, the same job started with `stocks usage-digest`; grants the service identity `roles/logging.viewer`). The job runs the service's image and environment; `scripts/deploy.sh` moves it with each promotion |
| Cloud Run service | no | `scripts/deploy.sh`; `cron.tf` only reads it (image, environment, identity) |
| App secrets on the VM | no | no API — the app reads `deploy/secrets.toml`, see `deploy_secrets_reminder` output |
| Telegram bot | no | @BotFather; never set a webhook (Profile linking polls `getUpdates`) |
| Google OIDC client | no | Google Cloud console, OAuth consent screen |
| R2 S3 credential pair | yes | `cloudflare_account_token` scoped to the bucket; S3 creds derived as access_key_id = token id, secret = `sha256(token value)` |

## Usage

```sh
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in values (git-ignored)
terraform init
```

Existing bucket (the live deploy already uses one) — import it, don't let
Terraform create a duplicate:

```sh
terraform import cloudflare_r2_bucket.stocks <account_id>/<bucket_name>/default
```

Existing repo secrets need no import — `terraform apply` overwrites them
idempotently.

The Google side takes no variable: the provider uses Application Default
Credentials (`gcloud auth application-default login`), or the gcloud user's
own token for a one-off run:

```sh
terraform plan
terraform apply
# or, with no ADC file on the machine:
GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token) terraform apply
```

The first apply enables the Cloud Scheduler API; if the scheduler jobs fail
on that run with a permission error on the new service account, the API's
service agent was still being created — apply again.

After apply, print the block for the deploy's `secrets.toml`:

```sh
terraform output deploy_secrets_reminder
```

## CI

The `infra` job in `.github/workflows/ci.yml` runs `terraform fmt -check`
and `terraform validate` (after `init -backend=false`) on every push and
PR. It needs no credentials and never reads or writes state — it only
catches syntax, unknown attributes and type errors before the next manual
`apply` would.

## State is secret

`terraform.tfstate` holds every secret in plaintext (`sensitive = true` only
hides values from CLI output, not from state). Local state is git-ignored via
`infra/.gitignore`. If you move to a remote backend, use one with encryption
at rest and restricted access.
