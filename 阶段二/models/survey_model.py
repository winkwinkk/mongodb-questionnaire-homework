
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from models.database import db


def create_survey(owner_id, title, description="", anonymous_allowed=False,
                  allow_multiple_responses=False):
    """创建一份草稿问卷。"""
    if not isinstance(title, str):
        raise ValueError("问卷标题必须是字符串")

    title = title.strip()

    if not title:
        raise ValueError("问卷标题不能为空")

    if len(title) > 200:
        raise ValueError("问卷标题不能超过 200 个字符")

    if not isinstance(description, str):
        raise ValueError("问卷说明必须是字符串")

    if len(description) > 5000:
        raise ValueError("问卷说明不能超过 5000 个字符")

    if not isinstance(anonymous_allowed, bool):
        raise ValueError("匿名填写设置必须是布尔值")

    if not isinstance(allow_multiple_responses, bool):
        raise ValueError("重复填写设置必须是布尔值")

    try:
        owner_oid = ObjectId(owner_id)
    except (InvalidId, TypeError):
        raise ValueError("用户 ID 无效")

    now = datetime.now(timezone.utc)

    survey = {
        "ownerId": owner_oid,
        "title": title,
        "description": description,
        "anonymousAllowed": anonymous_allowed,
        "allowMultipleResponses": allow_multiple_responses,
        "status": "draft",
        "deadline": None,
        "questions": [],
        "createdAt": now,
        "updatedAt": now
    }

    result = db.surveys.insert_one(survey)
    survey["_id"] = result.inserted_id

    return serialize_survey(survey)


def serialize_survey(survey):
    """将 MongoDB 文档转换为适合 API 返回的字典。"""
    return {
        "id": str(survey["_id"]),
        "ownerId": str(survey["ownerId"]),
        "title": survey["title"],
        "description": survey["description"],
        "anonymousAllowed": survey["anonymousAllowed"],
        "allowMultipleResponses": survey.get("allowMultipleResponses", False),
        "status": survey["status"],
        "deadline": (
            survey["deadline"].isoformat()
            if survey.get("deadline") else None
        ),
        "questionCount": len(survey.get("questions", [])),
        "createdAt": survey["createdAt"].isoformat(),
        "updatedAt": survey["updatedAt"].isoformat()
    }


def serialize_question(question, include_rules=False):
    """统一题目返回格式，只有管理接口包含跳转规则。"""
    result = {
        "id": str(question["_id"]),
        "type": question["type"],
        "title": question["title"],
        "required": question.get("required", False),
        "order": question.get("order", 0),
        "options": question.get("options", []),
        "validation": question.get("validation", {})
    }
    if include_rules:
        for key in ("sourceQuestionId", "sourceVersionId"):
            if key in question:
                result[key] = str(question[key])
        result["jumpRules"] = [
            {
                "condition": rule["condition"],
                "targetQuestionId": str(rule["targetQuestionId"])
            }
            for rule in question.get("jumpRules", [])
        ]
    for key in ("unit", "semanticDescription"):
        if key in question:
            result[key] = question[key]
    return result


def get_surveys_by_owner(owner_id):
    """只查询指定用户创建的问卷。"""
    try:
        owner_oid = ObjectId(owner_id)
    except (InvalidId, TypeError):
        raise ValueError("用户 ID 无效")

    surveys = db.surveys.find(
        {"ownerId": owner_oid}
    ).sort("createdAt", -1)

    return [serialize_survey(survey) for survey in surveys]


def publish_survey(survey_id, owner_id):
    """发布草稿问卷。只有创建者可以发布自己的问卷。"""
    try:
        survey_oid = ObjectId(survey_id)
        owner_oid = ObjectId(owner_id)
    except (InvalidId, TypeError):
        raise ValueError("问卷 ID 无效")

    # 只允许问卷创建者发布处于草稿状态的问卷
    survey = db.surveys.find_one({
        "_id": survey_oid,
        "ownerId": owner_oid,
        "status": "draft"
    })

    if survey is None:
        raise ValueError("问卷不存在、无权操作或不是草稿状态")

    # 没有题目的问卷不能发布
    if not survey.get("questions"):
        raise ValueError("问卷至少需要一道题才能发布")

    result = db.surveys.update_one(
        {
            "_id": survey_oid,
            "ownerId": owner_oid,
            "status": "draft"
        },
        {
            "$set": {
                "status": "published",
                "updatedAt": datetime.now(timezone.utc)
            }
        }
    )

    if result.modified_count != 1:
        raise ValueError("问卷发布失败，请检查问卷状态")

    return {
        "id": str(survey_oid),
        "status": "published"
    }
