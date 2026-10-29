# API 接口说明

## 1. 文档说明

本文档介绍问卷系统第二阶段的后端 JSON API，包括接口用途、请求参数、权限要求、主要返回结果和常见错误。第二阶段在第一阶段已有的用户管理、问卷管理、题目管理、条件跳转、答案校验、问卷提交和统计功能基础上，增加了逻辑题目与版本管理、题目共享、多题库、问卷题目快照、使用关系查询和跨问卷统计等功能。
本次升级保留第一阶段的核心业务流程和嵌入式问卷题目结构，没有用全新的系统替代原系统。

### 1.1 基本约定

- 基础路径：`/api`
- 数据格式：JSON。
- 认证方式：登录后使用 Flask Session Cookie。
- 请求中的日期时间使用实际接口支持的 ISO 时间字符串格式。
- `<survey_id>`、`<question_id>`、`<version_id>` 等为路径参数，实际请求时需要替换为对应的资源 ID。
- 除特别说明外，POST、PUT、PATCH 请求通过 JSON 请求体传递业务数据。

第二阶段需要特别区分三种标识：

| 标识 | 含义 | 主要用途 |
|---|---|---|
| 逻辑题目 ID | 可复用和管理版本的题目身份 | 题目管理、共享、版本管理和跨问卷统计 |
| 版本 ID | 逻辑题目的某一份具体内容 | 版本历史、恢复和版本切换 |
| 问卷题目实例 ID | 某道题在具体问卷中的身份 | 问卷编辑、答题、跳转和回答关联 |

问卷中的 `_id`、回答中的 `questionId` 和跳转规则中的目标题目 ID，仍然用于关联问卷内的题目实例，不能直接替换成逻辑题目 ID。

### 1.2 常见 HTTP 状态码

| 状态码 | 含义 |
|---|---|
| 200 | 请求成功 |
| 201 | 创建成功 |
| 400 | 请求参数或业务规则不符合要求 |
| 401 | 未登录、认证失败或当前会话无效 |
| 404 | 资源不存在，或当前用户无权访问该资源 |
| 409 | 资源状态、版本修订或唯一性约束发生冲突 |
| 500 | 服务端处理异常 |

---

## 2. 接口总览

### 2.1 第一阶段基础接口

以下接口继续承担原有业务功能。第二阶段通过新增接口扩展题目复用能力，不取代原有问卷创建、填写和统计流程。

| 模块 | 方法与路径 | 用途 |
|---|---|---|
| 健康检查 | `GET /api/health` | 检查后端路由是否能够响应 |
| 账号 | `POST /api/register` | 注册用户 |
| 账号 | `POST /api/login` | 登录 |
| 账号 | `GET /api/me` | 获取当前用户信息 |
| 账号 | `POST /api/logout` | 退出登录 |
| 问卷 | `POST /api/surveys` | 创建问卷 |
| 问卷 | `GET /api/surveys` | 查询本人问卷列表 |
| 问卷 | `GET /api/surveys/{survey_id}/manage` | 获取问卷管理配置 |
| 问卷 | `GET /api/surveys/{survey_id}` | 获取可填写问卷 |
| 问卷 | `PATCH /api/surveys/{survey_id}` | 修改草稿基本设置 |
| 问卷 | `POST /api/surveys/{survey_id}/publish` | 发布问卷 |
| 问卷 | `PUT /api/surveys/{survey_id}/deadline` | 设置或清除截止时间 |
| 问卷 | `POST /api/surveys/{survey_id}/close` | 关闭问卷 |
| 题目 | `POST /api/surveys/{survey_id}/questions` | 添加问卷题目 |
| 题目 | `PUT /api/surveys/{survey_id}/questions/{instance_id}` | 修改问卷题目 |
| 题目 | `DELETE /api/surveys/{survey_id}/questions/{instance_id}` | 删除问卷题目 |
| 跳转 | `POST /api/surveys/{survey_id}/questions/{source_id}/rules` | 添加跳转规则 |
| 跳转 | `DELETE /api/surveys/{survey_id}/questions/{instance_id}/rules/{rule_index}` | 删除跳转规则 |
| 填写 | `POST /api/surveys/{survey_id}/next` | 计算下一题 |
| 填写 | `POST /api/surveys/{survey_id}/responses` | 提交问卷 |
| 统计 | `GET /api/surveys/{survey_id}/statistics` | 查询整份问卷统计 |
| 统计 | `GET /api/surveys/{survey_id}/questions/{instance_id}/statistics` | 查询单题统计 |

### 2.2 第二阶段新增接口

