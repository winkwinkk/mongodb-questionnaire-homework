
from flask import Blueprint, request, jsonify, session
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from models.question_model import add_question
from models.question_model import build_question
from models.database import db
from bson import ObjectId
from datetime import datetime, timezone
from models.library_model import content_from, version_content

question_bp = Blueprint("questions", __name__, url_prefix="/api")


@question_bp.route(
    "/surveys/<survey_id>/questions",
    methods=["POST"]
)
def add_question_api(survey_id):
    owner_id = session.get("user_id")

    if not owner_id:
        return jsonify({"error": "请先登录"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400

    try:
        question = add_question(
            survey_id=survey_id,
            owner_id=owner_id,
            question_type=data.get("type"),
            title=data.get("title", ""),
            required=data.get("required", True),
            options=data.get("options"),
            validation=data.get("validation")
        )

        return jsonify({
            "message": "题目添加成功",
            "question": question
        }), 201

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except InvalidId:
        return jsonify({"error": "问卷 ID 无效"}), 400

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@question_bp.route("/surveys/<survey_id>/questions/<question_id>", methods=["PUT", "DELETE"])
def modify_question(survey_id, question_id):
    owner = session.get("user_id")
    if not owner:
        return jsonify({"error": "请先登录"}), 401
    try:
        query = {"_id": ObjectId(survey_id), "ownerId": ObjectId(owner), "status": "draft"}
        qid = ObjectId(question_id)
        survey = db.surveys.find_one(query)
        if not survey:
            return jsonify({"error": "问卷不存在、无权操作或已发布"}), 404
        old = next((q for q in survey["questions"] if q["_id"] == qid), None)
        if not old:
            return jsonify({"error": "题目不存在"}), 404
        questions = [dict(q) for q in survey["questions"]]
        if request.method == "DELETE":
            if any(r["targetQuestionId"] == qid for q in questions for r in q.get("jumpRules", [])):
                return jsonify({"error": "请先删除指向本题的跳转规则"}), 400
            questions = [q for q in questions if q["_id"] != qid]
            for index, q in enumerate(questions, 1):
                q["order"] = index
        else:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"error": "请求内容必须是 JSON 对象"}), 400
            if "sourceQuestionId" in data or "sourceVersionId" in data:
                return jsonify({"error": "来源字段只能通过选题接口设置"}), 400
            detach = data.get("detachSource", False)
            if not isinstance(detach, bool):
                return jsonify({"error": "detachSource 必须是布尔值"}), 400
            changed = build_question(data.get("type"), data.get("title"),
                                     data.get("required", True), data.get("options"), data.get("validation"))
            metadata = content_from({**version_content(changed),
                                     "unit": data.get("unit", old.get("unit", "")),
                                     "semanticDescription": data.get("semanticDescription", old.get("semanticDescription", ""))})
            for key in ("unit", "semanticDescription"):
                if key in old or key in data:
                    changed[key] = metadata[key]
            if old.get("sourceQuestionId") and not detach:
                before = content_from(version_content(old))
                after = content_from(version_content(changed))
                before.pop("required")
                after.pop("required")
                if before != after:
                    return jsonify({"error": "来源题目内容不能直接修改，请创建新版本或显式 detachSource"}), 409
                changed.update({key: old[key] for key in ("sourceQuestionId", "sourceVersionId")})
            if old.get("jumpRules") and (changed["type"] != old["type"] or changed.get("options") != old.get("options")):
                return jsonify({"error": "修改题型或选项前，请先删除本题的跳转规则"}), 400
            changed.update({"_id": qid, "order": old["order"], "jumpRules": old.get("jumpRules", [])})
            questions = [changed if q["_id"] == qid else q for q in questions]
        query["questions"] = survey["questions"]
        result = db.surveys.update_one(query, {"$set": {
            "questions": questions, "updatedAt": datetime.now(timezone.utc)
        }})
        if not result.matched_count:
            return jsonify({"error": "问卷已被修改，请刷新后重试"}), 409
        return jsonify({"message": "题目已保存" if request.method == "PUT" else "题目已删除"})
    except (ValueError, TypeError, InvalidId) as exc:
        return jsonify({"error": str(exc)}), 400
    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@question_bp.route("/surveys/<survey_id>/questions/<question_id>/rules/<int:rule_index>", methods=["DELETE"])
def delete_rule(survey_id, question_id, rule_index):
    if not session.get("user_id"):
        return jsonify({"error": "请先登录"}), 401
    try:
        query = {"_id": ObjectId(survey_id), "ownerId": ObjectId(session["user_id"]), "status": "draft"}
        survey = db.surveys.find_one(query)
        if not survey:
            return jsonify({"error": "问卷不存在、无权操作或已发布"}), 404
        questions = [dict(q) for q in survey["questions"]]
        question = next((q for q in questions if q["_id"] == ObjectId(question_id)), None)
        if not question or rule_index >= len(question.get("jumpRules", [])):
            return jsonify({"error": "规则不存在"}), 404
        question["jumpRules"] = [r for i, r in enumerate(question["jumpRules"]) if i != rule_index]
        query["questions"] = survey["questions"]
        result = db.surveys.update_one(query, {"$set": {"questions": questions, "updatedAt": datetime.now(timezone.utc)}})
        if not result.matched_count:
            return jsonify({"error": "配置已变化，请刷新后重试"}), 409
        return jsonify({"message": "规则已删除"})
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500
