# PostgreSQL 业务数据库

账号、登录会话和健康记录可存入 PostgreSQL。未设置 `ZHIJI_DATABASE_URL` 时仍使用原有 SQLite。医学知识库单独保留在本地 SQLite，不与账号和记录混放。此功能使用 PostgreSQL 官方数据库软件，不需要将个人健康数据上传到第三方平台。

## 本机启动

需要 Docker Desktop 的 Linux 引擎已启动。仓库根目录的 `compose.postgres.yml` 使用 [PostgreSQL 官方镜像](https://hub.docker.com/_/postgres) 的稳定 17 主版本，持久化到 Docker 命名卷，只绑定 `127.0.0.1`。使用自己生成的强密码，不要提交密码或含凭据的 URL。

PowerShell（在仓库根目录）：

```powershell
# 从密码管理器安全输入，不写入命令历史。
$postgresSecret = Read-Host 'PostgreSQL password' -AsSecureString
$env:POSTGRES_PASSWORD = [System.Net.NetworkCredential]::new('', $postgresSecret).Password
docker compose -f compose.postgres.yml up -d --wait

# URL 的密码部分需要编码；不输出整个 URL。
$encodedPassword = [uri]::EscapeDataString($env:POSTGRES_PASSWORD)
$env:ZHIJI_DATABASE_URL = "postgresql://zhiji:${encodedPassword}@127.0.0.1:5432/zhiji"
.venv/Scripts/python.exe -m pip install -r backend/requirements-lock.txt
```

全新部署可进入 `backend` 后运行 `../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。应用自动创建业务表及 `zhiji_schema_version`。已有 SQLite 数据时，先完成下面迁移，再启动应用。

`POSTGRES_PORT` 可修改宿主端口，同时调整 URL。`ZHIJI_DATABASE_URL` 优先于 `ZHIJI_DATABASE_PATH`。远程自管 PostgreSQL 应使用自己的地址与 TLS 配置，例如 URL 参数 `sslmode=verify-full`；不要把数据库公开暴露给浏览器。修改环境变量中的密码不会改变已有卷内账号密码，应通过 PostgreSQL 正式改密流程处理。

## SQLite 安全迁移

1. 停止业务 API 写入，备份原 SQLite 数据库及其 WAL 文件。迁移程序使用 SQLite 在线 backup API 创建一致性临时快照，而非直接复制正在写入的文件；停止写入确保切换时不会遗漏快照之后的新记录。
2. 启动一个**空的目标数据库**，设置上面的 `ZHIJI_DATABASE_URL`。不要提前让应用初始化该库。目标存在任何用户业务表时会拒绝迁移。
3. 在仓库根目录执行：

```powershell
Push-Location backend
../.venv/Scripts/python.exe -m app.migrate_postgres --source data/zhiji.sqlite3
Pop-Location
```

4. 成功时输出源库现有业务表的核验行数：旧库三张表，新库另外包含健康档案和测量观察，共五张表。使用同一个 `ZHIJI_DATABASE_URL` 启动 API，检查旧账号登录、记录查看、健康档案、设备读数和导出，然后再允许客户端写入。密码哈希、会话摘要、记录 ID、内容、版本和时间按原值迁移。

迁移仅从 `ZHIJI_DATABASE_URL` 读取目标，不接受含密码的命令行参数。建表、导入、版本记录和行数检查在一个 PostgreSQL 事务内完成；失败回滚，源库始终只读。不会自动删除源库或覆盖目标。只在尚未向 PostgreSQL 写入新数据时，移除 `ZHIJI_DATABASE_URL` 可退回原 SQLite；切换后新增的数据需单独备份和迁移，不能直接退回旧库。

## 事务与验证

适配层保留现有 SQL 的 `?` 参数和按列名/数字读取的行格式。为保持现有改密、会话撤销和记录版本冲突语义，业务写事务使用 PostgreSQL 事务级 advisory lock 串行执行；锁等待最多 15 秒，单条语句最多 30 秒。该策略适合当前应用规模，以后可按账号细化锁粒度。

数据库异常返回统一中文提示，客户端不会收到连接 URL、密码或原始驱动错误。开发测试不要求安装 PostgreSQL；`backend/tests/test_postgres.py` 包含适配层与迁移事务测试，并提供设置 `ZHIJI_TEST_POSTGRES_URL` 后运行的真实数据库集成测试。请使用专用空测试数据库，账号需要创建 schema 权限；测试创建并清理临时独立 schema，不会清空既有表。

```powershell
# 使用专用空测试库的 URL，在 backend 目录运行。
../.venv/Scripts/python.exe -m pytest tests/test_postgres.py -q -p no:cacheprovider
```
