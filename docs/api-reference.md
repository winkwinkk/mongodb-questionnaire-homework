# 问卷系统 API 说明

本文档按当前项目的 API 设计整理，供课程演示、接口测试和后续维护使用。接口路径以 `http://127.0.0.1:5000` 为基础地址。

## 1. 调用约定

- 有请求体的 JSON 接口使用 `Content-Type: application/json`，请求主体通常应为 JSON 对象。
- 登录采用 Flask Session Cookie。调用登录接口后，客户端需要保留 Cookie；本项目不是 Bearer Token 认证。
- 健康检查、注册、登录和退出不要求已有登录状态；其余业务 API 需要登录。
- 创建者权限根据当前会话用户与问卷 `ownerId` 判断，不以请求体中的用户 ID 授权。
- MongoDB 使用 `ObjectId`，API 中使用 24 位十六进制字符串。
- 时间以 ISO 8601 字符串传递或返回。设置截止时间时，必须提供带时区的时间，或传入 `null` 清除截止时间。
- 成功响应和错误状态码按具体接口说明为准。主动返回的错误通常使用 `{"error":"错误说明"}`；逐题校验错误可能附带 `questionId` 或 `questionIds`。

### 1.1 常见状态码

| 状态码 | 含义 |
|---|---|
| `200` | 查询、登录/退出、更新、关闭或逐题计算成功 |
| `201` | 注册、创建、添加题目/规则或提交回答成功 |
| `400` | 请求格式、参数、答案校验或业务规则不符合要求 |
| `401` | 未登录、账号密码错误或登录状态无效 |
| `404` | 资源不存在、无权访问，或问卷当前不可填写；具体含义以接口为准 |
| `409` | 用户名重复、重复提交或部分并发配置冲突 |
| `500` | 数据库异常或未被接口统一处理的程序异常 |

当前 PUT/DELETE 题目及 DELETE 规则接口未统一捕获非法 ObjectId，可能返回500；权限错误的状态码也尚未完全统一；未匹配路由或未捕获异常也可能返回 Flask 默认错误页面，不应假设所有错误都一定是 JSON。

时间语义为 UTC，但部分由 MongoDB 读回的时间直接 isoformat 输出，没有显式时区后缀；不能假设所有日期都带 Z 或 +00:00。该问题尚未在代码中统一修复。

以下请求和返回示例按代码结构编写，ID、日期和内容用于说明，不冒充实际抓取的原始响应。调用时替换为实际ID，截止时间应为执行时的未来时间。已有步骤及实际结果见 [测试用例](测试用例.md)。

## 2. 接口总表

| 编号 | 方法 | 路径 | 权限 |
|---|---|---|---|
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

## 3. 用户认证

| 接口 | 请求参数 | 成功结果 | 主要错误 |
|---|---|---|---|
| `GET /api/health` | 无 | `200`，返回服务运行提示；不检查 MongoDB 是否可用 | — |
| `POST /api/register` | `username`、`password` | `201`，返回用户 ID、用户名和注册时间；不返回密码哈希 | `400` 参数错误；`409` 用户名重复；`500` 数据库异常 |
| `POST /api/login` | `username`、`password` | `200`，返回用户信息并设置 Session Cookie | `400` 参数类型错误；`401` 账号或密码错误；`500` 数据库异常 |
| `GET /api/me` | 无 | `200`，返回当前登录用户信息 | `401` 未登录或用户不存在；`500` 数据库异常 |
| `POST /api/logout` | 无 | `200`，清除 Session，返回退出成功提示 | 通常无业务参数错误 |

注册请求示例：

```json
{
  "username": "student01",
  "password": "sample12345"
}
```

注册时用户名去除首尾空白后需为 3–30 个字符，密码至少 8 个字符。登录成功后应保存会话 Cookie，后续受保护接口才能识别当前用户。

## 4. 问卷管理

