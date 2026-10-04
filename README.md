# 知己：Python 后端与网页 / Android / iOS 客户端

这份重写代码位于 `zhiji-next/`，保留原来的 `zhiji/`、`zhiji-py/` 及其数据。

Python FastAPI 统一承担账号、会话、病程与分析逻辑；SQLite 以事务保存数据；Vue 3 + TypeScript 提供电脑网页与手机界面，Capacitor 将同一前端打包成 Android / iOS 应用。多个设备登录同一账号、连接同一服务器即可共享记录，刷新页面取得最新数据。编辑使用版本校验，冲突时提示重新加载，避免覆盖其他设备的修改。

已实现注册 / 登录 / 退出、独立账号数据、病程增查改删、症状与体征 / 用药记录、重复症状组合回顾、危险信号提示、本人数据 JSON 导出与注销账号。记录分析是本地确定性规则，没有调用外部模型。相似病程不能证明安全，历史用药不推断疗效。未实现设备数据接入、推送提醒、区域聚合、医学知识库或离线同步。

## 本机启动（Windows PowerShell）

需要 Python 3.11+、Node.js 22.12+ 和 pnpm 11。当前工作目录已安装项目内 `.venv` 与前端依赖。已有环境可在 `zhiji-next` 运行：

```powershell
.\start.ps1
```

打开 http://127.0.0.1:8788，首次注册自己的账号。接口文档：http://127.0.0.1:8788/docs。默认使用 `backend/data/zhiji.sqlite3`；不自动读取旧数据库或创建演示用户。换端口用 `.\start.ps1 -Port 9000`。

`start.ps1` 以 **UTF-8 with BOM** 保存，Windows PowerShell 5.1 才能正确读取其中的中文提示语；复制或重新保存该脚本时请保留 BOM，否则会因编码解析失败而无法启动。启动前需先有 `frontend/dist`（即先跑过 `pnpm build`）。

在新机器从项目根目录安装：

```powershell
cd zhiji-next
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
cd frontend
npm install --global pnpm@11.19.0
pnpm install --frozen-lockfile
pnpm build
cd ..
.\start.ps1
```

开发时后端在 8788，前端 `pnpm dev` 在 5173，通过 Vite 代理调用 `/api`。生产构建由 Python 同源托管，不需要分别配置网页跨域。Linux/macOS 后端启动：在 `backend` 运行 `../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8788`。

## Android / iOS

`frontend/android` 是 Android Studio 工程；`frontend/ios` 是 Xcode 工程。它们包含同一前端构建。生成工程不等于签名安装包；iOS 编译签名需要 macOS、Xcode 与相应 Apple 开发者配置。[Capacitor 官方工作流](https://capacitorjs.com/docs/basics/workflow)。

Android 命令行签名构建（本机已装 Temurin JDK 17、Android SDK platform 36 / build-tools 36）：

```powershell
cd frontend
pnpm cap:sync            # 先同步最新网页产物到原生工程
cd android
.\gradlew assembleRelease
```

产物在 `android/app/build/outputs/apk/release/app-release.apk`。签名信息从 `android/keystore.properties`（已加入 .gitignore）读取，缺失时 release 构建保持未签名而不会失败：

```properties
storeFile=zhiji-release.jks
storePassword=…
keyAlias=zhiji
keyPassword=…
```

`android/local.properties` 的 `sdk.dir` 需指向本机 Android SDK（例如 `C:/Users/<你>/AppData/Local/Android/Sdk`）。安装到手机后，仍需在与应用连接的 HTTPS 服务地址中登录。

手机不能通过 `127.0.0.1` 访问电脑上的服务。部署 Python 服务到可达的 HTTPS 域名，在 `frontend/.env.local` 设置真实地址（不附加 `/api/v1`）：

```dotenv
VITE_API_BASE_URL=https://health.your-domain.cn
```

随后在 `frontend` 运行：

```powershell
pnpm cap:sync
pnpm android
# macOS 上打开 iOS 项目
pnpm ios
```

当前原生客户端要求 HTTPS 服务地址；未配置时会显示连接配置提示。手机会话令牌只放内存，重新打开应用需要登录；网页使用 HttpOnly Cookie。原生导出调用系统分享面板，导出的内容由用户选择接收方。设备 / HealthKit / Health Connect 接入需要另行增加原生插件与权限。

## 服务部署与数据

环境变量示例见 `backend/.env.example`，在启动 shell 中设置；文件不会自动加载。正式 HTTPS 部署设置 `ZHIJI_COOKIE_SECURE=true`。`ZHIJI_ALLOWED_ORIGINS` 只允许明确来源，默认含 Capacitor 本地来源；增加独立网页域名时需显式填写。建议反向代理只向服务转发可信请求，不将开发服务直接作为公共入口。

此版本适合单机原型 / 小规模试用：SQLite 有事务与 WAL，但未实现数据库静态加密、共享限流、后台审计与备份系统。登录限流为单进程配置；扩大到多实例需共享限流及数据库迁移。备份应使用 SQLite 在线备份机制，不能在写入期间只复制主文件而遗漏 WAL。

旧数据未自动迁移：原型没有账号归属，需要先确认旧用户与新账号映射，并按新版字段验证后再导入。不要把旧 JSON 覆盖到 SQLite 文件。

## 目录与验证

```text
backend/app/       Python 接口、配置、验证、SQLite、会话、安全提示
backend/tests/     账号隔离、多设备数据、冲突及分析规则测试
frontend/src/      三端共享 Vue 界面、类型与 API 客户端
frontend/android/ Android 原生工程
frontend/ios/     iOS 原生工程
start.ps1         本机启动入口
```

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests -q
cd ../frontend
pnpm build
```

风险提示参考 [NHS 胸痛](https://www.nhs.uk/conditions/heart-attack/)、[呼吸困难](https://www.nhs.uk/symptoms/shortness-of-breath/)、[卒中信号](https://www.nhs.uk/conditions/stroke/symptoms/)、[成人发热](https://www.nhs.uk/symptoms/fever-in-adults/)与 [NHS England COVID-19 血氧监测](https://www.england.nhs.uk/coronavirus/documents/covid-19-standard-operating-procedure-covid-oximetry-home/)。这是健康记录原型，规则尚未经临床验证，词匹配不能可靠理解否定或既往描述；界面会要求确认提及的危险信号。血氧阈值来源有特定适用范围，不能替代个人治疗团队的指导。
