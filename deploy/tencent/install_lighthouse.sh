#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root."
  exit 1
fi

APP_ROOT="/opt/buddys"
ENV_DIR="/etc/buddys"
ENV_FILE="${ENV_DIR}/buddys.env"
SERVICE_SRC="${APP_ROOT}/deploy/tencent/buddys.service"
NGINX_SRC="${APP_ROOT}/deploy/tencent/nginx-buddys.conf"
ENV_WRAPPER_SRC="${APP_ROOT}/deploy/tencent/run_with_env_compat.sh"
SERVER_IP="$(hostname -I | awk '{print $1}')"

echo "Using env file at /etc/buddys/buddys.env"

apt-get update
apt-get install -y python3 python3-venv python3-pip nginx

mkdir -p "${APP_ROOT}" "${ENV_DIR}"

if [[ ! -d "${APP_ROOT}/src" ]]; then
  echo "Copy the Buddys repository into ${APP_ROOT} before running this script."
  exit 1
fi

python3 -m venv "${APP_ROOT}/.venv"
"${APP_ROOT}/.venv/bin/pip" install --upgrade pip
"${APP_ROOT}/.venv/bin/pip" install "${APP_ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<'EOF'
BUDDYS_DEFAULT_OPENAI_API_KEY=replace-with-real-key
BUDDYS_INVITE_CODE=replace-with-invite-code
BUDDYS_DEFAULT_MODEL=MiniMax-M3
EOF
  chmod 600 "${ENV_FILE}"
fi

cp "${SERVICE_SRC}" /etc/systemd/system/buddys.service
chmod +x "${ENV_WRAPPER_SRC}"
sed "s/server_name _;/server_name ${SERVER_IP};/" "${NGINX_SRC}" > /etc/nginx/sites-available/buddys.conf
ln -sf /etc/nginx/sites-available/buddys.conf /etc/nginx/sites-enabled/buddys.conf
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable buddys
systemctl restart buddys
nginx -t
systemctl enable nginx
systemctl restart nginx

echo "Buddys deployed. Verify http://<host>/healthz and http://<host>/console"