| 接口 | 请求参数或用途 | 成功结果 | 主要错误 |
|---|---|---|---|
| `POST /api/surveys` | `title` 必填；`description`、`anonymousAllowed`、`allowMultipleResponses` 可选 | `201`，返回新问卷摘要 | `400` 参数错误；`401` 未登录；`500` 数据库异常 |
| `GET /api/surveys` | 无；查询当前用户创建的问卷 | `200`，返回 `count` 和 `surveys` 列表，按创建时间倒序 | `401` 未登录；`500` 数据库异常 |
| `GET /api/surveys/<survey_id>/manage` | 无；获取完整管理配置 | `200`，返回问卷、题目和跳转规则 | `400` ID 无效；`401` 未登录；`404` 不存在或非创建者 |
| `GET /api/surveys/<survey_id>` | 无；读取供填写页面使用的问卷 | `200`，返回可填写配置及 `alreadySubmitted` 等信息 | `400` ID 错误或已截止；`401` 未登录；`404` 不存在、草稿或已关闭 |
| `PATCH /api/surveys/<survey_id>` | 传入至少一个可更新字段：`title`、`description`、`anonymousAllowed`、`allowMultipleResponses` | `200`，返回保存成功提示 | `400` 参数错误；`401` 未登录；`409` 非草稿、无权或配置冲突 |
| `POST /api/surveys/<survey_id>/publish` | 无请求体；草稿至少要有一道题 | `200`，返回发布成功及问卷状态 | `400` 问卷不符合发布条件；`401` 未登录；`500` 数据库异常 |
| `PUT /api/surveys/<survey_id>/deadline` | `deadline` 必须出现：带时区的未来 ISO 8601 字符串，或 `null` | `200`，返回更新后的截止时间 | `400` 时间或状态不合法；`401` 未登录；`404` 不存在或非创建者 |
| `POST /api/surveys/<survey_id>/close` | 无请求体；关闭已发布问卷 | `200`，返回 `status: "closed"` | `400` ID 错误或状态不允许；`401` 未登录；`404` 不存在或非创建者 |

创建问卷示例：

```json
{
  "title": "校园生活调查",
  "description": "了解大学生的校园生活",
  "anonymousAllowed": true,
  "allowMultipleResponses": false
}
```

`title` 必须为非空字符串，最长 200 个字符；`description` 默认为空字符串，最长 5000 个字符；两个设置字段均为 Boolean，默认 `false`。问卷状态和创建者 ID 由服务端生成，不应由客户端传入。发布后，题目和填写设置按当前业务规则锁定；已关闭问卷没有重新打开接口。

## 5. 题目与跳转规则

### 5.1 题目接口

| 接口 | 请求参数或用途 | 成功结果 | 主要错误 |
|---|---|---|---|
| `POST /api/surveys/<survey_id>/questions` | 一个题目对象 | `201`，返回保存的题目 | `400` 参数错误或问卷非草稿；`401` 未登录；`500` 数据库异常 |
| `PUT /api/surveys/<survey_id>/questions/<question_id>` | 完整题目配置，用于替换题目可编辑字段 | `200`，返回保存成功提示 | `400` 配置或规则冲突；`401` 未登录；`404` 问卷/题目不存在或无权；`409` 并发冲突 |
| `DELETE /api/surveys/<survey_id>/questions/<question_id>` | 无请求体；删除草稿题目 | `200`，返回删除成功提示，并重新整理题目顺序 | `400` 若其他规则仍指向该题；`401` 未登录；`404` 不存在或无权；`409` 并发冲突 |

题目 `type` 支持 `single_choice`、`multiple_choice`、`text` 和 `number`。公共字段包括 `title`、`required`、`options` 和 `validation`。选择题需要至少两个选项，每个选项包含不重复的 `value` 和显示用的 `label`。多选数量、文本长度和数字范围等限制由 `validation` 配置。

单选题示例：

```json
{
  "type": "single_choice",
  "title": "是否喜欢运动？",
  "required": true,
  "options": [
    {"value": "yes", "label": "喜欢"},
    {"value": "no", "label": "不喜欢"}
  ]
}
```

### 5.2 跳转规则接口

| 接口 | 请求参数或用途 | 成功结果 | 主要错误 |
|---|---|---|---|
| `POST /api/surveys/<survey_id>/questions/<source_id>/rules` | `operator`、`value`、`targetQuestionId` | `201`，返回新增规则 | `400` 条件或目标题不合法；`401` 未登录；`500` 数据库异常 |
| `DELETE /api/surveys/<survey_id>/questions/<question_id>/rules/<int:rule_index>` | 规则在 `jumpRules` 数组中的零基下标 | `200`，返回删除成功提示 | `401` 未登录；`404` 规则或资源不存在；`409` 并发冲突 |

规则示例：

```json
{
  "operator": "equals",
  "value": "yes",
  "targetQuestionId": "000000000000000000000103"
}
```

目标题必须属于同一问卷，并位于源题之后。单选支持 `equals`，多选支持 `contains`，数字题支持 `equals`、`gt`、`gte`、`lt`、`lte`。规则按保存顺序匹配；当前接口不自动去除完全重复的规则。删除规则后应重新获取管理详情，因为后续规则下标会变化。

