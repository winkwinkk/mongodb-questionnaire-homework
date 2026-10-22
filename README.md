# MongoDB 在线问卷系统

本项目是基于 Python、Flask 和 MongoDB 实现的在线问卷系统，支持问卷创建、发布分享、在线填写和结果统计。前端采用 HTML、CSS 和原生 JavaScript，业务数据保存在 MongoDB 的 users、surveys、responses 和 participations 四个集合中。

## 1. 主要功能

- 用户注册、登录、退出，以及本人问卷的管理与权限隔离。
- 创建和修改草稿，发布问卷、设置截止时间和关闭收集。
- 配置单选、多选、文本和数字题，设置必答、数量、长度及数值限制。
- 根据单选、多选和数字答案执行可配置的向后跳转。
- 逐题填写、返回修改、最终校验、匿名提交和重复填写控制。
- 查看整体或单题统计，包括选项次数、文本内容和数字平均值。

填写始终要求登录；匿名与重复填写开关独立，默认均关闭。发布后题目及填写设置锁定。匿名表示向创建者隐藏身份，后台参与记录仍可用于账号去重。

## 2. 运行环境

- Windows 与 PowerShell；项目已有开发环境使用 Python 3.13。
- MongoDB 4.2 或以上，支持单机模式，运行前须启动数据库服务。
- Python 依赖：Flask、PyMongo，安装入口为 `requirements.txt`。
- 浏览器直接访问 Flask 提供的网页，无需安装 Node.js 或启动独立前端服务。

## 3. 项目结构

| 文件或目录 | 用途 |
| --- | --- |
| `app.py` | Flask 应用与网页服务入口 |
| `start.ps1` | 初始化数据库并启动应用 |
| `init_schema.py` | 创建或更新四集合 Schema、索引及恢复待完成提交 |
| `requirements.txt` | Python 运行依赖 |
| `models/` | 数据访问、答案校验、跳转及提交处理 |
| `routes/` | JSON API 和网页路由 |
| `templates/`、`static/` | HTML 模板、CSS 和 JavaScript |
| `tests/` | 单元、API、数据库集成及页面测试 |
| `docs/` | 设计文档、测试用例、报告与 AI 使用记录 |

## 4. 安装与启动

### 首次运行

先安装 Python 和 MongoDB，并启动 MongoDB 服务。在 PowerShell 中进入解压后的项目根目录，即包含 `app.py` 的目录，执行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.ps1 -PythonPath '.\.venv\Scripts\python.exe'
```

脚本自动准备会话密钥，创建或更新数据库校验与索引，补建可识别历史用户的参与记录，恢复待完成提交，然后启动服务；不会主动删除已有回答。初始化失败时会停止启动。

打开 [http://127.0.0.1:5000](http://127.0.0.1:5000)，注册登录后即可创建问卷。使用流程为：创建草稿 → 添加题目与规则 → 发布并复制填写链接 → 登录填写 → 查看统计。终端需保持开启，按 `Ctrl+C` 停止服务。

再次运行只需执行启动命令。端口被占用时，可增加 `-Port 5001`。本机已有项目上一级 `.venv` 环境时，也可直接执行 `.\start.ps1`；其他环境应显式指定 `-PythonPath`。

### 可选配置

在启动前，可在同一 PowerShell 窗口通过 `$env:变量名 = '值'` 设置：

| 环境变量 | 默认值或作用 |
| --- | --- |
| `MONGO_URI` | `mongodb://localhost:27017/` |
| `MONGO_DATABASE` | `questionnaire_system` |
| `FLASK_SECRET_KEY` | 启动脚本在未设置时生成；直接运行 app.py 时必须设置 |
| `PORT` | app.py 默认使用 5000；启动脚本通过 `-Port` 设置 |
| `FLASK_DEBUG` | 默认关闭，值为 1 时开启调试 |

若 PowerShell 阻止脚本执行，可使用以下替代方式，无需修改执行策略：

```powershell
$env:FLASK_SECRET_KEY = & '.\.venv\Scripts\python.exe' -c 'import secrets; print(secrets.token_hex(32))'
& '.\.venv\Scripts\python.exe' -B init_schema.py
if ($LASTEXITCODE -eq 0) { & '.\.venv\Scripts\python.exe' -B app.py }
```

以上命令按新建的项目内 `.venv` 环境编写。服务默认仅监听本机，填写链接用于本机演示；跨设备访问需另行配置可达地址。更换会话密钥会使旧登录状态失效。

## 5. 运行测试

