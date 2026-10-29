
import os
import atexit

from pymongo import MongoClient
from pymongo.errors import PyMongoError


MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb://localhost:27017/"
)

DATABASE_NAME = os.getenv("MONGO_DATABASE", "questionnaire_system")

client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000
)
atexit.register(client.close)

db = client[DATABASE_NAME]


def init_database():
    """检查数据库连接，并创建必要的索引。"""
    client.admin.command("ping")

    # 用户名唯一，防止重复注册
    db.users.create_index(
        [("username", 1)],
        unique=True,
        name="unique_username"
    )

    # 按创建者查询问卷
    db.surveys.create_index(
        [("ownerId", 1)],
        name="surveys_by_owner"
    )

    # 按问卷查询回答
    db.responses.create_index(
        [("surveyId", 1)],
        name="responses_by_survey"
    )

    db.participations.create_index(
        [("surveyId", 1), ("userId", 1)], unique=True,
        name="unique_survey_participant"
    )

    print("MongoDB 连接成功！")
    print(f"数据库名称：{db.name}")
    print("必要索引创建成功。")


if __name__ == "__main__":
    try:
        init_database()
    except PyMongoError as exc:
        print(f"MongoDB 操作失败：{exc}")
    finally:
        client.close()
