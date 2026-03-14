#!/bin/bash
# Deploy ha-pura-homekit to Raspberry Pi
#
# Syncs the custom component into the HA config volume and optionally
# restarts the Home Assistant container so the integration reloads.
#
# Two environments are supported — select with --env:
#   production (default)  → container: homeassistant      config: ./config       port: 8123
#   test                  → container: homeassistant_test  config: ./config_test  port: 8124
#
# Usage:
#   ./deploy.sh                          # deploy to production + restart
#   ./deploy.sh --env test               # deploy to test + restart
#   ./deploy.sh --env production         # deploy to production + restart (explicit)
#   ./deploy.sh --env test --skip-restart  # deploy to test, no restart

set -euo pipefail   # exit on error, treat unset vars as errors, fail on pipe errors

# ── Constants ─────────────────────────────────────────────────────────────────
PI="pi@homeassistant.local"
COMPOSE_DIR="/home/pi/homeassistant"
COMPONENT_NAME="pura_homekit"
COMPONENT_SRC="custom_components/${COMPONENT_NAME}"

# ── Defaults ──────────────────────────────────────────────────────────────────
ENV="production"
SKIP_RESTART=false

# ── Parse flags ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --env)
      if [[ -z "${2:-}" ]]; then
        echo "❌ --env requires a value: production or test"
        exit 1
      fi
      ENV="$2"
      shift 2
      ;;
    --skip-restart)
      SKIP_RESTART=true
      shift
      ;;
    --help|-h)
      echo "Usage: ./deploy.sh [--env production|test] [--skip-restart]"
      echo ""
      echo "  --env production   Deploy to homeassistant container   (port 8123)  [default]"
      echo "  --env test         Deploy to homeassistant_test container (port 8124)"
      echo "  --skip-restart     Sync files without restarting the container"
      exit 0
      ;;
    *)
      echo "❌ Unknown argument: $1"
      echo "   Run ./deploy.sh --help for usage."
      exit 1
      ;;
  esac
done

# ── Resolve environment-specific values ───────────────────────────────────────
case "$ENV" in
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
    echo "❌ Unknown environment: '$ENV'  (valid values: production, test)"
    exit 1
    ;;
esac

COMPONENT_DEST="${HA_CONFIG}/custom_components/${COMPONENT_NAME}"

# ── Git info (best-effort) ─────────────────────────────────────────────────────
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_DIRTY=$(git status --porcelain 2>/dev/null | grep -q . && echo " (uncommitted changes)" || echo "")

echo "🚀 Deploying ha-pura-homekit @ ${GIT_SHA}${GIT_DIRTY}"
echo "   Target    : $PI"
echo "   Env       : ${ENV}"
echo "   Container : ${CONTAINER_NAME}"
echo "   Config    : ${HA_CONFIG}"
echo "   Port      : ${HA_PORT}"
echo "   Restart   : $([ "$SKIP_RESTART" = true ] && echo 'no (--skip-restart)' || echo 'yes')"

# ══════════════════════════════════════════════════════════════════════════════
# PART 1 — HA Custom Component
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "┌─────────────────────────────────────────────────┐"
echo "│  Deploying HA Custom Component                  │"
echo "└─────────────────────────────────────────────────┘"

# ── Verify source directory exists ─────────────────────────────────────────
if [ ! -d "$COMPONENT_SRC" ]; then
  echo "❌ Source directory not found: $COMPONENT_SRC"
  echo "   Run this script from the repository root."
  exit 1
fi

# ── Ensure pi owns the destination directory ────────────────────────────────
# Docker may have created custom_components/ as root — fix ownership once so
# rsync can write without sudo.
echo ""
echo "🔐 Ensuring correct ownership of component directory..."
ssh "$PI" "
  sudo mkdir -p '${COMPONENT_DEST}' && \
  sudo chown -R pi:pi '${HA_CONFIG}/custom_components'
"

