#!/usr/bin/env bash
# 知己 · 云服务器一键部署脚本（Ubuntu / Debian，适用于 47.82.146.124）
# 用法（在服务器上，把部署包先传到 /tmp）：
#   sudo bash /tmp/zhiji-next-deploy.tar.gz   <- 不是这样；先解包再执行本脚本
#   sudo tar -xzf /tmp/zhiji-next-deploy.tar.gz -C /opt/zhiji
#   # 本脚本随包放在 deploy/ 下：
#   sudo bash /opt/zhiji/deploy/setup-ubuntu.sh
set -euo pipefail

APP_DIR=/opt/zhiji
APP_USER=zhiji
PORT=8788

echo "==> 安装系统依赖"
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx

echo "==> 创建运行用户 $APP_USER"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

echo "==> 创建 Python 虚拟环境并安装后端依赖"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/backend/requirements-lock.txt"

echo "==> 建数据目录并交给运行用户"
mkdir -p "$APP_DIR/backend/data"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> 安装 systemd 服务"
install -m 0644 "$APP_DIR/deploy/zhiji.service" /etc/systemd/system/zhiji.service
systemctl daemon-reload
systemctl enable --now zhiji
systemctl --no-pager status zhiji || true

echo
echo "==> 后端已在本机 $PORT 端口运行。接下来："
echo "    1) 编辑 /etc/systemd/system/zhiji.service，把 your-domain.cn 换成你的域名；"
echo "       systemctl daemon-reload && systemctl restart zhiji"
echo "    2) 配置 nginx："
echo "       install -m0644 $APP_DIR/deploy/nginx-zhiji.conf /etc/nginx/sites-available/zhiji"
echo "       ln -sf /etc/nginx/sites-available/zhiji /etc/nginx/sites-enabled/zhiji"
echo "       nginx -t && systemctl reload nginx"
echo "    3) 用 certbot 申请证书：apt-get install -y certbot python3-certbot-nginx && certbot --nginx -d your-domain.cn"
echo "    4) 自测：curl -s http://127.0.0.1:$PORT/healthz"