| 模块 | 方法与路径 | 用途 |
|---|---|---|
| 逻辑题目 | `POST /api/questions` | 创建逻辑题目及初始版本 |
| 逻辑题目 | `GET /api/questions` | 查询本人逻辑题目 |
| 逻辑题目 | `GET /api/questions/{question_id}` | 查询逻辑题目和当前版本 |
| 版本 | `GET /api/questions/{question_id}/versions` | 查询版本历史 |
| 版本 | `GET /api/questions/{question_id}/versions/{version_id}` | 查询指定版本 |
| 版本 | `POST /api/questions/{question_id}/versions` | 创建新版本 |
| 版本 | `POST /api/questions/{question_id}/versions/{version_id}/restore` | 从历史版本创建新版本 |
| 版本 | `PUT /api/questions/{question_id}/current-version` | 显式选择当前版本 |
| 版本 | `GET /api/questions/{question_id}/version-diff` | 比较两个版本 |
| 版本操作 | `POST /api/questions/{question_id}/operations/{operation_id}/retry` | 重试或查询已有操作 |
| 复制 | `POST /api/questions/{question_id}/copies` | 创建独立题目副本 |
| 快照 | `POST /api/surveys/{survey_id}/questions/{instance_id}/save-to-library` | 将现有问卷题保存为逻辑题目 |
| 快照 | `POST /api/surveys/{survey_id}/questions/from-library` | 从指定版本添加题目 |
| 快照 | `PUT /api/surveys/{survey_id}/questions/{instance_id}/source-version` | 切换问卷题的来源版本 |
| 共享 | `POST /api/questions/{question_id}/shares` | 向指定用户共享题目 |
| 共享 | `GET /api/questions/{question_id}/shares` | 查询共享授权记录 |
| 共享 | `DELETE /api/questions/{question_id}/shares/{share_id}` | 撤销共享授权 |
| 共享 | `GET /api/shared-questions` | 查询收到的共享题目 |
| 题库 | `POST /api/question-banks` | 创建题库 |
| 题库 | `GET /api/question-banks` | 查询本人题库列表 |
| 题库 | `GET /api/question-banks/{bank_id}` | 查看指定题库 |
| 题库 | `PATCH /api/question-banks/{bank_id}` | 修改题库信息 |
| 题库 | `DELETE /api/question-banks/{bank_id}` | 软删除题库 |
| 题库条目 | `GET /api/question-banks/{bank_id}/items` | 查询题库条目 |
| 题库条目 | `POST /api/question-banks/{bank_id}/items` | 添加题库条目 |
| 题库条目 | `PUT /api/question-banks/{bank_id}/items/{item_id}` | 修改条目默认版本 |
| 题库条目 | `DELETE /api/question-banks/{bank_id}/items/{item_id}` | 移除题库条目 |
| 题库条目 | `POST /api/question-banks/{bank_id}/items/{item_id}/select` | 将题目选入问卷 |
| 使用关系 | `GET /api/questions/{question_id}/usage` | 查询本人问卷中的题目使用情况 |
| 跨问卷统计 | `GET /api/questions/{question_id}/statistics` | 查询跨问卷统计 |
| 统计兼容 | `GET /api/questions/{question_id}/statistics-configuration` | 查询统计兼容配置 |
| 统计兼容 | `PUT /api/questions/{question_id}/statistics-configuration` | 更新统计兼容配置 |
| 统计兼容 | `POST /api/questions/{question_id}/statistics-configuration/preview` | 检查兼容配置并预览提示 |

---

## 3. 用户认证接口

### 3.1 健康检查

**`GET /api/health`**

无需登录、无需请求体。
成功返回示例：

```json
{
  "message": "问卷系统后端运行正常"
}
```

该接口只能说明后端健康检查路由能够响应，不代表已经验证 MongoDB 的实际连接状态。

### 3.2 注册用户

**`POST /api/register`**

请求体：

```json
{
  "username": "student001",
  "password": "example-password"
}
```

| 参数 | 类型 | 约束 |
|---|---|---|
| `username` | string | 去除首尾空白后为 3～30 个字符 |
| `password` | string | 至少 8 个字符 |

成功返回 201，包含 `message` 和 `user`。用户名重复时返回 409，参数不合法时返回 400。
密码经过哈希处理后保存，不保存明文密码。

### 3.3 登录

**`POST /api/login`**

请求体：

```json
{
  "username": "student001",
  "password": "example-password"
}
```

成功返回 200，包含 `message` 和 `user`。用户对象包含 `id` 和 `username`。用户名或密码错误时返回 401，登录成功后建立 Session。

### 3.4 获取当前用户

**`GET /api/me`**

需要登录，无请求体。
成功返回 200，包含当前用户的 `id`、`username` 和 `createdAt` 等信息。未登录或当前用户不存在时返回 401。

### 3.5 退出登录