在项目根目录执行；测试客户端直接调用应用，无需另行启动网页服务器：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:RUN_MONGO_TESTS = '1'
& '.\.venv\Scripts\python.exe' -B -m unittest discover -s tests -v
Remove-Item Env:RUN_MONGO_TESTS
```

当前共 39 个测试方法，覆盖创建问卷、添加题目、跳转、校验、提交和统计，并补充权限、匿名去重、并发、中断恢复及页面检查。其中 15 个真实数据库测试要求 MongoDB 可连接，并使用独立随机临时库，结束后清理。

不设置 `RUN_MONGO_TESTS=1` 时，真实数据库测试会标为 `skipped`，不能算作全部通过。测试范围、步骤和执行记录见下方测试用例；原有 `test_database.py` 是历史基础检查脚本，正式测试入口采用上述 `tests/` 测试套件。

## 6. 数据库与 Schema 摘要

| 集合 | 主要数据与关系 | 索引 |
| --- | --- | --- |
| users | username、passwordHash、createdAt | username唯一 |
| surveys | ownerId引用用户；嵌入questions、options、validation、jumpRules | ownerId查询 |
| responses | surveyId引用问卷；嵌入本次answers；匿名省略respondentId | surveyId查询 |
| participations | surveyId、userId、固定responseId、pending/committed状态；临时payload供恢复 | (surveyId,userId)唯一 |

题目随问卷一起读取，回答持续增长而独立存储。ObjectId维护逻辑引用，Schema检查基础类型，后端执行权限、答案及跳转约束。完整字段、类型、必需性、默认值和嵌套结构见 [数据库设计](docs/database-design.md)，可执行Schema见 [init_schema.py](init_schema.py)。

## 7. API 摘要

JSON接口使用同源Session Cookie；有请求体时发送application/json，ID使用ObjectId字符串。权限、参数、返回对象和错误详见 [API说明](docs/api-reference.md)。

| 编号 | 方法 | 路径 | 权限 |
| --- | --- | --- | --- |
| A01 | GET | `/api/health` | 无 |
| A02 | POST | `/api/register` | 无 |
| A03 | POST | `/api/login` | 无 |
| A04 | GET | `/api/me` | 登录 |
| A05 | POST | `/api/logout` | 无 |
| A06 | POST | `/api/surveys` | 登录 |
| A07 | GET | `/api/surveys` | 登录，仅本人问卷 |
| A08 | GET | `/api/surveys/<survey_id>/manage` | 问卷创建者 |
| A09 | GET | `/api/surveys/<survey_id>` | 登录填写者 |
| A10 | PATCH | `/api/surveys/<survey_id>` | 创建者，草稿状态 |
| A11 | POST | `/api/surveys/<survey_id>/publish` | 创建者，草稿状态 |
| A12 | PUT | `/api/surveys/<survey_id>/deadline` | 创建者，已发布问卷 |
| A13 | POST | `/api/surveys/<survey_id>/close` | 创建者，已发布问卷 |
| A14 | POST | `/api/surveys/<survey_id>/questions` | 创建者，草稿状态 |
| A15 | PUT | `/api/surveys/<survey_id>/questions/<question_id>` | 创建者，草稿状态 |
| A16 | DELETE | `/api/surveys/<survey_id>/questions/<question_id>` | 创建者，草稿状态 |
| A17 | POST | `/api/surveys/<survey_id>/questions/<source_id>/rules` | 创建者，草稿状态 |
| A18 | DELETE | `/api/surveys/<survey_id>/questions/<question_id>/rules/<int:rule_index>` | 创建者，草稿状态 |
| A19 | POST | `/api/surveys/<survey_id>/next` | 登录填写者 |
| A20 | POST | `/api/surveys/<survey_id>/responses` | 登录填写者 |
| A21 | GET | `/api/surveys/<survey_id>/statistics` | 问卷创建者 |
| A22 | GET | `/api/surveys/<survey_id>/questions/<question_id>/statistics` | 问卷创建者 |

例如，登录后POST `/api/surveys` 输入 `{"title":"课程调查","anonymousAllowed":true}`，成功返回201及 `{message,survey}`，survey含id、标题、状态和时间等字段。再用真实id添加题目、配置规则、发布；填写时通过next计算下一题，最后调用responses保存。上述对象为结构说明，完整请求与响应示例见API文档。

## 8. 六类测试与结果摘要

| 测试 | 输入或步骤 | 预期结果 | 已有实际结果 |
| --- | --- | --- | --- |
| 创建问卷 | 注册登录，提交“流程测试” | 创建并返回ID | 201，后续配置成功 |
| 添加题目 | 添加四类题型；四线程追加12题 | 保存且题序完整 | 201；并发顺序1～12 |
| 跳转 | yes跳后题，数字≥18和多选包含a规则 | 按配置跳转 | 返回配置目标，末题后完成 |
| 校验 | 必答多选[]、无效选项、18.5年龄 | 拒绝非法答案 | 校验断言通过；非法提交400且无回答 |
| 提交 | 开启重复，提交年龄18和20，第二份匿名 | 两份保存且匿名省略身份 | 均201，共2份，匿名无respondentId |
| 统计 | 查询上述两份回答及他人访问 | 总数2、平均19、a次数2；他人拒绝 | 数值断言通过，他人404 |

历史完整记录为2026年10月20日39项通过；本会话10月22日曾复核原有39项，8.725秒、OK、无跳过，见 [测试执行记录](docs/测试用例.md)。该摘要不是完整原始日志，本轮仅文档更新未重新测试。现有用例不代表所有边界已验收，范围见 [测试用例](docs/测试用例.md)。

当前部分题目接口非法ID可能返回500，日期时区后缀未完全统一，重复规则未自动拦截，统计在Python中汇总。这些保留为实际限制，不列为已修复能力。

## 9. AI 使用说明

前期使用ChatGPT讨论需求和结构，后期使用Codex结合本地文件实施和验证。主要代码生成与后期修改由AI辅助完成，本人参与业务规则确认、范围控制、实际运行反馈及复测。工具、提示词、生成内容、是否修改及验证情况见 [AI使用日志与说明](docs/ai-usage.md)，不把AI直接写入的实现描述为本人独立手写。

## 10. 文档索引

- [系统说明](docs/system-overview.md)
- [数据库设计](docs/database-design.md)
- [API 说明](docs/api-reference.md)
- [关键逻辑说明](docs/key-logic.md)
- [测试用例与执行记录](docs/测试用例.md)
- [历史完整测试输出（2026年10月20日）](docs/test-results-web-2026-10-20.txt)
- [项目报告](docs/项目报告.md)
- [AI 使用日志与说明](docs/ai-usage.md)
