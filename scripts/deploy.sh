#!/usr/bin/env bash
# Deploy to Cloud Run — staging by default, prod behind a CI check + confirm.
#
# Usage:
#   ./scripts/deploy.sh                    # -> topstocks-staging
#   ./scripts/deploy.sh prod               # -> topstocks (gated)
#   ./scripts/deploy.sh prod --min-instances 0    # accept cold starts, save €
#   ./scripts/deploy.sh staging --secret topstocks-secrets-staging:3
#   ./scripts/deploy.sh prod --no-canary   # old behaviour: traffic on deploy
#   ./scripts/deploy.sh prod --allow-unmerged     # ship a branch tip anyway
#
# Both services are source deploys of this checkout (same as the manual
# command in the runbook). Settings the flags below don't mention are
# preserved from the service's current configuration — including the
# STREAMLIT_SECRETS_TOML secret binding, which is pinned to a Secret Manager
# *version*: publishing a new secret version does nothing until a deploy (or
# --secret here) points at it.
#
# The new revision goes up with NO traffic, under the `candidate` tag, and is
# smoke-tested on its own URL before a single visitor reaches it. A revision
# that fails to boot, or answers /status with the wrong revision name, never
# gets promoted and the currently-serving one keeps taking traffic. To undo a
# promotion afterwards: ./scripts/rollback.sh [staging|prod].
#
# Prod also refuses a commit that is not on origin/main. Deploying a branch tip
# is how prod ends up serving work that main's history does not contain, and
# how the *next* deploy — cut from main, green on CI — silently removes it
# again. --allow-unmerged is the escape hatch, and it still refuses quietly:
# every revision is stamped with its commit, so the gate can list exactly which
# commits a deploy would take away from prod and make you type the service name.
#
# Staging caveat: Google OIDC redirects to the exact URI in the secret, so
# login on staging works only with a staging secret whose [auth] redirect_uri
# is the staging URL (and that URI registered on the OAuth client). Everything
# outside login works with the prod secret.
#
# Requires: gcloud authed on the project; gh CLI (prod gate) authenticated.

set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${STOCKS_GCP_PROJECT:-topstocks-507209}"
REGION="${STOCKS_GCP_REGION:-europe-west1}"

ENV="${1:-staging}"
shift || true

MIN_INSTANCES=""
SECRET=""
CANARY=1
ALLOW_UNMERGED=0
while [ $# -gt 0 ]; do
    case "$1" in
        --min-instances) MIN_INSTANCES="$2"; shift 2 ;;
        --secret) SECRET="$2"; shift 2 ;;
        --no-canary) CANARY=0; shift ;;
        --allow-unmerged) ALLOW_UNMERGED=1; shift ;;
        *) echo "unknown flag: $1" >&2; exit 1 ;;
    esac
done

case "$ENV" in
    prod)
        SERVICE="${STOCKS_GCP_SERVICE:-topstocks}"
        # min 1 keeps one instance warm: Streamlit's cold start (container
        # boot + first session) is seconds, long enough to lose a visitor.
        MIN_INSTANCES="${MIN_INSTANCES:-1}"
        # One replica, not three: a Streamlit session lives in the instance
        # that holds its websocket, and the file-upload PUT is a separate HTTP
        # request. Cloud Run's session affinity is best-effort, so with more
        # than one instance the upload regularly lands on the wrong replica
        # and fails with "Invalid session_id" (a red file chip in the chat and
        # Import pages). Concurrency is 80 — one instance is plenty here.
        MAX_INSTANCES=1
        ;;
    staging)
        SERVICE="${STOCKS_GCP_SERVICE:-topstocks}-staging"
        MIN_INSTANCES="${MIN_INSTANCES:-0}" # scale-to-zero: staging is free when idle
        MAX_INSTANCES=1
        ;;
    *) echo "usage: $0 [staging|prod] [--min-instances N] [--secret NAME:VER] [--no-canary] [--allow-unmerged]" >&2
       exit 1 ;;
esac

describe() {
    gcloud run services describe "$SERVICE" --project "$PROJECT" \
        --region "$REGION" --format "value($1)"
}

# The commit this deploy ships, stamped onto the revision below so that "what
# is prod running" is a label and a /status field rather than an inference from
# build timestamps. Staging may ship a dirty tree; say so in the stamp.
# --untracked-files=all, not `git diff`: the deploy uploads the working tree,
# so a file that was never added ships just the same as a modified one. Files
# .gitignore already covers (secrets.toml, portfolio.db, the statements folder)
# do not show up here and do not reach the build context either — .gcloudignore
# includes .gitignore.
SHA="$(git rev-parse HEAD)"
DIRTY="$(git status --porcelain --untracked-files=all)"
STAMP="$SHA"
if [ -n "$DIRTY" ]; then
    STAMP="$SHA-dirty"