## 6. 填写与提交

| 接口 | 请求参数或用途 | 成功结果 | 主要错误 |
|---|---|---|---|
| `POST /api/surveys/<survey_id>/next` | `answers` 对象，键为题目 ID，值按题型传入；首次传 `{}` | `200`，返回下一题、已访问题目 ID，或 `completed: true` | `400` 答案或路径错误；`401` 未登录；`404` 问卷不可填写 |
| `POST /api/surveys/<survey_id>/responses` | `answers` 必填；`anonymous` 可选 Boolean，默认 `false` | `201`，返回 `responseId`、答案数量、匿名标记和恢复标记 | `400` 答案、匿名权限或截止时间错误；`401` 未登录；`404` 问卷不可填写；`409` 已提交；`500` 数据库异常 |

填写请求中的 `answers` 是以题目 ID 为键的对象，而不是数据库中保存的答案数组。例如：

```json
{
  "answers": {
    "000000000000000000000101": "yes",
    "000000000000000000000103": 18
  }
}
```

多选答案使用字符串数组，数字答案使用 JSON 数字。逐题接口会根据当前答案计算下一题，但不会保存正式回答。最终提交时，服务端会重新检查问卷状态、截止时间、答案合法性和完整答题路径。

匿名提交示例：

```json
{
  "answers": {
    "000000000000000000000101": "yes"
  },
  "anonymous": true
}
```

只有问卷允许匿名填写时才能使用 `anonymous: true`。匿名回答不保存 `respondentId`，但参与记录仍用于禁止重复填写的控制。禁止重复时再次提交会返回 `409`；如果此前提交中断，系统可能通过固定回答 ID 和待处理参与记录恢复首次接受的内容。恢复机制及其限制见 `key-logic.md`。

## 7. 统计接口

| 接口 | 权限与用途 | 成功结果 | 主要错误 |
|---|---|---|---|
| `GET /api/surveys/<survey_id>/statistics` | 创建者查询整份问卷统计 | `200`，返回提交总数及各题统计 | `400` ID 错误；`401` 未登录；`404` 不存在或非创建者；`500` 数据库异常 |
| `GET /api/surveys/<survey_id>/questions/<question_id>/statistics` | 创建者查询单题统计 | `200`，直接返回该题统计对象 | `400` ID 错误；`401` 未登录；`404` 无权或题目不存在；`500` 数据库异常 |

整体统计外层包含 `responseCount`（提交总份数）和 `questions` 数组；每题含 `answeredCount`（实际回答该题的份数）。单题接口直接返回题统计对象，不含 `responseCount` 或外层 `questions`。单选、多选返回 `optionCounts`；文本题返回已保存的文本答案；数字题返回数字答案列表和平均值，没有有效数字时平均值为 `null`。多选题各选项次数之和可能大于回答人数；允许重复填写时，统计按提交次数计算，而不是独立用户数。

## 8. 网页入口

| 方法与路径 | 用途 |
|---|---|
| `GET /` | 根据登录状态跳转到问卷列表或登录页 |
| `GET /login`、`GET /register` | 登录与注册页面 |
| `GET /dashboard` | 我的问卷页面 |
| `GET /surveys/new` | 创建问卷页面 |
| `GET /surveys/<survey_id>/edit` | 问卷编辑页面 |
| `GET /survey/<survey_id>` | 在线填写页面 |
| `GET /surveys/<survey_id>/statistics` | 问卷统计页面 |

未登录访问受保护网页时会跳转到登录页面。网页入口返回成功并不代表问卷 ID 有效或当前用户有权限，页面仍会调用 API 检查并读取数据。静态文件由 Flask 的 `/static/<path:filename>` 提供。

## 9. 常见调用顺序

- 创建并发布： 注册 → 登录 → 创建问卷 → 添加题目 → 添加跳转规则（如需要）→ 发布。
- 管理问卷： 获取管理详情 → 修改草稿配置或题目/规则 → 重新获取管理详情确认结果。
- 填写问卷： 登录 → 获取可填写问卷 → 多次调用 `next` → 最后调用提交接口。
- 查看统计： 以创建者身份登录 → 调用整份问卷统计或单题统计接口。


## 10. 请求参数明细

### 10.1 路径与通用参数

