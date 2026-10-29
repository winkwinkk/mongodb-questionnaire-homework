"""Batch-4 real MongoDB API, privacy and uniqueness tests on disposable databases."""
import copy
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

from bson import ObjectId
from pymongo.errors import DuplicateKeyError, WriteError

from models.library_schema import initialize_library


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置 RUN_MONGO_TESTS=1 启用真实共享题库测试")
class SharingBankTests(unittest.TestCase):
    def setUp(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.setUp(self)
        self.owner, self.recipient, self.stranger = ObjectId(), ObjectId(), ObjectId()
        for uid, name in ((self.owner, "owner"), (self.recipient, "recipient"), (self.stranger, "stranger")):
            self.db.users.insert_one({"_id": uid, "username": name, "passwordHash": "fixture-only",
                                      "createdAt": datetime.now(timezone.utc)})
        self.as_user(self.owner)
        self.content = {"type": "number", "title": "年龄", "unit": "岁",
                        "validation": {"min": 0, "max": 120}}
        response = self.browser.post("/api/questions", json={"operationId": "sharing-question", "content": self.content})
        self.assertEqual(response.status_code, 201)
        self.question = response.get_json()
        self.qid = self.question["question"]["id"]
        self.vid = self.question["version"]["id"]
        self.qbase = "/api/questions/" + self.qid

    def initialize(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.initialize(self)

    def drop_test_database(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.drop_test_database(self)

    def as_user(self, uid):
        with self.browser.session_transaction() as session:
            session["user_id"] = str(uid)

    def grant(self):
        self.as_user(self.owner)
        response = self.browser.post(self.qbase + "/shares", json={"recipientUserId": str(self.recipient)})
        self.assertIn(response.status_code, (200, 201), response.get_json())
        self.assertEqual(response.get_json()["share"]["recipientUsername"], "recipient")
        return response.get_json()["share"]

    def revoke(self, share):
        self.as_user(self.owner)
        response = self.browser.delete(self.qbase + "/shares/" + share["id"])
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["share"]

    def bank(self, name="常用题"):
        response = self.browser.post("/api/question-banks", json={"name": name})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["bank"]

    def path(self, bank):
        return "/api/question-banks/" + bank["id"]

    def add(self, bank, version=None):
        response = self.browser.post(self.path(bank) + "/items", json={
            "questionId": self.qid, "defaultVersionId": version or self.vid})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["item"]

    def survey(self):
        response = self.browser.post("/api/surveys", json={"title": "我的问卷"})
        self.assertEqual(response.status_code, 201)
        return response.get_json()["survey"]["id"]

    def next_version(self):
        self.as_user(self.owner)
        response = self.browser.post(self.qbase + "/versions", json={
            "operationId": "next-shared-version", "basedOnVersionId": self.vid, "expectedRevision": 0,
            "content": {**self.content, "title": "周岁年龄"}})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["version"]["id"]

    def test_grant_by_username_and_validate_recipient(self):
        response = self.browser.post(self.qbase + "/shares", json={"recipientUsername": "recipient"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["share"]["recipientUserId"], str(self.recipient))
        for body, expected in (({}, 400), ({"recipientUserId": str(self.owner)}, 400),
                               ({"recipientUserId": str(ObjectId())}, 404),
                               ({"recipientUsername": "missing"}, 404),
                               ({"recipientUserId": [], "recipientUsername": "recipient"}, 400),
                               ({"recipientUserId": None}, 400)):
            self.assertEqual(self.browser.post(self.qbase + "/shares", json=body).status_code, expected)

    def test_recipient_reads_uses_but_cannot_manage_original(self):
        self.grant()
        self.as_user(self.recipient)
        self.assertEqual(self.browser.get(self.qbase).status_code, 200)
        self.assertEqual(self.browser.get(self.qbase + "/versions/" + self.vid).status_code, 200)
        self.assertEqual(self.browser.post(self.qbase + "/shares", json={"recipientUserId": str(self.stranger)}).status_code, 404)
        self.assertEqual(self.browser.get(self.qbase + "/shares").status_code, 404)
        self.assertEqual(self.browser.post(self.qbase + "/versions", json={}).status_code, 404)
        bank = self.bank()
        item = self.add(bank)
        result = self.browser.post(self.path(bank) + "/items/" + item["id"] + "/select", json={"surveyId": self.survey()})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.get_json()["question"]["sourceVersionId"], self.vid)

    def test_revoke_and_regrant_keep_history_and_old_id_cannot_revoke_new(self):
        first = self.grant()
        revoked = self.revoke(first)
        self.assertEqual(revoked["status"], "revoked")
        self.assertIsNotNone(revoked["revokedAt"])
        second = self.grant()
        self.assertNotEqual(first["id"], second["id"])
        self.revoke(first)
        self.assertEqual(self.db.question_shares.count_documents({"status": "active"}), 1)
        history = self.browser.get(self.qbase + "/shares").get_json()["shares"]
        self.assertEqual(len(history), 2)
        self.assertEqual(len(self.browser.get(self.qbase + "/shares?status=revoked").get_json()["shares"]), 1)

    def test_concurrent_grants_have_only_one_active_record(self):
        barrier = Barrier(6)
        def grant(_):
            with self.app.test_client() as client:
                with client.session_transaction() as session:
                    session["user_id"] = str(self.owner)
                barrier.wait()
                response = client.post(self.qbase + "/shares", json={"recipientUserId": str(self.recipient)})
                return response.status_code, response.get_json()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(grant, range(6)))
        self.assertTrue(all(code in (200, 201) for code, _ in results), results)
        self.assertEqual(len({data["share"]["id"] for _, data in results}), 1)
        self.assertEqual(self.db.question_shares.count_documents({"status": "active"}), 1)

    def test_revoke_blocks_stale_item_and_direct_paths_without_breaking_snapshot(self):
        share = self.grant()
        self.as_user(self.recipient)
        bank, survey = self.bank(), self.survey()
        item = self.add(bank)
        path = self.path(bank) + "/items/" + item["id"]
        response = self.browser.post(path + "/select", json={"surveyId": survey})
        snapshot = response.get_json()["question"]
        before = self.db.surveys.find_one({"_id": ObjectId(survey)})
        self.revoke(share)
        # Later changes to the owner's management name must not leak through the retained entry.
        self.db.questions.update_one({"_id": ObjectId(self.qid)}, {"$set": {"title": "撤销后私有名称"}})
        self.as_user(self.recipient)
        self.assertEqual(self.browser.get(self.qbase).status_code, 404)
        entry = self.browser.get(self.path(bank) + "/items").get_json()["items"][0]
        self.assertFalse(entry["canUse"])
        self.assertEqual(entry["displayTitleSnapshot"], "年龄")
        self.assertNotIn("content", entry)
        self.assertEqual(self.browser.post(path + "/select", json={"surveyId": survey, "shareId": share["id"]}).status_code, 404)
        self.assertEqual(self.browser.put(path, json={"defaultVersionId": self.vid, "expectedRevision": 0}).status_code, 404)
        self.assertEqual(self.browser.post(self.path(bank) + "/items", json={"questionId": self.qid, "defaultVersionId": self.vid}).status_code, 404)
        self.assertEqual(self.browser.post("/api/surveys/" + survey + "/questions/from-library", json={
            "questionId": self.qid, "versionId": self.vid, "shareId": share["id"]}).status_code, 404)
        self.assertEqual(self.browser.post(self.qbase + "/copies", json={"operationId": "revoked-copy-operation", "versionId": self.vid}).status_code, 404)
        self.assertEqual(self.db.surveys.find_one({"_id": ObjectId(survey)}), before)
        self.browser.post("/api/surveys/" + survey + "/publish")
        submit = self.browser.post("/api/surveys/" + survey + "/responses", json={"answers": {snapshot["id"]: 20}})
        self.assertEqual(submit.status_code, 201, submit.get_json())

    def test_regrant_restores_existing_item_with_same_identity(self):
        share = self.grant()
        self.as_user(self.recipient)
        bank = self.bank()
        item = self.add(bank)
        self.revoke(share)
        new_share = self.grant()
        self.as_user(self.recipient)
        entry = self.browser.get(self.path(bank) + "/items").get_json()["items"][0]
        self.assertEqual(entry["id"], item["id"])
        self.assertTrue(entry["canUse"])
        self.assertNotEqual(share["id"], new_share["id"])
        self.assertEqual(self.browser.post(self.path(bank) + "/items/" + item["id"] + "/select", json={"surveyId": self.survey()}).status_code, 201)

    def test_received_list_is_recipient_only_and_excludes_revoked(self):
        share = self.grant()
        self.as_user(self.recipient)
        response = self.browser.get("/api/shared-questions")
        self.assertEqual(len(response.get_json()["shares"]), 1)
        self.assertNotIn("password", response.get_data(as_text=True))
        self.as_user(self.stranger)
        self.assertEqual(self.browser.get("/api/shared-questions").get_json()["shares"], [])
        self.revoke(share)
        self.as_user(self.recipient)
        self.assertEqual(self.browser.get("/api/shared-questions").get_json()["shares"], [])

    def test_wrong_question_and_stranger_cannot_revoke(self):
        share = self.grant()
        self.as_user(self.stranger)
        self.assertEqual(self.browser.delete(self.qbase + "/shares/" + share["id"]).status_code, 404)
        self.as_user(self.owner)
        other = self.browser.post("/api/questions", json={"operationId": "other-question", "content": self.content}).get_json()
        self.assertEqual(self.browser.delete("/api/questions/" + other["question"]["id"] + "/shares/" + share["id"]).status_code, 404)
        self.assertEqual(self.db.question_shares.count_documents({"status": "active"}), 1)

    def test_multiple_banks_and_owner_isolation(self):
        first, second = self.bank(), self.bank()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.browser.get("/api/question-banks").get_json()["banks"]), 2)
        self.as_user(self.recipient)
        self.assertEqual(self.browser.get("/api/question-banks").get_json()["banks"], [])
        for method in (self.browser.get, self.browser.delete):
            self.assertEqual(method(self.path(first)).status_code, 404)
        self.assertEqual(self.browser.patch(self.path(first), json={"name": "越权修改", "expectedRevision": 0}).status_code, 404)
        self.assertEqual(self.browser.patch(self.path(first)).status_code, 400)
        self.assertEqual(self.browser.post(self.path(first) + "/items", json={}).status_code, 404)
        self.assertEqual(self.browser.get(self.path(first) + "/items").status_code, 404)

    def test_bank_update_uses_revision_and_delete_is_non_cascading(self):
        bank = self.bank()
        item = self.add(bank)
        response = self.browser.patch(self.path(bank), json={"name": "重命名", "expectedRevision": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["bank"]["revision"], 1)
        self.assertEqual(self.browser.patch(self.path(bank), json={"name": "旧请求", "expectedRevision": 0}).status_code, 409)
        self.assertEqual(self.browser.delete(self.path(bank)).status_code, 200)
        self.assertEqual(self.browser.delete(self.path(bank)).status_code, 200)
        self.assertEqual(self.browser.get(self.path(bank)).status_code, 404)
        self.assertEqual(self.browser.get(self.path(bank) + "/items").status_code, 404)
        self.assertEqual(self.browser.post(self.path(bank) + "/items/" + item["id"] + "/select", json={"surveyId": self.survey()}).status_code, 404)
        self.assertEqual(self.db.questions.count_documents({}), 1)
        self.assertEqual(self.db.question_versions.count_documents({}), 1)
        self.assertEqual(self.db.question_bank_items.count_documents({}), 1)

    def test_same_question_in_multiple_banks_uses_independent_defaults(self):
        first, second = self.bank("A"), self.bank("B")
        one = self.add(first)
        v2 = self.next_version()
        two = self.add(second, v2)
        self.assertEqual(one["defaultVersionId"], self.vid)
        self.assertEqual(two["defaultVersionId"], v2)
        self.assertEqual(self.browser.post(self.path(first) + "/items", json={"questionId": self.qid, "defaultVersionId": v2}).status_code, 409)

    def test_concurrent_item_additions_are_unique(self):
        bank = self.bank()
        barrier = Barrier(6)
        def add(_):
            with self.app.test_client() as client:
                with client.session_transaction() as session:
                    session["user_id"] = str(self.owner)
                barrier.wait()
                response = client.post(self.path(bank) + "/items", json={"questionId": self.qid, "defaultVersionId": self.vid})
                return response.status_code
        with ThreadPoolExecutor(max_workers=6) as pool:
            statuses = list(pool.map(add, range(6)))
        self.assertEqual(statuses.count(201), 1, statuses)
        self.assertEqual(statuses.count(409), 5, statuses)
        self.assertEqual(self.db.question_bank_items.count_documents({}), 1)

    def test_default_update_only_affects_future_snapshots_and_detects_stale_edit(self):
        bank = self.bank()
        item, survey = self.add(bank), self.survey()
        path = self.path(bank) + "/items/" + item["id"]
        old = self.browser.post(path + "/select", json={"surveyId": survey}).get_json()["question"]
        v2 = self.next_version()
        response = self.browser.put(path, json={"defaultVersionId": v2, "expectedRevision": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.browser.put(path, json={"defaultVersionId": self.vid, "expectedRevision": 0}).status_code, 409)
        new = self.browser.post(path + "/select", json={"surveyId": survey}).get_json()["question"]
        self.assertNotEqual(old["id"], new["id"])
        self.assertEqual([q["sourceVersionId"] for q in self.db.surveys.find_one({})["questions"]],
                         [ObjectId(self.vid), ObjectId(v2)])

    def test_default_version_belongs_to_question_and_select_cannot_override_it(self):
        bank, survey = self.bank(), self.survey()
        item = self.add(bank)
        path = self.path(bank) + "/items/" + item["id"]
        other = self.browser.post("/api/questions", json={"operationId": "other-question", "content": self.content}).get_json()
        self.assertEqual(self.browser.put(path, json={"defaultVersionId": other["version"]["id"], "expectedRevision": 0}).status_code, 404)
        response = self.browser.post(path + "/select", json={"surveyId": survey, "versionId": other["version"]["id"]})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["question"]["sourceVersionId"], self.vid)

    def test_entry_removal_after_revocation_keeps_question_and_snapshot(self):
        share = self.grant()
        self.as_user(self.recipient)
        bank, survey = self.bank(), self.survey()
        item = self.add(bank)
        path = self.path(bank) + "/items/" + item["id"]
        self.browser.post(path + "/select", json={"surveyId": survey})
        self.revoke(share)
        self.as_user(self.recipient)
        self.assertEqual(self.browser.delete(path).status_code, 200)
        self.assertEqual(self.browser.delete(path).status_code, 200)
        self.assertEqual(self.db.question_bank_items.count_documents({}), 0)
        self.assertEqual(len(self.db.surveys.find_one({})["questions"]), 1)
        self.assertEqual(self.db.question_versions.count_documents({}), 1)

    def test_existing_independent_copy_survives_revoke(self):
        share = self.grant()
        self.as_user(self.recipient)
        response = self.browser.post(self.qbase + "/copies", json={"operationId": "shared-independent-copy", "versionId": self.vid})
        self.assertEqual(response.status_code, 201)
        copied = response.get_json()["question"]["id"]
        self.revoke(share)
        self.as_user(self.recipient)
        self.assertEqual(self.browser.get("/api/questions/" + copied).status_code, 200)
        self.assertEqual(self.browser.get(self.qbase).status_code, 404)

    def test_pagination_and_input_errors(self):
        self.bank("A")
        self.bank("B")
        self.bank("C")
        page = self.browser.get("/api/question-banks?limit=2").get_json()
        self.assertTrue(page["hasMore"])
        rest = self.browser.get("/api/question-banks", query_string={"limit": 2, "before": page["nextBefore"]}).get_json()
        self.assertEqual(len(rest["banks"]), 1)
        for query in ("limit=0", "limit=101", "limit=x", "before=bad"):
            self.assertEqual(self.browser.get("/api/question-banks?" + query).status_code, 400)
        for payload in ([], {}, {"name": " "}, {"name": True}, {"name": "A", "description": []}):
            self.assertEqual(self.browser.post("/api/question-banks", json=payload).status_code, 400)
        bank = self.bank()
        self.assertEqual(self.browser.patch(self.path(bank), json={"name": "A", "expectedRevision": True}).status_code, 400)

    def test_archive_blocks_new_grants_and_item_use_without_deleting_entries(self):
        self.grant()
        self.as_user(self.recipient)
        bank = self.bank()
        item = self.add(bank)
        self.db.questions.update_one({"_id": ObjectId(self.qid)}, {"$set": {"status": "archived"}})
        self.assertFalse(self.browser.get(self.path(bank) + "/items").get_json()["items"][0]["canUse"])
        self.assertEqual(self.browser.post(self.path(bank) + "/items/" + item["id"] + "/select", json={"surveyId": self.survey()}).status_code, 404)
        self.as_user(self.owner)
        self.assertEqual(self.browser.post(self.qbase + "/shares", json={"recipientUserId": str(self.stranger)}).status_code, 404)

    def test_bad_default_stays_unavailable_after_reauthorization(self):
        share = self.grant()
        self.as_user(self.recipient)
        bank = self.bank()
        item = self.add(bank)
        self.revoke(share)
        self.db.question_bank_items.update_one({"_id": ObjectId(item["id"])}, {"$set": {"defaultVersionId": ObjectId()}})
        self.grant()
        self.as_user(self.recipient)
        entry = self.browser.get(self.path(bank) + "/items").get_json()["items"][0]
        self.assertFalse(entry["canUse"])
        self.assertEqual(self.browser.post(self.path(bank) + "/items/" + item["id"] + "/select", json={"surveyId": self.survey()}).status_code, 404)

    def test_schema_partial_unique_and_repeat_initialization(self):
        first = self.grant()
        self.revoke(first)
        second = self.grant()
        initialize_library(self.db)
        self.assertEqual(self.db.question_shares.count_documents({}), 2)
        index = self.db.question_shares.index_information()["unique_active_question_share"]
        self.assertTrue(index["unique"])
        self.assertEqual(index["partialFilterExpression"], {"status": "active"})
        duplicate = self.db.question_shares.find_one({"_id": ObjectId(second["id"])})
        duplicate["_id"] = ObjectId()
        with self.assertRaises(DuplicateKeyError):
            self.db.question_shares.insert_one(duplicate)
        duplicate.update({"status": "revoked", "revokedAt": datetime.now(timezone.utc)})
        self.db.question_shares.insert_one(duplicate)
        broken = copy.deepcopy(duplicate)
        broken["_id"] = ObjectId()
        broken["revokedAt"] = None
        with self.assertRaises(WriteError):
            self.db.question_shares.insert_one(broken)

    def test_bank_items_are_private_and_do_not_grant_survey_statistics(self):
        self.grant()
        owner_bank = self.bank()
        owner_item = self.add(owner_bank)
        owner_survey = self.survey()
        self.as_user(self.recipient)
        self.assertEqual(self.browser.get(self.path(owner_bank) + "/items").status_code, 404)
        self.assertEqual(self.browser.delete(self.path(owner_bank) + "/items/" + owner_item["id"]).status_code, 404)
        self.assertEqual(self.browser.get("/api/surveys/" + owner_survey + "/statistics").status_code, 404)
        self.assertEqual(self.browser.get("/api/surveys/" + owner_survey + "/manage").status_code, 404)

    def test_logged_out_cannot_access_new_endpoints(self):
        bank = self.bank()
        self.browser.post("/api/logout")
        for path in ("/api/question-banks", self.path(bank), "/api/shared-questions", self.qbase + "/shares"):
            self.assertEqual(self.browser.get(path).status_code, 401)
        self.assertEqual(self.browser.post(self.qbase + "/shares", json={}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
