#!/usr/bin/env bash
# One-time Artifact Registry cleanup policy for the Cloud Run source-deploy
# repository. Without it every deploy leaves its image behind forever: 12
# images and 4.5 GB by September 2026, on a 0.5 GB free tier, growing with
# every ship and never read again.
#
# The policy (infra/registry-cleanup-policy.json) is two rules:
#   keep-recent-5       keep the 5 newest versions whatever their age
#   delete-untagged-14d delete untagged images older than 14 days
# Keep rules win over Delete rules, so the newest 5 survive unconditionally —
# that is the floor under ./scripts/rollback.sh, which can only reach a
# revision whose image still exists.
#
# Usage:
#   ./scripts/setup_registry_cleanup.sh --dry-run   # log what it WOULD delete
#   ./scripts/setup_registry_cleanup.sh             # arm it for real
#   ./scripts/setup_registry_cleanup.sh --show      # current policy + size
#
# Deletion is permanent — start with --dry-run, read the logs after a day
# (Cloud Logging, resource.type=artifactregistry.googleapis.com/Repository),
# then re-run without the flag.
#
# Requires: gcloud authed on the project with Artifact Registry Administrator.

set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${STOCKS_GCP_PROJECT:-topstocks-507209}"
REGION="${STOCKS_GCP_REGION:-europe-west1}"
REPO="${STOCKS_GCP_AR_REPO:-cloud-run-source-deploy}"
POLICY="infra/registry-cleanup-policy.json"

show() {
    gcloud artifacts repositories describe "$REPO" --location "$REGION" \
        --project "$PROJECT" \
        --format 'yaml(name, sizeBytes, cleanupPolicyDryRun, cleanupPolicies)'
}

case "${1:-}" in
    --show)
        show
        exit 0
        ;;
    --dry-run) DRY=(--dry-run) ;;
    "")        DRY=(--no-dry-run) ;;
    *) echo "usage: $0 [--dry-run | --show]" >&2; exit 1 ;;
esac

[ -f "$POLICY" ] || { echo "error: $POLICY not found" >&2; exit 1; }

if [ "${DRY[0]}" = "--no-dry-run" ]; then
    echo "This ARMS deletion on $REGION/$REPO (project $PROJECT)."
    echo "Untagged images older than 14 days will be deleted permanently;"
    echo "the 5 newest versions are kept whatever their age."
    printf "Proceed? [y/N] "
    read -r reply
    case "$reply" in y|Y|yes) ;; *) echo "aborted"; exit 1 ;; esac
fi

gcloud artifacts repositories set-cleanup-policies "$REPO" \
    --location "$REGION" --project "$PROJECT" \
    --policy "$POLICY" "${DRY[@]}"

echo
show
