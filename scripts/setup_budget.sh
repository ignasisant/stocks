#!/usr/bin/env bash
# GCP budget alert for the project — the cost backstop for Cloud Run
# (min-instances, egress, chat runs held open after their reader left) and
# everything else billed to it.
#
# Usage:
#   gcloud billing accounts list        # find the billing account ID
#   ./scripts/setup_budget.sh 0X0X0X-0X0X0X-0X0X0X [amount] [currency]
#
# Defaults: 10 EUR/month, emails at 5% / 10% / 50% / 100% of it — 0.50, 1, 5
# and 10 EUR — to the billing account admins (Cloud Billing's default
# recipients; add more people under Billing > Budgets & alerts if needed).
# The app normally costs nothing, so the first email is the signal and the
# later ones say how fast it grows. A budget only alerts; it never stops the
# service.
#
# Idempotent: an existing topstocks-budget is updated to these figures.

set -euo pipefail

PROJECT="${STOCKS_GCP_PROJECT:-topstocks-507209}"
BILLING_ACCOUNT="${1:-}"
AMOUNT="${2:-10}"
CURRENCY="${3:-EUR}"
THRESHOLDS=(0.05 0.1 0.5 1.0)

[ -n "$BILLING_ACCOUNT" ] || {
    echo "usage: $0 <billing-account-id> [amount] [currency]" >&2
    echo "       (gcloud billing accounts list)" >&2
    exit 1
}

existing="$(gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" \
    --filter='displayName=topstocks-budget' --format='value(name)' 2>/dev/null | head -1)"

if [ -n "$existing" ]; then
    added=()
    for t in "${THRESHOLDS[@]}"; do added+=("--add-threshold-rule=percent=$t"); done
    gcloud billing budgets update "$existing" \
        --budget-amount="${AMOUNT}${CURRENCY}" \
        --clear-threshold-rules \
        "${added[@]}"
    echo "updated: topstocks-budget (${AMOUNT} ${CURRENCY}/month, alerts at ${THRESHOLDS[*]})"
    exit 0
fi

rules=()
for t in "${THRESHOLDS[@]}"; do rules+=("--threshold-rule=percent=$t"); done
gcloud billing budgets create \
    --billing-account="$BILLING_ACCOUNT" \
    --display-name="topstocks-budget" \
    --budget-amount="${AMOUNT}${CURRENCY}" \
    --filter-projects="projects/$PROJECT" \
    "${rules[@]}"

echo "created: topstocks-budget (${AMOUNT} ${CURRENCY}/month, alerts at ${THRESHOLDS[*]})"
