#!/usr/bin/env bash
# Move Cloud Run traffic back to a revision that worked.
#
# Usage:
#   ./scripts/rollback.sh prod --list        # ready revisions, * marks the serving one
#   ./scripts/rollback.sh prod               # -> previous ready revision (confirms)
#   ./scripts/rollback.sh prod topstocks-00018-h6r    # -> that exact revision
#   ./scripts/rollback.sh prod --yes         # no prompt (for a script, not a person)
#
# This is the *other* kind of bad deploy: scripts/deploy.sh already refuses to
# promote a revision that fails to boot, so what reaches here is a revision
# that came up healthy and is wrong. Nothing is rebuilt — the image is already
# in the registry and traffic is a pointer, which is why this takes seconds
# where a redeploy takes minutes.
#
# The shift is verified the way deploy.sh verifies a candidate: /status is read
# back and must name the revision asked for. A rollback that reports success
# without that is how an incident continues with everyone believing it is over.
#
# Requires: gcloud authed on the project.

set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${STOCKS_GCP_PROJECT:-topstocks-507209}"
REGION="${STOCKS_GCP_REGION:-europe-west1}"

ENV="${1:-}"
shift || true

LIST=0
ASSUME_YES=0
TARGET=""
while [ $# -gt 0 ]; do
    case "$1" in
        --list) LIST=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        -*) echo "unknown flag: $1" >&2; exit 1 ;;
        *) TARGET="$1"; shift ;;
    esac
done

case "$ENV" in
    prod) SERVICE="${STOCKS_GCP_SERVICE:-topstocks}" ;;
    staging) SERVICE="${STOCKS_GCP_SERVICE:-topstocks}-staging" ;;
    *) echo "usage: $0 [staging|prod] [--list] [--yes] [REVISION]" >&2
       exit 1 ;;
esac

describe() {
    gcloud run services describe "$SERVICE" --project "$PROJECT" \
        --region "$REGION" --format "value($1)"
}

# Ready revisions, newest first. A revision that never became Ready is not a
# rollback target — it is the deploy you are rolling back from.
ready_revisions() {
    gcloud run revisions list --service "$SERVICE" --project "$PROJECT" \
        --region "$REGION" --sort-by "~metadata.creationTimestamp" \
        --filter "status.conditions.type=Ready AND status.conditions.status=True" \
        --format "value(metadata.name)"
}

URL="$(describe status.url)"
# The revision actually taking traffic, which is not necessarily the newest
# one: a failed canary leaves a newer revision sitting at 0%.
SERVING="$(describe 'status.traffic[0].revisionName')"
REVISIONS="$(ready_revisions)"

if [ -z "$REVISIONS" ]; then
    echo "error: no ready revisions on $SERVICE" >&2
    exit 1
fi

if [ "$LIST" = 1 ]; then
    echo "$SERVICE ($PROJECT / $REGION)"
    while IFS= read -r rev; do
        [ -z "$rev" ] && continue
        stamp="$(gcloud run revisions describe "$rev" --project "$PROJECT" \
            --region "$REGION" --format "value(metadata.labels.commit)" 2>/dev/null || true)"
        if [ "$rev" = "$SERVING" ]; then mark="*"; else mark=" "; fi
        printf '%s %-32s %s\n' "$mark" "$rev" "${stamp:-<no commit label>}"
    done <<< "$REVISIONS"
    exit 0
fi

if [ -z "$TARGET" ]; then
    # The one before the serving revision, in creation order.
    TARGET="$(echo "$REVISIONS" | grep -v -x -F "$SERVING" | head -1)"
    if [ -z "$TARGET" ]; then
        echo "error: $SERVING is the only ready revision — nothing to roll back to" >&2
        exit 1
    fi
elif ! echo "$REVISIONS" | grep -q -x -F "$TARGET"; then
    echo "error: $TARGET is not a ready revision of $SERVICE" >&2
    echo "Ready:" >&2
    echo "$REVISIONS" >&2
    exit 1
fi

if [ "$TARGET" = "$SERVING" ]; then
    echo "$SERVICE already serves $TARGET — nothing to do."
    exit 0
fi

echo "$SERVICE: $SERVING  ->  $TARGET"
if [ "$ASSUME_YES" != 1 ]; then
    printf 'Shift 100%% of traffic? [y/N] '
    read -r answer
    case "$answer" in
        y|Y|yes) ;;
        *) echo "aborted"; exit 1 ;;
    esac
fi

gcloud run services update-traffic "$SERVICE" --project "$PROJECT" \
    --region "$REGION" --to-revisions "$TARGET=100"

# Same probe as deploy.sh: staging is a private service, so an unauthenticated
# curl gets a Google 403 at the edge and has to retry with an identity token.
probe() {
    local target="$1" out
    if out="$(curl -fsS --max-time 20 "$target" 2>/dev/null)"; then
        printf '%s' "$out"
        return 0
    fi
    out="$(curl -fsS --max-time 20 \
        -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
        "$target" 2>/dev/null)" || return 1
    printf '%s' "$out"
}

echo
echo "Verifying $URL/status names $TARGET"
for i in 1 2 3 4 5 6 7 8 9 10; do
    if out="$(probe "$URL/status")"; then
        case "$out" in
            *"\"$TARGET\""*)
                echo "  /status $out"
                echo
                echo "Serving: $TARGET"
                exit 0
                ;;
        esac
    fi
    sleep 3
done

echo "  last answer: ${out:-<none>}" >&2
echo "error: traffic was shifted but /status does not name $TARGET yet." >&2
echo "Check:  gcloud run services describe $SERVICE --project $PROJECT --region $REGION --format='value(status.traffic)'" >&2
exit 1