| 参数 | 类型 | 必填性 | 说明 |
| --- | --- | --- | --- |
| survey_id | 24位十六进制String | 路径出现时必填 | 问卷ObjectId；由创建接口取得 |
| question_id / source_id | 同上 | 路径出现时必填 | 题目ObjectId；由添加或管理接口取得 |
| rule_index | 非负Int | 删除规则时必填 | 当前规则数组从0起的下标；删除后重新读取 |
| username、password | String | 注册和登录必填 | 注册用户名去首尾空白后3～30字符、密码至少8字符 |

未列请求体的 GET 接口及 publish、close、logout 不需要请求体。GET 本人问卷列表无服务端分页或搜索参数，网页在已加载列表中筛选。

### 10.2 创建及修改问卷

| 参数 | 类型 | 创建时 | PATCH时 | 约束及默认 |
| --- | --- | --- | --- | --- |
| title | String | 必填 | 可选 | 非空，最长200字符；保存去首尾空白的标题 |
| description | String | 可选 | 可选 | 默认空字符串，最长5000字符 |
| anonymousAllowed | Boolean | 可选 | 可选 | 默认false，草稿可改 |
| allowMultipleResponses | Boolean | 可选 | 可选 | 默认false，草稿可改 |
| deadline | String或null | 不在创建接口配置 | 不由PATCH修改 | 专用PUT接口必含该键；未来ISO时间须带时区，null清除 |

PATCH至少包含一个可更新字段。状态、ownerId和questions不由该接口直接写入。deadline仅能在published状态设置或清除；closed不能重新打开。

### 10.3 添加与完整替换题目

| 参数 | 类型 | 必填性 | 约束及默认 |
| --- | --- | --- | --- |
| type | String | 必填 | single_choice、multiple_choice、text、number |
| title | String | 必填 | 去首尾空白后非空；当前没有额外题干长度上限 |
| required | Boolean | 可选 | 默认true |
| options | Array of Object | 选择题必需 | 至少两个；每项value和label为非空白字符串，value不重复；非选择题不能有非空选项 |
| validation | Object | 可选 | 缺省或null按该题型默认；不接受数组等错误类型 |

PUT为完整配置替换，type和title必填，其他省略字段按默认值处理。保留原题目_id、order和jumpRules；已有规则时修改题型或选项需先删除规则。删除目标题前需解除其他题目指向它的规则。

| 题型 | validation字段 | 默认值 | 限制 |
| --- | --- | --- | --- |
| 多选 | minSelections、maxSelections：Int | 0、选项数量 | 排除Boolean，0≤min≤max≤选项数 |
| 文本 | minLength、maxLength：Int | 0、1000 | 排除Boolean，0≤min≤max |
| 数字 | min、max：Number或null | null、null | 排除Boolean及非有限数字，min≤max，整数需在BSON范围 |
| 数字 | integerOnly：Boolean | false | 整数限制允许18和18.0，不允许18.5 |
| 单选 | 无专用validation | 空对象形式返回 | 选项合法性由答案校验判断 |

### 10.4 跳转及答案

| 参数 | 类型 | 必填性 | 说明 |
| --- | --- | --- | --- |
| operator | String | 添加规则必填 | 单选equals、多选contains、数字equals/gt/gte/lt/lte |
| value | String或Number | 添加规则必填 | 选择题为有效选项value，数字题为非Boolean有限数值 |
| targetQuestionId | ObjectId字符串 | 添加规则必填 | 同问卷且位于源题之后 |
| answers | Object | next和responses必填 | 键为题目ID；单选/文本值为String，多选为String数组，数字为Number |
| anonymous | Boolean | responses可选 | 默认false，true须问卷允许匿名 |

next首次传 `{"answers":{}}`。以后每次传截至当前的全部路径答案，缺键表示尚未到达该题；主动跳过可选题需传该键及null等空值。最终提交缺少可选题按跳过处理，实际路径必答题缺失报错。两个入口均拒绝外问卷、被跳过或抢先提交题目的答案。

## 11. 返回结构与示例

### 11.1 通用对象

SurveySummary字段为：id、ownerId、title、description、anonymousAllowed、allowMultipleResponses、status、deadline、questionCount、createdAt、updatedAt。ID为字符串，开关为Boolean，questionCount为整数，deadline为空或时间字符串，其他时间为ISO字符串。

Question字段为：id、type、title、required、order、options、validation。管理接口额外返回jumpRules，其中condition含operator和value，targetQuestionId序列化为字符串。没有选项或限制时API补空数组/对象，不代表数据库一定保存了相同空字段。

下表中对象名表示以上字段结构，不是响应中的字符串或额外字段。

