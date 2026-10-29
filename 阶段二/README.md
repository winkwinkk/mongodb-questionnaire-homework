# MongoDB 问卷系统

## 1. 项目简介与功能说明

本项目基于 Flask 和 MongoDB 实现，主要用于练习 MongoDB 数据建模、后端接口设计、条件跳转、答案校验及问卷统计等内容。

项目分为两个阶段。第一阶段实现用户管理、问卷创建、题目管理、条件跳转、答案提交和问卷统计等基础功能。第二阶段根据新的用户需求，在保留原有代码结构和核心功能的基础上，增加独立题目管理、题目版本管理、指定用户共享、多题库管理、题目使用关系查询和跨问卷统计等功能。

### 1.1 主要功能

| 阶段 | 主要功能 |
| --- | --- |
| 第一阶段 | 用户注册与登录、问卷管理、单选题、多选题、文本题、数字题、条件跳转、答案校验、匿名与重复提交控制、问卷及单题统计 |
| 第二阶段 | 独立逻辑题目、题目复用、版本历史与恢复、并发版本冲突处理、指定用户共享与撤销、多题库管理、来源追踪、题目使用关系查询、跨问卷统计 |

前端使用 Jinja、HTML、CSS 和原生 JavaScript，由 Flask 提供页面服务，无需单独启动前端服务。填写问卷需要登录，匿名提交与允许重复填写是两个独立设置。问卷发布后，题目内容及填写设置按照当前业务规则锁定。

第二阶段没有重新实现一套独立系统，而是在原有问卷和回答结构的基础上进行扩展，尽量减少新增功能对原有填写、跳转和统计流程的影响。

## 2. 环境配置与启动方法

### 2.1 环境与依赖

| 项目 | 环境或工具 |
| --- | --- |
| 编程语言 | Python |
| Web 框架 | Flask |
| 数据库 | MongoDB |
| 数据库驱动 | PyMongo |
| 后端测试 | Python 标准库 `unittest`、`unittest.mock`、Flask 测试客户端 |
| 浏览器测试 | Node.js、Playwright、Chrome |

根据现有环境记录，当前开发环境使用 Python 3.13.0、Flask 3.1.3 和 PyMongo 4.18.1。保存的隔离 MongoDB 集成测试使用 MongoDB 8.3.11。
项目运行依赖以根目录的 `requirements.txt` 为准，该文件列出依赖，但没有锁定全部版本。

### 2.2 安装依赖与配置数据库

以下命令以 Windows PowerShell 为例，在项目根目录执行。

先确保 MongoDB 已启动，然后创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
```

如果已经有可用的项目虚拟环境，可以直接复用，不必重复创建。

配置数据库连接：

```powershell
$env:MONGO_URI = "mongodb://localhost:27017/"
$env:MONGO_DATABASE = "questionnaire_system_stage2"
```

项目支持以下环境变量：

| 环境变量 | 作用 | 默认值或行为 |
| --- | --- | --- |
| `MONGO_URI` | MongoDB 连接地址 | `mongodb://localhost:27017/` |
| `MONGO_DATABASE` | 数据库名称 | `questionnaire_system` |
| `FLASK_SECRET_KEY` | Flask 会话密钥 | 直接运行应用时需要提供 |
| `PORT` | 服务端口 | 默认 `5000` |
| `FLASK_DEBUG` | 是否开启调试模式 | 默认关闭，设置为 `1` 时开启 |

数据库名称由 `MONGO_DATABASE` 决定，不会因为项目目录名称不同而自动变化。第二阶段建议使用独立的测试数据库，避免测试数据影响已有业务数据。

### 2.3 初始化数据库并启动服务

项目提供 `start.ps1` 启动脚本。配置好数据库环境变量后，可以执行：

```powershell
.\start.ps1 -PythonPath ".\.venv\Scripts\python.exe" -Port 5001
```

