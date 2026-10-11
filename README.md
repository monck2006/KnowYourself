# 知己：Python 后端与网页 / Android / iOS 客户端

项目代码位于 `KnowYourself/`，保留工作区中其他旧版本及其数据。下文命令从本项目目录运行。

Python FastAPI 统一承担账号、会话、病程与分析逻辑；SQLite 以事务保存数据；Vue 3 + TypeScript 提供电脑网页与手机界面，Capacitor 将同一前端打包成 Android / iOS 应用。多个设备登录同一账号、连接同一服务器即可共享记录，刷新页面取得最新数据。编辑使用版本校验，冲突时提示重新加载，避免覆盖其他设备的修改。

已实现注册 / 登录 / 退出、昵称修改、修改密码并撤销其他设备会话、独立账号数据、病程增查改删、症状与体征 / 用药记录、重复症状组合回顾、危险信号提示、本人数据 JSON 导出与注销账号。我的记录支持按开始日期与状态筛选，按症状 / 用药 / 笔记组合搜索，四种排序、每页 12 条展示，以及当前筛选结果的 CSV 导出。CSV 可用 Excel 打开，完整备份使用 JSON；尚不支持备份导入。

概览与记录通过 `/api/v1/workspace` 一次读取；账号、历史与记录弹窗按需加载。退出登录会清除当前记录和详情，并忽略之前账号的未完成读取。已实现个人档案、病程与用药全过程、发病前静息基线、区域症状汇总和官方资料查询；Android Health Connect / iOS HealthKit 原生读取代码已接入。问诊工作区支持按症状补问、保存答案后重评、七天测量趋势、同名用药核对和自建知识库证据检索。可选 DeepSeek 生成带引用的解释，默认关闭；未实现推送提醒或离线同步。

就诊摘要：在「我的记录」筛选后点击「就诊摘要」，可整理全部筛选结果（包括其他分页）；在单条详情中可整理该次病程。摘要按开始日期列出症状、实际填写的体征、用药与笔记，统计症状 / 用药出现的记录条数，并允许临时补充就诊问题。网页端可调用浏览器打印，选择“另存为 PDF”；也可下载带完整样式的 HTML 离线打开。Android / iOS 使用系统分享面板导出 HTML。问题清单仅属于本次预览，关闭后清空；生成报告不修改原始记录，不产生诊断，也不调用外部模型。

## 本机启动（Windows PowerShell）

需要 Python 3.11+、Node.js 22.18+ 和 pnpm。当前工作目录已安装项目内 `.venv` 与前端依赖。已有环境可在 `KnowYourself` 运行：

```powershell
.\start.ps1 -Local
```

打开脚本打印的实际网址，首次注册自己的账号。8788 被占用或被 Windows 保留时会自动选择可用端口；接口文档为实际网址后加 `/docs`。`-Local` 使用 `backend/data/zhiji.sqlite3` 和独立知识库，临时忽略遗留 PostgreSQL URL 并设置本地 HTTP 登录 Cookie。不创建演示用户、不清空已有数据。换端口用 `.\start.ps1 -Local -Port 9000`。[本地使用说明](docs/local-use.md)。

`start.ps1` 以 **UTF-8 with BOM** 保存，Windows PowerShell 5.1 才能正确读取其中的中文提示语；复制或重新保存该脚本时请保留 BOM，否则会因编码解析失败而无法启动。启动前需先有 `frontend/dist`（即先跑过 `pnpm build`）。

在新机器从项目根目录安装：

```powershell
cd KnowYourself
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

Android 命令行构建需要 JDK 21、Android SDK platform 36。已验证设备插件 Kotlin 编译和 debug APK 构建；最新版网页更改后需重新同步打包。[设备接入与验证范围](docs/device-integration.md)。

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

当前原生客户端要求 HTTPS 服务地址；未配置时会显示连接配置提示。手机会话令牌只放内存，重新打开应用需要登录；网页使用 HttpOnly Cookie。原生导出调用系统分享面板，导出的内容由用户选择接收方。HealthKit / Health Connect 只读插件与权限已接入，真实设备读取尚需手机授权验收；本地网页版可手动录入测量，兼容浏览器还可连接标准蓝牙心率设备。

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
pnpm test
pnpm build
```

风险提示参考 [NHS 胸痛](https://www.nhs.uk/conditions/heart-attack/)、[呼吸困难](https://www.nhs.uk/symptoms/shortness-of-breath/)、[卒中信号](https://www.nhs.uk/conditions/stroke/symptoms/)、[成人发热](https://www.nhs.uk/symptoms/fever-in-adults/)与 [NHS England COVID-19 血氧监测](https://www.england.nhs.uk/coronavirus/documents/covid-19-standard-operating-procedure-covid-oximetry-home/)。规则尚未经临床验证，词匹配不能可靠理解否定或既往描述；结构化补问会标记矛盾，保留较高处理优先级。血氧参考阈值有特定适用范围。

## DeepSeek 与问诊工作区

本地不配置模型也可完成补问、重评、趋势与知识检索。按 [DeepSeek 配置与严格提示词说明](docs/llm-assessment.md) 在本机设置密钥后，主动点击「生成本次证据解释」才调用模型。云端调用前显示发送范围并需勾选本次同意；提示词、结构校验、引用 ID 校验和风险规则分别执行。模型不能修改分流或生成处方，失败时保留完整本地结果。
