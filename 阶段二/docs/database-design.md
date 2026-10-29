# MongoDB 数据库设计

## 1. 设计背景与目标

第一阶段已经实现用户管理、问卷创建、题目编辑、条件跳转、答案校验、问卷提交和结果统计。原有设计将题目嵌入 `surveys` 文档的 `questions` 数组中，回答则单独保存到 `responses` 集合。这种结构适合按问卷读取完整配置，也让填写、跳转和校验可以围绕同一份问卷数据工作。

第二阶段新增了常用题目复用、指定用户共享、题目版本与恢复、多题库、题目使用关系查询和跨问卷统计等需求。仅把题干复制到另一份问卷，无法可靠地追踪题目来源、版本和共享授权；如果直接修改旧问卷里的题目，又可能影响历史问卷内容的稳定性。因此，本阶段在保留原有问卷结构的基础上，增加独立的逻辑题目、版本、共享、题库及辅助记录集合。

设计遵循以下原则：

1. **增量扩展，不推倒重做。** 保留第一阶段的 `users`、`surveys`、`responses`、`participations` 及原有答题流程。
2. **区分题目身份、题目版本和问卷内实例。** 三者有不同用途，不能混用 ID。
3. **保存问卷题目快照。** 问卷使用题库题目时，复制所选版本的内容到问卷，并记录来源；题库后续变化不应自动改写既有问卷。
4. **版本历史可追溯。** 新版本保留历史版本，恢复旧版本时创建新版本，而不是覆盖旧记录。
5. **共享是授权，不是转移所有权。** 共享对象只能在有效授权下使用原题，不能修改原题版本。
6. **数据结构约束与业务权限分层。** MongoDB Schema 约束基本文档结构，后端负责校验引用归属、授权、题型规则和统计权限。
7. **兼容旧数据。** 第一阶段问卷和回答可以缺少第二阶段新增的来源字段；不能为了新功能而要求旧文档全部重建。

## 2. 集合总体结构

当前系统包含四个第一阶段集合，以及第二阶段新增的五个主要业务集合和两个辅助集合。

| 集合 | 阶段 | 主要职责 |
|---|---|---|
| `users` | 第一阶段保留 | 用户账号和注册信息 |
| `surveys` | 第一阶段保留并扩展 | 问卷配置、问卷内题目实例、题目快照和跳转规则 |
| `responses` | 第一阶段保留 | 每次提交的回答及提交时间 |
| `participations` | 第一阶段保留 | 参与资格、重复填写控制和提交恢复 |
| `questions` | 第二阶段新增 | 逻辑题目身份、所有者、状态和当前版本指针 |
| `question_versions` | 第二阶段新增 | 不可变的题目内容版本、来源和兼容性初始配置 |
| `question_shares` | 第二阶段新增 | 指定用户的共享授权、撤销及授权历史 |
| `question_banks` | 第二阶段新增 | 用户拥有的多个题库 |
| `question_bank_items` | 第二阶段新增 | 题库与逻辑题目的关联及默认版本 |
| `question_version_operations` | 第二阶段辅助集合 | 版本创建、恢复、选择等操作的持久化回执和恢复依据 |
| `question_statistics_events` | 第二阶段辅助集合 | 跨版本统计兼容性配置的追加式变更记录 |

辅助集合并不是为了把每个字段都拆出去，而是因为版本操作和统计配置变更需要保留操作结果或历史，不能只依赖一个会被覆盖的当前状态字段。

## 3. 核心数据关系与 ID 语义

### 3.1 三类题目身份必须区分

| 字段 | 含义 | 用途 |
|---|---|---|
| 问卷题目 `_id` | 一道题在某一份问卷中的实例 ID | 题目排序、跳转目标和问卷内操作 |
| `answers[].questionId` | 回答所对应的问卷内题目实例 ID | 将答案与本次问卷中的具体题目对应起来 |
| `sourceQuestionId` | 问卷题目快照来源的逻辑题目 ID | 跨问卷追踪同一道逻辑题目 |
| `sourceVersionId` | 问卷题目快照来源的版本 ID | 确定该问卷实际使用的题目版本 |

