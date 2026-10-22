
import math

from bson import ObjectId
from pymongo import ReturnDocument

from models.database import db


CHOICE_TYPES = {"single_choice", "multiple_choice"}
SUPPORTED_TYPES = CHOICE_TYPES | {"text", "number"}


def build_question(question_type, title, required=True, options=None, validation=None):
    if not isinstance(title, str):
        raise ValueError("题目标题必须是字符串")

    title = title.strip()

    if not title:
        raise ValueError("题目标题不能为空")

    if not isinstance(question_type, str) or question_type not in SUPPORTED_TYPES:
        raise ValueError("不支持的题目类型")

    if not isinstance(required, bool):
        raise ValueError("required 必须是布尔值")

    if options is None:
        options = []
    if validation is None:
        validation = {}

    if not isinstance(options, list) or not isinstance(validation, dict):
        raise ValueError("options 必须是数组，validation 必须是对象")

    if question_type in CHOICE_TYPES:
        if len(options) < 2:
            raise ValueError("选择题至少需要两个选项")

        values = []
        for option in options:
            if not isinstance(option, dict):
                raise ValueError("每个选项必须是对象")

            value = option.get("value")
            label = option.get("label")

            if not isinstance(value, str) or not value.strip():
                raise ValueError("选项 value 不能为空")

            if not isinstance(label, str) or not label.strip():
                raise ValueError("选项 label 不能为空")

            values.append(value)

        if len(values) != len(set(values)):
            raise ValueError("选项 value 不能重复")

    elif options:
        raise ValueError("填空题不应包含选项")

    question = {
        "_id": ObjectId(),
        "type": question_type,
        "title": title,
        "required": required,
        "order": 0,
        "jumpRules": []
    }

    if question_type in CHOICE_TYPES:
        question["options"] = options

    if question_type == "multiple_choice":
        min_selections = validation.get("minSelections", 0)
        max_selections = validation.get(
            "maxSelections", len(options)
        )

        if (
            not isinstance(min_selections, int)
            or isinstance(min_selections, bool)
            or not isinstance(max_selections, int)
            or isinstance(max_selections, bool)
        ):
            raise ValueError("选择数量限制必须是整数")

        if (
            min_selections < 0
            or max_selections < min_selections
            or max_selections > len(options)
        ):
            raise ValueError("多选题数量限制不合法")

        question["validation"] = {
            "minSelections": min_selections,
            "maxSelections": max_selections
        }


    elif question_type == "text":
        min_length = validation.get("minLength", 0)
        max_length = validation.get("maxLength", 1000)

        if (
            not isinstance(min_length, int)
            or isinstance(min_length, bool)
            or not isinstance(max_length, int)
            or isinstance(max_length, bool)
        ):
            raise ValueError("文本长度限制必须是整数")

        if min_length < 0 or max_length < min_length:
            raise ValueError("文本长度限制不合法")

        question["validation"] = {
            "minLength": min_length,
            "maxLength": max_length
        }

    elif question_type == "number":
        min_value = validation.get("min")
        max_value = validation.get("max")
        integer_only = validation.get("integerOnly", False)

        if not isinstance(integer_only, bool):
            raise ValueError("integerOnly 必须是布尔值")

        for value in (min_value, max_value):
            if value is not None:
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                ):
                    raise ValueError("数字范围限制必须是数字")

                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("数字范围限制必须是有限数字")

                if isinstance(value, int) and not -(2 ** 63) <= value < 2 ** 63:
                    raise ValueError("数字范围限制超出数据库可保存的整数范围")

        if (
            min_value is not None
            and max_value is not None
            and min_value > max_value
        ):
            raise ValueError("最小值不能大于最大值")

        question["validation"] = {
            "min": min_value,
            "max": max_value,
            "integerOnly": integer_only
        }


    return question


def add_question(
    survey_id,
    owner_id,
    question_type,
    title,
    required=True,
    options=None,
    validation=None
):
    question = build_question(question_type, title, required, options, validation)

    survey = db.surveys.find_one_and_update(
        {
            "_id": ObjectId(survey_id),
            "ownerId": ObjectId(owner_id),
            "status": "draft"
        },
        [
            {
                "$set": {
                    "questions": {
                        "$concatArrays": [
                            {"$ifNull": ["$questions", []]},
                            [
                                {
                                    "$mergeObjects": [
                                        {"$literal": question},
                                        {
                                            "order": {
                                                "$add": [
                                                    {
                                                        "$size": {
                                                            "$ifNull": ["$questions", []]
                                                        }
                                                    },
                                                    1
                                                ]
                                            }
                                        }
                                    ]
                                }
                            ]
                        ]
                    },
                    "updatedAt": "$$NOW"
                }
            }
        ],
        return_document=ReturnDocument.AFTER
    )

    if survey is None:
        raise ValueError("问卷不存在、无权修改或不处于草稿状态")

    # 从原子更新结果中读取实际保存的题目，不再执行第二次写入。
    question = next(
        item for item in survey["questions"]
        if item["_id"] == question["_id"]
    )

    return {
        "id": str(question["_id"]),
        "type": question["type"],
        "title": question["title"],
        "required": question["required"],
        "order": question["order"],
        "options": question.get("options", []),
        "validation": question.get("validation", {}),
        "jumpRules": question["jumpRules"]
    }
