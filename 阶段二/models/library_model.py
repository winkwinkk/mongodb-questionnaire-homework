"""Logical questions, initial versions and snapshots; edits live in version_model."""
from copy import deepcopy
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from models.database import db
from models.question_model import build_question, append_question_document
from models.survey_model import serialize_question


class LibraryError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def oid(value):
    if not isinstance(value, (str, ObjectId)):
        raise LibraryError("ID 必须是有效的 ObjectId")
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise LibraryError("ID 必须是有效的 ObjectId")


def text(value, field, limit=5000, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise LibraryError(f"{field} 格式不正确")
    return value


def content_from(data):
    if not isinstance(data, dict):
        raise LibraryError("content 必须是对象")
    allowed = {"type", "title", "required", "options", "validation", "unit", "semanticDescription"}
    if set(data) - allowed:
        raise LibraryError("content 含有不支持的字段")
    question = build_question(data.get("type"), data.get("title"), data.get("required", True),
                              data.get("options"), data.get("validation"))
    result = {key: deepcopy(question[key]) for key in
              ("type", "title", "required", "options", "validation") if key in question}
    for key in ("unit", "semanticDescription"):
        result[key] = text(data.get(key, ""), key, 1000)
    return result


def version_content(question):
    return {key: deepcopy(question[key]) for key in
            ("type", "title", "required", "options", "validation", "unit", "semanticDescription")
            if key in question}


def public_version(version):
    return {"id": str(version["_id"]), "questionId": str(version["questionId"]),
            "versionNumber": version["versionNumber"], "content": deepcopy(version["content"]),
            "basedOnVersionId": str(version["basedOnVersionId"]) if version.get("basedOnVersionId") else None,
            "restoredFromVersionId": str(version["restoredFromVersionId"]) if version.get("restoredFromVersionId") else None,
            "copiedFromQuestionId": str(version["copiedFromQuestionId"]) if version.get("copiedFromQuestionId") else None,
            "copiedFromVersionId": str(version["copiedFromVersionId"]) if version.get("copiedFromVersionId") else None,
            "changeNote": version["changeNote"], "createdAt": version["createdAt"].isoformat()}


def public_question(question):
    return {"id": str(question["_id"]), "ownerId": str(question["ownerId"]),
            "title": question["title"], "status": question["status"],
            "currentVersionId": str(question["currentVersionId"]),
            "currentVersionNumber": question["currentVersionNumber"],
            "versionRevision": question.get("versionRevision", 0),
            "createdAt": question["createdAt"].isoformat(), "updatedAt": question["updatedAt"].isoformat()}


def finish_initial(question):
    """Replay the accepted payload; fixed IDs make interrupted creation recoverable."""
    if question["status"] == "creating":
        version = question["pendingVersion"]
        try:
            db.question_versions.update_one({"_id": version["_id"]},
                                            {"$setOnInsert": version}, upsert=True)
        except DuplicateKeyError:
            if db.question_versions.find_one({"_id": version["_id"]}) is None:
                raise
        saved = db.question_versions.find_one({"_id": version["_id"]})
        if not saved or any(saved.get(key) != version.get(key) for key in
                            ("questionId", "versionNumber", "content", "createdBy", "copiedFromQuestionId",
                             "copiedFromVersionId", "basedOnVersionId", "restoredFromVersionId", "changeNote")):
            raise LibraryError("初始版本数据冲突，需要检查数据库", 409)
        db.questions.update_one({"_id": question["_id"], "status": "creating"}, {
            "$set": {"status": "active", "currentVersionId": version["_id"],
                     "currentVersionNumber": 1}, "$unset": {"pendingVersion": ""}})
        question = db.questions.find_one({"_id": question["_id"]})
    version = db.question_versions.find_one({"_id": question.get("initialVersionId", question["currentVersionId"]),
                                           "questionId": question["_id"]})
    if not version:
        raise LibraryError("当前版本不存在，需要检查数据库", 409)
    return {"question": public_question(question), "version": public_version(version)}


def replay_initial(owner_id, operation_id):
    owner = oid(owner_id)
    text(operation_id, "operationId", 128, empty=False)
    if len(operation_id) < 8:
        raise LibraryError("operationId 至少8个字符，建议使用 UUID")
    existing = db.questions.find_one({"ownerId": owner, "operationId": operation_id})
    return finish_initial(existing) if existing else None


def create_initial(owner_id, operation_id, data, name=None, note="", copied_from=None):
    replay = replay_initial(owner_id, operation_id)
    if replay:
        return replay
    owner = oid(owner_id)
    content = content_from(data)
    title = text(content["title"] if name is None else name, "管理名称", 200, empty=False).strip()
    note = text(note, "changeNote")
    qid, vid = ObjectId(), ObjectId()
    now = datetime.now(timezone.utc)
    version = {"_id": vid, "questionId": qid, "versionNumber": 1, "content": content,
               "basedOnVersionId": None, "restoredFromVersionId": None,
               "copiedFromQuestionId": copied_from[0] if copied_from else None,
               "copiedFromVersionId": copied_from[1] if copied_from else None,
               "createdBy": owner, "createdAt": now, "changeNote": note,
               "statisticsGroups": {"version": str(vid)}}
    question = {"_id": qid, "ownerId": owner, "title": title, "status": "creating",
                "operationId": operation_id, "initialVersionId": vid, "versionRevision": 0,
                "versionCounter": 1, "pendingVersion": version,
                "createdAt": now, "updatedAt": now}
    try:
        db.questions.insert_one(question)
    except DuplicateKeyError:
        existing = db.questions.find_one({"ownerId": owner, "operationId": operation_id})
        if existing is None:
            raise
        question = existing
    return finish_initial(question)


def recover_initial_questions():
    for question in db.questions.find({"status": "creating"}):
        finish_initial(question)


def get_version(user_id, question_id, version_id=None):
    user, qid = oid(user_id), oid(question_id)
    question = db.questions.find_one({"_id": qid, "status": "active"})
    # A saved item or a former authorization ID never substitutes for a live grant.
    if question is None or (question["ownerId"] != user and not db.question_shares.find_one({
            "questionId": qid, "ownerId": question["ownerId"], "recipientUserId": user, "status": "active"})):
        raise LibraryError("题目不存在、已归档或无权访问", 404)
    vid = oid(version_id) if version_id is not None else question["currentVersionId"]
    version = db.question_versions.find_one({"_id": vid, "questionId": qid})
    if version is None:
        raise LibraryError("版本不存在或不属于该题目", 404)
    return question, version


def list_owned(user_id):
    return [public_question(q) for q in db.questions.find({"ownerId": oid(user_id), "status": "active"})
            .sort("updatedAt", -1)]


def copy_question(user_id, question_id, version_id, body):
    replay = replay_initial(user_id, body.get("operationId"))
    if replay:
        return replay
    question, version = get_version(user_id, question_id, version_id)
    data = body.get("content", version["content"])
    return create_initial(user_id, body["operationId"], data, body.get("title"),
                          body.get("changeNote", ""), (question["_id"], version["_id"]))


def save_survey_question(user_id, survey_id, instance_id, body):
    replay = replay_initial(user_id, body.get("operationId"))
    if replay:
        return replay
    survey = db.surveys.find_one({"_id": oid(survey_id), "ownerId": oid(user_id)})
    if survey is None:
        raise LibraryError("问卷不存在或无权访问", 404)
    qid = oid(instance_id)
    instance = next((q for q in survey["questions"] if q["_id"] == qid), None)
    if instance is None:
        raise LibraryError("问卷题目不存在", 404)
    copied = ((instance["sourceQuestionId"], instance["sourceVersionId"])
              if instance.get("sourceQuestionId") and instance.get("sourceVersionId") else None)
    return create_initial(user_id, body["operationId"], version_content(instance),
                          body.get("title"), body.get("changeNote", ""), copied)


def import_snapshot(user_id, survey_id, question_id, version_id, required=None):
    question, version = get_version(user_id, question_id, version_id)
    snapshot = snapshot_from(question, version, required)
    return serialize_question(append_question_document(oid(survey_id), oid(user_id), snapshot), include_rules=True)


def snapshot_from(question, version, required=None):
    snapshot = build_question(**{"question_type": version["content"]["type"],
                                "title": version["content"]["title"],
                                "required": version["content"]["required"],
                                "options": deepcopy(version["content"].get("options")),
                                "validation": deepcopy(version["content"].get("validation"))})
    if required is not None:
        if not isinstance(required, bool):
            raise LibraryError("required 必须是布尔值")
        snapshot["required"] = required
    snapshot.update({"sourceQuestionId": question["_id"], "sourceVersionId": version["_id"],
                     "unit": version["content"].get("unit", ""),
                     "semanticDescription": version["content"].get("semanticDescription", "")})
    return snapshot


def switch_snapshot(user_id, survey_id, instance_id, version_id):
    query = {"_id": oid(survey_id), "ownerId": oid(user_id), "status": "draft"}
    survey = db.surveys.find_one(query)
    if survey is None:
        raise LibraryError("问卷不存在、无权修改或已发布", 404)
    iid = oid(instance_id)
    old = next((q for q in survey["questions"] if q["_id"] == iid), None)
    if old is None or not old.get("sourceQuestionId"):
        raise LibraryError("题目不存在或没有题库来源", 404)
    question, version = get_version(user_id, old["sourceQuestionId"], oid(version_id))
    changed = snapshot_from(question, version, old["required"])
    if old.get("jumpRules") and (changed["type"] != old["type"] or changed.get("options") != old.get("options")):
        raise LibraryError("版本题型或选项与已有跳转规则冲突，请先处理规则", 409)
    changed.update({"_id": iid, "order": old["order"], "jumpRules": deepcopy(old.get("jumpRules", []))})
    query["questions"] = survey["questions"]
    result = db.surveys.update_one(query, {"$set": {
        "questions": [changed if q["_id"] == iid else q for q in survey["questions"]],
        "updatedAt": datetime.now(timezone.utc)}})
    if not result.matched_count:
        raise LibraryError("问卷配置已变化，请刷新后重试", 409)
    return serialize_question(changed, include_rules=True)