该脚本负责准备会话密钥、执行数据库初始化，并在初始化成功后启动 Flask 应用。如果初始化失败，脚本会停止启动流程。

启动成功后，在浏览器中打开：

`http://127.0.0.1:5001`

服务默认仅监听本机地址。终端应保持开启，停止服务时按 `Ctrl+C`。

如果不使用启动脚本，需要自行准备会话密钥并完成数据库初始化，再启动应用：

```powershell
$env:FLASK_SECRET_KEY = & ".\.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_hex(32))"
$env:PORT = "5001"
& ".\.venv\Scripts\python.exe" -B init_schema.py
if ($LASTEXITCODE -eq 0) {
    & ".\.venv\Scripts\python.exe" -B app.py
}
```

数据库初始化会创建或更新集合校验规则和索引，并执行已有参与记录补全及待处理操作恢复。初始化不会自动将旧问卷的回答映射到新建的独立逻辑题目。

需要注意：单独启动 `app.py` 不会自动执行数据库初始化；更换会话密钥可能导致原有登录会话失效。执行初始化前应再次确认数据库连接地址和数据库名称。

### 2.4 页面使用

常用页面入口如下：

| 页面 | 路径 | 用途 |
| --- | --- | --- |
| 注册 | `/register` | 创建用户账号 |
| 登录 | `/login` | 登录系统 |
| 工作台 | `/dashboard` | 查看和管理本人问卷 |
| 题目库 | `/library` | 管理独立题目 |
| 我的题库 | `/question-banks` | 管理个人题库 |

推荐的基本使用流程：

1. 创建独立题目，并查看其初始版本。
2. 将题目加入题库。
3. 创建问卷草稿，从题目库或题库中选择题目。
4. 配置问卷题目、校验规则和条件跳转。
5. 发布问卷，登录填写并提交答案。
6. 查看单份问卷统计或符合权限范围的跨问卷统计。
7. 创建新版本，检查版本历史以及已有问卷快照是否保持稳定。
8. 使用不同账号体验题目共享、撤销共享、重新授权和权限隔离。

## 3. 项目目录结构

项目主要目录如下，具体以最终提交的项目文件为准。

```text
work2/
├── app.py
├── start.ps1
├── init_schema.py
├── requirements.txt
├── models/
├── routes/
├── templates/
├── static/
├── tests/
├── tools/
├── docs/
│   ├── system-overview.md
│   ├── database-design.md
│   ├── API.md
│   ├── key-logic.md
│   ├── 测试用例.md
│   ├── 项目报告.md
│   └── ai-usage.md
└── README.md
```

| 目录或文件 | 作用 |
| --- | --- |
| `models/` | 数据访问、数据模型及主要业务逻辑 |
| `routes/` | 页面路由与 JSON API 接口 |
| `templates/` | Jinja 页面模板 |
| `static/` | CSS、JavaScript 等静态资源 |
| `tests/` | 单元、API、数据库、页面及相关自动化测试 |
| `tools/` | 隔离数据库测试和浏览器测试工具 |
| `init_schema.py` | 数据库 Schema、索引初始化及相关恢复入口 |
| `start.ps1` | 数据库初始化与服务启动脚本 |
| `docs/` | 系统说明、数据库设计、API、关键逻辑、测试和项目报告 |

## 4. 数据库集合与 Schema

第一阶段使用 `users`、`surveys`、`responses` 和 `participations` 四个集合。第二阶段在保留原有结构的基础上，增加题目、版本、共享授权、题库及相关辅助数据结构。

下表为主要集合概览，并非完整 Schema。

