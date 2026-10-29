
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from flask import Blueprint, jsonify, request, session
from pymongo.errors import PyMongoError

from models.database import db
from models.survey_model import serialize_question
from models.participation_model import save_response
from models.response_flow import (
    ResponseFlowError, check_fillable, walk_response_path
)


response_bp = Blueprint("responses", __name__, url_prefix="/api")


def _get_owned_survey(survey_id, owner_id):
    """只允许问卷创建者访问管理功能。"""
    try:
        survey_oid = ObjectId(survey_id)
        owner_oid = ObjectId(owner_id)
    except (InvalidId, TypeError):
        raise ValueError("问卷 ID 无效")

    survey = db.surveys.find_one({
        "_id": survey_oid,
        "ownerId": owner_oid
    })

    if survey is None:
        raise LookupError("问卷不存在或无权操作")

    return survey


def _get_questions(survey):
    return sorted(
        survey.get("questions", []),
        key=lambda q: q.get("order", 0)
    )


@response_bp.route("/surveys/<survey_id>/next", methods=["POST"])
def next_question_api(survey_id):
    """只计算下一题，不保存回答；完成后仍须调用 responses 提交。"""
    if not session.get("user_id"):
        return jsonify({"error": "请先登录后填写问卷"}), 401
    try:
        survey_oid = ObjectId(survey_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "问卷 ID 无效"}), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400
    try:
        survey = db.surveys.find_one({"_id": survey_oid, "status": "published"})
        check_fillable(survey)
        path = walk_response_path(survey, data.get("answers"), partial=True)
        question = path["nextQuestion"]
        return jsonify({
            "surveyId": str(survey["_id"]),
            "completed": question is None,
            "nextQuestion": serialize_question(question) if question else None,
            "visitedQuestionIds": path["visitedQuestionIds"]
        })
    except ResponseFlowError as exc:
        return jsonify(exc.payload), exc.status
    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@response_bp.route(
    "/surveys/<survey_id>/responses",
    methods=["POST"]
)
def submit_response(survey_id):
    """校验实际答题路径，并保存一份完整回答。"""
    user_id = session.get("user_id")

    # 课程需求要求填写者先登录
    if not user_id:
        return jsonify({"error": "请先登录后填写问卷"}), 401

    try:
        survey_oid = ObjectId(survey_id)
    except (InvalidId, TypeError):
        return jsonify({"error": "问卷 ID 无效"}), 400

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400

    answers_input = data.get("answers")

    if not isinstance(answers_input, dict):
        return jsonify({
            "error": "answers 必须是以题目 ID 为键的 JSON 对象"
        }), 400

    anonymous = data.get("anonymous", False)

    if not isinstance(anonymous, bool):
        return jsonify({"error": "anonymous 必须是布尔值"}), 400

    try:
        user_oid = ObjectId(user_id)

        survey = db.surveys.find_one({
            "_id": survey_oid,
            "status": "published"
        })

        check_fillable(survey)
        now = datetime.now(timezone.utc)

        if anonymous and not survey.get("anonymousAllowed", False):
            return jsonify({
                "error": "该问卷不允许匿名填写"
            }), 400

        # 与逐题接口共用路径计算，最终提交仍重新完整校验。
        path = walk_response_path(survey, answers_input)
        saved_answers = path["answers"]

        response_doc = {
            "surveyId": survey_oid,
            "answers": saved_answers,
            "submittedAt": now
        }

        if not anonymous:
            response_doc["respondentId"] = user_oid

        response_id, recovered = save_response(survey, user_oid, response_doc)
        if recovered:
            original = db.responses.find_one({"_id": response_id})
            saved_answers = original["answers"]
            anonymous = "respondentId" not in original

        return jsonify({
            "message": "问卷提交成功",
            "responseId": str(response_id),
            "answerCount": len(saved_answers),
            "anonymous": anonymous,
            "recovered": recovered
        }), 201

    except ResponseFlowError as exc:
        return jsonify(exc.payload), exc.status

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@response_bp.route(
    "/surveys/<survey_id>/close",
    methods=["POST"]
)
def close_survey(survey_id):
    owner_id = session.get("user_id")

    if not owner_id:
        return jsonify({"error": "请先登录"}), 401

    try:
        survey = _get_owned_survey(survey_id, owner_id)

        if survey.get("status") != "published":
            return jsonify({
                "error": "只有已发布的问卷可以关闭"
            }), 400

        db.surveys.update_one(
            {
                "_id": survey["_id"],
                "ownerId": survey["ownerId"],
                "status": "published"
            },
            {
                "$set": {
                    "status": "closed",
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )

        return jsonify({
            "message": "问卷已关闭",
            "surveyId": survey_id,
            "status": "closed"
        })

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@response_bp.route(
    "/surveys/<survey_id>/deadline",
    methods=["PUT"]
)
def set_survey_deadline(survey_id):
    owner_id = session.get("user_id")

    if not owner_id:
        return jsonify({"error": "请先登录"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or "deadline" not in data:
        return jsonify({
            "error": "请提供 deadline，使用 ISO 8601 时间格式；传 null 可清除截止时间"
        }), 400

    deadline_text = data["deadline"]
    deadline = None

    if deadline_text is not None:
        if not isinstance(deadline_text, str):
            return jsonify({
                "error": "deadline 必须是 ISO 8601 时间字符串或 null"
            }), 400

        try:
            deadline = datetime.fromisoformat(
                deadline_text.replace("Z", "+00:00")
            )

            if deadline.tzinfo is None:
                return jsonify({
                    "error": "deadline 必须包含时区，例如 +08:00 或 Z"
                }), 400

            deadline = deadline.astimezone(timezone.utc)

        except ValueError:
            return jsonify({"error": "deadline 时间格式无效"}), 400

        if deadline <= datetime.now(timezone.utc):
            return jsonify({"error": "截止时间必须晚于当前时间"}), 400

    try:
        survey = _get_owned_survey(survey_id, owner_id)

        if survey.get("status") != "published":
            return jsonify({
                "error": "只能为已发布的问卷设置截止时间"
            }), 400

        db.surveys.update_one(
            {"_id": survey["_id"]},
            {
                "$set": {
                    "deadline": deadline,
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )

        return jsonify({
            "message": "截止时间已更新",
            "deadline": deadline.isoformat() if deadline else None
        })

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@response_bp.route(
    "/surveys/<survey_id>/statistics",
    methods=["GET"]
)
def survey_statistics(survey_id):
    owner_id = session.get("user_id")

    if not owner_id:
        return jsonify({"error": "请先登录"}), 401

    try:
        survey = _get_owned_survey(survey_id, owner_id)

        responses = list(db.responses.find({
            "surveyId": survey["_id"]
        }))

        questions = _get_questions(survey)
        results = []

        for question in questions:
            question_id = question["_id"]
            question_answers = []

            for response in responses:
                for answer in response.get("answers", []):
                    if answer.get("questionId") == question_id:
                        question_answers.append(answer.get("value"))

            question_result = {
                "questionId": str(question_id),
                "title": question["title"],
                "type": question["type"],
                "answeredCount": len(question_answers)
            }

            if question["type"] in {
                "single_choice", "multiple_choice"
            }:
                counts = {
                    option["value"]: 0
                    for option in question.get("options", [])
                }

                for value in question_answers:
                    selected = value if isinstance(value, list) else [value]

                    for item in selected:
                        if item in counts:
                            counts[item] += 1

                question_result["optionCounts"] = [
                    {
                        "value": option["value"],
                        "label": option["label"],
                        "count": counts[option["value"]]
                    }
                    for option in question.get("options", [])
                ]

            elif question["type"] == "text":
                question_result["answers"] = question_answers

            elif question["type"] == "number":
                numbers = [
                    value for value in question_answers
                    if isinstance(value, (int, float))
                    and not isinstance(value, bool)
                ]

                question_result["numericAnswers"] = numbers
                question_result["average"] = (
                    sum(numbers) / len(numbers)
                    if numbers else None
                )

            results.append(question_result)

        return jsonify({
            "surveyId": str(survey["_id"]),
            "title": survey["title"],
            "responseCount": len(responses),
            "questions": results
        })

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@response_bp.route(
    "/surveys/<survey_id>/questions/<question_id>/statistics",
    methods=["GET"]
)
def question_statistics(survey_id, question_id):
    owner_id = session.get("user_id")

    if not owner_id:
        return jsonify({"error": "请先登录"}), 401

    try:
        survey = _get_owned_survey(survey_id, owner_id)

        try:
            question_oid = ObjectId(question_id)
        except (InvalidId, TypeError):
            return jsonify({"error": "题目 ID 无效"}), 400

        question = next(
            (
                q for q in survey.get("questions", [])
                if q["_id"] == question_oid
            ),
            None
        )

        if question is None:
            return jsonify({"error": "题目不存在"}), 404

        responses = list(db.responses.find({
            "surveyId": survey["_id"]
        }))

        values = []

        for response in responses:
            for answer in response.get("answers", []):
                if answer.get("questionId") == question_oid:
                    values.append(answer.get("value"))

        result = {
            "questionId": str(question_oid),
            "title": question["title"],
            "type": question["type"],
            "answeredCount": len(values)
        }

        if question["type"] in {"single_choice", "multiple_choice"}:
            counts = {
                option["value"]: 0
                for option in question.get("options", [])
            }

            for value in values:
                selected = value if isinstance(value, list) else [value]
                for item in selected:
                    if item in counts:
                        counts[item] += 1

            result["optionCounts"] = [
                {
                    "value": option["value"],
                    "label": option["label"],
                    "count": counts[option["value"]]
                }
                for option in question.get("options", [])
            ]

        elif question["type"] == "text":
            result["answers"] = values

        elif question["type"] == "number":
            numbers = [
                value for value in values
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
            ]

            result["numericAnswers"] = numbers
            result["average"] = (
                sum(numbers) / len(numbers)
                if numbers else None
            )

        return jsonify(result)

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500
