# 本地使用

在仓库根目录运行 `./start.ps1 -Local`，然后打开脚本打印的实际网址。默认绑定 `127.0.0.1:8788`；若端口被占用或被 Windows 保留，自动改用系统分配的可绑定端口。可指定 `-Port 9000`，或用 `-Port 0` 主动分配空闲端口。前端仍需预先构建，Python 依赖仍需安装。

`-Local` 明确使用本仓库的 `backend/data/zhiji.sqlite3` 业务库和 `backend/data/zhiji.knowledge.sqlite3` 独立知识库，临时清除 PostgreSQL URL，并设置 HTTP 可用的非 Secure 登录 Cookie。退出服务后恢复调用该脚本前的四个数据库/Cookie 环境变量，不修改 `.env`、不迁移或清空已有数据库。不加 `-Local` 时继续使用原有环境配置。脚本保留 UTF-8 BOM，兼容 Windows PowerShell 5.1。

已有健康档案、手动测量、病程分析及导出可在本地使用。知识库中的健康主题和已导入竞赛样本可离线检索；openFDA 药品原文更新需要联网，已有缓存遵循有效期。来源链接、发布日期、下载日期和 SHA 可用于核验所引用资料；主题零命中不能排除疾病，竞赛标注不能用作个人诊断或处方依据。
