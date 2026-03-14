#!/bin/bash
# Deploy ha-pura-homekit to Raspberry Pi
#
# Syncs the custom component into the HA config volume and optionally
# restarts the Home Assistant container so the integration reloads.
#
# Usage:
#   ./deploy.sh                   # full deploy + HA restart
#   ./deploy.sh --skip-restart    # deploy files without restarting HA

set -euo pipefail   # exit on error, treat unset vars as errors, fail on pipe errors

PI="pi@homeassistant.local"
HA_CONFIG="/home/pi/homeassistant/config"
COMPONENT_NAME="pura_homekit"
COMPONENT_SRC="custom_components/${COMPONENT_NAME}"
COMPONENT_DEST="${HA_CONFIG}/custom_components/${COMPONENT_NAME}"
SKIP_RESTART=false

# ── Parse flags ───────────────────────────────────────────────────────────────
for arg in "$@"; do
  case $arg in
    --skip-restart) SKIP_RESTART=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ── Git info (best-effort) ─────────────────────────────────────────────────────
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_DIRTY=$(git status --porcelain 2>/dev/null | grep -q . && echo " (uncommitted changes)" || echo "")
echo "🚀 Deploying ha-pura-homekit @ ${GIT_SHA}${GIT_DIRTY}"
echo "   Target : $PI"
echo "   Restart: $([ "$SKIP_RESTART" = true ] && echo 'no (--skip-restart)' || echo 'yes')"

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
  echo "🔄 Restarting Home Assistant container..."
  ssh "$PI" "cd /home/pi/homeassistant && docker compose restart homeassistant"

  echo ""
  echo "⏳ Waiting for HA to come back online (up to 120s)..."
  # HA's API returns 401 (Unauthorized) when up but no token is provided.
  # Both 200 and 401 mean HA is running and accepting connections — either is
  # success.  We cannot use curl -f because -f treats 4xx as failure.
  for i in $(seq 1 60); do
    sleep 2
    HTTP_CODE=$(ssh "$PI" \
      "curl -s -o /dev/null -w '%{http_code}' http://localhost:8123/" \
      2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "401" ]; then
      echo "✅ Home Assistant is back online (${i}s × 2s, HTTP ${HTTP_CODE})."
      break
    fi
    if [ "$i" -eq 60 ]; then
      echo "⚠️  HA did not respond after 120s — check logs on the Pi:"
      echo "     ssh $PI 'cd /home/pi/homeassistant && docker compose logs --tail=50 homeassistant'"
    fi
  done
else
  echo ""
  echo "⏭️  Skipping HA restart (--skip-restart flag set)."
  echo "   Run manually: ssh $PI 'cd /home/pi/homeassistant && docker compose restart homeassistant'"
fi

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "✅ Deploy complete!"
echo "   Commit    : ${GIT_SHA}${GIT_DIRTY}"
echo "   Component : ${COMPONENT_DEST}"
echo "   Version   : ${MANIFEST_VERSION}"
echo ""
echo "   Useful commands on the Pi:"
echo "     HA logs      : ssh $PI 'cd /home/pi/homeassistant && docker compose logs -f homeassistant'"
echo "     HA errors    : ssh $PI 'cd /home/pi/homeassistant && docker compose logs homeassistant 2>&1 | grep -i pura'"
echo "     Restart HA   : ssh $PI 'cd /home/pi/homeassistant && docker compose restart homeassistant'"