**`POST /api/logout`**

需要登录，无请求体。
成功返回 200，包含 `message`。接口清除当前 Session。



## 4. 第一阶段问卷管理接口

本节保留第一阶段的主要调用约定。第二阶段没有取消原有问卷管理和填写流程。

### 4.1 创建问卷

**`POST /api/surveys`**

请求体示例：
```json
{
  "title": "大学生校园生活调查",
  "description": "了解大学生的校园生活与学习情况",
  "anonymousAllowed": false
}
```

主要参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `title` | string | 必填，非空，最长 200 个字符 |
| `description` | string | 问卷说明，最长 5000 个字符 |
| `anonymousAllowed` | boolean | 是否允许匿名填写，默认 false |

重复填写设置采用实际接口支持的字段名，默认行为以当前实现为准。
需要登录。成功返回 201，包含 `message` 和 `survey`，新问卷的初始状态为 `draft`。

### 4.2 查询本人问卷列表

**`GET /api/surveys`**

需要登录，仅返回当前用户拥有的问卷。
成功返回 200，包含 `count` 和 `surveys`。列表项为问卷摘要，不等同于完整的管理配置。当前接口未实现服务端分页。

### 4.3 获取问卷管理配置

**`GET /api/surveys/{survey_id}/manage`**

仅问卷所有者可以访问。
成功返回 200，包含 `survey`，其中提供问卷配置、题目、跳转规则和适用的来源信息。该接口用于问卷编辑与管理，不是面向普通填写者的公开配置接口。

### 4.4 修改问卷基本设置

**`PATCH /api/surveys/{survey_id}`**

仅允许所有者修改草稿的基本设置。请求体至少包含一个可更新字段，可修改字段以实际路由实现为准。
成功返回 200，包含 `message`。不存在、无权访问或问卷状态不允许修改时，接口会拒绝请求。

### 4.5 发布问卷

**`POST /api/surveys/{survey_id}/publish`**

仅所有者可以发布自己的草稿，且问卷必须至少包含一道题目。
成功返回 200，包含 `message` 和 `survey`。空问卷、非草稿或无权操作时会返回错误。

### 4.6 获取填写问卷

**`GET /api/surveys/{survey_id}`**

需要登录。接口检查问卷状态、截止时间和填写资格等条件，并返回可供填写的题目配置及 `alreadySubmitted` 等信息。
该接口不向填写者返回管理用的完整跳转规则配置。不可填写的问卷会被拒绝访问。

### 4.7 关闭问卷

**`POST /api/surveys/{survey_id}/close`**

仅所有者可以关闭已经发布的问卷。
成功返回 200，包含 `message`、`surveyId` 和 `status`。无权访问或问卷状态不符合要求时会返回错误。

### 4.8 设置截止时间

**`PUT /api/surveys/{survey_id}/deadline`**

请求体中的 `deadline` 为必填字段：
- 传入带时区的 ISO 时间字符串：设置截止时间。
- 传入 `null`：清除截止时间。
非空时间必须晚于当前时间。成功返回 200，包含 `message` 和 `deadline`。

### 4.9 添加问卷题目

**`POST /api/surveys/{survey_id}/questions`**

仅问卷所有者可以在草稿中添加题目。
请求体根据题型提供 `type`、`title`、`required`，以及适用的 `options`、`validation` 等字段。

支持的题型包括：
- `single_choice`：单选题
- `multiple_choice`：多选题
- `text`：文本题
- `number`：数字题
成功返回 201，包含 `message` 和 `question`。

### 4.10 修改问卷题目

**`PUT /api/surveys/{survey_id}/questions/{instance_id}`**

修改现有问卷题目，采用完整内容替换方式，而不是默认的局部字段合并。
第二阶段需要特别注意 `detachSource` 参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `detachSource` | boolean | 是否解除题目与来源逻辑题目的关联，默认 false |

保留来源时，修改必答设置不等于修改来源版本的原始内容。如果修改导致题目内容与来源版本不一致，接口会拒绝请求。需要将题目变成独立题目时，应使用实际支持的 `detachSource` 行为。
成功返回 200，包含 `message`。

### 4.11 删除问卷题目

**`DELETE /api/surveys/{survey_id}/questions/{instance_id}`**

仅问卷所有者可以删除草稿中的题目。
如果仍有跳转规则指向该题目，系统会拒绝删除，以避免留下无效目标。成功返回 200，包含 `message`。



## 5. 条件跳转接口

### 5.1 添加跳转规则

**`POST /api/surveys/{survey_id}/questions/{source_id}/rules`**

仅问卷所有者可以在草稿中添加规则。
请求体示例：

```json
{
  "operator": "equals",
  "value": "yes",
  "targetQuestionId": "目标问卷题目实例ID"
}
```