第一阶段的 `answers[].questionId`、问卷题目 `_id` 和跳转规则中的目标题目 ID 继续保持原有实例语义。不能把原有 `questionId` 改成逻辑题目 ID，否则会破坏原有答案关联、跳转判断和统计逻辑。

新建的问卷内题目实例拥有自己的 `_id`。即使两份问卷使用同一道逻辑题目、同一个版本，它们在各自问卷中的实例 ID 也不同。

### 3.2 逻辑关系

- 一个用户可以拥有多道逻辑题目。
- 一道逻辑题目可以有多个版本，`question_versions.questionId` 指向所属逻辑题目。
- 一道逻辑题目可以授权给多个用户；有效授权记录保存在 `question_shares`。
- 一个用户可以创建多个题库；题库通过 `question_bank_items` 收录逻辑题目，并为该题设置默认版本。
- 一份问卷包含多个嵌入式题目实例；有题库来源的实例保存 `sourceQuestionId` 和 `sourceVersionId`。
- 一份问卷可以有多次提交；每份回答的 `answers` 数组使用问卷内实例 ID 关联答案。

MongoDB 不会因为某个字段保存了 `ObjectId` 就自动验证被引用的文档一定存在。因此，题目与版本的归属、共享授权、题库所有权和问卷来源一致性都需要由后端检查。

## 4. 第一阶段保留的集合

### 4.1 `users`：用户集合

`users` 保存账号信息，用于登录、问卷归属和参与身份识别。

| 字段 | 类型 | 含义与约束 |
|---|---|---|
| `_id` | `ObjectId` | 用户唯一标识 |
| `username` | `String` | 必填、非空、唯一的用户名 |
| `passwordHash` | `String` | 必填，保存密码哈希而非明文密码 |
| `createdAt` | `Date` | 注册时间 |

用户数据独立存储，问卷和参与记录通过用户 ID 关联，避免在每份问卷中重复保存账号信息。

### 4.2 `surveys`：问卷集合

`surveys` 保存问卷基本信息和完整的问卷内题目配置。题目仍然嵌入 `questions` 数组，以支持原有问卷编辑、填写、跳转和校验流程。

| 字段 | 类型 | 含义与约束 |
|---|---|---|
| `_id` | `ObjectId` | 问卷 ID |
| `ownerId` | `ObjectId` | 创建者用户 ID |
| `title` | `String` | 必填、非空标题 |
| `description` | `String` | 问卷说明 |
| `anonymousAllowed` | `Boolean` | 是否允许匿名填写 |
| `allowMultipleResponses` | `Boolean` | 是否允许同一登录用户重复填写；旧文档缺少该字段时，应用按兼容规则处理 |
| `status` | `String` | `draft`、`published` 或 `closed` |
| `deadline` | `Date` 或 `null` | 可选截止时间 |
| `questions` | `Array<Object>` | 问卷内题目实例列表 |
| `createdAt` | `Date` | 创建时间 |
| `updatedAt` | `Date` | 最近更新时间 |

问卷内题目的主要字段如下：

| 字段 | 类型 | 含义 |
|---|---|---|
| `_id` | `ObjectId` | 当前问卷中的题目实例 ID |
| `type` | `String` | `single_choice`、`multiple_choice`、`text` 或 `number` |
| `title` | `String` | 填写者看到的题干 |
| `required` | `Boolean` | 当前问卷中是否必答 |
| `order` | 数值 | 显示顺序 |
| `options` | `Array<Object>` | 选择题选项，通常包含稳定的 `value` 和显示用的 `label` |
| `validation` | `Object` | 文本长度、数字范围、多选数量等校验配置 |
| `jumpRules` | `Array<Object>` | 当前问卷中的条件跳转规则 |
| `sourceQuestionId` | `ObjectId`，可选 | 来源逻辑题目 ID |
| `sourceVersionId` | `ObjectId`，可选 | 来源题目版本 ID |
| `unit` | `String`，可选 | 题目的计量单位或统计单位信息 |
| `semanticDescription` | `String`，可选 | 用于说明题目测量含义，辅助统计兼容性判断 |

