"""单机 MongoDB 的提交去重：唯一参与记录 + 可重放的持久化提交内容。"""
from datetime import datetime, timezone

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from models.database import db
from models.response_flow import ResponseFlowError


def finish_claim(claim):
    response_doc = claim["payload"]
    try:
        db.responses.update_one(
            {"_id": response_doc["_id"]}, {"$setOnInsert": response_doc}, upsert=True
        )
    except DuplicateKeyError:
        if db.responses.find_one({"_id": response_doc["_id"]}) is None:
            raise
    db.participations.update_one({"_id": claim["_id"]}, {
        "$set": {"status": "committed", "submittedAt": response_doc["submittedAt"]},
        "$unset": {"payload": ""}
    })
    return response_doc["_id"]


def recover_pending_participations():
    """启动初始化时恢复已经接受的提交，即使问卷此后已经截止。"""
    for claim in db.participations.find({"status": "pending"}):
        finish_claim(claim)


def save_response(survey, user_id, response_doc):
    if survey.get("allowMultipleResponses", False):
        return db.responses.insert_one(response_doc).inserted_id, False

    # 必须由数据库唯一索引仲裁，而不是依赖“先查再插入”。
    db.participations.create_index(
        [("surveyId", 1), ("userId", 1)], unique=True,
        name="unique_survey_participant"
    )
    key = {"surveyId": survey["_id"], "userId": user_id}
    response_doc = {**response_doc, "_id": ObjectId()}
    claim = {**key, "status": "pending", "responseId": response_doc["_id"],
             "payload": response_doc, "createdAt": datetime.now(timezone.utc)}
    recovered = False
    try:
        result = db.participations.insert_one(claim)
        claim["_id"] = result.inserted_id
    except DuplicateKeyError:
        claim = db.participations.find_one(key)
        if not claim or claim["status"] == "committed":
            raise ResponseFlowError("你已提交过这份问卷，不能重复填写", 409)
        # 第一次提交已持久化；重试只重放第一次的答案，不接受第二份内容。
        response_doc = claim["payload"]
        recovered = True

    return finish_claim(claim), recovered