主要字段：

| 参数 | 说明 |
|---|---|
| `operator` | 条件运算符 |
| `value` | 用于匹配的条件值 |
| `targetQuestionId` | 目标问卷题目实例 ID |

当前支持的运算符：

| 题型 | 支持的运算符 |
|---|---|
| 单选题 | `equals` |
| 多选题 | `contains` |
| 数字题 | `equals`、`gt`、`gte`、`lt`、`lte` |
| 文本题 | 不支持条件跳转 |

目标必须是同一问卷中位于源题之后的题目。
成功返回 201，包含 `message` 和 `rule`。

### 5.2 删除跳转规则

**`DELETE /api/surveys/{survey_id}/questions/{instance_id}/rules/{rule_index}`**

删除指定题目的跳转规则。`rule_index` 从 0 开始，必须为整数。
成功返回 200。规则不存在或问卷状态不允许修改时，接口会返回相应错误。



## 6. 答题提交与第一阶段统计

### 6.1 计算下一题

**`POST /api/surveys/{survey_id}/next`**

根据已经填写的答案计算下一道题，不直接保存最终回答。

请求体示例：

```json
{
  "answers": {
    "问卷题目实例ID": "yes"
  }
}
```

`answers` 是以问卷题目实例 ID 为键、答案为值的对象。
成功返回 200，主要字段包括：

- `surveyId`：问卷 ID。
- `completed`：当前答题路径是否完成。
- `nextQuestion`：下一道题；结束时按实际响应返回空值。
- `visitedQuestionIds`：当前路径中访问过的题目实例 ID。

缺少某个题目键表示尚未作答；主动跳过可选题时，应遵守接口对空值的实际约定。两者的区别会影响路径计算。

### 6.2 提交问卷

**`POST /api/surveys/{survey_id}/responses`**

请求体示例：

