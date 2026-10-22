
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash, check_password_hash

from models.database import db


def create_user(username, password):
    """创建用户，返回新用户的基本信息。"""
    username = username.strip()

    if not username:
        raise ValueError("用户名不能为空")

    if len(username) < 3 or len(username) > 30:
        raise ValueError("用户名长度必须为 3～30 个字符")

    if len(password) < 8:
        raise ValueError("密码至少需要 8 个字符")

    user = {
        "username": username,
        "passwordHash": generate_password_hash(password),
        "createdAt": datetime.now(timezone.utc)
    }

    result = db.users.insert_one(user)

    return {
        "id": str(result.inserted_id),
        "username": username,
        "createdAt": user["createdAt"].isoformat()
    }


def authenticate_user(username, password):
    """验证用户名和密码，成功时返回用户基本信息。"""
    username = username.strip()

    user = db.users.find_one({"username": username})

    if user is None:
        return None

    if not check_password_hash(user["passwordHash"], password):
        return None

    return {
        "id": str(user["_id"]),
        "username": user["username"]
    }


def get_user_by_id(user_id):
    """根据用户 ID 获取基本信息。"""
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        object_id = ObjectId(user_id)
    except (InvalidId, TypeError):
        return None

    user = db.users.find_one(
        {"_id": object_id},
        {"username": 1, "createdAt": 1}
    )

    if user is None:
        return None

    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "createdAt": user["createdAt"].isoformat()
    }
