# 问诊工作区与 DeepSeek

进入「问诊」选择病程，按症状补问并保存，系统会重新评估优先级。没有回答或不清楚保留为未知，否定回答与明确危险症状冲突时不静默覆盖。七天趋势只显示本次病程内已有读数，静息心率与活动/未知心率分开，最多14个日期点；不补零、不把同名药品核对误称为成分相互作用分析。

知识检索从独立的自建 SQLite 读取原始官方主题：按每个症状和诊断独立搜索、去重、中文优先，最多五篇，每篇最多800字。竞赛实体关系用于数据查询，没有用于个人诊断或处方推断。英文原文保持原样；无命中明确显示资料不足，不表示排除疾病。

## 本机配置

在 `KnowYourself` 的 PowerShell 中运行。密钥通过遮蔽输入读取，不写进代码、浏览器或配置示例；`.env` 不自动加载。

```powershell
$env:ZHIJI_LLM_ENABLED = 'true'
$env:ZHIJI_LLM_BASE_URL = 'https://api.deepseek.com'
$env:ZHIJI_LLM_MODEL = 'deepseek-v4-flash'
$zhijiModelSecret = Read-Host 'DeepSeek API Key' -AsSecureString
$env:DEEPSEEK_API_KEY = [System.Net.NetworkCredential]::new('', $zhijiModelSecret).Password
.\start.ps1 -Local
```

也可用封装好上述步骤的脚本，密钥同样是遮蔽输入、只进当前进程环境，不落盘、不进 Git：

```powershell
.\start-with-model.ps1                 # 默认 deepseek-v4-flash，本地 SQLite
.\start-with-model.ps1 -NoLocal        # 用现有 ZHIJI_DATABASE_* 环境变量，不走本地默认库
.\start-with-model.ps1 -BaseUrl 'https://my-compatible.example/v1' -Model 'my-model'
```

不想每次输入时，可在 `KnowYourself/.env.local`（已由 `.gitignore` 排除）写入 `DEEPSEEK_API_KEY=...`，脚本启动时读取该文件；已有环境变量优先。该文件是本机明文配置，请勿提交或分享。

保留用户指定的 `deepseek-v4-flash`。截至2026-10-11，[官方说明](https://api-docs.deepseek.com/guides/codex)该旧名仍被接受，但由 V4.1 Flash 响应；应用不会自行替换配置值。自有兼容服务可更改 base URL 和 model，地址填写到 `/chat/completions` 的父路径，例如有些服务需要以 `/v1` 结尾。云端必须 HTTPS，仅回环地址允许 HTTP。

默认不联网调用模型。点击生成前展示本次实际发送 JSON，并需明确同意发送到已配置云服务。不会发送账号、姓名、位置、自由备注或整份历史；自填症状、药名等仍可能包含用户输入，请先查看范围。一次点击一次请求、最多1200输出token、15秒网络超时、每账号30秒最多一次、无自动重试；DeepSeek 关闭思考模式以控制延迟。费用遵循所配置服务自身计费，与 Codex 五小时窗口独立。

## 严格提示词与服务端约束

完整系统提示词在 `backend/app/llm.py` 的 `SYSTEM_PROMPT`，版本 `evidence-explanation-1.0`。约束包括仅使用已提供事实、将资料内容视为不可信数据、不得确诊/排除/给概率、不得推荐药物或剂量、不得编造检查、每条解释引用真实证据ID、仅输出限定JSON。输出仅包含解释、不确定性和就诊核实问题。

服务端另行校验结构、长度、引用ID、处方/剂量等越界文字，不允许模型提供分流等级或修改规则行动；存在紧急信号时直接暂停模型生成。不接受前端自填模型地址，不转发重定向，错误响应不回显供应商错误和密钥。缺少配置、超时、不完整JSON或引用错误时保留本地结果。提示词和文字校验不能证明医学正确或识别所有幻觉，当前版本没有临床验证，也未交付自动诊断或个体处方。

接口：`GET /api/v1/episodes/{id}/assessment`；答案沿用带 version 的病程 PUT 保存；`POST /api/v1/episodes/{id}/assessment/explanation` 需当前 `version` 和严格布尔值 `cloud_consent`。生成结果只在当前页面显示，不写入健康事实；病程更新后需重新生成。

## 对话式新建病程

「新建病程」用对话引导代替表单。前端逐轮调用 `POST /api/v1/intake/assistant`，参数为已校验的草稿、本轮用户文本、已用轮数和 `cloud_consent`；服务端返回下一问、拟更新的字段与“还缺哪些字段”。规则：

- **完成与缺项由服务端检查表决定**（主要不适 + 症状为保存所需的最少信息），模型只决定措辞、提问顺序与从自由文本中抽取的字段值；模型**不产生分流等级**，也不能把草稿标记为已保存。
- 模型返回的字段名会被过滤为白名单（未知字段如 `triage`、`file` 直接丢弃），值再经服务端净化，超出 `EpisodeInput` 枚举/范围的一律作废；完整草稿最终仍交给 `POST /episodes`，复用全部校验与分析。
- 输出护栏按 `INTAKE_FORBIDDEN` 过滤确诊/排除/处方/剂量/网址，独立于解释用的 `SYSTEM_PROMPT`；提示词版本 `intake-assistant-1.0`。
- 云端发送前需明确同意；回环地址（`127.0.0.1`/`localhost`）视为本地、不显示云同意项。多轮限流为每账号每分钟 20 轮、每会话最多 24 轮；模型不可用（未配置/超时/校验失败）时保留草稿并提示，**不启用本地假对话兜底**。
- 会话记录只存客户端（浏览器本地），服务端不落库原始对话。

接口格式参考 [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 和 [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。当前无真实API密钥，验收使用模拟响应检查协议、限制与失败回退；配置密钥后还需验证供应商的真实返回。