```json
{
  "answers": {
    "问卷题目实例ID": "yes"
  },
  "anonymous": false
}
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `answers` | object | 必填，包含题目实例 ID 与对应答案 |
| `anonymous` | boolean | 是否匿名提交，默认 false |

系统会校验答案内容，并检查问卷状态、填写权限、跳转路径和重复提交限制。

成功返回 201，主要字段包括：

- `message`
- `responseId`
- `answerCount`
- `anonymous`
- `recovered`

当问卷禁止重复填写且用户已经提交时，重复提交会被拒绝。由于保存流程包含可恢复的中间状态，遇到服务器异常时不能直接认定数据完全没有写入。

### 6.3 查询整份问卷统计

**`GET /api/surveys/{survey_id}/statistics`**

仅问卷所有者可以访问。

成功返回 200，主要字段如下：

| 字段 | 含义 |
|---|---|
| `surveyId` | 问卷 ID |
| `title` | 问卷标题 |
| `responseCount` | 已保存的回答份数 |
| `questions` | 按题目顺序组织的单题统计结果 |

不同题型返回不同的统计字段：

- 单选题、多选题：`optionCounts`，包含选项值、选项文字和选择次数。
- 文本题：`answers`，包含已保存的文本回答。
- 数字题：`numericAnswers` 和 `average`，没有有效数字回答时，`average` 为 `null`。

多选题的选项次数之和可能大于回答份数。允许重复填写时，回答份数也不等于独立用户数。

### 6.4 查询单题统计

**`GET /api/surveys/{survey_id}/questions/{instance_id}/statistics`**

查询某份问卷中一道题的统计结果。
成功返回 200，直接返回单题统计对象，不额外嵌套在 `question` 或 `survey` 字段中，也不包含整份问卷的 `responseCount`。
这里的统计范围是单份问卷，与第二阶段的逻辑题跨问卷统计不同。



## 7. 逻辑题目与版本管理

这是第二阶段的重要扩展。第一阶段的题目主要属于具体问卷；第二阶段增加可复用的逻辑题目及其版本，让同一道逻辑题目可以保留多份历史内容。

### 7.1 创建逻辑题目

**`POST /api/questions`**

创建逻辑题目及其初始版本。

请求体主要字段：

| 参数 | 说明 |
|---|---|
| `operationId` | 本次创建操作的唯一标识 |
| `content` | 初始题目内容 |
| `title` | 可选的题目标题 |
| `changeNote` | 可选的版本说明 |

`content` 中的题型、题干、选项和校验字段应符合实际模型的校验规则。
成功返回 201，包含 `question` 和 `version`。

### 7.2 查询本人逻辑题目

**`GET /api/questions`**

查询当前用户拥有且处于 `active` 状态的逻辑题目。
成功返回 200，包含 `questions` 和 `count`。当前接口不分页。

### 7.3 查询逻辑题目详情

**`GET /api/questions/{question_id}`**

查询逻辑题目及其当前版本。
题目必须处于可访问状态。所有者或具有有效共享授权的用户可以读取允许访问的题目内容，但共享授权不代表获得原题的版本管理权限。
成功返回 200，包含 `question` 和 `version`。

### 7.4 查询指定版本

**`GET /api/questions/{question_id}/versions/{version_id}`**

查询指定逻辑题目下的某个版本。
系统会检查版本是否属于对应逻辑题目。成功返回 200，包含 `version`。

### 7.5 查询版本历史

**`GET /api/questions/{question_id}/versions`**

仅逻辑题目所有者可以访问。
可选查询参数：

| 参数 | 类型 | 默认值或限制 | 说明 |
|---|---|---|---|
| `limit` | integer | 默认 50，范围 1～100 | 每次读取的版本数量 |
| `before` | 正整数 | 可选 | 从指定版本号之前继续读取 |

成功返回 200，包含 `question`、`versions`、`hasMore` 和 `nextBefore`。
`hasMore` 表示是否还有更多记录，`nextBefore` 用于继续查询。版本号游标不能与共享记录或题库条目的 ObjectId 游标混用。

### 7.6 创建新版本

**`POST /api/questions/{question_id}/versions`**

仅原题所有者可以为逻辑题目创建新版本。
请求体主要字段：

| 参数 | 说明 |
|---|---|
| `operationId` | 本次操作的唯一标识 |
| `basedOnVersionId` | 本次修改所依据的版本 ID |
| `expectedRevision` | 预期的当前修订号 |
| `content` | 新版本的完整题目内容 |
| `changeNote` | 可选的变更说明 |

版本内容保存后不应直接覆盖已有历史版本。
系统会检查当前修订状态。如果依据版本仍适用于当前状态，新版本可以成为当前版本；如果并发修改使其不再适合直接采用，系统也可能保存该版本作为分支。
分支保存成功不等于操作失败。 返回 201 只表示创建操作成功，不能据此断定新版本一定成为当前版本。发生冲突时，应先查询操作结果和当前版本，再决定是否需要进一步处理。

### 7.7 从历史版本恢复

**`POST /api/questions/{question_id}/versions/{version_id}/restore`**

仅原题所有者可以操作。

请求体必须包含：

- `operationId`
- `basedOnVersionId`
- `expectedRevision`

恢复内容取自路径中的 `version_id`。
恢复操作不会删除中间版本，也不会直接覆盖当前版本，而是使用历史内容创建一个新版本。成功创建新版本时返回 201；依据版本已经过时的情况下，新版本仍可能被保存为分支。

### 7.8 显式选择当前版本

**`PUT /api/questions/{question_id}/current-version`**

从已有版本中显式选择当前版本。
请求体示例：

```json
{
  "operationId": "本次操作的唯一标识",
  "versionId": "希望选中的版本ID",
  "expectedCurrentVersionId": "预期当前版本ID",
  "expectedRevision": 1
}
```

仅原题所有者可以执行该操作。
系统会检查目标版本、当前版本 ID 和修订号。成功返回 200；如果当前版本或修订号已经发生变化，可能返回 409。
该接口用于选择已有版本，与创建新版本是两种不同操作。

### 7.9 比较版本

**`GET /api/questions/{question_id}/version-diff`**

仅所有者可以查询。

查询参数：

| 参数 | 说明 |
|---|---|
| `from` | 起始版本 ID |
| `to` | 目标版本 ID |

成功返回 200，主要字段包括 `questionId`、`fromVersionId`、`toVersionId`、`changes` 和 `equal`。
`equal` 表示比较内容是否相同，`changes` 用于呈现差异。

### 7.10 重试或查询已有版本操作

**`POST /api/questions/{question_id}/operations/{operation_id}/retry`**

仅所有者可以调用。操作 ID 位于路径中，不需要重新提交一份新的题目内容。
该接口用于查询或重试已有操作，避免网络中断或重复请求导致重复创建版本。已有操作结果会按实际保存的操作记录返回；操作不存在时返回 404，发生选择冲突时可能返回 409。

### 7.11 复制逻辑题目

**`POST /api/questions/{question_id}/copies`**

从指定版本创建属于当前用户的独立逻辑题目副本。

请求体主要字段：

| 参数 | 说明 |
|---|---|
| `versionId` | 要复制的版本 ID |
| `operationId` | 操作唯一标识 |
| `content` | 可选，按实际实现覆盖副本内容 |
| `title` | 可选的副本标题 |
| `changeNote` | 可选的说明 |

成功返回 201，包含 `question` 和 `version`。
复制后形成新的逻辑题目，其所有权属于复制者。它不等同于给原题创建新版本，也不会因为复制而继承原题的版本管理权限或统计权限。



## 8. 问卷题目快照与来源管理

第二阶段采用方案：将指定版本的题目内容复制到问卷中，同时保存来源逻辑题目 ID 和版本 ID。
因此，问卷题目实例仍然保存完整内容。题库版本更新不会自动修改已经使用该版本的问卷题目快照。

### 8.1 将现有问卷题保存到题库

**`POST /api/surveys/{survey_id}/questions/{instance_id}/save-to-library`**

将已有问卷题保存为可复用的逻辑题目。
请求体必须包含 `operationId`。
仅问卷所有者可以执行。成功返回 201，包含 `question` 和 `version`。
该操作创建可复用题目，不修改原问卷题目实例，也不会自动把原问卷的历史回答纳入新逻辑题目的跨问卷统计。

### 8.2 从指定版本添加题目

**`POST /api/surveys/{survey_id}/questions/from-library`**

将指定逻辑题目的某个版本添加到问卷草稿。
请求体示例：

```json
{
  "questionId": "逻辑题目ID",
  "versionId": "指定版本ID",
  "required": true
}
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `questionId` | ID | 必填，逻辑题目 ID |
| `versionId` | ID | 必填，指定的版本 ID |
| `required` | boolean | 可选，问卷中的必答设置 |