`sourceQuestionId` 和 `sourceVersionId` 是第二阶段新增的可选来源字段。旧问卷可以不包含它们；如果题目有来源，两者应成对出现。只有当快照内容仍与指定版本一致时，才可以将其纳入对应逻辑题目的版本统计。

题目版本内容与问卷配置有不同职责。版本内容包括题型、题干、选项、默认必答设置、校验配置、单位和语义说明；问卷实例的 `_id`、`order`、`jumpRules` 和来源字段属于具体问卷，不应原样存进可复用版本内容。

### 4.3 `responses`：回答集合

每次成功提交产生一份独立的回答文档。回答与问卷配置分开存储，避免回答不断增长导致问卷文档持续变大。

| 字段 | 类型 | 含义与约束 |
|---|---|---|
| `_id` | `ObjectId` | 本次提交的唯一 ID |
| `surveyId` | `ObjectId` | 所属问卷 ID |
| `respondentId` | `ObjectId`，可选 | 登录填写者 ID；匿名回答可不保存该字段 |
| `answers` | `Array<Object>` | 本次提交的答案列表 |
| `submittedAt` | `Date` | 提交时间 |

每个答案至少包含 `questionId` 和 `value`。`questionId` 继续指向问卷内实例；新版本来源信息可以作为成对的可选字段 `sourceQuestionId`、`sourceVersionId` 保存。来源字段由服务端根据可信问卷快照派生，不应直接信任客户端传入的统计归属。旧回答缺少来源字段时仍应可读取，但不会自动纳入第二阶段跨问卷统计。

将一次提交的答案放在同一份 `responses` 文档中，便于以提交为单位读取和统计；不同提交则分成独立文档，适应回答持续增长的特点。

### 4.4 `participations`：参与记录集合

该集合用于控制重复填写，并支持提交过程中断后的恢复。

| 字段 | 类型 | 含义与约束 |
|---|---|---|
| `_id` | `ObjectId` | 参与记录 ID |
| `surveyId` | `ObjectId` | 问卷 ID |
| `userId` | `ObjectId` | 参与用户 ID |
| `responseId` | `ObjectId` | 与该次参与关联的固定回答 ID |
| `status` | `String` | `pending` 或 `committed` |
| `payload` | `Object`，可选 | 待完成提交暂存的首次有效答案；完成后可清理 |
| `createdAt` | `Date` | 参与记录创建时间 |
| `submittedAt` | `Date`，可选 | 提交时间 |

`(surveyId, userId)` 的复合唯一索引保证同一登录用户对同一问卷只有一条参与记录。匿名设置和重复填写设置是不同概念：匿名回答可以不在 `responses` 中保存 `respondentId`，但参与记录仍可保存登录用户 ID 以控制重复填写。因此，本项目的匿名不等于数据库中不存在任何可关联身份的信息。

## 5. 第二阶段新增的业务集合

### 5.1 `questions`：逻辑题目集合

该集合代表一道可复用题目的稳定身份，不直接承担某一份问卷里的排序和跳转配置。