| 集合 | 主要作用 | 关键字段或关联 |
| --- | --- | --- |
| `users` | 用户账号 | `_id`、`username`、`passwordHash`、`createdAt`；用户名唯一 |
| `surveys` | 问卷及其题目快照 | `ownerId`、`status`、`questions`；题目、选项、校验和跳转规则嵌入问卷 |
| `responses` | 问卷提交记录 | `surveyId`、`answers`、`submittedAt`；答案中的 `questionId` 关联问卷内题目实例 |
| `participations` | 重复提交控制及提交恢复 | `surveyId`、`userId`、`responseId`、`status`；问卷和用户建立复合唯一约束 |
| `questions` | 逻辑题目 | `ownerId`、`currentVersionId`、`versionRevision`、`versionCounter` |
| `question_versions` | 不可变的题目版本 | `questionId`、`versionNumber`、`content`、`basedOnVersionId`、`restoredFromVersionId` |
| `question_shares` | 指定用户共享授权 | `questionId`、`ownerId`、`recipientUserId`、授权状态 |
| `question_banks` | 个人题库 | `ownerId`、`name`、`revision`、状态 |
| `question_bank_items` | 题库中的题目条目 | `bankId`、`questionId`、`defaultVersionId`、`revision` |
| `question_version_operations` | 版本操作回执与恢复辅助记录 | `questionId`、`operationId`、`kind`、`outcome` |
| `question_statistics_events` | 统计兼容配置及其变更记录 | `questionId`、`groups`、`revision`、`previousEventId`、`actorId`、`reason` |

### 4.1 三类题目标识

第二阶段需要明确区分三种 ID：

- **问卷内题目实例 ID：** `surveys.questions._id`，用于问卷编辑、排序、跳转及回答关联。
- **逻辑题目 ID：** `questions._id`，用于题目复用、共享、版本管理和跨问卷追踪。
- **题目版本 ID：** `question_versions._id`，对应某一份确定的题目内容。

问卷内的题目实例通过 `sourceQuestionId` 和 `sourceVersionId` 记录来源。即使同一逻辑题目被加入同一问卷多次，也会创建不同的问卷内题目实例。

题目版本更新或题库默认版本变化，不会自动修改已有问卷的题目快照。恢复历史内容会创建新版本；显式选择已有推荐版本则不需要重新创建版本。

### 4.2 Schema 与索引

原有集合的 Schema 定义见 `init_schema.py`，新增题目相关的 Schema 和索引见 `models/library_schema.py`。

数据库校验规则用于约束字段类型、必填字段及枚举值；索引用于支持常见查询并保证必要的唯一性。引用是否存在、用户是否拥有操作权限、版本是否允许修改，以及快照与来源是否一致等业务规则，仍需要由后端进行检查。

完整字段定义、索引设计和选择这些结构的原因见 [MongoDB 数据库设计文档](docs/database-design.md)。

## 5. API 接口说明

项目通过 Flask 提供 JSON API。需要登录的接口使用登录后的 Session Cookie；存在请求体时，通常使用 `application/json` 格式。

下表列出主要接口，完整参数、响应字段、错误状态及权限要求见 [API 接口文档](docs/API.md)。