系统会检查问卷所有权、草稿状态、题目访问权限和版本归属。
成功返回 201，包含 `question`。
每次引入都会创建新的问卷题目实例 ID。即使两道题使用同一个逻辑题目和版本，它们也有各自独立的问卷题目实例 ID。

### 8.3 切换已有问卷题目的来源版本

**`PUT /api/surveys/{survey_id}/questions/{instance_id}/source-version`**

将现有问卷题目切换到同一逻辑题目的指定版本。
请求体示例：

```json
{
  "versionId": "目标版本ID"
}
```

仅问卷所有者可以在草稿中执行该操作。
系统会检查来源逻辑题目的访问权限和目标版本归属。成功切换后，保留原问卷题目实例 ID、题序和必答设置，并检查跳转规则是否仍然有效。
如果切换会导致跳转规则不合法，接口会拒绝修改。成功返回 200，包含 `question`。


## 9. 题目共享与多题库

### 9.1 向指定用户共享题目

**`POST /api/questions/{question_id}/shares`**

向指定用户授予题目使用权限。

请求体通过 `userId` 或 `username` 指定接收用户，二者不能同时使用。
仅处于 `active` 状态的逻辑题目所有者可以创建共享授权。
首次授权成功返回 201，包含 `share` 和 `alreadyActive: false`。如果对方已经拥有有效授权，接口返回 200，并标明 `alreadyActive: true`。

### 9.2 查询共享授权记录

**`GET /api/questions/{question_id}/shares`**

仅题目所有者可以查询授权记录。

可选查询参数 `status` 用于筛选 `active` 或 `revoked` 状态的记录。
成功返回 200，包含 `shares`、`hasMore` 和 `nextBefore`。
该接口返回的授权记录包含历史信息，不等于当前仍可使用的共享列表。

### 9.3 撤销共享授权

**`DELETE /api/questions/{question_id}/shares/{share_id}`**

仅题目所有者可以撤销指定授权。

成功返回 200，包含 `share`。
重复撤销不会覆盖首次撤销时间；后续重新授权应形成新的授权记录。
撤销共享后，原接收者不能再通过该授权执行新的选题操作，但已有问卷快照、已经创建的独立副本和历史回答不会因此被删除。

### 9.4 查询收到的共享题目

**`GET /api/shared-questions`**

查询当前用户收到的共享题目。

成功返回 200，包含 `shares`、`hasMore` 和 `nextBefore`。
列表中的题目不一定全部可立即使用。题目归档、授权撤销或其他状态变化可能导致 `canUse` 为 `false`。
前端显示的可用状态不能代替后端权限检查。实际选题时仍需重新验证授权和题目状态。

### 9.5 创建题库

**`POST /api/question-banks`**

请求体示例：

