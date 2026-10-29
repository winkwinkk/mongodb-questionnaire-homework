
from flask import Blueprint, request, jsonify, session
from pymongo.errors import PyMongoError

from models.jump_model import add_jump_rule

jump_bp = Blueprint("jump", __name__, url_prefix="/api")


@jump_bp.route(
    "/surveys/<survey_id>/questions/<source_id>/rules",
    methods=["POST"]
)
def create_jump_rule_api(survey_id, source_id):
    owner_id = session.get("user_id")

    if not owner_id:
        return jsonify({"error": "请先登录"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400

    if not all(
        key in data
        for key in ("operator", "value", "targetQuestionId")
    ):
        return jsonify({"error": "缺少跳转规则字段"}), 400

    try:
        rule = add_jump_rule(
            survey_id=survey_id,
            owner_id=owner_id,
            source_question_id=source_id,
            operator=data["operator"],
            value=data["value"],
            target_question_id=data["targetQuestionId"]
        )

        return jsonify({
            "message": "跳转规则添加成功",
            "rule": rule
        }), 201

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500
