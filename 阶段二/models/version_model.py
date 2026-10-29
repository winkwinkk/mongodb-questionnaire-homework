"""Recoverable version edits: one bounded pending slot and durable operation receipts.

Only the question's atomic decision updates the current pointer. Version content
is inserted once; receipts record the original outcome even after later edits.
"""
from copy import deepcopy
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from models.database import db
from models.library_model import LibraryError, oid, text, content_from, public_question, public_version


def owned(user_id, question_id):
    question = db.questions.find_one({"_id": oid(question_id), "ownerId": oid(user_id)})
    if question is None or question["status"] not in ("active", "archived"):
        raise LibraryError("题目不存在或无权管理版本", 404)
    return question


def token(value):
    text(value, "operationId", 128, empty=False)
    if len(value) < 8:
        raise LibraryError("operationId 至少8个字符")
    return value


def revision(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 2 ** 63 - 1:
        raise LibraryError("expectedRevision 必须是非负整数")
    return value


def version_for(question_id, version_id):
    version = db.question_versions.find_one({"_id": oid(version_id), "questionId": question_id})
    if version is None:
        raise LibraryError("版本不存在或不属于当前题目", 404)
    return version


def receipt_for(question_id, operation_id):
    return db.question_version_operations.find_one({"questionId": question_id, "operationId": operation_id})


def clear_pending(question_id, receipt):
    db.questions.update_one({"_id": question_id, "pendingVersionOperation._id": receipt["_id"],
                             "pendingVersionOperation.phase": "decided"},
                            {"$unset": {"pendingVersionOperation": ""}})


def operation_result(receipt):
    question = db.questions.find_one({"_id": receipt["questionId"]})
    version = version_for(receipt["questionId"], receipt["versionId"])
    return {"question": public_question(question), "version": public_version(version),
            "operation": {"id": receipt["operationId"], "kind": receipt["kind"],
                          "outcome": receipt["outcome"], "completedAt": receipt["completedAt"].isoformat()},
            "conflict": receipt["outcome"] in ("branch", "conflict"),
            "message": ("基于旧状态的修改已保存为分支，未切换当前版本" if receipt["outcome"] == "branch"
                        else "当前版本已变化，本次选择未生效" if receipt["outcome"] == "conflict"
                        else "版本操作已完成")}


def finish_pending(question_id):
    """Every step can repeat after a lost reply or a process interruption."""
    question = db.questions.find_one({"_id": question_id})
    operation = question.get("pendingVersionOperation") if question else None
    if not operation:
        return None
    op_id = operation["_id"]
    existing = db.question_version_operations.find_one({"_id": op_id})
    if existing:
        clear_pending(question_id, existing)
        return existing
    if operation["phase"] == "prepared":
        if operation["kind"] != "select":
            payload = operation["version"]
            try:
                db.question_versions.update_one({"_id": payload["_id"]}, {"$setOnInsert": payload}, upsert=True)
            except DuplicateKeyError:
                if db.question_versions.find_one({"_id": payload["_id"]}) is None:
                    raise
            saved = version_for(question_id, payload["_id"])
            for key in ("versionNumber", "content", "createdBy", "operationId", "basedOnVersionId",
                        "restoredFromVersionId", "changeNote", "statisticsGroups"):
                if saved.get(key) != payload.get(key):
                    raise LibraryError("版本持久化内容冲突，请检查数据库", 409)
        else:
            version_for(question_id, operation["versionId"])
        now = datetime.now(timezone.utc)
        decision = {"pendingVersionOperation.phase": "decided",
                    "pendingVersionOperation.outcome": "selected" if operation["kind"] == "select" else "adopted",
                    "pendingVersionOperation.completedAt": now,
                    "currentVersionId": operation["versionId"],
                    "currentVersionNumber": operation["versionNumber"], "updatedAt": now}
        guard = {"_id": question_id, "status": "active", "pendingVersionOperation._id": op_id,
                 "pendingVersionOperation.phase": "prepared", "currentVersionId": operation["expectedVersionId"],
                 "$expr": {"$eq": [{"$ifNull": ["$versionRevision", 0]}, operation["expectedRevision"]]}}
        decided = db.questions.find_one_and_update(guard, {"$set": decision, "$inc": {"versionRevision": 1}},
                                                  return_document=ReturnDocument.AFTER)
        if decided is None:
            decided = db.questions.find_one_and_update(
                {"_id": question_id, "pendingVersionOperation._id": op_id,
                 "pendingVersionOperation.phase": "prepared"},
                {"$set": {"pendingVersionOperation.phase": "decided", "pendingVersionOperation.completedAt": now,
                          "pendingVersionOperation.outcome": "conflict" if operation["kind"] == "select" else "branch"}},
                return_document=ReturnDocument.AFTER)
        if decided is None:
            decided = db.questions.find_one({"_id": question_id})
        pending = decided.get("pendingVersionOperation", {})
        if pending.get("_id") != op_id:
            return db.question_version_operations.find_one({"_id": op_id})
        operation = pending
    receipt = {key: operation[key] for key in ("_id", "operationId", "questionId", "actorId", "kind",
                                               "versionId", "versionNumber", "expectedVersionId", "expectedRevision",
                                               "outcome", "createdAt", "completedAt", "changeNote")}
    try:
        db.question_version_operations.update_one({"_id": op_id}, {"$setOnInsert": receipt}, upsert=True)
    except DuplicateKeyError:
        if db.question_version_operations.find_one({"_id": op_id}) is None:
            raise
    saved_receipt = db.question_version_operations.find_one({"_id": op_id})
    if any(saved_receipt.get(key) != receipt.get(key) for key in
           ("questionId", "operationId", "versionId", "kind", "outcome", "actorId")):
        raise LibraryError("操作回执冲突，请检查数据库", 409)
    clear_pending(question_id, saved_receipt)
    return saved_receipt


def submit(user_id, question_id, data, kind="edit", restore_id=None):
    question = owned(user_id, question_id)
    operation_id = token(data.get("operationId"))
    for _ in range(32):
        previous = receipt_for(question["_id"], operation_id)
        if previous:
            if previous["kind"] != kind:
                raise LibraryError("operationId 已用于其他类型的操作", 409)
            clear_pending(question["_id"], previous)
            return operation_result(previous)
        question = owned(user_id, question_id)
        if question.get("pendingVersionOperation"):
            finish_pending(question["_id"])
            continue
        # A receipt may have been committed between the first lookup and this
        # fresh question read. Recheck before reserving with its new sequence.
        if receipt_for(question["_id"], operation_id):
            continue
        if question["status"] != "active":
            raise LibraryError("归档题目不能执行新的版本操作", 409)
        if kind != "select" and question["versionCounter"] >= 2 ** 63 - 1:
            raise LibraryError("版本号已达到数据库整数上限")
        expected_id = oid(data.get("expectedCurrentVersionId") if kind == "select" else data.get("basedOnVersionId"))
        version_for(question["_id"], expected_id)
        expected_revision = revision(data.get("expectedRevision"))
        now = datetime.now(timezone.utc)
        op_id, version_id = ObjectId(), ObjectId()
        operation = {"_id": op_id, "operationId": operation_id, "questionId": question["_id"],
                     "actorId": oid(user_id), "kind": kind, "phase": "prepared", "createdAt": now,
                     "expectedVersionId": expected_id, "expectedRevision": expected_revision,
                     "changeNote": text(data.get("changeNote", ""), "changeNote")}
        if kind == "select":
            target = version_for(question["_id"], data.get("versionId"))
            operation.update({"versionId": target["_id"], "versionNumber": target["versionNumber"]})
            next_counter = {"$ifNull": ["$versionCounter", 1]}
            pending = {"$literal": operation}
        else:
            content = (deepcopy(version_for(question["_id"], restore_id)["content"]) if kind == "restore"
                       else content_from(data.get("content")))
            version = {"_id": version_id, "questionId": question["_id"], "content": content,
                       "basedOnVersionId": expected_id, "restoredFromVersionId": oid(restore_id) if kind == "restore" else None,
                       "copiedFromQuestionId": None, "copiedFromVersionId": None, "createdBy": oid(user_id),
                       "createdAt": now, "changeNote": operation["changeNote"],
                       "operationId": operation_id, "statisticsGroups": {"version": str(version_id)}}
            operation["versionId"] = version_id
            next_counter = {"$add": [{"$ifNull": ["$versionCounter", 1]}, 1]}
            pending = {"$mergeObjects": [{"$literal": operation}, {"versionNumber": next_counter,
                       "version": {"$mergeObjects": [{"$literal": version}, {"versionNumber": next_counter}]}}]}
        reserved = db.questions.find_one_and_update(
            {"_id": question["_id"], "ownerId": oid(user_id), "status": "active",
             "pendingVersionOperation": {"$exists": False},
             "$expr": {"$eq": [{"$ifNull": ["$operationSequence", 0]}, question.get("operationSequence", 0)]}},
            [{"$set": {"versionCounter": next_counter, "pendingVersionOperation": pending,
                       "operationSequence": {"$add": [{"$ifNull": ["$operationSequence", 0]}, 1]}}}],
            return_document=ReturnDocument.AFTER)
        if reserved is not None:
            finish_pending(question["_id"])
            completed = receipt_for(question["_id"], operation_id)
            if completed:
                return operation_result(completed)
    # Continuous competing edits can retry with the same token; no request payload was lost.
    raise LibraryError("题目操作繁忙，请使用相同 operationId 重试", 409)


def retry_operation(user_id, question_id, operation_id):
    question = owned(user_id, question_id)
    operation_id = token(operation_id)
    receipt = receipt_for(question["_id"], operation_id)
    if receipt:
        clear_pending(question["_id"], receipt)
        return operation_result(receipt)
    if question.get("pendingVersionOperation", {}).get("operationId") != operation_id:
        raise LibraryError("操作不存在", 404)
    receipt = finish_pending(question["_id"])
    return operation_result(receipt)


def recover_version_operations():
    for question in db.questions.find({"pendingVersionOperation": {"$exists": True}}):
        finish_pending(question["_id"])


def history(user_id, question_id, limit=50, before=None):
    question = owned(user_id, question_id)
    if not 1 <= limit <= 100:
        raise LibraryError("limit 必须在1至100之间")
    query = {"questionId": question["_id"]}
    if before is not None:
        if before < 1:
            raise LibraryError("before 必须为正整数")
        query["versionNumber"] = {"$lt": before}
    versions = list(db.question_versions.find(query).sort("versionNumber", -1).limit(limit + 1))
    has_more = len(versions) > limit
    items = []
    for version in versions[:limit]:
        receipt = receipt_for(question["_id"], version["operationId"]) if "operationId" in version else None
        item = public_version(version)
        item.update({"isCurrent": version["_id"] == question["currentVersionId"],
                     "creationOutcome": receipt["outcome"] if receipt else "pending" if "operationId" in version else "initial",
                     "operationId": version.get("operationId")})
        items.append(item)
    return {"question": public_question(question), "versions": items, "hasMore": has_more,
            "nextBefore": items[-1]["versionNumber"] if has_more and items else None}


def difference(user_id, question_id, left_id, right_id):
    question = owned(user_id, question_id)
    left, right = (version_for(question["_id"], value) for value in (left_id, right_id))
    a, b = left["content"], right["content"]
    changes = [{"field": key, "fromPresent": key in a, "toPresent": key in b,
                "from": a.get(key), "to": b.get(key)} for key in sorted(set(a) | set(b))
               if a.get(key) != b.get(key) or (key in a) != (key in b)]
    return {"questionId": str(question["_id"]), "fromVersionId": str(left["_id"]),
            "toVersionId": str(right["_id"]), "changes": changes, "equal": not changes}