fi

if [ "$ENV" = "prod" ]; then
    if [ -n "$DIRTY" ]; then
        echo "error: working tree not clean — prod deploys ship exactly one commit" >&2
        echo "$DIRTY" >&2
        echo "Commit it, or add it to .gitignore if it must not ship." >&2
        exit 1
    fi
    # The CI gate: this commit must have a green `ci` run on GitHub.
    STATUS="$(gh run list --workflow ci --commit "$SHA" \
        --json conclusion --jq '.[0].conclusion' 2>/dev/null || echo none)"
    if [ "$STATUS" != "success" ]; then
        echo "error: no green CI run for $SHA (found: $STATUS)." >&2
        echo "Push the commit and wait for ci.yml, or check: gh run list" >&2
        exit 1
    fi
    # The merge gate: this commit must already be on origin/main. A branch tip
    # that passes CI passes every other check here too, which is exactly how
    # prod comes to serve a commit main never took.
    git fetch --quiet origin main 2>/dev/null \
        || echo "warning: could not reach origin — ancestry uses the local origin/main" >&2
    if ! git merge-base --is-ancestor "$SHA" origin/main 2>/dev/null; then
        if [ "$ALLOW_UNMERGED" = 0 ]; then
            echo "error: ${SHA:0:10} is not on origin/main." >&2
            echo "Ahead of main by $(git rev-list --count origin/main..HEAD 2>/dev/null || echo '?') commit(s):" >&2
            git log --oneline origin/main..HEAD >&2 2>/dev/null || true
            echo "Merge the PR first, or ship it as-is with --allow-unmerged." >&2
            exit 1
        fi
        echo "warning: ${SHA:0:10} is not on origin/main — shipping it anyway." >&2
    fi

    # What this deploy would take AWAY. The revision serving now carries the
    # commit it was built from as a label; if that commit is not an ancestor of
    # HEAD, the deploy is not a fast-forward and prod loses the difference.
    LOSES=""
    LIVE_REV="$(describe status.traffic.revisionName | head -1)"
    if [ -n "$LIVE_REV" ]; then
        LIVE_SHA="$(gcloud run revisions describe "$LIVE_REV" --project "$PROJECT" \
            --region "$REGION" --format 'value(metadata.labels.commit)' 2>/dev/null || true)"
        LIVE_SHA="${LIVE_SHA%-dirty}"
        if [ -z "$LIVE_SHA" ]; then
            echo "note: $LIVE_REV predates commit stamping — cannot tell what prod runs." >&2
        elif ! git cat-file -e "${LIVE_SHA}^{commit}" 2>/dev/null; then
            echo "note: prod runs $LIVE_SHA, which this checkout does not have. Fetch it." >&2
        elif ! git merge-base --is-ancestor "$LIVE_SHA" HEAD; then
            LOSES="$(git log --oneline "HEAD..$LIVE_SHA")"
        fi
    fi

    if [ -n "$LOSES" ]; then
        echo >&2
        echo "WARNING: $SERVICE serves ${LIVE_SHA:0:10}, which this commit does not contain." >&2
        echo "Deploying ${SHA:0:10} REMOVES this from production:" >&2
        echo "$LOSES" | sed 's/^/  /' >&2
        echo >&2
        printf "Type the service name (%s) to ship it anyway: " "$SERVICE"
        read -r reply
        [ "$reply" = "$SERVICE" ] || { echo "aborted"; exit 1; }
    else
        printf "Deploy %s to PRODUCTION (%s)? [y/N] " "${SHA:0:10}" "$SERVICE"
        read -r reply
        case "$reply" in y|Y|yes) ;; *) echo "aborted"; exit 1 ;; esac
    fi
fi

# A first deploy has no revision to keep serving, so --no-traffic would leave
# the service with nowhere to send requests. Canary from the second one on.
if [ "$CANARY" = 1 ] && ! describe status.url >/dev/null 2>&1; then
    echo "note: $SERVICE does not exist yet — first deploy takes traffic directly"
    CANARY=0
fi

