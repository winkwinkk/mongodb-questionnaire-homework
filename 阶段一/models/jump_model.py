
import math

from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, timezone

from models.database import db


def add_jump_rule(
    survey_id,
    owner_id,
    source_question_id,
    operator,
    value,
    target_question_id
):
    """为草稿问卷中的一道题添加跳转规则。"""

    if not isinstance(operator, str):
        raise ValueError("跳转操作符必须是字符串")

    try:
        survey_oid = ObjectId(survey_id)
        owner_oid = ObjectId(owner_id)
        source_oid = ObjectId(source_question_id)
        target_oid = ObjectId(target_question_id)
    except (InvalidId, TypeError):
        raise ValueError("问卷 ID 或题目 ID 无效")

    survey = db.surveys.find_one({
        "_id": survey_oid,
        "ownerId": owner_oid,
        "status": "draft"
    })

    if survey is None:
        raise ValueError("问卷不存在、无权修改或不是草稿状态")

    questions = survey.get("questions", [])

    source = next(
        (q for q in questions if q["_id"] == source_oid),
        None
    )
    target = next(
        (q for q in questions if q["_id"] == target_oid),
        None
    )

    if source is None or target is None:
        raise ValueError("跳转题目必须属于当前问卷")

    if target["order"] <= source["order"]:
        raise ValueError("第一阶段只允许跳转到后面的题目")

    question_type = source["type"]

    # 检查操作符和条件值是否适用于当前题型
    if question_type == "single_choice":
        if operator != "equals":
            raise ValueError("单选题目前只支持 equals")

        valid_values = {
            option["value"]
            for option in source.get("options", [])
        }

        if not isinstance(value, str) or value not in valid_values:
            raise ValueError("跳转条件必须使用当前题目的有效选项")

    elif question_type == "multiple_choice":
        if operator != "contains":
            raise ValueError("多选题目前只支持 contains")

        valid_values = {
            option["value"]
            for option in source.get("options", [])
        }

        if not isinstance(value, str) or value not in valid_values:
            raise ValueError("跳转条件必须使用当前题目的有效选项")

    elif question_type == "number":
        if operator not in {"equals", "gt", "gte", "lt", "lte"}:
            raise ValueError("数字题不支持该比较操作符")

        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            raise ValueError("数字跳转条件必须是有限数字")

        if isinstance(value, int) and not -(2 ** 63) <= value < 2 ** 63:
            raise ValueError("跳转条件超出数据库可保存的整数范围")

    else:
        raise ValueError("文本填空题暂不支持跳转")

    rule = {
        "condition": {
            "operator": operator,
            "value": value
        },
        "targetQuestionId": target_oid
    }

    result = db.surveys.update_one(
        {
            "_id": survey_oid,
            "ownerId": owner_oid,
            "status": "draft",
            "questions._id": source_oid
        },
        {
            "$push": {
                "questions.$.jumpRules": rule
            },
            "$set": {
                "updatedAt": datetime.now(timezone.utc)
            }
        }
    )

    if result.modified_count != 1:
        raise ValueError("规则未能保存，请检查问卷状态")

    return {
        "sourceQuestionId": str(source_oid),
        "operator": operator,
        "value": value,
        "targetQuestionId": str(target_oid)
    }
