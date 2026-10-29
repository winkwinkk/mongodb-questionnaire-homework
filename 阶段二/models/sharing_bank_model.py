"""Owner-only sharing and private banks; every new use rechecks authorization."""
from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from models.database import db
from models import library_model as library
from models.library_model import LibraryError, oid, text


def owner_question(user_id, question_id, active=False):
    query = {"_id": oid(question_id), "ownerId": oid(user_id)}
    if active:
        query["status"] = "active"
    question = db.questions.find_one(query)
    if question is None or question["status"] not in ("active", "archived"):
        raise LibraryError("题目不存在、状态不允许或无权管理", 404)
    return question


def share_json(share):
    # Authorized share records need a recognizable recipient name in the UI.
    recipient = db.users.find_one({"_id": share["recipientUserId"]}, {"username": 1})
    return {"id": str(share["_id"]), "questionId": str(share["questionId"]),
            "ownerId": str(share["ownerId"]), "recipientUserId": str(share["recipientUserId"]),
            "recipientUsername": recipient["username"] if recipient else None,
            "status": share["status"], "createdAt": share["createdAt"].isoformat(),
            "revokedAt": share["revokedAt"].isoformat() if share.get("revokedAt") else None}


def grant(user_id, question_id, data):
    question = owner_question(user_id, question_id, active=True)
    if ("recipientUserId" in data) == ("recipientUsername" in data):
        raise LibraryError("recipientUserId 与 recipientUsername 必须且只能提供一个")
    if "recipientUserId" in data:
        recipient = db.users.find_one({"_id": oid(data["recipientUserId"])}, {"_id": 1})
    else:
        name = text(data["recipientUsername"], "recipientUsername", 30, empty=False).strip()
        recipient = db.users.find_one({"username": name}, {"_id": 1})
    if recipient is None:
        raise LibraryError("接收用户不存在", 404)
    if recipient["_id"] == question["ownerId"]:
        raise LibraryError("无需向自己共享题目")
    key = {"questionId": question["_id"], "recipientUserId": recipient["_id"], "status": "active"}
    existing = db.question_shares.find_one(key)
    if existing:
        return {"share": share_json(existing), "alreadyActive": True}, 200
    share = {**key, "ownerId": question["ownerId"], "createdAt": datetime.now(timezone.utc),
             "revokedAt": None, "displayTitleSnapshot": question["title"]}
    try:
        share["_id"] = db.question_shares.insert_one(share).inserted_id
    except DuplicateKeyError:
        existing = db.question_shares.find_one(key)
        if existing is None:
            raise LibraryError("授权状态已变化，请刷新后重试", 409)
        return {"share": share_json(existing), "alreadyActive": True}, 200
    return {"share": share_json(share), "alreadyActive": False}, 201


