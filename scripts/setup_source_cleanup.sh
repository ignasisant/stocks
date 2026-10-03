#!/usr/bin/env bash
# One-time lifecycle rule for the Cloud Run source-upload bucket. Every
# `gcloud run deploy --source` drops a zip of the repo in
# gs://run-sources-<project>-<region>/ that Cloud Build reads once and nothing
# reads again. They pile up forever otherwise (538 MiB by October 2026), and a
# regional EU bucket has no free storage tier — and an archive from before the
# .gcloudignore fix carries every secret in terraform.tfstate.
#
# The rule (infra/run-sources-lifecycle.json) deletes any object older than 3
# days: long enough for a build that is still running or being retried.
#
# Usage:
#   ./scripts/setup_source_cleanup.sh          # arm it
#   ./scripts/setup_source_cleanup.sh --show   # current rule + size
#
# Deletion is permanent, but nothing in the bucket is needed after its build:
# rollback.sh redeploys an image from Artifact Registry, never a source zip.
#
# Requires: gcloud authed on the project with Storage Admin.

set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${STOCKS_GCP_PROJECT:-topstocks-507209}"
REGION="${STOCKS_GCP_REGION:-europe-west1}"
BUCKET="gs://run-sources-$PROJECT-$REGION"
POLICY="infra/run-sources-lifecycle.json"

show() {
    gcloud storage buckets describe "$BUCKET" --project "$PROJECT" \
        --format 'yaml(name, location, lifecycle_config)'
    gcloud storage du -s -r "$BUCKET" --project "$PROJECT"
}

case "${1:-}" in
    --show) show; exit 0 ;;
    "") ;;
    *) echo "usage: $0 [--show]" >&2; exit 1 ;;
esac

[ -f "$POLICY" ] || { echo "error: $POLICY not found" >&2; exit 1; }

echo "This ARMS deletion on $BUCKET:"
echo "every object older than 3 days will be deleted permanently."
printf "Proceed? [y/N] "
read -r reply
case "$reply" in y|Y|yes) ;; *) echo "aborted"; exit 1 ;; esac

gcloud storage buckets update "$BUCKET" --project "$PROJECT" \
    --lifecycle-file "$POLICY"

echo
show
