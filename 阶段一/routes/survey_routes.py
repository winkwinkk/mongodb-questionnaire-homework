
from flask import Blueprint, request, jsonify, session
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from models.survey_model import (
    create_survey,
    get_surveys_by_owner,
    publish_survey,
    serialize_survey,
    serialize_question
)
from models.database import db
from models.response_flow import check_fillable, ResponseFlowError

survey_bp = Blueprint("surveys", __name__, url_prefix="/api/surveys")


@survey_bp.route("", methods=["POST"])
def create_survey_api():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400

    title = data.get("title")
    description = data.get("description", "")
    anonymous_allowed = data.get("anonymousAllowed", False)

    if not isinstance(title, str):
        return jsonify({"error": "问卷标题必须是字符串"}), 400

    try:
        survey = create_survey(
            user_id,
            title,
            description,
            anonymous_allowed,
            data.get("allowMultipleResponses", False)
        )

        return jsonify({
            "message": "问卷创建成功",
            "survey": survey
        }), 201

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except (InvalidId, TypeError):
        session.clear()
        return jsonify({"error": "登录状态无效，请重新登录"}), 401

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@survey_bp.route("", methods=["GET"])
def list_surveys_api():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    try:
        surveys = get_surveys_by_owner(user_id)

        return jsonify({
            "count": len(surveys),
            "surveys": surveys
        })

    except (InvalidId, TypeError):
        session.clear()
        return jsonify({"error": "登录状态无效，请重新登录"}), 401

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@survey_bp.route("/<survey_id>/publish", methods=["POST"])
def publish_survey_api(survey_id):
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    try:
        survey = publish_survey(survey_id, user_id)

        return jsonify({
            "message": "问卷发布成功",
            "survey": survey
        }), 200

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@survey_bp.route("/<survey_id>", methods=["GET"])
def get_published_survey_api(survey_id):
    """获取已发布的问卷，供填写者查看。"""
    if not session.get("user_id"):
        return jsonify({"error": "请先登录后填写问卷"}), 401

    try:
        survey_oid = ObjectId(survey_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "问卷 ID 无效"}), 400

    try:
        survey = db.surveys.find_one({
            "_id": survey_oid,
            "status": "published"
        })

        check_fillable(survey)

        # 不向填写者返回创建者内部信息或跳转规则
        questions = []

        for question in sorted(
            survey.get("questions", []),
            key=lambda q: q.get("order", 0)
        ):
            item = serialize_question(question)
            questions.append(item)

        return jsonify({
            "survey": {
                "id": str(survey["_id"]),
                "title": survey["title"],
                "description": survey.get("description", ""),
                "anonymousAllowed": survey.get(
                    "anonymousAllowed", False
                ),
                "allowMultipleResponses": survey.get("allowMultipleResponses", False),
                "alreadySubmitted": (
                    not survey.get("allowMultipleResponses", False)
                    and db.participations.find_one({
                        "surveyId": survey["_id"], "userId": ObjectId(session["user_id"]),
                        "status": "committed"
                    }, {"_id": 1}) is not None
                ),
                "deadline": (
                    survey["deadline"].isoformat()
                    if survey.get("deadline") else None
                ),
                "questions": questions
            }
        }), 200

    except ResponseFlowError as exc:
        return jsonify(exc.payload), exc.status

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@survey_bp.route("/<survey_id>", methods=["PATCH"])
def update_survey_api(survey_id):
    owner = session.get("user_id")
    if not owner:
        return jsonify({"error": "请先登录"}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400
    try:
        from datetime import datetime, timezone
        query = {"_id": ObjectId(survey_id), "ownerId": ObjectId(owner), "status": "draft"}
        fields = {}
        for name in ("title", "description"):
            if name in data:
                value = data[name]
                limit = 200 if name == "title" else 5000
                if not isinstance(value, str) or len(value) > limit or (name == "title" and not value.strip()):
                    return jsonify({"error": "标题或说明格式不正确"}), 400
                fields[name] = value.strip() if name == "title" else value
        for name in ("anonymousAllowed", "allowMultipleResponses"):
            if name in data:
                if not isinstance(data[name], bool):
                    return jsonify({"error": "填写设置必须是布尔值"}), 400
                fields[name] = data[name]
        if not fields:
            return jsonify({"error": "没有可更新的字段"}), 400
        fields["updatedAt"] = datetime.now(timezone.utc)
        result = db.surveys.update_one(query, {"$set": fields})
        if not result.matched_count:
            return jsonify({"error": "问卷不存在、无权操作或已发布"}), 409
        return jsonify({"message": "问卷设置已保存"})
    except (InvalidId, TypeError):
        return jsonify({"error": "问卷 ID 无效"}), 400
    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@survey_bp.route("/<survey_id>/manage", methods=["GET"])
def get_managed_survey_api(survey_id):
    """创建者读取任意状态问卷的完整配置；仅草稿可编辑。"""
    owner_id = session.get("user_id")
    if not owner_id:
        return jsonify({"error": "请先登录"}), 401
    try:
        survey_oid = ObjectId(survey_id)
        owner_oid = ObjectId(owner_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "问卷或用户 ID 无效"}), 400
    try:
        survey = db.surveys.find_one({"_id": survey_oid, "ownerId": owner_oid})
        if survey is None:
            return jsonify({"error": "问卷不存在或无权操作"}), 404
        result = serialize_survey(survey)
        result["canEdit"] = survey["status"] == "draft"
        result["questions"] = [
            serialize_question(q, include_rules=True)
            for q in sorted(survey.get("questions", []), key=lambda q: q["order"])
        ]
        return jsonify({"survey": result})
    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500