| 字段 | 类型 | 含义 |
|---|---|---|
| `_id` | `ObjectId` | 逻辑题目 ID |
| `ownerId` | `ObjectId` | 所有者用户 ID |
| `title` | `String` | 题目管理名称，可与填写题干不同 |
| `status` | `String` | `creating`、`active` 或 `archived` |
| `currentVersionId` | `ObjectId`，完成后必需 | 当前推荐版本 ID |
| `currentVersionNumber` | 正整数，完成后必需 | 当前推荐版本号 |
| `versionCounter` | 正整数 | 版本号分配计数器 |
| `versionRevision` | 整数 | 版本状态修订号，用于并发判断 |
| `operationSequence` | 整数 | 版本操作序列辅助字段 |
| `operationId` | `String` | 初始创建操作标识，用于幂等重试 |
| `initialVersionId` | `ObjectId` | 初始版本 ID |
| `pendingVersion` | `Object`，创建中可选 | 初始创建过程中的恢复信息 |
| `pendingVersionOperation` | `Object`，可选 | 版本操作准备/决策阶段的临时持久状态 |
| `statisticsRevision` | 整数，可选 | 当前生效统计配置修订号 |
| `statisticsEventId` | `ObjectId`，可选 | 当前生效统计配置事件 ID |
| `createdAt` / `updatedAt` | `Date` | 创建和更新时间 |

`creating` 是内部恢复状态，不应作为可选题目暴露给用户；只有创建流程完成、存在有效版本指针的题目才可正常使用。`versionCounter` 用于分配版本号，`currentVersionId` 和 `currentVersionNumber` 表示当前推荐版本，两者不能混为一谈。归档题目不应再被新选用，但已有问卷快照仍需保留。

### 5.2 `question_versions`：题目版本集合

每个版本保存一份确定的可复用题目内容。版本创建后，应用程序不应原地修改其内容；编辑或恢复应创建新版本。

| 字段 | 类型 | 含义 |
|---|---|---|
| `_id` | `ObjectId` | 版本 ID |
| `questionId` | `ObjectId` | 所属逻辑题目 ID |
| `versionNumber` | 正整数 | 该逻辑题目下的版本号 |
| `content` | `Object` | 题型、题干、默认必答、选项、校验、单位和语义说明 |
| `basedOnVersionId` | `ObjectId` 或 `null` | 创建操作所依据的版本 |
| `restoredFromVersionId` | `ObjectId` 或 `null` | 恢复时复制内容的历史版本 |
| `copiedFromQuestionId` | `ObjectId` 或 `null` | 独立副本的来源逻辑题目 |
| `copiedFromVersionId` | `ObjectId` 或 `null` | 独立副本的来源版本 |
| `createdBy` | `ObjectId` | 创建者用户 ID |
| `createdAt` | `Date` | 创建时间 |
| `changeNote` | `String` | 创建、修改或恢复说明 |
| `statisticsGroups` | `Object` | 版本创建时的初始统计兼容配置 |
| `operationId` | `String`，版本操作可选 | 用于识别同一次版本操作和幂等重试 |

几个来源字段含义不同：`basedOnVersionId` 表示本次修改基于哪个版本；`restoredFromVersionId` 表示恢复操作复制了哪个历史版本的内容；`copiedFromQuestionId` 与 `copiedFromVersionId` 表示独立副本从哪里复制而来。副本建立后拥有新的逻辑题目身份和所有者，不继承来源题目的修改权限或回答查看权。

`content` 只保存可复用题目内容，不包括问卷实例 `_id`、`order`、`jumpRules` 和来源字段。版本的不可变性主要由后端写入流程保证，MongoDB Schema 本身并不能阻止拥有数据库写权限的程序直接更新已有文档。

### 5.3 `question_shares`：共享授权集合

该集合记录题目所有者向指定用户授予或撤销题目使用权的历史。

| 字段 | 类型 | 含义 |
|---|---|---|
| `_id` | `ObjectId` | 授权记录 ID |
| `questionId` | `ObjectId` | 被共享的逻辑题目 ID |
| `ownerId` | `ObjectId` | 题目所有者 ID |
| `recipientUserId` | `ObjectId` | 被授权用户 ID |
| `status` | `String` | `active` 或 `revoked` |
| `createdAt` | `Date` | 授权创建时间 |
| `revokedAt` | `Date` 或 `null` | 撤销时间 |
| `displayTitleSnapshot` | `String`，可选 | 授权时保存的显示名称快照 |