| 功能 | 方法与路径 | 用途 |
| --- | --- | --- |
| 健康检查 | `GET /api/health` | 检查健康检查路由是否可访问，不代表数据库连接一定正常 |
| 用户注册与登录 | `POST /api/register`、`POST /api/login` | 创建账号及登录 |
| 问卷管理 | `POST /api/surveys`、`GET /api/surveys` | 创建和列出本人问卷 |
| 问卷配置 | `GET /api/surveys/{sid}/manage`、`PATCH /api/surveys/{sid}` | 查看问卷配置、修改草稿设置 |
| 问卷发布 | `POST /api/surveys/{sid}/publish` | 发布草稿问卷 |
| 题目管理 | `POST /api/surveys/{sid}/questions`、`PUT /api/surveys/{sid}/questions/{iid}` | 添加或编辑问卷内题目 |
| 条件跳转 | `POST /api/surveys/{sid}/questions/{iid}/rules` | 配置题目跳转规则 |
| 填写与提交 | `POST /api/surveys/{sid}/next`、`POST /api/surveys/{sid}/responses` | 计算下一题并提交答案 |
| 单份问卷统计 | `GET /api/surveys/{sid}/statistics` | 查看本人问卷的统计结果 |
| 独立题目 | `POST /api/questions`、`GET /api/questions` | 创建及列出本人逻辑题目 |
| 版本管理 | `GET /api/questions/{qid}/versions`、`POST /api/questions/{qid}/versions` | 查看版本历史、创建新版本 |
| 版本差异与恢复 | `GET /api/questions/{qid}/version-diff`、`POST /api/questions/{qid}/versions/{vid}/restore` | 比较版本及恢复历史内容 |
| 推荐版本 | `PUT /api/questions/{qid}/current-version` | 显式选择当前推荐版本 |
| 独立副本 | `POST /api/questions/{qid}/copies` | 创建自己的题目副本 |
| 共享授权 | `POST /api/questions/{qid}/shares`、`DELETE /api/questions/{qid}/shares/{share_id}` | 创建或撤销指定用户的共享授权 |
| 共享题目列表 | `GET /api/shared-questions` | 查看当前用户收到的有效共享 |
| 多题库管理 | `POST /api/question-banks`、`GET /api/question-banks` | 创建及列出个人题库 |
| 题库条目 | `GET /api/question-banks/{bid}/items`、`POST /api/question-banks/{bid}/items` | 查看和添加题库条目 |
| 从题库选题 | `POST /api/question-banks/{bid}/items/{item_id}/select` | 将题库中的指定版本选入本人草稿 |
| 使用关系 | `GET /api/questions/{qid}/usage` | 查询本人问卷中的题目使用情况 |
| 跨问卷统计 | `GET /api/questions/{qid}/statistics` | 汇总符合权限及统计口径的回答 |
| 统计兼容配置 | `GET /api/questions/{qid}/statistics-configuration`、`PUT /api/questions/{qid}/statistics-configuration` | 查看及确认统计兼容配置 |

共享题目不代表获得原题版本管理权，也不代表能够查看其他用户的问卷回答。题目所有权、有效共享授权、问卷状态和版本冲突等限制由后端进行检查。

## 6. 测试用例、输入输出与结果

项目使用单元测试、真实 MongoDB 集成测试、浏览器自动化测试及人工网页操作检查系统功能。

以下列出具有代表性的历史自动化测试场景。预期结果来自测试设计，实际结果来自保存的历史测试记录；本次整理 README 没有重新执行测试。

### 6.1 代表性自动化测试

| 编号与场景 | 测试步骤与输入 | 预期结果 | 历史实际结果 |
| --- | --- | --- | --- |
| T01 原有流程回归 | 创建不同题型并设置条件跳转；提交必答多选题空数组 `[]`，再提交合法选项 `["a"]`；提交年龄 18 和 20 | 非法提交返回 400 且不保存；合法提交成功；选项计数与数字均值正确 | 历史测试断言通过 |
| T02 题目复用与来源 | 将同一逻辑题目及版本加入草稿两次，发布后提交两个题目实例的答案 | 两个实例 ID 不同，来源版本一致，答案仍关联实例 ID | 内存及真实 MongoDB 对应测试通过 |
| T03 版本恢复 | 创建数字题 V1、V2，再恢复 V1 的内容 | 恢复操作生成新版本，历史记录保留，基准版本与恢复来源分别记录 | 历史测试断言通过 |
| T04 撤销共享 | A 授权 B，B 将题目加入题库并选入问卷；撤销授权后再次尝试选题 | 后续选题被拒绝；已有合法问卷快照不被直接删除 | 历史测试断言通过 |
| T05 跨版本统计 | V1 有一次数值答案 10，V2 有三次数值答案 30，随后确认合并数字均值 | 有效答案数为 4，加权均值为 25；版本明细仍可区分 | 历史测试断言通过 |
| T06 跨用户统计隔离 | A、B 分别在自己的问卷中使用共享题并提交 10、90，分别查询统计 | 双方只能查看本人问卷范围内的统计；撤销共享不删除已有合法数据 | 历史测试断言通过 |