```json
{
  "name": "常用调查题目",
  "description": "个人常用题目的整理"
}
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `name` | string | 必填，非空，最长 200 个字符 |
| `description` | string | 可选，默认空字符串，最长 5000 个字符 |

成功返回 201，包含 `bank`。
每个用户可以创建多个题库，用于分类管理自己拥有或获准使用的题目。

### 9.6 查询本人题库列表

**`GET /api/question-banks`**

查询当前用户拥有且处于 `active` 状态的题库。
成功返回 200，包含 `banks`、`hasMore` 和 `nextBefore`。

### 9.7 查看指定题库

**`GET /api/question-banks/{bank_id}`**

仅题库所有者可以访问有效题库。
成功返回 200，包含 `bank`。不可访问时返回 404。

### 9.8 修改题库信息

**`PATCH /api/question-banks/{bank_id}`**

修改题库名称或说明。
请求体至少包含一个可修改字段，并且必须提供 `expectedRevision`，用于检查题库是否已被其他操作修改。
成功返回 200，包含 `bank`。修订号不匹配时返回 409。

### 9.9 删除题库

**`DELETE /api/question-banks/{bank_id}`**

软删除题库。成功返回 200，包含 `message`。
删除题库不会级联删除逻辑题目、题目版本或已有问卷快照。重复删除仍按接口实现返回相应结果。

### 9.10 查询题库条目

**`GET /api/question-banks/{bank_id}/items`**

仅题库所有者可以查询有效题库中的条目。
成功返回 200，包含 `items`、`hasMore` 和 `nextBefore`。
如果条目对应的共享授权已经撤销，该条目仍可保留，但会标记为不可使用。

### 9.11 向题库添加题目

**`POST /api/question-banks/{bank_id}/items`**

请求体示例：

```json
{
  "questionId": "逻辑题目ID",
  "defaultVersionId": "默认版本ID"
}
```

两个字段均为必需字段。系统会检查题目、版本和当前用户的使用权限。
成功返回 201，包含 `item`。同一题库中重复添加同一逻辑题目会返回 409。

### 9.12 修改题库条目的默认版本

**`PUT /api/question-banks/{bank_id}/items/{item_id}`**

请求体主要字段：

- `defaultVersionId`：新的默认版本 ID。
- `expectedRevision`：预期修订号。

系统会检查目标版本是否属于对应逻辑题目，以及修订号是否匹配。
成功返回 200，包含 `item`。目标版本归属不正确时返回 404，修订号冲突时返回 409。

### 9.13 移除题库条目

**`DELETE /api/question-banks/{bank_id}/items/{item_id}`**

移除题库与指定逻辑题目之间的关联。
成功返回 200，包含 `message`。该操作不会删除逻辑题目或其版本。

### 9.14 从题库选题

**`POST /api/question-banks/{bank_id}/items/{item_id}/select`**

将题库条目选入指定问卷草稿。

请求体示例：

```json
{
  "surveyId": "问卷ID",
  "required": true
}
```

`surveyId` 为必需字段，`required` 为可选布尔值。

系统使用条目保存的 `defaultVersionId`，并重新检查问卷权限、版本归属和共享授权。
成功返回 201，包含 `question`。每次选题都会创建新的问卷题目实例，不会复用原题或其他问卷中的实例 ID。


## 10. 使用关系与跨问卷统计

### 10.1 查询题目使用情况

**`GET /api/questions/{question_id}/usage`**

查询逻辑题目在当前用户自己创建的问卷中的使用情况。

可选查询参数：

| 参数 | 说明 |
|---|---|
| `versionId` | 按指定版本筛选 |
| `limit` | 每页记录数，默认 50，范围 1～100 |
| `before` | 用于继续查询的问卷 ID 游标 |
成功返回 200，包含问卷数量、实例数量、问卷列表、题目实例列表和分页信息。

需要区分：

- 问卷数量：使用该逻辑题目的不同问卷数。
- 实例数量：实际使用该题目的问卷题目实例数。

同一逻辑题目在同一问卷中出现两次时，问卷数增加一次，实例数增加两次。
本接口只查询当前用户拥有的问卷，不提供其他用户的问卷使用明细。共享题目并不意味着共享者可以查看接收者的问卷管理信息。

### 10.2 查询跨问卷统计

**`GET /api/questions/{question_id}/statistics`**

查询逻辑题目跨问卷的统计结果，仅统计当前用户拥有的问卷。

可选查询参数：

| 参数 | 说明 |
|---|---|
| `versionId` | 限定统计的逻辑题目版本 |
| `bins` | 指定数字分布的分组边界，必须符合接口要求的 JSON 数组格式 |

成功返回 200，主要结果包括问卷数量、题目实例数量、提交数量、有效答案数量、分组结果、版本明细、排除原因和配置修订信息。
跨问卷统计不会简单地把所有同名题目相加，而是根据逻辑题目来源、版本和答案有效性筛选数据。

主要统计口径如下：

| 字段 | 含义 |
|---|---|
| `surveyCount` | 具有合法来源快照的不同问卷数量 |
| `instanceCount` | 合法来源题目实例数量，同一问卷重复使用可以贡献多个实例 |
| `submissionCount` | 相关问卷中不同的已保存提交数量，即使某次提交未回答该题，也可能计入 |
| `answerCount` | 来源与版本匹配、通过校验且非空的答案项数量 |

以下情况不会计入有效答案：
- 缺少来源信息或来源不匹配。
- 答案值不合法。
- 重复答案项。
- 空白文本。
- 空多选答案。

数字统计使用有效数字答案计算平均值；没有有效数字时，平均值为 `null`。数字分布根据接口实现的区间规则处理边界，并区分上下溢出数据。
为控制响应大小，数字频数和文本明细可能截断，具体以响应中的截断信息为准。整体文本统计主要提供数量，不应理解为完整返回所有文本内容。
当前实现不提供独立用户人数，`independentPeopleAvailable` 为 `false`。因此，不能把提交数或有效答案数直接解释为参与人数。
本接口与第一阶段的单份问卷统计具有不同的字段和计算口径，不能直接混用。

### 10.3 查询统计兼容配置

**`GET /api/questions/{question_id}/statistics-configuration`**

仅逻辑题目所有者可以访问。
成功返回 200，包含 `revision`、`events` 和 `default`。
该配置用于说明不同版本的统计结果在什么条件下可以合并，不会直接修改不可变的历史版本内容。

### 10.4 更新统计兼容配置

**`PUT /api/questions/{question_id}/statistics-configuration`**

仅逻辑题目所有者可以操作。

请求体必须包含：

| 参数 | 说明 |
|---|---|
| `operationId` | 本次配置操作的唯一标识 |
| `expectedRevision` | 预期配置修订号 |
| `confirmed` | 所有者是否明确确认 |
| `reason` | 本次调整的理由 |
| `groups` | 本次完整的统计兼容分组配置 |

其中 `confirmed` 必须严格为 `true`，`reason` 必须符合接口的非空和长度校验要求，`groups` 是完整配置而不是追加到旧配置的局部字段。

每个兼容分组需要包含：

- `metric`：统计指标类型。
- `groupId`：兼容分组标识。
- `versionIds`：纳入该分组的版本 ID 列表。

支持的指标类型包括：

- `choiceDistribution`
- `numericMean`
- `numericDistribution`
- `textResponses`

分组数量、版本数量、重复版本、数字单位和校验配置等均受后端约束。空数组表示按照接口的完整替换语义清空分组。
成功返回 200，包含 `event` 和 `replayed`。如果修订号发生竞争冲突，或同一个操作 ID 对应不一致的请求，接口可能返回 409。

### 10.5 预览统计兼容配置

**`POST /api/questions/{question_id}/statistics-configuration/preview`**

仅逻辑题目所有者可以访问。

请求体提供待检查的 `groups`。
成功返回 200，包含 `groups`、`warnings`、`requiresOwnerConfirmation` 和 `revision`。
该接口只检查兼容配置并预览潜在变化提示，不会计算调整后的统计结果，也不会保存配置或代替所有者完成确认。
如果确认后需要真正更新配置，应调用上一节的 PUT 接口。


## 11. 权限与兼容性注意事项

### 11.1 题目共享权与所有者管理权不同

共享用户可以在有效授权范围内读取和使用题目，但不能因此获得原题的完整版本管理权限，也不能查询其他用户问卷的统计结果。

原题所有者负责创建原题新版本、选择当前版本、管理共享授权和确认统计兼容配置。其他用户需要独立修改题目内容时，可以创建自己的副本。

### 11.2 共享撤销不删除历史数据

撤销共享限制后续使用，不会自动删除已经保存的问卷快照、独立副本或历史回答。
但旧题库条目不能绕过授权检查。后端在新的选题操作中仍需重新验证共享授权及题目状态。

### 11.3 题目版本与问卷快照相互独立

逻辑题目的新版本不会自动覆盖已有问卷中的题目快照。

问卷所有者需要在草稿中显式切换来源版本。切换时，系统保留问卷题目实例 ID，并检查跳转规则等配置是否仍然有效。
如果问卷题目的内容已经与原版本不一致，则不能仅凭保留的来源 ID 将其视为原版本内容。

### 11.4 旧数据继续保留

第一阶段已经存在的问卷和回答继续使用原有结构。将旧题保存到题库不会自动建立旧回答与新逻辑题目的统计关联。

因此，第一阶段的问卷统计和第二阶段的跨问卷逻辑题统计需要分别理解。缺少可靠来源信息的旧题或旧回答，不应仅凭相同题目标题被自动合并。

### 11.5 版本冲突与重复请求

版本创建、恢复、当前版本选择和统计兼容配置更新等操作，应按照接口要求提供 `operationId`、`expectedRevision` 或预期当前版本 ID。

遇到冲突时，应先读取当前状态和已有操作结果，再决定下一步操作，不要直接使用新的操作 ID 重复提交相同业务请求。