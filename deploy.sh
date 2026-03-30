#!/usr/bin/env bash
# deploy.sh — Deploy ha-pura-homekit to a Raspberry Pi running Home Assistant.
#
# Syncs the custom component into the HA config volume via rsync over SSH and
# optionally restarts the Home Assistant container so the integration reloads.
#
# Two environments are supported — select with --env:
#
#   production (default)  container: homeassistant       config: ./config       port: 8123
#   test                  container: homeassistant_test   config: ./config_test  port: 8124
#
# Usage:
#   ./deploy.sh                              # deploy to production + restart
#   ./deploy.sh --env test                   # deploy to test + restart
#   ./deploy.sh --env production             # deploy to production + restart (explicit)
#   ./deploy.sh --env test --skip-restart    # deploy to test, no restart
#   ./deploy.sh --help                       # show this help and exit

set -euo pipefail  # exit on error, unset vars are errors, fail on pipe errors

# ── Constants ─────────────────────────────────────────────────────────────────
readonly PI_HOST="pi@homeassistant.local"
readonly COMPOSE_DIR="/home/pi/homeassistant"
readonly COMPONENT_NAME="pura_homekit"
readonly COMPONENT_SRC="custom_components/${COMPONENT_NAME}"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEPLOY_ENV="production"
SKIP_RESTART=false

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --env)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --env requires a value: production or test" >&2
                exit 1
            fi
            DEPLOY_ENV="$2"
            shift 2
            ;;
        --skip-restart)
            SKIP_RESTART=true
            shift
            ;;
        --help | -h)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Error: Unknown argument: $1" >&2
            echo "  Run ./deploy.sh --help for usage." >&2
            exit 1
            ;;
    esac
done

# ── Resolve environment-specific values ───────────────────────────────────────
case "$DEPLOY_ENV" in
    production)
        HA_CONFIG="${COMPOSE_DIR}/config"
        CONTAINER_NAME="homeassistant"
        HA_PORT="8123"
        ;;
    test)
        HA_CONFIG="${COMPOSE_DIR}/config_test"
        CONTAINER_NAME="homeassistant_test"
        HA_PORT="8124"
        ;;
    *)
        echo "Error: Unknown environment: '${DEPLOY_ENV}'  (valid: production, test)" >&2
        exit 1
        ;;
esac

readonly COMPONENT_DEST="${HA_CONFIG}/custom_components/${COMPONENT_NAME}"

# ── Git metadata (best-effort; tolerates non-git directories) ─────────────────
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_DIRTY=$(git status --porcelain 2>/dev/null | grep -q . && echo " (uncommitted changes)" || echo "")

# ── Banner ────────────────────────────────────────────────────────────────────
echo "Deploying ha-pura-homekit @ ${GIT_SHA}${GIT_DIRTY}"
echo "  Target    : ${PI_HOST}"
echo "  Env       : ${DEPLOY_ENV}"
echo "  Container : ${CONTAINER_NAME}"
echo "  Config    : ${HA_CONFIG}"
echo "  Port      : ${HA_PORT}"
echo "  Restart   : $([ "$SKIP_RESTART" = true ] && echo 'no (--skip-restart)' || echo 'yes')"

# ══════════════════════════════════════════════════════════════════════════════
# PART 1 — Sync integration files
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "--- Syncing HA Custom Component ---"

# Verify the source directory exists before touching the Pi.
if [[ ! -d "$COMPONENT_SRC" ]]; then
    echo "Error: Source directory not found: ${COMPONENT_SRC}" >&2
    echo "  Run this script from the repository root." >&2
    exit 1
fi

# Ensure the pi user owns the destination directory.
# Docker may have created custom_components/ as root — fix ownership once so
# rsync can write without sudo on subsequent deploys.
echo ""
echo "Ensuring correct ownership of component directory on Pi..."
ssh "$PI_HOST" "
    sudo mkdir -p '${COMPONENT_DEST}' && \
    sudo chown -R pi:pi '${HA_CONFIG}/custom_components'