只有所有者可以创建、撤销和重新授权。撤销时保留原记录并更新状态和时间；重新授权产生新的有效记录，不覆盖历史撤销记录。系统对有效授权重新检查，而不能仅凭旧授权 ID 或旧题库条目允许再次选题。共享授权不赋予接收者修改原题、创建原题版本或查看所有者其他问卷回答的权限。

### 5.4 `question_banks`：题库集合

每个用户可以创建多个私有题库。第二阶段不实现整库共享，题目共享与题库归属分别管理。

| 字段 | 类型 | 含义 |
|---|---|---|
| `_id` | `ObjectId` | 题库 ID |
| `ownerId` | `ObjectId` | 题库所有者 |
| `name` | `String` | 非空题库名称，长度受 Schema 限制 |
| `description` | `String` | 题库说明 |
| `status` | `String` | `active` 或 `deleted` |
| `revision` | 整数 | 题库更新修订号 |
| `createdAt` / `updatedAt` | `Date` | 创建和更新时间 |

题库名称允许重复，因为题库身份由 `_id` 区分。题库删除状态不应被误解为删除题目版本或既有问卷快照。

### 5.5 `question_bank_items`：题库条目集合

该集合将题库与逻辑题目关联起来，并保存该题在当前题库中的默认选用版本。

| 字段 | 类型 | 含义 |
|---|---|---|
| `_id` | `ObjectId` | 题库条目 ID |
| `bankId` | `ObjectId` | 所属题库 ID |
| `questionId` | `ObjectId` | 逻辑题目 ID |
| `defaultVersionId` | `ObjectId` | 默认选用版本 ID |
| `addedBy` | `ObjectId` | 添加者用户 ID |
| `addedAt` | `Date` | 添加时间 |
| `displayTitleSnapshot` | `String` | 添加时的显示名称快照 |
| `revision` | 整数 | 条目更新修订号 |

同一题库中同一道逻辑题目只保留一个条目；同一道题可以进入多个题库。默认版本只影响后续选题，不会自动更新已经创建的问卷。新增或更新条目时，后端应验证题库归属、版本是否属于该题以及当前用户是否仍具有选用权限。

### 5.6 `question_version_operations`：版本操作回执集合

该集合用于保存创建版本、恢复版本或选择当前版本等操作的最终结果，支持幂等重试与中断恢复。

| 字段 | 类型 | 含义 |
|---|---|---|
| `_id` | `ObjectId` | 操作回执 ID |
| `questionId` | `ObjectId` | 逻辑题目 ID |
| `operationId` | `String` | 调用方提供的稳定操作标识 |
| `actorId` | `ObjectId` | 操作者用户 ID |
| `kind` | `String` | `edit`、`restore` 或 `select` |
| `versionId` | `ObjectId` | 涉及的版本 ID |
| `versionNumber` | 正整数 | 涉及的版本号 |
| `expectedVersionId` | `ObjectId` | 操作依据的当前版本 ID |
| `expectedRevision` | 整数 | 操作开始时预期的版本修订号 |
| `outcome` | `String` | `adopted`、`branch`、`selected` 或 `conflict` |
| `changeNote` | `String` | 操作说明，可选 |
| `createdAt` / `completedAt` | `Date` | 操作开始与完成时间 |

回执记录一次操作最终被采用、作为分支保留、选择了历史版本或发生冲突的结果。它与版本文档的职责不同：版本保存内容，回执保存操作结果。使用稳定 `operationId` 可以在重试时识别同一操作，避免因重复请求再次创建版本。

### 5.7 `question_statistics_events`：统计配置变更事件集合

跨问卷统计不能仅凭题目标题相同就合并不同版本。该集合保存题目所有者确认后的兼容性配置，并以追加事件的方式保留变更历史。

