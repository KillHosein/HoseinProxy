#!/usr/bin/env bash
set -e

# =========================================================
# MTProto ALL-IN-ONE Professional Installer (FINAL)
# Docker Compose + Zero Downtime
# Created by: t.me/KillHosein
# =========================================================

[[ $EUID -ne 0 ]] && { echo "Run as root"; exit 1; }

clear
cat <<'EOF'
╔══════════════════════════════════════════════╗
║   MTProto ALL-IN-ONE Professional Installer  ║
║   Docker Compose + Zero Downtime             ║
║   Created by: t.me/KillHosein                ║
╚══════════════════════════════════════════════╝
EOF
echo

# ---------------- Docker ----------------
if ! command -v docker >/dev/null 2>&1; then
  echo "📦 Installing Docker..."
  apt update
  apt install -y docker.io curl
  systemctl enable docker
  systemctl start docker
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "📦 Installing Docker Compose (standalone)..."
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -SL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

# ---------------- System ----------------
CPU=$(nproc)
MAX_WORKERS=$((CPU * 2))
echo "🖥 CPU cores           : $CPU"
echo "🧠 Safe total WORKERS : $MAX_WORKERS"
echo

# ---------------- Inputs ----------------
read -rp "Server public IP: " SERVER_IP
read -rp "Number of proxies: " COUNT
read -rp "WORKERS per proxy: " WORKERS

TOTAL_WORKERS=$((COUNT * WORKERS))
if (( TOTAL_WORKERS > MAX_WORKERS )); then
  echo "⚠️ TOTAL_WORKERS=$TOTAL_WORKERS exceeds safe limit!"
  read -rp "Continue anyway? [y/N]: " X
  [[ "$X" =~ ^[Yy]$ ]] || exit 1
fi

echo
echo "Port mode:"
echo " 1) Auto increment"
echo " 2) Manual"
read -rp "Choose [1/2]: " PMODE

PORTS=()
if [[ "$PMODE" == "1" ]]; then
  read -rp "Starting port: " START
  for ((i=0;i<COUNT;i++)); do PORTS+=($((START+i))); done
else
  for ((i=1;i<=COUNT;i++)); do
    read -rp "Port for proxy $i: " P
    PORTS+=("$P")
  done
fi

# ---------------- Secrets ----------------
echo
echo "🔐 Generating Secrets"
SECRETS=()
for ((i=0;i<COUNT;i++)); do
  SECRETS+=("$(openssl rand -hex 16)")
  echo "Proxy $((i+1)) → ${SERVER_IP}:${PORTS[$i]} | ${SECRETS[$i]}"
done

echo
echo "👉 Register these proxies in @MTProxybot and get Ad Tags"
read -rp "Press ENTER to continue..."

# ---------------- Ad Tags ----------------
echo
echo "Ad Tag mode:"
echo " 1) One Ad Tag for all"
echo " 2) Different Ad Tag per proxy"
read -rp "Choose [1/2]: " TMODE

TAG=()
if [[ "$TMODE" == "1" ]]; then
  read -rp "Ad Tag: " TAG
  for ((i=0;i<COUNT;i++)); do TAG+=("$TAG"); done
else
  for ((i=1;i<=COUNT;i++)); do
    read -rp "Ad Tag for proxy $i: " TAG
    TAG+=("$TAG")
  done
fi

# ---------------- docker-compose.yml ----------------
echo
echo "🧩 Generating docker-compose.yml"
cat > docker-compose.yml <<EOF
version: "3.8"
services:
EOF

for ((i=0;i<COUNT;i++)); do
cat >> docker-compose.yml <<EOF
  mtproto_${PORTS[$i]}:
    image: telegrammessenger/proxy
    container_name: mtproto_${PORTS[$i]}
    restart: always
    ports:
      - "${PORTS[$i]}:443"
    environment:
      SECRET: ${SECRETS[$i]}
      TAG: ${TAG[$i]}
      WORKERS: ${WORKERS}

EOF
done

# ---------------- Deploy ----------------
echo
echo "🚀 Deploying proxies (Docker Compose)"
docker compose up -d

# ---------------- Links ----------------
OUT="mtproto_links.txt"
echo > "$OUT"
echo
echo "🔗 Proxy Links:"
for ((i=0;i<COUNT;i++)); do
  LINK="https://t.me/proxy?server=$SERVER_IP&port=${PORTS[$i]}&secret=${SECRETS[$i]}"
  echo "$LINK"
  echo "$LINK" >> "$OUT"
done

# ---------------- Rolling Update ----------------
cat > rolling_update.sh <<'EOF'
#!/usr/bin/env bash
echo "🔄 Zero-Downtime Rolling Update"
for SVC in $(docker compose config --services); do
  echo "Updating $SVC..."
  docker compose pull $SVC
  docker compose up -d --no-deps $SVC
  sleep 5
done
echo "✅ Update completed"
EOF
chmod +x rolling_update.sh

# ---------------- Done ----------------
cat <<EOF

==============================================
 MTProto Proxy successfully deployed
 Links saved to: mtproto_links.txt
 Zero-downtime update: ./rolling_update.sh
 Created by: t.me/KillHosein
==============================================

EOF