def revoke(user_id, question_id, share_id):
    question = owner_question(user_id, question_id)
    key = {"_id": oid(share_id), "questionId": question["_id"], "ownerId": oid(user_id)}
    share = db.question_shares.find_one_and_update({**key, "status": "active"},
        {"$set": {"status": "revoked", "revokedAt": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER)
    if share is None:
        share = db.question_shares.find_one(key)
    if share is None:
        raise LibraryError("授权不存在或不属于该题目", 404)
    return {"share": share_json(share)}


def page_query(query, before, limit):
    if not 1 <= limit <= 100:
        raise LibraryError("limit 必须在1至100之间")
    if before is not None:
        query["_id"] = {"$lt": oid(before)}
    return query


def page_result(rows, key, limit):
    return {key: rows[:limit], "hasMore": len(rows) > limit,
            "nextBefore": rows[limit - 1]["id"] if len(rows) > limit else None}


def share_history(user_id, question_id, status, limit=50, before=None):
    question = owner_question(user_id, question_id)
    query = {"questionId": question["_id"]}
    if status not in (None, "active", "revoked"):
        raise LibraryError("status 只能为 active 或 revoked")
    if status:
        query["status"] = status
    rows = db.question_shares.find(page_query(query, before, limit)).sort("_id", -1).limit(limit + 1)
    return page_result([share_json(row) for row in rows], "shares", limit)


def received(user_id, limit=50, before=None):
    query = page_query({"recipientUserId": oid(user_id), "status": "active"}, before, limit)
    rows = []
    for share in db.question_shares.find(query).sort("_id", -1).limit(limit + 1):
        row = share_json(share)
        row["displayTitleSnapshot"] = share.get("displayTitleSnapshot", "共享题目")
        try:
            question, _ = library.get_version(user_id, share["questionId"])
            row.update({"canUse": True, "question": library.public_question(question)})
        except LibraryError:
            row.update({"canUse": False, "reason": "题目当前不可选用"})
        rows.append(row)
    return page_result(rows, "shares", limit)


def bank_for(user_id, bank_id, deleted=False):
    query = {"_id": oid(bank_id), "ownerId": oid(user_id)}
    if not deleted:
        query["status"] = "active"
    bank = db.question_banks.find_one(query)
    if bank is None:
        raise LibraryError("题库不存在或无权管理", 404)
    return bank


def bank_json(bank):
    return {"id": str(bank["_id"]), "ownerId": str(bank["ownerId"]), "name": bank["name"],
            "description": bank["description"], "status": bank["status"], "revision": bank.get("revision", 0),
            "createdAt": bank["createdAt"].isoformat(), "updatedAt": bank["updatedAt"].isoformat()}


def expected_revision(data):
    value = data.get("expectedRevision")
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 2 ** 63 - 1:
        raise LibraryError("expectedRevision 必须是非负整数")
    return value


def create_bank(user_id, data):
    now = datetime.now(timezone.utc)
    bank = {"ownerId": oid(user_id), "name": text(data.get("name"), "题库名称", 200, empty=False).strip(),
            "description": text(data.get("description", ""), "题库说明"), "status": "active", "revision": 0,
            "createdAt": now, "updatedAt": now}
    bank["_id"] = db.question_banks.insert_one(bank).inserted_id
    return {"bank": bank_json(bank)}


def list_banks(user_id, limit=50, before=None):
    query = page_query({"ownerId": oid(user_id), "status": "active"}, before, limit)
    return page_result([bank_json(bank) for bank in db.question_banks.find(query).sort("_id", -1).limit(limit + 1)], "banks", limit)


def update_bank(user_id, bank_id, data):
    bank = bank_for(user_id, bank_id)
    fields = {}
    if "name" in data:
        fields["name"] = text(data["name"], "题库名称", 200, empty=False).strip()
    if "description" in data:
        fields["description"] = text(data["description"], "题库说明")
    if not fields:
        raise LibraryError("没有可更新的题库字段")
    revision = expected_revision(data)
    updated = db.question_banks.find_one_and_update(
        {"_id": bank["_id"], "ownerId": oid(user_id), "status": "active", "revision": revision},
        {"$set": {**fields, "updatedAt": datetime.now(timezone.utc)}, "$inc": {"revision": 1}},
        return_document=ReturnDocument.AFTER)
    if updated is None:
        raise LibraryError("题库已变化，请刷新后重试", 409)
    return {"bank": bank_json(updated)}


def delete_bank(user_id, bank_id):
    bank = bank_for(user_id, bank_id, deleted=True)
    # One-document soft deletion avoids partially deleting items across collections.
    db.question_banks.update_one({"_id": bank["_id"], "ownerId": oid(user_id), "status": "active"},
        {"$set": {"status": "deleted", "updatedAt": datetime.now(timezone.utc)}, "$inc": {"revision": 1}})
    return {"message": "题库已删除；题目、版本和已有问卷不受影响"}


def item_for(user_id, bank_id, item_id):
    bank = bank_for(user_id, bank_id)
    item = db.question_bank_items.find_one({"_id": oid(item_id), "bankId": bank["_id"]})
    if item is None:
        raise LibraryError("题库条目不存在", 404)
    return bank, item


def item_json(item, user_id):
    row = {"id": str(item["_id"]), "bankId": str(item["bankId"]), "questionId": str(item["questionId"]),
           "defaultVersionId": str(item["defaultVersionId"]), "addedBy": str(item["addedBy"]),
           "addedAt": item["addedAt"].isoformat(), "displayTitleSnapshot": item["displayTitleSnapshot"],
           "revision": item.get("revision", 0)}
    try:
        _, version = library.get_version(user_id, item["questionId"], item["defaultVersionId"])
        row.update({"canUse": True, "defaultVersionNumber": version["versionNumber"]})
    except LibraryError:
        row.update({"canUse": False, "reason": "授权已失效、题目已归档或默认版本不可用"})
    return row


def add_item(user_id, bank_id, data):
    bank = bank_for(user_id, bank_id)
    question, version = library.get_version(user_id, data.get("questionId"), oid(data.get("defaultVersionId")))
    item = {"bankId": bank["_id"], "questionId": question["_id"], "defaultVersionId": version["_id"],
            "addedBy": oid(user_id), "addedAt": datetime.now(timezone.utc),
            "displayTitleSnapshot": question["title"], "revision": 0}
    try:
        item["_id"] = db.question_bank_items.insert_one(item).inserted_id
    except DuplicateKeyError:
        raise LibraryError("同一题目已在当前题库中", 409)
    return {"item": item_json(item, user_id)}


def list_items(user_id, bank_id, limit=50, before=None):
    bank = bank_for(user_id, bank_id)
    query = page_query({"bankId": bank["_id"]}, before, limit)
    return page_result([item_json(item, user_id) for item in
                        db.question_bank_items.find(query).sort("_id", -1).limit(limit + 1)], "items", limit)


def update_item(user_id, bank_id, item_id, data):
    bank, item = item_for(user_id, bank_id, item_id)
    question, version = library.get_version(user_id, item["questionId"], oid(data.get("defaultVersionId")))
    updated = db.question_bank_items.find_one_and_update(
        {"_id": item["_id"], "bankId": bank["_id"], "revision": expected_revision(data)},
        {"$set": {"defaultVersionId": version["_id"], "displayTitleSnapshot": question["title"]},
         "$inc": {"revision": 1}}, return_document=ReturnDocument.AFTER)
    if updated is None:
        raise LibraryError("条目已变化，请刷新后重试", 409)
    return {"item": item_json(updated, user_id)}


def remove_item(user_id, bank_id, item_id):
    bank = bank_for(user_id, bank_id)
    db.question_bank_items.delete_one({"_id": oid(item_id), "bankId": bank["_id"]})
    return {"message": "题库条目已移除；原题和问卷快照保留"}


def select_item(user_id, bank_id, item_id, data):
    _, item = item_for(user_id, bank_id, item_id)
    if "required" in data and not isinstance(data["required"], bool):
        raise LibraryError("required 必须是布尔值")
    result = library.import_snapshot(user_id, oid(data.get("surveyId")), item["questionId"],
                                     item["defaultVersionId"], data.get("required"))
    return {"question": result}
