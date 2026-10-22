# 题目结构与校验规则

本文依据 `models/question_model.py`、`models/answer_validator.py`、`models/jump_model.py`、`models/jump_engine.py` 和 `init_schema.py` 整理。

## 1. 存储位置与公共字段

题目嵌入 `surveys.questions` 数组，不单独建立集合。数据库中的 ID 使用 BSON ObjectId，API 中序列化为字符串；题目 API 将 `_id` 输出为 `id`。

| 字段 | 数据类型 | 说明 |
| --- | --- | --- |
| `_id` | ObjectId | 服务端生成的题目标识 |
| `type` | string | single_choice、multiple_choice、text、number |
| `title` | string | 去除首尾空白后不能为空 |
| `required` | bool | 是否必答，创建时默认 true |
| `order` | number | 题序；添加时由数据库原子更新分配，从 1 开始 |
| `options` | array | 选择题选项；文本与数字题存储时省略 |
| `validation` | object | 题型相关限制；单选题可省略 |
| `jumpRules` | array | 有序跳转规则，创建时为空数组 |

数据库 Schema 要求 `_id`、`type`、`title`、`required`、`order` 存在，并校验基本类型及题型枚举。选项有效性、题型与限制的匹配、跳转目标关系由应用层进一步校验，不能仅依赖集合 Schema。

## 2. 四类题型

| 题型 | options | validation 默认值 | 答案类型 |
| --- | --- | --- | --- |
| single_choice | 至少两个选项 | 无专用限制 | string |
| multiple_choice | 至少两个选项 | minSelections=0，maxSelections=选项数 | string[] |
| text | 不允许非空选项 | minLength=0，maxLength=1000 | string |
| number | 不允许非空选项 | min=null，max=null，integerOnly=false | number |

选项格式为 `{"value":"a","label":"选项 A"}`。value 和 label 均须为非空白字符串，同题 value 不得重复。答案和跳转条件使用 value。

多选数量限制与文本长度限制必须为整数，不能是布尔值，且满足 `0 ≤ 最小值 ≤ 最大值`；多选最大值不能超过选项数。数字边界可为 null 或有限数字，最小值不能大于最大值；整数必须在 BSON 有符号 64 位范围内，integerOnly 必须为布尔值。

## 3. 创建示例

向 `POST /api/surveys/<survey_id>/questions` 提交以下 JSON；题目 ID、题序和规则列表由服务端生成：

```json
{
  "type": "multiple_choice",
  "title": "你使用哪些数据库？",
  "required": true,
  "options": [
    {"value": "mongodb", "label": "MongoDB"},
    {"value": "mysql", "label": "MySQL"}
  ],
  "validation": {"minSelections": 1, "maxSelections": 2}
}
```

配置修改仅允许问卷创建者在草稿状态下进行。完整接口与错误响应见 [API 说明](api-reference.md)。

## 4. 答案校验

答案结构为 `{"questionId":"题目 ID 字符串","value":答案}`。必答题拒绝 null、空字符串；必答多选拒绝空数组，必答文本拒绝纯空白。非必答空值可以通过空值检查。

单选值必须属于有效选项；多选值必须为字符串数组，不能重复或包含无效选项，并满足数量限制。非空文本按字符长度校验。数字不能使用布尔值、NaN 或无穷大，须满足范围及整数要求；整数须适合 BSON 64 位存储。integerOnly 允许数学上为整数的浮点值。

最终提交还会检查题目归属和实际跳转路径，避免保存跳过题目的答案。详见 [关键逻辑](key-logic.md)。

## 5. 跳转规则

规则存放在来源题目的 jumpRules 中：

```json
{
  "condition": {"operator": "equals", "value": "yes"},
  "targetQuestionId": "目标题目 ID（数据库中为 ObjectId）"
}
```

单选支持 equals，多选支持 contains，数字支持 equals、gt、gte、lt、lte；文本题暂不支持规则。选项条件必须使用当前题目的有效 value，数字条件必须为有限数字。

目标必须属于同一问卷并位于来源题之后。执行时按规则存储顺序取首个匹配且目标有效的规则；无匹配则进入下一题，末题之后返回结束。
