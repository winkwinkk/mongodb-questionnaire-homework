"""Batch-3 recovery/concurrency tests on real isolated MongoDB, never a business DB."""
import copy
import os
import unittest
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId
from pymongo.errors import AutoReconnect, DuplicateKeyError

from models import version_model as versions


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置 RUN_MONGO_TESTS=1 启用真实版本测试")
class VersionTests(unittest.TestCase):
    def setUp(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.setUp(self)
        self.user = ObjectId()
        with self.browser.session_transaction() as session:
            session["user_id"] = str(self.user)
        self.content = {"type": "number", "title": "年龄", "unit": "岁",
                        "validation": {"min": 0, "max": 120, "integerOnly": True}}
        response = self.browser.post("/api/questions", json={"operationId": "initial-question", "content": self.content})
        self.assertEqual(response.status_code, 201)
        self.initial = response.get_json()
        self.qid = self.initial["question"]["id"]
        self.v1 = self.initial["version"]["id"]
        self.base = "/api/questions/" + self.qid

    def initialize(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.initialize(self)

    def drop_test_database(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.drop_test_database(self)

    def edit_body(self, operation="edit-operation", title="新年龄", base=None, rev=0):
        return {"operationId": operation, "basedOnVersionId": base or self.v1, "expectedRevision": rev,
                "content": {**self.content, "title": title}, "changeNote": "测试修改"}

    def edit(self, **kwargs):
        response = self.browser.post(self.base + "/versions", json=self.edit_body(**kwargs))
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def current(self):
        return self.db.questions.find_one({"_id": ObjectId(self.qid)})

    def choose_body(self, target, expected, rev, operation="choose-operation"):
        return {"operationId": operation, "versionId": target, "expectedCurrentVersionId": expected,
                "expectedRevision": rev}

    def test_new_version_preserves_old_content_and_records_parent(self):
        before = self.db.question_versions.find_one({"_id": ObjectId(self.v1)})
        result = self.edit()
        self.assertEqual(result["operation"]["outcome"], "adopted")
        self.assertEqual(result["version"]["versionNumber"], 2)
        self.assertEqual(result["version"]["basedOnVersionId"], self.v1)
        self.assertEqual(result["question"]["versionRevision"], 1)
        self.assertEqual(self.db.question_versions.find_one({"_id": ObjectId(self.v1)}), before)
        self.assertNotIn("pendingVersionOperation", self.current())

    def test_stale_base_produces_branch_without_moving_current(self):
        adopted = self.edit()
        branch = self.edit(operation="branch-operation", title="另一个修改")
        self.assertTrue(branch["conflict"])
        self.assertEqual(branch["operation"]["outcome"], "branch")
        self.assertEqual(branch["version"]["versionNumber"], 3)
        self.assertEqual(str(self.current()["currentVersionId"]), adopted["version"]["id"])

    def test_owner_selects_branch_without_creating_another_version(self):
        first, branch = self.edit(), self.edit(operation="branch-operation")
        response = self.browser.put(self.base + "/current-version", json=self.choose_body(
            branch["version"]["id"], first["version"]["id"], 1))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["operation"]["outcome"], "selected")
        self.assertEqual(self.current()["currentVersionNumber"], 3)
        self.assertEqual(self.db.question_versions.count_documents({}), 3)

    def test_selection_conflict_is_persisted_and_replayed(self):
        first = self.edit()
        body = self.choose_body(self.v1, self.v1, 0)
        response = self.browser.put(self.base + "/current-version", json=body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["operation"]["outcome"], "conflict")
        self.assertEqual(self.browser.put(self.base + "/current-version", json=body).status_code, 409)
        self.assertEqual(str(self.current()["currentVersionId"]), first["version"]["id"])

    def test_aba_pointer_change_detected_by_revision(self):
        first = self.edit()
        self.browser.put(self.base + "/current-version", json=self.choose_body(
            self.v1, first["version"]["id"], 1))
        branch = self.edit(operation="stale-aba-request")
        self.assertEqual(branch["operation"]["outcome"], "branch")
        self.assertEqual(self.current()["currentVersionId"], ObjectId(self.v1))
        self.assertEqual(self.current()["versionRevision"], 2)

    def test_restore_creates_new_version_with_two_distinct_sources(self):
        first = self.edit()
        response = self.browser.post(self.base + "/versions/" + self.v1 + "/restore", json={
            "operationId": "restore-operation", "basedOnVersionId": first["version"]["id"],
            "expectedRevision": 1, "changeNote": "恢复旧题"})
        self.assertEqual(response.status_code, 201, response.get_json())
        result = response.get_json()
        self.assertEqual(result["version"]["content"], self.initial["version"]["content"])
        self.assertEqual(result["version"]["versionNumber"], 3)
        self.assertEqual(result["version"]["basedOnVersionId"], first["version"]["id"])
        self.assertEqual(result["version"]["restoredFromVersionId"], self.v1)

    def test_restore_from_stale_base_keeps_branch(self):
        first = self.edit()
        response = self.browser.post(self.base + "/versions/" + self.v1 + "/restore", json={
            "operationId": "stale-restore", "basedOnVersionId": self.v1, "expectedRevision": 0})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["operation"]["outcome"], "branch")
        self.assertEqual(str(self.current()["currentVersionId"]), first["version"]["id"])

    def test_history_diff_and_pagination(self):
        first = self.edit()
        self.edit(operation="branch-operation")
        result = self.browser.get(self.base + "/versions?limit=2").get_json()
        self.assertTrue(result["hasMore"])
        self.assertEqual([v["versionNumber"] for v in result["versions"]], [3, 2])
        self.assertEqual(result["versions"][0]["creationOutcome"], "branch")
        page = self.browser.get(self.base + "/versions?before=2&limit=2").get_json()
        self.assertEqual([v["versionNumber"] for v in page["versions"]], [1])
        diff = self.browser.get(self.base + "/version-diff", query_string={
            "from": self.v1, "to": first["version"]["id"]}).get_json()
        self.assertEqual([change["field"] for change in diff["changes"]], ["title"])

    def test_operation_retries_preserve_first_payload_and_original_outcome(self):
        first = self.edit()
        branch = self.edit(operation="branch-operation", title="首次分支")
        self.browser.put(self.base + "/current-version", json=self.choose_body(
            branch["version"]["id"], first["version"]["id"], 1))
        retry = self.edit(operation="branch-operation", title="重试不能覆盖")
        self.assertEqual(retry["version"]["id"], branch["version"]["id"])
        self.assertEqual(retry["version"]["content"]["title"], "首次分支")
        self.assertEqual(retry["operation"]["outcome"], "branch")
        self.assertEqual(self.db.question_versions.count_documents({}), 3)

    def test_failure_after_reservation_replays_original_payload_and_number(self):
        fault = SimpleNamespace(questions=self.db.questions, question_versions=self.db.question_versions,
                                question_version_operations=self.db.question_version_operations)
        with patch.object(versions, "db", fault), patch.object(fault.question_versions, "update_one", side_effect=AutoReconnect("fault")):
            response = self.browser.post(self.base + "/versions", json=self.edit_body(title="首次接受"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.current()["versionCounter"], 2)
        result = self.edit(title="不应覆盖")
        self.assertEqual(result["version"]["content"]["title"], "首次接受")
        self.assertEqual(result["version"]["versionNumber"], 2)
        self.assertEqual(self.current()["versionCounter"], 2)

    def test_failure_after_version_insert_before_decision_recovers(self):
        fault = SimpleNamespace(questions=self.db.questions, question_versions=self.db.question_versions,
                                question_version_operations=self.db.question_version_operations)
        original = fault.questions.find_one_and_update
        def fail_decision(query, update, **kwargs):
            if isinstance(update, dict):
                raise AutoReconnect("decision fault")
            return original(query, update, **kwargs)
        with patch.object(versions, "db", fault), patch.object(fault.questions, "find_one_and_update", side_effect=fail_decision):
            response = self.browser.post(self.base + "/versions", json=self.edit_body())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.db.question_versions.count_documents({}), 2)
        self.assertEqual(self.current()["currentVersionId"], ObjectId(self.v1))
        versions.recover_version_operations()
        versions.recover_version_operations()
        self.assertEqual(self.current()["currentVersionNumber"], 2)
        self.assertNotIn("pendingVersionOperation", self.current())

    def test_lost_decision_reply_does_not_reapply_or_change_outcome(self):
        fault = SimpleNamespace(questions=self.db.questions, question_versions=self.db.question_versions,
                                question_version_operations=self.db.question_version_operations)
        original = fault.questions.find_one_and_update
        def lose_reply(query, update, **kwargs):
            result = original(query, update, **kwargs)
            if isinstance(update, dict) and result:
                raise AutoReconnect("write committed, reply lost")
            return result
        with patch.object(versions, "db", fault), patch.object(fault.questions, "find_one_and_update", side_effect=lose_reply):
            response = self.browser.post(self.base + "/versions", json=self.edit_body())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.current()["versionRevision"], 1)
        self.assertEqual(self.current()["pendingVersionOperation"]["outcome"], "adopted")
        result = self.edit()
        self.assertEqual(result["operation"]["outcome"], "adopted")
        self.assertEqual(self.current()["versionRevision"], 1)

    def test_receipt_failure_then_later_request_completes_first_operation(self):
        fault = SimpleNamespace(questions=self.db.questions, question_versions=self.db.question_versions,
                                question_version_operations=self.db.question_version_operations)
        with patch.object(versions, "db", fault), patch.object(fault.question_version_operations, "update_one", side_effect=AutoReconnect("receipt fault")):
            response = self.browser.post(self.base + "/versions", json=self.edit_body())
        self.assertEqual(response.status_code, 500)
        second = self.edit(operation="second-operation", base=str(self.current()["currentVersionId"]), rev=1)
        receipt = self.db.question_version_operations.find_one({"operationId": "edit-operation"})
        self.assertEqual(receipt["outcome"], "adopted")
        self.assertEqual(second["version"]["versionNumber"], 3)
        retried = self.edit()
        self.assertEqual(retried["operation"]["outcome"], "adopted")
        self.assertEqual(self.current()["currentVersionId"], ObjectId(second["version"]["id"]))
        self.assertEqual(self.current()["versionRevision"], 2)

    def test_cleanup_failure_retries_do_not_duplicate_receipts(self):
        with patch.object(versions, "clear_pending", side_effect=AutoReconnect("cleanup fault")):
            response = self.browser.post(self.base + "/versions", json=self.edit_body())
        self.assertEqual(response.status_code, 500)
        result = self.browser.post(self.base + "/operations/edit-operation/retry")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.db.question_version_operations.count_documents({}), 1)
        self.assertNotIn("pendingVersionOperation", self.current())

    def test_parallel_edits_have_one_winner_and_unique_numbers(self):
        barrier = Barrier(6)
        def edit(i):
            with self.app.test_client() as client:
                with client.session_transaction() as session:
                    session["user_id"] = str(self.user)
                barrier.wait()
                response = client.post(self.base + "/versions", json=self.edit_body(operation=f"parallel-edit-{i}"))
                return response.status_code, response.get_json()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(edit, range(6)))
        self.assertTrue(all(status == 201 for status, _ in results), results)
        outcomes = [body["operation"]["outcome"] for _, body in results]
        self.assertEqual(outcomes.count("adopted"), 1)
        self.assertEqual(outcomes.count("branch"), 5)
        self.assertEqual(sorted(body["version"]["versionNumber"] for _, body in results), list(range(2, 8)))
        self.assertEqual(self.current()["versionRevision"], 1)

    def test_parallel_same_token_allocates_once(self):
        barrier = Barrier(6)
        def edit(i):
            with self.app.test_client() as client:
                with client.session_transaction() as session:
                    session["user_id"] = str(self.user)
                barrier.wait()
                response = client.post(self.base + "/versions", json=self.edit_body(title=f"首次内容{i}"))
                return response.status_code, response.get_json()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(edit, range(6)))
        self.assertTrue(all(status == 201 for status, _ in results), results)
        self.assertEqual(len({body["version"]["id"] for _, body in results}), 1)
        self.assertEqual(self.current()["versionCounter"], 2)
        self.assertEqual(self.db.question_version_operations.count_documents({}), 1)

    def test_invalid_owner_shared_user_and_cross_question_versions_rejected(self):
        another = self.browser.post("/api/questions", json={"operationId": "another-question", "content": self.content}).get_json()
        self.assertEqual(self.browser.post(self.base + "/versions", json=self.edit_body(base=another["version"]["id"])).status_code, 404)
        stranger = ObjectId()
        self.db.question_shares.insert_one({"questionId": ObjectId(self.qid), "ownerId": self.user,
                                          "recipientUserId": stranger, "status": "active",
                                          "createdAt": datetime.now(timezone.utc), "revokedAt": None})
        with self.browser.session_transaction() as session:
            session["user_id"] = str(stranger)
        self.assertEqual(self.browser.post(self.base + "/versions", json=self.edit_body()).status_code, 404)
        self.assertEqual(self.browser.get(self.base + "/versions").status_code, 404)
        self.assertEqual(self.browser.post(self.base + "/operations/edit-operation/retry").status_code, 404)

    def test_archive_during_accepted_operation_preserves_history_without_adoption(self):
        fault = SimpleNamespace(questions=self.db.questions, question_versions=self.db.question_versions,
                                question_version_operations=self.db.question_version_operations)
        with patch.object(versions, "db", fault), patch.object(fault.question_versions, "update_one", side_effect=AutoReconnect("fault")):
            self.browser.post(self.base + "/versions", json=self.edit_body())
        self.db.questions.update_one({"_id": ObjectId(self.qid)}, {"$set": {"status": "archived"}})
        versions.recover_version_operations()
        self.assertEqual(self.current()["currentVersionId"], ObjectId(self.v1))
        self.assertEqual(self.db.question_version_operations.find_one({})["outcome"], "branch")
        self.assertEqual(self.browser.get(self.base + "/versions").status_code, 200)
        self.assertEqual(self.browser.post(self.base + "/versions", json=self.edit_body(operation="new-archived-op")).status_code, 409)

    def test_snapshots_stay_fixed_and_initial_creation_retry_stays_v1(self):
        survey = self.browser.post("/api/surveys", json={"title": "旧问卷"}).get_json()["survey"]
        base = "/api/surveys/" + survey["id"]
        self.browser.post(base + "/questions/from-library", json={"questionId": self.qid, "versionId": self.v1})
        self.browser.post(base + "/publish")
        before = self.db.surveys.find_one({})
        self.edit()
        self.assertEqual(self.db.surveys.find_one({}), before)
        replay = self.browser.post("/api/questions", json={"operationId": "initial-question"}).get_json()
        self.assertEqual(replay["version"]["id"], self.v1)

    def test_bad_inputs_and_operation_kind_reuse(self):
        for value in (True, -1, None, "0"):
            self.assertEqual(self.browser.post(self.base + "/versions", json={**self.edit_body(), "expectedRevision": value}).status_code, 400)
        self.assertEqual(self.browser.get(self.base + "/versions?limit=0").status_code, 400)
        self.assertEqual(self.browser.get(self.base + "/versions?before=x").status_code, 400)
        self.edit()
        response = self.browser.put(self.base + "/current-version", json=self.choose_body(self.v1, self.v1, 0, "edit-operation"))
        self.assertEqual(response.status_code, 409)
        duplicate = copy.deepcopy(self.db.question_versions.find_one({"versionNumber": 2}))
        duplicate["_id"] = ObjectId()
        with self.assertRaises(DuplicateKeyError):
            self.db.question_versions.insert_one(duplicate)

    def test_receipt_committed_between_lookup_and_reservation_is_not_duplicated(self):
        original = versions.receipt_for
        triggered = False
        def delayed_lookup(question_id, operation_id):
            nonlocal triggered
            result = original(question_id, operation_id)
            if not triggered:
                triggered = True
                versions.submit(self.user, self.qid, self.edit_body())
                return None
            return result
        with patch.object(versions, "receipt_for", side_effect=delayed_lookup):
            result = self.edit()
        self.assertEqual(result["version"]["versionNumber"], 2)
        self.assertEqual(self.current()["versionCounter"], 2)
        self.assertEqual(self.db.question_version_operations.count_documents({}), 1)

    def test_selected_version_retry_after_later_edit_does_not_switch_back(self):
        first = self.edit()
        body = self.choose_body(self.v1, first["version"]["id"], 1)
        fault = SimpleNamespace(questions=self.db.questions, question_versions=self.db.question_versions,
                                question_version_operations=self.db.question_version_operations)
        with patch.object(versions, "db", fault), patch.object(fault.question_version_operations, "update_one", side_effect=AutoReconnect("receipt fault")):
            response = self.browser.put(self.base + "/current-version", json=body)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.current()["currentVersionId"], ObjectId(self.v1))
        newer = self.edit(operation="later-edit-operation", base=self.v1, rev=2)
        retry = self.browser.put(self.base + "/current-version", json=body)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.get_json()["operation"]["outcome"], "selected")
        self.assertEqual(self.current()["currentVersionId"], ObjectId(newer["version"]["id"]))
        self.assertEqual(self.current()["versionRevision"], 3)


if __name__ == "__main__":
    unittest.main()
