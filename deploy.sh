#!/bin/bash
# =============================================================
# deploy.sh — MIM-Ops-Oracle one-click deployment (systemd)
# =============================================================
# Prerequisites:
#   1. SSH key configured at $KEY path
#   2. git push already completed on local machine
#   3. /opt/mim-ops/MIM-Ops-Oracle exists on Oracle VM
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh          → full redeploy (all files)
#   ./deploy.sh check    → health check only (no deploy)
#   ./deploy.sh logs     → tail live logs only
# =============================================================

set -e

# ─────────────────────────────────────────────────────────────
# Configuration — edit if environment changes
# ─────────────────────────────────────────────────────────────
VM_IP="132.145.187.95"
VM_USER="ubuntu"
KEY="${HOME}/.ssh/your-key.pem"          # ← update SSH key path
REMOTE="/opt/mim-ops/MIM-Ops-Oracle"    # ★ production path (NOT /home/ubuntu/)
API_PORT=5000
UI_PORT=8501

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
SSH="ssh -i $KEY -o StrictHostKeyChecking=no $VM_USER@$VM_IP"
DIVIDER="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

banner() { echo ""; echo "$DIVIDER"; echo "  $1"; echo "$DIVIDER"; echo ""; }

check_key() {
    if [ ! -f "$KEY" ]; then
        echo "❌ SSH key not found: $KEY"
        echo "   Edit the KEY variable in deploy.sh and retry."
        exit 1
    fi
}

health_check() {
    banner "📡 Health Check"
    echo "Checking API at http://$VM_IP:$API_PORT/health ..."
    RESP=$(curl -s --max-time 8 "http://$VM_IP:$API_PORT/health" || echo "TIMEOUT")
    if echo "$RESP" | grep -qi "ok\|healthy\|running"; then
        echo "✅ API is healthy: $RESP"
    else
        echo "⚠️  API response: $RESP"
        echo "   Check logs: $SSH 'sudo journalctl -u mim-ops-api -n 30'"
    fi
    echo ""
    echo "🌐 Access:"
    echo "   API : http://$VM_IP:$API_PORT"
    echo "   UI  : http://$VM_IP:$UI_PORT"
}

# ─────────────────────────────────────────────────────────────
# Mode: check / logs / full deploy
# ─────────────────────────────────────────────────────────────
MODE=${1:-"all"}

case "$MODE" in
  check)
    health_check
    exit 0
    ;;
  logs)
    banner "📋 Live Logs (Ctrl+C to exit)"
    echo "─── API ────────────────────────────────────────"
    $SSH "sudo journalctl -fu mim-ops-api" &
    echo "─── UI  ────────────────────────────────────────"
    $SSH "sudo journalctl -fu mim-ops-streamlit"
    exit 0
    ;;
esac

# ─────────────────────────────────────────────────────────────
# Full deploy
# ─────────────────────────────────────────────────────────────
check_key

banner "🚀 MIM-Ops-Oracle Deployment"
echo "  Target : $VM_USER@$VM_IP:$REMOTE"
echo "  SSH key: $KEY"
echo ""

# Step 1: Show local git status
banner "📋 Local Git Status"
git status --short
echo ""
COMMIT=$(git log --oneline -1)
echo "Latest commit: $COMMIT"

# Step 2: git pull on Oracle VM
banner "🔄 Step 1/3 — git pull on Oracle VM"
$SSH "
  set -e
  cd $REMOTE
  echo '📥 Pulling latest code from GitHub...'
  git pull origin main
  echo ''
  echo '📄 Changed files:'
  git diff --name-only HEAD~1 HEAD 2>/dev/null || echo '  (first pull or no diff available)'
  echo ''
  echo '📌 Current commit:'
  git log --oneline -1
"

# Step 3: Install/update Python dependencies if requirements.txt changed
banner "📦 Step 2/3 — Dependency Check"
$SSH "
  cd $REMOTE
  CHANGED=\$(git diff --name-only HEAD~1 HEAD 2>/dev/null || echo '')
  if echo \"\$CHANGED\" | grep -q 'requirements.txt'; then
    echo '⚙️  requirements.txt changed — installing packages...'
    $REMOTE/venv/bin/pip install -r $REMOTE/requirements.txt --quiet
    echo '✅ Packages updated.'
  else
    echo '✅ requirements.txt unchanged — skipping pip install.'
  fi
"

# Step 4: Restart systemd services
banner "🔄 Step 3/3 — Restart systemd Services"
$SSH "
  sudo systemctl restart mim-ops-api mim-ops-streamlit
  sleep 3
  echo '─── Service Status ───────────────────────────────'
  sudo systemctl is-active mim-ops-api     && echo '  mim-ops-api       : ✅ active' || echo '  mim-ops-api       : ❌ failed'
  sudo systemctl is-active mim-ops-streamlit && echo '  mim-ops-streamlit : ✅ active' || echo '  mim-ops-streamlit : ❌ failed'
  echo '──────────────────────────────────────────────────'
"

# Step 5: Health check
sleep 2
health_check

banner "✅ Deployment Complete"
echo "  Commit : $COMMIT"
echo "  API    : http://$VM_IP:$API_PORT"
echo "  UI     : http://$VM_IP:$UI_PORT"
echo ""
echo "  View logs:"
echo "    $SSH 'sudo journalctl -fu mim-ops-api'"
echo "    $SSH 'sudo journalctl -fu mim-ops-streamlit'"
echo ""
