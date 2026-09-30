#!/usr/bin/env bash
# One-time Cloud Monitoring setup for the Cloud Run service: an uptime check
# on /livez, an alert when it fails, an alert on ERROR-severity app logs, and
# alerts on the WARNING events that mean something will not fix itself — a
# sustained 503 rate, a torn cache, a held ticker Yahoo does not list.
#
# Log-based metrics (infra/monitoring/metrics/*.json) are created before the
# policies (infra/monitoring/*.json), because a rate alert counts one. Both
# carry __SERVICE__, replaced with the service name at create time, so a run
# with STOCKS_GCP_SERVICE=topstocks-staging watches staging and not prod.
# tests/test_monitoring.py checks every event a filter names is still emitted.
#
# The path is /livez, not /healthz: Google's frontend answers /healthz itself
# with a 404 before the request reaches Cloud Run, so a check on that path
# would fail forever while the service is perfectly healthy.
#
# Usage:
#   ./scripts/setup_monitoring.sh you@example.com
#
# Idempotent-ish: each resource is looked up by display name first and skipped
# when it already exists, so re-running after a partial failure is safe.
#
# Requires: gcloud authenticated on the project (gcloud auth login), with the
# Monitoring Editor role. Project/service/region match the deployed app; the
# STOCKS_GCP_* variables override them (same ones stocks/logs_query.py reads).

set -euo pipefail

PROJECT="${STOCKS_GCP_PROJECT:-topstocks-507209}"
SERVICE="${STOCKS_GCP_SERVICE:-topstocks}"
REGION="${STOCKS_GCP_REGION:-europe-west1}"
EMAIL="${1:-}"

[ -n "$EMAIL" ] || { echo "usage: $0 <alert-email>" >&2; exit 1; }

HOST="$(gcloud run services describe "$SERVICE" --project "$PROJECT" \
    --region "$REGION" --format 'value(status.url)' | sed 's|https://||')"
[ -n "$HOST" ] || { echo "error: Cloud Run service $SERVICE not found" >&2; exit 1; }
echo "service host: $HOST"

# --- notification channel (email) --------------------------------------------
CHANNEL="$(gcloud beta monitoring channels list --project "$PROJECT" \
    --filter "displayName='stocks-alerts' AND type='email'" \
    --format 'value(name)' | head -1)"
if [ -z "$CHANNEL" ]; then
    CHANNEL="$(gcloud beta monitoring channels create --project "$PROJECT" \
        --display-name "stocks-alerts" --type email \
        --channel-labels "email_address=$EMAIL" --format 'value(name)')"
    echo "created channel: $CHANNEL"
else
    echo "channel exists: $CHANNEL"
fi

# --- uptime check on /livez -------------------------------------------------
if gcloud monitoring uptime list-configs --project "$PROJECT" \
    --format 'value(displayName)' | grep -qx "stocks-healthz"; then
    echo "uptime check exists"
else
    gcloud monitoring uptime create "stocks-healthz" \
        --project "$PROJECT" \
        --resource-type uptime-url \
        --resource-labels "host=$HOST,project_id=$PROJECT" \
        --protocol https --path /livez --port 443 \
        --period 5 --timeout 10
    echo "created uptime check"
fi

cd "$(dirname "$0")/.."

# Replace __SERVICE__ in a JSON file and print the result.
with_service() {
    python3 - "$1" "$SERVICE" <<'EOF'
import json, sys
text = json.dumps(json.load(open(sys.argv[1]))).replace("__SERVICE__", sys.argv[2])
print(text)
EOF
}

# --- log-based metrics (JSON in infra/monitoring/metrics/) ---------------------
# Counted from the structured logs, so a policy can alert on a rate rather
# than on every single line. Existing ones are left alone: a changed filter
# is `gcloud logging metrics update NAME --config-from-file ...` by hand.
for f in infra/monitoring/metrics/*.json; do
    METRIC="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "$f")"
    if gcloud logging metrics describe "$METRIC" --project "$PROJECT" >/dev/null 2>&1; then
        echo "metric exists: $METRIC"
        continue
    fi
    with_service "$f" > /tmp/metric.json
    gcloud logging metrics create "$METRIC" --project "$PROJECT" \
        --config-from-file /tmp/metric.json
    echo "created metric: $METRIC"
done

# --- alert policies (JSON in infra/monitoring/) --------------------------------
for f in infra/monitoring/*.json; do
    NAME="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['displayName'])" "$f")"
    if gcloud alpha monitoring policies list --project "$PROJECT" \
        --filter "displayName='$NAME'" --format 'value(name)' | grep -q .; then
        echo "policy exists: $NAME"
        continue
    fi
    # Inject the service name and the channel at create time.
    with_service "$f" > /tmp/policy.json
    # A metric created a moment ago can take a minute to become visible to
    # Monitoring, and until then a policy on it is refused: retry, don't fail.
    for attempt in 1 2 3 4 5 6; do
        if gcloud alpha monitoring policies create --project "$PROJECT" \
            --policy-from-file /tmp/policy.json \
            --notification-channels "$CHANNEL"; then
            echo "created policy: $NAME"
            break
        fi
        [ "$attempt" -lt 6 ] || { echo "error: policy $NAME refused" >&2; exit 1; }
        echo "policy $NAME refused, retrying in 20s ($attempt/6)"
        sleep 20
    done
done

echo
echo "Done. Test: pause the service or curl a bad deploy, or run"
echo "  uv run stocks logs errors --since 1h"
