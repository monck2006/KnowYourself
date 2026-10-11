#!/usr/bin/env bash
# 在服务器上安装模型环境文件并重启知己服务。
# 密钥在运行时输入，只经 stdin 送到服务器上的 /etc/zhiji/zhiji.env（0600，root），
# 不写入本地仓库、不写入本脚本、不打印到终端。
#
# 用法（在 KnowYourself 目录，用 Git Bash 或任意带 ssh 的终端）：
#   ZHIJI_HOST=你的服务器地址 ZHIJI_SSH_USER=root ZHIJI_DOMAIN=your-domain.cn bash deploy/set-model-key.sh
set -euo pipefail

HOST="${ZHIJI_HOST:?请设置 ZHIJI_HOST=服务器地址}"
SSH_USER="${ZHIJI_SSH_USER:-root}"
APP_DIR="${ZHIJI_APP_DIR:-/opt/zhiji}"
DOMAIN="${ZHIJI_DOMAIN:?请设置 ZHIJI_DOMAIN=你的域名}"
MODEL="${ZHIJI_LLM_MODEL:-deepseek-v4-flash}"
BASE_URL="${ZHIJI_LLM_BASE_URL:-https://api.deepseek.com}"

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  read -r -s -p "DeepSeek API Key: " DEEPSEEK_API_KEY
  echo
fi
[ -n "$DEEPSEEK_API_KEY" ] || { echo "未输入密钥，已取消。"; exit 1; }

ENV_FILE="$(mktemp)"
chmod 600 "$ENV_FILE"
trap 'rm -f "$ENV_FILE"' EXIT
cat > "$ENV_FILE" <<EOF
ZHIJI_DATABASE_PATH=$APP_DIR/backend/data/zhiji.sqlite3
ZHIJI_KNOWLEDGE_DATABASE_PATH=$APP_DIR/backend/data/zhiji.knowledge.sqlite3
ZHIJI_COOKIE_SECURE=true
ZHIJI_ALLOWED_ORIGINS=https://$DOMAIN,capacitor://localhost
ZHIJI_LLM_ENABLED=true
ZHIJI_LLM_BASE_URL=$BASE_URL
ZHIJI_LLM_MODEL=$MODEL
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY
EOF

echo "连接 $SSH_USER@$HOST …"
ssh "$SSH_USER@$HOST" "sudo install -d -m 0700 /etc/zhiji"
ssh "$SSH_USER@$HOST" "sudo install -m 0600 /dev/stdin /etc/zhiji/zhiji.env" < "$ENV_FILE"
ssh "$SSH_USER@$HOST" "sudo install -m 0644 '$APP_DIR/deploy/zhiji.service' /etc/systemd/system/zhiji.service && sudo systemctl daemon-reload && sudo systemctl restart zhiji && sleep 2 && systemctl is-active zhiji"
echo "完成。登录后访问 https://$DOMAIN/api/v1/assistant/status 确认 status 为 ready。"