ARGS=(
    run deploy "$SERVICE"
    --source .
    --project "$PROJECT"
    --region "$REGION"
    --port 8080
    --session-affinity           # Streamlit needs sticky sessions
    --min-instances "$MIN_INSTANCES"
    --max-instances "$MAX_INSTANCES"
    # Update, never set: --labels/--set-env-vars would drop everything the
    # service already carries, including the secrets binding's siblings.
    --update-labels "commit=$STAMP"
    --update-env-vars "STOCKS_COMMIT=$STAMP"
)
if [ -n "$SECRET" ]; then
    ARGS+=(--update-secrets "STREAMLIT_SECRETS_TOML=$SECRET")
fi
if [ "$CANARY" = 1 ]; then
    ARGS+=(--no-traffic --tag candidate)
fi

echo "gcloud ${ARGS[*]}"
gcloud "${ARGS[@]}"

URL="$(describe status.url)"
REVISION="$(describe status.latestCreatedRevisionName)"

# /livez, never /healthz: on Cloud Run Google's frontend answers /healthz
# itself before the request reaches the container, so a check on that path
# says "ok" even when the app is dead. See src/stocks/web/server.py.
#
# Staging is a private service — an unauthenticated curl gets a Google 403 at
# the edge — so fall back to an identity token when the open request bounces.
#
# `curl -f` does not fail on a 3xx — it returns success with an empty body, so
# a redirected probe shows up as a blank line and looks like silence. The HTTP
# code is read explicitly, and a redirect is reported as what it is: the app
# bouncing the tagged candidate hostname to the canonical one, where the
# revision already serving would answer. Exit 2 means that; retrying cannot fix
# it, so smoke() gives up immediately instead of sleeping ten times.
probe() {
    local target="$1" raw code body
    raw="$(curl -sS --max-time 20 -w '\n%{http_code}' "$target" 2>/dev/null || true)"
    code="${raw##*$'\n'}"
    case "$code" in
        401|403)
            raw="$(curl -sS --max-time 20 -w '\n%{http_code}' \
                -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
                "$target" 2>/dev/null || true)"
            code="${raw##*$'\n'}"
            ;;
    esac
    body="${raw%$'\n'*}"
    case "$code" in
        200) printf '%s' "$body"; return 0 ;;
        3??) echo "  $target answered $code — redirected off the candidate host." >&2
             echo "  The canonical-host redirect must exempt this path (server.py" >&2
             echo "  _NEVER_REDIRECT), or the smoke test reads the old revision." >&2
             return 2 ;;
        *)   return 1 ;;
    esac
}

# Retry: a scale-to-zero service has to cold-start before it can answer, and
# a freshly tagged URL takes a moment to route.
smoke() {
    local base="$1" i out rc
    for i in 1 2 3 4 5 6 7 8 9 10; do
        rc=0
        out="$(probe "$base/livez")" || rc=$?
        if [ "$rc" = 2 ]; then
            return 1
        fi
        if [ "$rc" = 0 ]; then
            echo "  /livez  $out"
            rc=0
            out="$(probe "$base/status")" || rc=$?
            [ "$rc" = 0 ] || return 1
            echo "  /status $out"
            case "$out" in
                *"\"$REVISION\""*) return 0 ;;
                *) echo "  expected revision $REVISION" >&2; return 1 ;;
            esac
        fi
        sleep 3
    done
    echo "  no answer from $base/livez after 10 tries" >&2
    return 1
}

if [ "$CANARY" = 1 ]; then
    CANDIDATE_URL="${URL/https:\/\//https://candidate---}"
    echo
    echo "Smoking candidate $REVISION at $CANDIDATE_URL (0% traffic)"
    if ! smoke "$CANDIDATE_URL"; then
        echo >&2
        echo "error: candidate failed its smoke test — NOT promoted." >&2
        echo "$SERVICE still serves the previous revision; nobody saw this one." >&2
        echo "Logs:  gcloud run services logs read $SERVICE --project $PROJECT --region $REGION" >&2
        echo "Clean: gcloud run services update-traffic $SERVICE --project $PROJECT --region $REGION --remove-tags candidate" >&2
        exit 1
    fi
    echo
    echo "Candidate healthy — promoting to 100% traffic"
    gcloud run services update-traffic "$SERVICE" --project "$PROJECT" \
        --region "$REGION" --to-latest
    # Drop the tag: it pins the revision's image against registry cleanup and
    # would otherwise point at an ever-older revision.
    gcloud run services update-traffic "$SERVICE" --project "$PROJECT" \
        --region "$REGION" --remove-tags candidate >/dev/null
fi

echo
echo "$URL"
echo "Serving: $REVISION"
echo "Verify:  curl -fsS $URL/livez && curl -fsS $URL/status"
echo "Undo:    ./scripts/rollback.sh $ENV"