| 接口编号 | 成功状态 | 返回结构 |
| --- | --- | --- |
| A01 | 200 | {message:运行提示} |
| A02 | 201 | {message:注册成功, user:{id,username,createdAt}} |
| A03 | 200 | {message:登录成功, user:{id,username}}，设置会话Cookie |
| A04 | 200 | {user:{id,username,createdAt}} |
| A05 | 200 | {message:已退出登录} |
| A06 | 201 | {message:问卷创建成功, survey:SurveySummary} |
| A07 | 200 | {count:整数, surveys:[SurveySummary]} |
| A08 | 200 | {survey:SurveySummary加canEdit和questions}；questions含规则 |
| A09 | 200 | {survey:{id,title,description,anonymousAllowed,allowMultipleResponses,alreadySubmitted,deadline,questions}}；不含ownerId或jumpRules |
| A10 | 200 | {message:问卷设置已保存} |
| A11 | 200 | {message:问卷发布成功, survey:{id,status}} |
| A12 | 200 | {message:截止时间已更新, deadline:时间字符串或null} |
| A13 | 200 | {message:问卷已关闭, surveyId,status} |
| A14 | 201 | {message:题目添加成功, question:Question加jumpRules} |
| A15 | 200 | {message:题目已保存} |
| A16 | 200 | {message:题目已删除} |
| A17 | 201 | {message:跳转规则添加成功, rule:{sourceQuestionId,operator,value,targetQuestionId}} |
| A18 | 200 | {message:规则已删除} |
| A19 | 200 | {surveyId,completed,nextQuestion,visitedQuestionIds} |
| A20 | 201 | {message,responseId,answerCount,anonymous,recovered} |
| A21 | 200 | {surveyId,title,responseCount,questions:[QuestionStatistics]} |
| A22 | 200 | QuestionStatistics，不增加外层对象 |

### 11.2 逐题计算

输入示例为已完成一道题的累计答案；下一题取决于该问卷实际规则：

```json
{"answers":{"000000000000000000000101":"yes"}}
```

未完成时的返回结构示例：

```json
{
  "surveyId":"000000000000000000000100",
  "completed":false,
  "nextQuestion":{
    "id":"000000000000000000000103","type":"number","title":"年龄",
    "required":true,"order":3,"options":[],
    "validation":{"min":0,"max":120,"integerOnly":true}
  },
  "visitedQuestionIds":["000000000000000000000101"]
}
```

完成时nextQuestion为null，completed为true，visitedQuestionIds包含实际校验过的题目（包括主动跳过的可选题）；此时尚未写入正式回答。

### 11.3 最终提交与错误

完整答案示例（该配置允许Q1跳过Q2到Q3，且Q3为末题）：

```json
{"answers":{"000000000000000000000101":"yes","000000000000000000000103":18},"anonymous":true}
```

成功返回示例：

```json
{
  "message":"问卷提交成功","responseId":"000000000000000000000200",
  "answerCount":2,"anonymous":true,"recovered":false
}
```

answerCount是保存的非空题目答案数量。recovered=true表示恢复了第一次已接受的内容，返回的数量和匿名模式以实际保存内容为准。已有committed资格返回409；同一pending的并发重试可能返回同一responseId的多个201，但只有一份回答。允许重复时不提供通用请求幂等键，每次合法提交新增回答。

错误示例：未登录返回401及 `{"error":"请先登录"}`（具体路由措辞可能不同）；逐题必答错误返回400，例如：

```json
{"error":"本题为必答题，不能为空","questionId":"000000000000000000000101"}
```

路径错误可带questionIds数组；数据库异常通常返回500及 `{"error":"数据库操作失败"}`。非法ObjectId的未捕获异常可能是Flask默认HTML500，不能依据通用错误示例假定所有错误都有相同格式。

### 11.4 统计对象

QuestionStatistics公共字段为questionId:String、title:String、type:String、answeredCount:Int；选择题增加optionCounts:[{value,label,count}]，文本增加answers:String数组，数字增加numericAnswers:Number数组和average:Number或null。

整体统计的简化返回示例：

```json
{
  "surveyId":"000000000000000000000100","title":"年龄调查","responseCount":2,
  "questions":[{
    "questionId":"000000000000000000000103","title":"年龄","type":"number",
    "answeredCount":2,"numericAnswers":[18,20],"average":19.0
  }]
}
```

单题统计直接返回上例questions中的一个对象，不含responseCount。选项比例由前端计算，API没有percentage字段。答案列表没有显式排序约定。当前两个统计入口均在应用层遍历该问卷回答，未使用数据库聚合或分页。