以上场景的输入和预期结果用于说明测试方法，不应代替完整测试代码及原始日志。对应测试方法可以在以下文件中查找：

- T01：`tests/test_mongodb_backend.py`
- T02：`tests/test_library.py`
- T03：`tests/test_versions.py`
- T04：`tests/test_sharing_banks.py`
- T05、T06：`tests/test_question_statistics.py`

### 6.2 历史测试结果

根据保存的历史测试记录：

| 测试类型 | 历史结果 |
| --- | --- |
| 后端自动化测试 | 2026-10-28 第六批累计 146 次测试执行，全部通过、无跳过；其中 41 次为非数据库测试执行，105 次为真实 MongoDB 测试执行 |
| 浏览器自动化测试 | 23 组 Chrome 流程通过，覆盖题目选用、填写、版本、共享、统计、冲突处理及页面布局等 |
| 人工网页测试 | 已实际进行题目创建与复用、版本管理、共享、多题库、跨问卷统计、权限隔离、异常提示及原有功能体验；逐项输入和输出记录不完整，因此不将所有人工操作认定为独立验收通过 |

上述批次是累计记录，不能直接相加作为独立测试用例数量。相同业务场景在内存环境与真实数据库环境中分别执行，也会分别计次。

第五批首轮执行时，141 次测试中 138 次通过、3 次失败。根据实施记录，失败与故障注入测试的模拟对象不一致有关；调整模拟对象并补充测试后，第五批累计 145 次测试全部通过，第六批累计 146 次测试全部通过。

详细测试步骤、输入输出、历史结果和限制见 [测试用例与结果文档](docs/测试用例.md)。

### 6.3 测试复现方法

**后端与 API 测试**

准备本机 MongoDB 可执行文件及 Python 依赖后，可以通过隔离数据库测试工具运行测试：

```powershell
& ".\.venv\Scripts\python.exe" -B tools/run_isolated_mongo_tests.py --mongod "C:\数据库\bin\mongod.exe" --output "$env:TEMP\questionnaire-stage2-tests.txt"
```

如果 MongoDB 安装位置不同，需要将 `--mongod` 后的路径替换为实际路径。

该工具用于启动独立的临时 MongoDB 测试实例、启用真实数据库测试、执行自动化测试并保存日志。测试会写入和清理测试数据，不能将其指向正式业务数据库。

**浏览器自动化测试**

浏览器测试需要 Node.js、Chrome 以及 Playwright 相关依赖。运行前，应根据实际安装位置配置 MongoDB、Node.js、依赖目录和浏览器路径。具体参数以 `tools/run_frontend_checks.py` 的实现为准。

浏览器测试会启动独立测试服务和数据库，并生成相应的结果记录及截图。执行前应注意保留需要提交的历史测试证据。

**人工测试**

人工测试应通过浏览器实际操作，并分别记录测试步骤、输入、预期结果、实际输出及结论。自动化测试结果不能直接代替人工测试记录。

## 7. 相关文档

| 文档 | 内容 |
| --- | --- |
| [系统说明](docs/system-overview.md) | 系统功能、组成及模块职责 |
| [数据库设计](docs/database-design.md) | 集合、Schema、索引及设计理由 |
| [API 接口说明](docs/API.md) | 接口路径、参数、响应与权限 |
| [关键业务逻辑](docs/key-logic.md) | 版本、快照、共享、跳转、校验及统计逻辑 |
| [测试用例与结果](docs/测试用例.md) | 测试步骤、输入输出、历史结果和验证范围 |
| [自动化测试执行日志（2026-10-28）](docs/自动化测试执行日志-2026-10-28.txt) | 已保存的历史自动化测试原始输出 |
| [项目完成报告](docs/项目报告.md) | 需求变化、设计取舍、开发问题与个人思考 |
| [AI 使用日志与说明](docs/ai-usage.md) | AI 工具、提示词、生成和修改内容及本人判断 |