"

# Rsync integration files to the Pi, excluding build artefacts.
echo ""
echo "Syncing integration files..."
rsync -av --delete \
    --exclude='.DS_Store' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    "${COMPONENT_SRC}/" \
    "${PI_HOST}:${COMPONENT_DEST}/"

# ── Stamp manifest with git SHA ───────────────────────────────────────────────
# Appending the short SHA to the version makes every deploy look like a new
# version to HA, which prevents stale-cache issues during iterative development.
echo ""
echo "Stamping manifest.json with git SHA..."
readonly MANIFEST_VERSION="1.1.0+${GIT_SHA}"
ssh "$PI_HOST" "python3 -c \"
import json
path = '${COMPONENT_DEST}/manifest.json'
with open(path) as f:
    manifest = json.load(f)
manifest['version'] = '${MANIFEST_VERSION}'
with open(path, 'w') as f:
    json.dump(manifest, f, indent=2)
    f.write('\n')
\""
echo "  manifest.json version -> ${MANIFEST_VERSION}"

# Verify the sync completed successfully.
echo ""
echo "Verifying deployed files..."
FILE_COUNT=$(ssh "$PI_HOST" "find '${COMPONENT_DEST}' \( -name '*.py' -o -name '*.json' \) | wc -l")
echo "  ${FILE_COUNT} Python / JSON files present on target"

# ══════════════════════════════════════════════════════════════════════════════
# PART 2 — Restart Home Assistant (optional)
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$SKIP_RESTART" == false ]]; then
    echo ""
    echo "--- Restarting Home Assistant ---"
    echo ""
    echo "Restarting ${CONTAINER_NAME} container..."
    ssh "$PI_HOST" "cd '${COMPOSE_DIR}' && docker compose restart ${CONTAINER_NAME}"

    echo ""
    echo "Waiting for HA to come back online (up to 120 s)..."
    # HA's API returns 401 (Unauthorized) when running but no token is provided.
    # Both HTTP 200 and 401 mean HA is up and accepting connections — either is
    # treated as success here.
    for attempt in $(seq 1 60); do
        sleep 2
        HTTP_STATUS=$(
            ssh "$PI_HOST" \
                "curl -s -o /dev/null -w '%{http_code}' http://localhost:${HA_PORT}/" \
                2>/dev/null || echo "000"
        )
        if [[ "$HTTP_STATUS" == "200" || "$HTTP_STATUS" == "401" ]]; then
            echo "Home Assistant is back online (${attempt} x 2 s, HTTP ${HTTP_STATUS})."
            break
        fi
        if [[ "$attempt" -eq 60 ]]; then
            echo "Warning: HA did not respond after 120 s — check logs on the Pi:"
            echo "  ssh ${PI_HOST} 'cd ${COMPOSE_DIR} && docker compose logs --tail=50 ${CONTAINER_NAME}'"
        fi
    done
else
    echo ""
    echo "Skipping HA restart (--skip-restart)."
    echo "  Restart manually: ssh ${PI_HOST} 'cd ${COMPOSE_DIR} && docker compose restart ${CONTAINER_NAME}'"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "Deploy complete!"
echo "  Commit    : ${GIT_SHA}${GIT_DIRTY}"
echo "  Env       : ${DEPLOY_ENV}"
echo "  Component : ${COMPONENT_DEST}"
echo "  Version   : ${MANIFEST_VERSION}"
echo ""
echo "  Useful commands:"
echo "  HA logs   : ssh ${PI_HOST} 'cd ${COMPOSE_DIR} && docker compose logs -f ${CONTAINER_NAME}'"
echo "  Pura logs : ssh ${PI_HOST} 'cd ${COMPOSE_DIR} && docker compose logs ${CONTAINER_NAME} 2>&1 | grep -i pura'"
echo "  Restart   : ssh ${PI_HOST} 'cd ${COMPOSE_DIR} && docker compose restart ${CONTAINER_NAME}'"
echo "  Open HA   : http://homeassistant.local:${HA_PORT}"