| 字段 | 类型 | 含义 |
|---|---|---|
| `_id` | `ObjectId` | 统计配置事件 ID |
| `questionId` | `ObjectId` | 逻辑题目 ID |
| `operationId` | `String` | 操作幂等标识 |
| `actorId` | `ObjectId` | 确认配置的用户 ID |
| `createdAt` | `Date` | 确认时间 |
| `revision` | 正整数 | 统计配置修订号 |
| `expectedRevision` | 整数 | 提交时预期的修订号 |
| `previousEventId` | `ObjectId` 或 `null` | 前一个配置事件 |
| `groups` | `Array<Object>` | 指标、分组 ID 和参与分组的版本 ID |
| `reason` | `String` | 所有者确认兼容性的说明 |
| `warnings` | `Array` | 预览或校验时产生的提示 |

`groups` 中的指标包括选择分布、数字平均值、数字分布和文本回答等。系统会先检查题型、选项、校验条件、单位和语义说明是否兼容，再允许所有者确认合并。`questions.statisticsRevision` 与 `questions.statisticsEventId` 指向当前生效配置；只沿有效事件链可追溯到的事件属于生效历史。该事件集合不应通过修改题目版本内容来替代。

## 6. Schema 校验与索引设计

### 6.1 Schema 校验的作用

`init_schema.py` 负责初始化第一阶段集合的校验规则，并调用 `initialize_library()` 为第二阶段新增集合建立或更新校验规则和索引。对于已经存在的集合，初始化使用 `collMod` 更新校验器，不以删除集合重建的方式迁移数据。

Schema 主要约束必需字段、BSON 数据类型、部分枚举值和嵌套结构。例如，题目版本的 `content` 必须包含 `type`、`title`、`required`、`unit` 和 `semanticDescription`；版本号为正整数；共享状态只能是 `active` 或 `revoked`。

Schema 不能代替所有业务校验。引用文档是否存在、版本是否属于某道题、调用者是否拥有题目、共享是否仍有效、快照内容是否与版本一致，都由后端业务逻辑检查。版本不可变也是应用层写入约定，不是 Schema 能完全保证的性质。

### 6.2 第一阶段索引

| 集合 | 索引字段 | 类型 | 作用 |
|---|---|---|---|
| `users` | `username` | 唯一索引，`unique_username` | 防止重复用户名 |
| `surveys` | `ownerId` | 普通索引，`surveys_by_owner` | 查询某用户创建的问卷 |
| `responses` | `surveyId` | 普通索引，`responses_by_survey` | 按问卷查询回答和统计 |
| `participations` | `surveyId`、`userId` | 复合唯一索引，`unique_survey_participant` | 防止同一用户对同一问卷重复参与 |

### 6.3 第二阶段索引

| 集合 | 索引字段 | 类型与名称 | 作用 |
|---|---|---|---|
| `questions` | `ownerId`、`operationId` | 唯一，`unique_question_creation_operation` | 防止同一用户的初始创建操作重复执行 |
| `questions` | `ownerId`、`updatedAt` 降序 | 普通，`questions_by_owner` | 按所有者列出并排序题目 |
| `question_versions` | `questionId`、`versionNumber` | 唯一，`unique_question_version` | 同一逻辑题目下版本号唯一 |
| `question_versions` | `questionId`、`createdAt` 降序 | 普通，`question_version_history` | 查询版本历史 |
| `question_versions` | `questionId`、`operationId` | 部分唯一，`unique_version_operation` | 对存在 `operationId` 的版本操作防止重复写入 |
| `question_version_operations` | `questionId`、`operationId` | 唯一，`unique_version_operation_receipt` | 每个逻辑题目的一次操作只保留一个回执 |
| `question_shares` | `questionId`、`recipientUserId` | 部分唯一，`unique_active_question_share`，仅对 `status: active` 生效 | 同一题目与接收者最多有一条有效授权，同时保留撤销历史 |
| `question_shares` | `recipientUserId`、`status` | 普通，`received_question_shares` | 查询用户收到的有效共享 |
| `question_shares` | `questionId`、`status` | 普通，`question_share_history` | 查询题目共享历史 |
| `question_banks` | `ownerId` | 普通，`banks_by_owner` | 查询用户的多个题库 |
| `question_bank_items` | `bankId`、`questionId` | 唯一，`unique_bank_question` | 同一题库内防止重复收录同一道题 |
| `question_bank_items` | `questionId` | 普通，`banks_by_question` | 按题目查找其题库关联 |
| `question_statistics_events` | `questionId`、`operationId` | 唯一，`unique_statistics_operation` | 防止统计配置操作重复写入 |
| `question_statistics_events` | `questionId`、`revision` 降序 | 普通，`statistics_event_candidates` | 查找某题目的统计配置事件候选 |
| `surveys` | `ownerId`、`questions.sourceQuestionId` | 普通，`owned_question_usage` | 查询当前用户问卷中的逻辑题目使用关系 |
| `surveys` | `ownerId`、`questions.sourceVersionId` | 普通，`owned_version_usage` | 查询当前用户问卷中使用的具体版本 |

