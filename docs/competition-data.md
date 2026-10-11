# 本地医学竞赛标注数据

本模块导入用户从脑启数据平台官方医疗栏目授权下载的 CMeIE 与 CMeEE-V2。它们是中文医学信息抽取/实体识别竞赛资料，用于查看原文、关系和实体标注，**不作为医学指南、诊断依据或个性化治疗建议**。不会自动训练模型，也不会改动现有病程分析或风险规则。

两份 ZIP 的 README 仅说明文件格式、评估指标和提交格式，未提供明确再分发许可。当前只在用户本地进行科研与数据核验；源 ZIP 和语料均存放在 Git 忽略的 `backend/data/competition`、知识数据库中，不随代码仓库再分发。来源标识中的“官方”是该平台官方竞赛发布，不代表卫生主管机关的临床数据库。进一步共享或商用应另行核验数据提供方授权。

## 已核验的原件

| 数据集 | 官方来源 | train | dev | test | 结构 |
| --- | --- | ---: | ---: | ---: | --- |
| CMeIE | [脑启 CMeIE](https://naoqi-data.nanhubrain.cn/#/data-detail/2) | 14,339 | 3,585 | 4,482 | 53 种关系 schema；54,286 条关系；72,047 个定位实体 |
| CMeEE-V2 | [脑启 CMeEE-V2](https://naoqi-data.nanhubrain.cn/#/data-detail/1) | 15,000 | 5,000 | 3,000 | 9 种实体类型；108,730 个实体标注 |

CMeIE ZIP SHA-256：`def00cab6e93a2a3475b0f354bb7626ceda51a92bbb31eb75f834539adae7b8c`。

CMeEE-V2 ZIP SHA-256：`f99529d5356d2eb4cd760ff1a89f53249927b6715c2107e3ac193f3bc13dce86`。

代码资源中的 `backend/resources/competition-manifest.json` 仅保存来源、SHA 和计数，不含语料。每次真实导入的 UTC 时间、原始 ZIP 保存位置、来源 URL、SHA、split 计数、schema/实体数也存入独立知识库的 `competition_datasets`，以实际导入元数据为准。

## 导入与部署

在 `backend` 目录执行，使用独立知识库路径，切勿使用账号/病程业务数据库：

```powershell
../.venv/Scripts/python.exe -m app.competition_data import --cmeie D:/Download/CMeIE.zip --cmeee D:/Download/CMeEE-V2.zip --database data/zhiji.knowledge.sqlite3
```

可单独指定其中一个包；`--archive-dir` 可指定本地原件保存目录。原件按 `<dataset>/<SHA256>.zip` 保存，不解压到磁盘目录。部署到自己管理的服务器时，需要在授权范围内单独提供 ZIP 并在服务器执行同样的本地导入命令；代码部署不会自动上传或包含语料。不要将知识库路径指向 `postgresql://` 业务数据库。

导入先检查压缩包与总解压大小均不超过 100 MB、精确成员白名单、重复路径、加密/符号链接成员、JSON 结构、关系 schema 和实体文字位置。所有待导入包验证成功后，在一个 SQLite 事务内替换对应数据集；失败保留旧数据及其他官方知识表。拒绝包含账号/病程业务表的目标库。旧版已授权原件按 SHA 保留，便于审计。

## 查询约定

`competition_status(path)` 返回数据集来源与计数；`search_competition(path, query, dataset='cmeie', split='train', page=1, page_size=10)` 返回带标签的原文、关系与实体。默认仅查询 train；可明确选择 dev 或 test，test 不会混入默认查询。检索词最多 80 字，`%`、`_`、反斜杠作为普通文字匹配；每页最多 50 条。

CMeEE 原始 `end_idx` 为包含末字符的位置，查询结果统一为 Python 切片约定 `[start,end)`。CMeIE 原始关系不提供位置，查询所示实体位置是主体/客体在原文的首次精确匹配，不冒充原始字符位置标注。原 ZIP 完整保留。CMeEE 保留九类原始类型代码：`dis/sym/dru/bod/pro/mic/equ/ite/dep`。

```powershell
../.venv/Scripts/python.exe -m pytest tests/test_competition_data.py -q -p no:cacheprovider
```

测试含合成样例验证与本机授权原 ZIP 的全量计数/哈希/导入核验；其他机器没有原 ZIP 时会跳过原件测试，不会尝试联网获取或接受条款。
