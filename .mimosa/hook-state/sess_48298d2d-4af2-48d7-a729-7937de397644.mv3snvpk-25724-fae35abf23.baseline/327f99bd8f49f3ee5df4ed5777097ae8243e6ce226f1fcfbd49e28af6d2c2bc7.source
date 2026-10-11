#!/usr/bin/env bash
# 更新 /opt/zhiji 代码（保留 data/ 与 .venv），供 KnowYourself 新版部署使用。
# 本轮新增：官方知识库模块、参赛数据模块、PostgreSQL 适配（psycopg）。
set -euo pipefail

STAGE=/opt/zhiji-new
APP=/opt/zhiji

echo "==> 保留旧 data 目录"
rm -rf /tmp/zhiji-data-keep
cp -a "$APP/backend/data" /tmp/zhiji-data-keep

echo "==> 覆盖后端应用代码"
rm -rf "$APP/backend/app"
cp -a "$STAGE/backend/app" "$APP/backend/app"
cp -a "$STAGE/backend/requirements.txt" "$APP/backend/requirements.txt"
cp -a "$STAGE/backend/requirements-lock.txt" "$APP/backend/requirements-lock.txt"
rm -rf "$APP/backend/tests"
[ -d "$STAGE/backend/tests" ] && cp -a "$STAGE/backend/tests" "$APP/backend/tests"
# backend/resources（竞赛原件清单，运行时/文档引用）
rm -rf "$APP/backend/resources"
[ -d "$STAGE/backend/resources" ] && cp -a "$STAGE/backend/resources" "$APP/backend/resources"

echo "==> 覆盖前端构建与源码"
rm -rf "$APP/frontend/dist" "$APP/frontend/src"
cp -a "$STAGE/frontend/dist" "$APP/frontend/dist"
cp -a "$STAGE/frontend/src" "$APP/frontend/src"
cp -a "$STAGE/frontend/package.json" "$APP/frontend/package.json"

echo "==> 覆盖 deploy / docs / 文档 / compose"
cp -a "$STAGE/deploy/." "$APP/deploy/"
rm -rf "$APP/docs"; [ -d "$STAGE/docs" ] && cp -a "$STAGE/docs" "$APP/docs"
[ -f "$STAGE/README.md" ] && cp -a "$STAGE/README.md" "$APP/README.md"
[ -f "$STAGE/CHANGES.md" ] && cp -a "$STAGE/CHANGES.md" "$APP/CHANGES.md"
[ -f "$STAGE/compose.postgres.yml" ] && cp -a "$STAGE/compose.postgres.yml" "$APP/compose.postgres.yml"

echo "==> 恢复 data（安全兜底）"
mkdir -p "$APP/backend/data"
cp -a /tmp/zhiji-data-keep/. "$APP/backend/data/"
rm -rf /tmp/zhiji-data-keep

echo "==> 安装/更新后端依赖（psycopg 可选）"
"$APP/.venv/bin/pip" install -r "$APP/backend/requirements-lock.txt" -q && echo "pip ok"
"$APP/.venv/bin/python" -c "import fastapi,uvicorn,pydantic;print('fastapi',fastapi.__version__,'uvicorn',uvicorn.__version__,'pydantic',pydantic.__version__)"
"$APP/.venv/bin/python" -c "import psycopg;print('psycopg',psycopg.__version__)" 2>/dev/null || echo "psycopg not installed (optional)"

echo "==> 校验"
stat -c 'main.py size=%s' "$APP/backend/app/main.py"
echo "--- dist assets ---"; ls "$APP/frontend/dist/assets/" | tr '\n' ' '; echo
echo "--- data rows (business) ---"
"$APP/.venv/bin/python" - <<'PY'
import sqlite3
c=sqlite3.connect('/opt/zhiji/backend/data/zhiji.sqlite3')
for t in ('users','episodes','sessions'):
    print(t, c.execute(f'select count(*) from {t}').fetchone()[0])
PY

echo "==> 归属"
chown -R zhiji:zhiji "$APP"
echo "DONE"