索引只为常见查询和关键唯一性约束建立。索引可以提高查询效率，但会占用额外空间并增加写入维护成本。对于 `surveys.questions` 中的嵌套数组，实际查询需要将来源字段按同一个数组元素匹配，避免把不同题目实例的来源字段错误组合起来。

## 7. 为什么采用嵌入、引用和快照相结合的设计？

### 7.1 保留问卷内题目嵌入

问卷详情、填写、校验和跳转通常需要一起读取题目、选项和规则。继续将题目配置嵌入 `surveys.questions`，可以减少答题时额外查询，也保留了第一阶段的核心数据结构。代价是问卷内题目配置需要遵守文档大小限制，且问卷级编辑仍需维护嵌入数组。

### 7.2 独立保存逻辑题目、版本和授权

逻辑题目、版本、共享授权和题库条目有独立的生命周期，需要分别查询和维护。例如，同一道逻辑题目可以存在多个版本，一道题可以共享给多个用户，一个用户也可以把题目放入多个题库。将它们分别保存比把所有关系塞进问卷文档更清晰，也便于建立相应的唯一索引。

### 7.3 保存问卷快照

从题库选题时，后端根据经过权限检查的版本内容构建问卷内快照，并保存 `sourceQuestionId` 和 `sourceVersionId`。问卷快照保留具体题目内容，而不是仅存一个版本引用。

这样设计是因为修改题库当前版本不会自动修改已创建的问卷。不同问卷可以使用同一道逻辑题目的不同版本。撤销共享后，已合法创建的问卷仍然可以继续填写和查看历史结果。第一阶段答题流程仍然可以从问卷内题目读取题干、选项、校验和跳转配置。

快照也带来数据冗余和来源一致性维护成本。因此，题干、题型、选项、校验、单位或语义说明等内容若要改变，不能在保留旧来源标识的同时随意修改；应当显式切换到有效版本，或在允许的草稿场景中脱离题库来源。来源字段只有在快照内容与来源版本匹配时才有统计意义。

## 8. MongoDB 操作与统计方式

| 操作 | 项目中的用途 | 设计说明 |
|---|---|---|
| `insert_one` / `insert_many` | 创建用户、问卷、回答、题目、版本、共享记录或操作事件 | 将不同生命周期的数据写入相应集合 |
| `find` / `find_one` | 按所有者查询问卷和题目、读取版本、检查共享授权、按问卷查询回答 | 为管理、权限校验和统计提供数据 |
| `update_one` / `find_one_and_update` | 更新问卷状态、题库条目、共享状态、版本指针和操作状态 | 在有条件的更新中检查当前状态，减少并发覆盖风险 |
| 唯一索引 | 用户名、参与记录、版本号、有效共享、题库条目和操作回执 | 将关键唯一性约束交给数据库执行 |
| `$jsonSchema` | 初始化和更新集合校验规则 | 约束字段类型、必填字段和部分结构规则 |
| Python 应用层汇总 | 读取本人有权统计的问卷、回答和有效题目实例后计算结果 | 当前跨问卷统计在应用层进行，并未声称使用 MongoDB 聚合管道 |

