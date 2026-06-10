#!/usr/bin/env bash
# =============================================================================
# CAIMP — Test-mode startup script for low-RAM Ubuntu VMs (4 GB)
# Run as: bash scripts/start-test.sh
# =============================================================================
set -euo pipefail

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.test.yml"

# ── 1. Swap ──────────────────────────────────────────────────────────────────
setup_swap() {
  if swapon --show | grep -q '/swapfile'; then
    echo "[swap] /swapfile already active — skipping"
    return
  fi
  echo "[swap] Creating 4 GB swapfile…"
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  # Persist across reboots
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  # Reduce swappiness — only swap when truly necessary
  sudo sysctl vm.swappiness=10
  grep -q 'vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
  echo "[swap] Done — $(free -h | awk '/Swap/{print $2}') swap active"
}

# ── 2. Docker check ──────────────────────────────────────────────────────────
check_docker() {
  if ! command -v docker &>/dev/null; then
    echo "[docker] Docker not found. Installing…"
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "[docker] Installed. You may need to log out and back in for group membership."
    echo "         Re-run this script after logging back in."
    exit 0
  fi
  docker info &>/dev/null || { echo "[docker] Docker daemon not running. Start it with: sudo systemctl start docker"; exit 1; }
  echo "[docker] OK — $(docker --version)"
}

# ── 3. .env check ────────────────────────────────────────────────────────────
check_env() {
  if [ ! -f .env ]; then
    echo "[env] .env not found — copying from .env.example"
    cp .env.example .env
    # Generate a real JWT secret
    JWT=$(openssl rand -hex 64)
    sed -i "s|change_me_jwt_secret_min_64_chars.*|$JWT|" .env
    echo "[env] .env created. Edit passwords before production use."
  fi
  # Source so we can check required vars
  set -a; source .env; set +a
  for var in POSTGRES_PASSWORD REDIS_PASSWORD NATS_PASSWORD JWT_SECRET CA_KEY_PASSPHRASE; do
    val="${!var:-}"
    if [ -z "$val" ] || [[ "$val" == change_me* ]]; then
      echo "[env] WARNING: $var is unset or still at default in .env"
    fi
  done
}

# ── 4. Build images ──────────────────────────────────────────────────────────
build_images() {
  echo "[build] Building service images (first run takes a few minutes)…"
  $COMPOSE build --parallel 2>&1 | grep -E 'Step|Successfully|ERROR|error' || true
  echo "[build] Done"
}

# ── 5. Start stack ───────────────────────────────────────────────────────────
start_stack() {
  echo "[up] Starting CAIMP test stack (no Ollama, no Prometheus, no Grafana)…"
  $COMPOSE up -d
  echo ""
  echo "[up] Waiting for services to become healthy…"
  sleep 10

  echo ""
  echo "════════════════════════════════════════════"
  echo " CAIMP Test Stack — Service Status"
  echo "════════════════════════════════════════════"
  $COMPOSE ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || $COMPOSE ps
  echo ""
  echo "════════════════════════════════════════════"
  echo " Access Points"
  echo "════════════════════════════════════════════"
  echo " Dashboard (React):  http://localhost:3000"
  echo " Admin Dashboard:    http://localhost:3000/admin.html"
  echo " Admin API:          http://localhost:8001/docs"
  echo " Query API:          http://localhost:8002/docs"
  echo " NATS monitor:       http://localhost:8222"
  echo ""
  echo " Login: admin@caimp.local / Admin1234!"
  echo "════════════════════════════════════════════"
  echo ""
  echo " Memory usage:"
  free -h | awk 'NR<=2'
  echo ""
  echo " To stop:  docker compose -f docker-compose.yml -f docker-compose.test.yml down"
  echo " To logs:  docker compose -f docker-compose.yml -f docker-compose.test.yml logs -f"
}

# ── Main ─────────────────────────────────────────────────────────────────────
cd "$(dirname "$0")/.."   # run from project root

setup_swap
check_docker
check_env
build_images
start_stack
