#!/usr/bin/env bash
# =============================================================================
# CAIMP v2 Agent Installer
# Usage:  curl -fsSL https://<platform>/install.sh | bash -s -- --token <TOKEN>
#         OR: bash install.sh --token <TOKEN>
# =============================================================================
set -euo pipefail

PLATFORM_URL="${CAIMP_PLATFORM_URL:-https://caimp.local}"
INSTALL_DIR="/opt/caimp-agent"
DATA_DIR="/etc/caimp-agent"
SERVICE_USER="caimp-agent"
ENROLLMENT_TOKEN=""

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        --token)   ENROLLMENT_TOKEN="$2"; shift 2 ;;
        --url)     PLATFORM_URL="$2";     shift 2 ;;
        *)         echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$ENROLLMENT_TOKEN" ]]; then
    echo "ERROR: --token <enrollment_token> is required"
    exit 1
fi

# ---------------------------------------------------------------------------
# Requirements check
# ---------------------------------------------------------------------------
require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1"; exit 1; }; }
require python3
require pip3
require curl
require systemctl

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [[ "$(echo -e "3.12\n$PYTHON_VERSION" | sort -V | head -1)" != "3.12" ]]; then
    echo "Python 3.12+ required (found $PYTHON_VERSION)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Manifest verification (SHA-256)
# ---------------------------------------------------------------------------
echo "→ Verifying installer manifest …"
MANIFEST_URL="${PLATFORM_URL}/agents/installer/manifest"
MANIFEST=$(curl -fsSL "$MANIFEST_URL" 2>/dev/null || echo "")

if [[ -n "$MANIFEST" ]]; then
    EXPECTED_SHA=$(echo "$MANIFEST" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('sha256',''))" 2>/dev/null || echo "")
    if [[ -n "$EXPECTED_SHA" ]]; then
        ACTUAL_SHA=$(sha256sum "$0" | awk '{print $1}')
        if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]]; then
            echo "ERROR: SHA-256 mismatch — installer may be tampered."
            echo "  Expected: $EXPECTED_SHA"
            echo "  Got:      $ACTUAL_SHA"
            exit 1
        fi
        echo "  ✓ Installer SHA-256 verified"
    fi
else
    echo "  ⚠ Manifest not available — skipping verification (dev mode)"
fi

# ---------------------------------------------------------------------------
# Create system user
# ---------------------------------------------------------------------------
echo "→ Creating service user '$SERVICE_USER' …"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# ---------------------------------------------------------------------------
# Install files
# ---------------------------------------------------------------------------
echo "→ Installing to $INSTALL_DIR …"
mkdir -p "$INSTALL_DIR" "$DATA_DIR"
cp -r "$(dirname "$0")/." "$INSTALL_DIR/"

python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "$DATA_DIR"
chmod 700 "$DATA_DIR"

# Write env file
cat > "$DATA_DIR/env" <<EOF
CAIMP_PLATFORM_URL=$PLATFORM_URL
CAIMP_DATA_DIR=$DATA_DIR
LOG_LEVEL=INFO
EOF
chmod 600 "$DATA_DIR/env"

# ---------------------------------------------------------------------------
# Enroll the agent
# ---------------------------------------------------------------------------
echo "→ Enrolling agent (generating keypair + submitting CSR) …"
CAIMP_ADMIN_URL="$PLATFORM_URL" \
    "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/main.py" --enroll "$ENROLLMENT_TOKEN"

# ---------------------------------------------------------------------------
# Install systemd service
# ---------------------------------------------------------------------------
echo "→ Installing systemd service …"
cp "$INSTALL_DIR/caimp-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable caimp-agent
systemctl start  caimp-agent

echo ""
echo "✓ CAIMP Agent installed and started."
echo "  Status:  systemctl status caimp-agent"
echo "  Logs:    journalctl -u caimp-agent -f"