当前跨问卷统计只汇总当前用户有权限查看的本人问卷，不会因为用户拥有某道逻辑题目或获得共享授权，就允许其查看其他人的原始回答。旧回答若没有可靠的来源版本映射，不会仅凭题干相同就自动纳入跨问卷统计。

统计口径还需区分：

- **问卷数**：不同 `surveyId` 的数量。
- **题目实例数**：问卷中符合来源与版本条件的实例数量。同一题在一份问卷出现两次，会计为两个实例。
- **提交数**：不同 `responseId` 的数量，不等于答案数量。
- **答案数**：通过来源匹配和答案校验的有效答案项数量。
- **平均值**：有效数值的总和除以有效数值答案数量，不是对各版本平均值再次简单求平均。
- **版本合并**：默认按版本分别统计；只有题目所有者确认且系统检查题型、选项、单位和语义等条件兼容后，才按配置分组合并相应指标。

统计配置事件保留确认人、时间、理由、参与版本和修订关系，便于追溯统计口径为何发生变化。兼容性确认不应越过实际结构差异，例如不同题型或语义不一致的数字题不能仅因标题相同就合并。

## 9. 关键数据完整性与兼容性规则

1. **所有权和权限。** 问卷由 `ownerId` 确定所有者；逻辑题目由 `questions.ownerId` 确定所有者。后端必须在管理操作中检查归属，不能只依赖前端隐藏按钮。
2. **共享撤销。** 每次新的选题或版本访问都要检查当前有效授权。旧授权记录和旧题库条目不能替代有效授权；撤销共享不会删除已合法保存的问卷快照或独立副本。
3. **版本当前指针。** `currentVersionId` 和 `currentVersionNumber` 必须指向同一版本。版本号更大不意味着该版本自动包含其他并发分支的修改。基于过期版本产生的分支应保留，是否成为当前推荐版本需要显式决策。
4. **恢复版本。** 恢复旧版本通过复制其内容创建新版本，并记录 `restoredFromVersionId`；不能覆盖被恢复的历史版本。
5. **快照来源。** 服务端根据已验证的版本生成快照，不信任客户端自行提交的来源 ID 作为统计依据。若内容脱离来源版本修改，必须切换到有效版本或清除来源关联。
6. **题库默认版本。** 默认版本必须属于对应逻辑题目，且当前用户在选用时仍具有权限。修改默认版本只影响后续选题。
7. **旧问卷与旧回答。** 旧问卷可以缺少来源字段，原有实例 ID、回答关联和跳转规则不变。旧回答不会自动进入跨问卷统计，除非系统有可靠来源映射。
8. **提交恢复。** 原有参与记录和回答恢复机制继续保留。待处理提交使用固定回答 ID 和持久化状态进行幂等恢复；该机制降低重复写入风险，但不应被描述成跨集合事务。
9. **统计权限。** 题目所有权或共享使用权不等于其他问卷的回答查看权。没有独立授权时，跨问卷统计只包含当前用户有权访问的问卷。
10. **匿名语义。** 匿名回答不在 `responses` 中保存 `respondentId`，但参与记录可能保存登录用户 ID 以执行重复填写控制。因此报告不把它描述为数据库中完全不可关联身份。


## 10. 小结

第一阶段使用嵌入式题目结构支持问卷的整体读取和答题流程，第二阶段在不改变原有问卷内题目 ID 语义的前提下，增加逻辑题目、不可变版本、共享授权、多题库和统计配置事件。数据库设计根据数据生命周期、查询方式和一致性要求选择嵌入、引用和快照相结合的方式。

这次扩展最重要的设计取舍是：题库负责复用和管理，版本负责保留内容历史，问卷快照负责固定某份问卷实际使用的内容，回答仍然关联问卷内的题目实例。这样既能支持新的题目复用需求，也尽量保留第一阶段的答题、跳转、校验、提交和统计流程。
