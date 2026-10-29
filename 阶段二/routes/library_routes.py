"""Library and version-management APIs; saved version content is never overwritten."""
from functools import wraps

from flask import Blueprint, jsonify, request, session
from pymongo.errors import PyMongoError

from models import library_model as library
from models import version_model as versions


library_bp = Blueprint("library", __name__, url_prefix="/api")


def endpoint(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "请先登录"}), 401
        try:
            return view(*args, **kwargs)
        except library.LibraryError as error:
            return jsonify({"error": str(error)}), error.status
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except PyMongoError:
            return jsonify({"error": "数据库操作失败，请检查状态后重试；带 operationId 的操作请保留原值"}), 500
    return wrapped


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise library.LibraryError("请求内容必须是 JSON 对象")
    return data


@library_bp.route("/questions", methods=["POST", "GET"])
@endpoint
def questions():
    user = session["user_id"]
    if request.method == "GET":
        items = library.list_owned(user)
        return jsonify({"questions": items, "count": len(items)})
    data = body()
    return jsonify(library.create_initial(user, data.get("operationId"), data.get("content"),
                                          data.get("title"), data.get("changeNote", ""))), 201


@library_bp.route("/questions/<question_id>", methods=["GET"])
@endpoint
def detail(question_id):
    question, version = library.get_version(session["user_id"], question_id)
    return jsonify({"question": library.public_question(question), "version": library.public_version(version)})


@library_bp.route("/questions/<question_id>/versions/<version_id>", methods=["GET"])
@endpoint
def version(question_id, version_id):
    _, item = library.get_version(session["user_id"], question_id, version_id)
    return jsonify({"version": library.public_version(item)})


@library_bp.route("/questions/<question_id>/versions", methods=["GET", "POST"])
@endpoint
def version_history(question_id):
    if request.method == "GET":
        try:
            limit = int(request.args.get("limit", "50"))
            before = int(request.args["before"]) if "before" in request.args else None
        except ValueError:
            raise library.LibraryError("limit 和 before 必须是整数")
        return jsonify(versions.history(session["user_id"], question_id, limit, before))
    return jsonify(versions.submit(session["user_id"], question_id, body())), 201


@library_bp.route("/questions/<question_id>/versions/<version_id>/restore", methods=["POST"])
@endpoint
def restore_version(question_id, version_id):
    return jsonify(versions.submit(session["user_id"], question_id, body(), "restore", version_id)), 201


@library_bp.route("/questions/<question_id>/current-version", methods=["PUT"])
@endpoint
def choose_version(question_id):
    result = versions.submit(session["user_id"], question_id, body(), "select")
    return jsonify(result), 409 if result["operation"]["outcome"] == "conflict" else 200


@library_bp.route("/questions/<question_id>/version-diff", methods=["GET"])
@endpoint
def version_diff(question_id):
    return jsonify(versions.difference(session["user_id"], question_id,
                                       request.args.get("from"), request.args.get("to")))


@library_bp.route("/questions/<question_id>/operations/<operation_id>/retry", methods=["POST"])
@endpoint
def retry_version_operation(question_id, operation_id):
    result = versions.retry_operation(session["user_id"], question_id, operation_id)
    return jsonify(result), 409 if result["operation"]["outcome"] == "conflict" else 200


@library_bp.route("/questions/<question_id>/copies", methods=["POST"])
@endpoint
def copy(question_id):
    data = body()
    if "versionId" not in data:
        raise library.LibraryError("请明确提供 versionId")
    return jsonify(library.copy_question(session["user_id"], question_id, library.oid(data["versionId"]), data)), 201


@library_bp.route("/surveys/<survey_id>/questions/<instance_id>/save-to-library", methods=["POST"])
@endpoint
def save(survey_id, instance_id):
    return jsonify(library.save_survey_question(session["user_id"], survey_id, instance_id, body())), 201


@library_bp.route("/surveys/<survey_id>/questions/from-library", methods=["POST"])
@endpoint
def select(survey_id):
    data = body()
    if not all(key in data for key in ("questionId", "versionId")):
        raise library.LibraryError("请提供 questionId 和 versionId")
    if "required" in data and not isinstance(data["required"], bool):
        raise library.LibraryError("required 必须是布尔值")
    result = library.import_snapshot(session["user_id"], survey_id, data["questionId"],
                                     library.oid(data["versionId"]), data.get("required"))
    return jsonify({"question": result}), 201


@library_bp.route("/surveys/<survey_id>/questions/<instance_id>/source-version", methods=["PUT"])
@endpoint
def switch(survey_id, instance_id):
    data = body()
    return jsonify({"question": library.switch_snapshot(session["user_id"], survey_id,
                                                        instance_id, data.get("versionId"))})