# ── Sync integration files ──────────────────────────────────────────────────
echo ""
echo "📦 Syncing integration files..."
rsync -av --delete \
    --exclude='.DS_Store' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    "${COMPONENT_SRC}/" \
    "${PI}:${COMPONENT_DEST}/"

# ── Stamp manifest with git SHA (ensures HA reloads cleanly) ────────────────
# Appending the short SHA to the version makes every deploy look like a new
# version to HA, preventing stale-cache issues during iterative development.
echo ""
echo "🔖 Stamping manifest with git SHA..."
MANIFEST_VERSION="1.0.0+${GIT_SHA}"
ssh "$PI" "
  python3 -c \"
import json
with open('${COMPONENT_DEST}/manifest.json', 'r') as f:
    m = json.load(f)
m['version'] = '${MANIFEST_VERSION}'
with open('${COMPONENT_DEST}/manifest.json', 'w') as f:
    json.dump(m, f, indent=2)
    f.write('\n')
\"
"
echo "   manifest.json version → ${MANIFEST_VERSION}"

# ── Verify files landed correctly ───────────────────────────────────────────
echo ""
echo "🔍 Verifying deployed files..."
FILE_COUNT=$(ssh "$PI" "find '${COMPONENT_DEST}' -name '*.py' -o -name '*.json' | wc -l")
echo "   ✔  ${FILE_COUNT} Python / JSON files on target"

# ══════════════════════════════════════════════════════════════════════════════
# PART 2 — Restart Home Assistant
# ══════════════════════════════════════════════════════════════════════════════
if [ "$SKIP_RESTART" = false ]; then
  echo ""
  echo "┌─────────────────────────────────────────────────┐"
  echo "│  Restarting Home Assistant                      │"
  echo "└─────────────────────────────────────────────────┘"
  echo ""
  echo "🔄 Restarting ${CONTAINER_NAME} container..."
  ssh "$PI" "cd '${COMPOSE_DIR}' && docker compose restart ${CONTAINER_NAME}"

  echo ""
  echo "⏳ Waiting for HA to come back online (up to 120s)..."
  # HA's API returns 401 (Unauthorized) when up but no token is provided.
  # Both 200 and 401 mean HA is running and accepting connections — either is
  # success.  We cannot use curl -f because -f treats 4xx as failure.
  for i in $(seq 1 60); do
    sleep 2
    HTTP_CODE=$(ssh "$PI" \
      "curl -s -o /dev/null -w '%{http_code}' http://localhost:${HA_PORT}/" \
      2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "401" ]; then
      echo "✅ Home Assistant is back online (${i}s × 2s, HTTP ${HTTP_CODE})."
      break
    fi
    if [ "$i" -eq 60 ]; then
      echo "⚠️  HA did not respond after 120s — check logs on the Pi:"
      echo "     ssh $PI 'cd ${COMPOSE_DIR} && docker compose logs --tail=50 ${CONTAINER_NAME}'"
    fi
  done
else
  echo ""
  echo "⏭️  Skipping HA restart (--skip-restart flag set)."
  echo "   Run manually: ssh $PI 'cd ${COMPOSE_DIR} && docker compose restart ${CONTAINER_NAME}'"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "✅ Deploy complete!"
echo "   Commit    : ${GIT_SHA}${GIT_DIRTY}"
echo "   Env       : ${ENV}"
echo "   Component : ${COMPONENT_DEST}"
echo "   Version   : ${MANIFEST_VERSION}"
echo ""
echo "   Useful commands on the Pi:"
echo "     HA logs    : ssh $PI 'cd ${COMPOSE_DIR} && docker compose logs -f ${CONTAINER_NAME}'"
echo "     HA errors  : ssh $PI 'cd ${COMPOSE_DIR} && docker compose logs ${CONTAINER_NAME} 2>&1 | grep -i pura'"
echo "     Restart    : ssh $PI 'cd ${COMPOSE_DIR} && docker compose restart ${CONTAINER_NAME}'"
echo "     Open HA    : http://homeassistant.local:${HA_PORT}"