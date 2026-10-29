
from flask import Blueprint, request, jsonify, session
from pymongo.errors import DuplicateKeyError, PyMongoError

from models.user_model import (
    create_user,
    authenticate_user,
    get_user_by_id
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api")


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({"error": "请输入有效的用户名和密码"}), 400

    try:
        user = create_user(username, password)
        return jsonify({
            "message": "注册成功",
            "user": user
        }), 201

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except DuplicateKeyError:
        return jsonify({"error": "用户名已存在"}), 409

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "请求内容必须是 JSON 对象"}), 400

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify({"error": "请输入有效的用户名和密码"}), 400

    try:
        user = authenticate_user(username, password)

        if user is None:
            return jsonify({
                "error": "用户名或密码错误"
            }), 401

        session.clear()
        session["user_id"] = user["id"]

        return jsonify({
            "message": "登录成功",
            "user": user
        })

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@auth_bp.route("/me", methods=["GET"])
def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"error": "请先登录"}), 401

    try:
        user = get_user_by_id(user_id)

        if user is None:
            session.clear()
            return jsonify({"error": "用户不存在，请重新登录"}), 401

        return jsonify({"user": user})

    except PyMongoError:
        return jsonify({"error": "数据库操作失败"}), 500


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "已退出登录"})
