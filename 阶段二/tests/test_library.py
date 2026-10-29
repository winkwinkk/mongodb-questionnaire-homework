"""API/model tests with a limited in-memory double and optional real MongoDB.

The double checks application behavior, not MongoDB validators or concurrency.
The identical scenarios run against real random test databases when enabled.
"""
import copy
import os
import threading
import unittest
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId
from pymongo.errors import AutoReconnect, DuplicateKeyError, WriteError

from app import create_app
from models import library_model as library
from models.library_schema import initialize_library


class Cursor(list):
    def sort(self, key, direction):
        return Cursor(sorted(self, key=lambda item: item[key], reverse=direction < 0))


class Collection:
    def __init__(self):
        self.items = []
        self.unique = [[("_id", 1)]]
        self.lock = threading.RLock()

    def create_index(self, keys, **kwargs):
        if kwargs.get("unique") and keys not in self.unique:
            self.unique.append(keys)

    def find_one(self, query, *args):
        return next(iter(self.find(query)), None)

    def find(self, query=None):
        return Cursor(copy.deepcopy([item for item in self.items
                                    if all(item.get(key) == value for key, value in (query or {}).items())]))

    def insert_one(self, item):
        with self.lock:
            item.setdefault("_id", ObjectId())
            for keys in self.unique:
                if any(all(old.get(key) == item.get(key) for key, _ in keys) for old in self.items):
                    raise DuplicateKeyError("test duplicate")
            self.items.append(copy.deepcopy(item))
            return SimpleNamespace(inserted_id=item["_id"])

    def update_one(self, query, update, upsert=False):
        with self.lock:
            old = self.find_one(query)
            if old is None:
                if upsert:
                    self.insert_one({**query, **copy.deepcopy(update.get("$setOnInsert", {}))})
                return SimpleNamespace(matched_count=0, modified_count=0)
            for item in self.items:
                if item["_id"] == old["_id"]:
                    item.update(copy.deepcopy(update.get("$set", {})))
                    for key in update.get("$unset", {}):
                        item.pop(key, None)
                    return SimpleNamespace(matched_count=1, modified_count=1)

    def find_one_and_update(self, query, pipeline, **kwargs):
        with self.lock:
            item = self.find_one(query)
            if item is None:
                return None
            q = copy.deepcopy(pipeline[0]["$set"]["questions"]["$concatArrays"][1][0]["$mergeObjects"][0]["$literal"])
            q["order"] = len(item["questions"]) + 1
            item["questions"].append(q)
            self.update_one(query, {"$set": {"questions": item["questions"]}})
            return item

    def count_documents(self, query):
        return len(self.find(query))


class Database:
    def __getattr__(self, key):
        value = Collection()
        setattr(self, key, value)
        return value


class LibraryCases:
    def prepare(self):
        self.user = ObjectId()
        with self.browser.session_transaction() as session:
            session["user_id"] = str(self.user)

    def content(self, title="年龄"):
        return {"type": "number", "title": title, "required": True,
                "validation": {"min": 0, "max": 120, "integerOnly": True}, "unit": "岁"}

    def create(self, operation="operation-0001", content=None):
        response = self.browser.post("/api/questions", json={"operationId": operation,
                                                            "content": content or self.content()})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def survey(self):
        response = self.browser.post("/api/surveys", json={"title": "快照测试"})
        self.assertEqual(response.status_code, 201)
        return "/api/surveys/" + response.get_json()["survey"]["id"]

    def select(self, base, item, **fields):
        return self.browser.post(base + "/questions/from-library", json={
            "questionId": item["question"]["id"], "versionId": item["version"]["id"], **fields})

    def test_create_immutable_content_and_management_read(self):
        item = self.create()
        self.assertEqual(item["version"]["versionNumber"], 1)
        self.assertNotIn("_id", item["version"]["content"])
        self.assertNotIn("order", item["version"]["content"])
        self.assertNotIn("jumpRules", item["version"]["content"])
        self.assertEqual(self.browser.get("/api/questions").get_json()["count"], 1)
        self.assertEqual(self.browser.get("/api/questions/" + item["question"]["id"]).status_code, 200)
        self.assertEqual(self.browser.put("/api/questions/" + item["question"]["id"], json={}).status_code, 405)

    def test_repeated_operation_replays_first_content(self):
        first = self.create()
        second = self.create(content=self.content("不应覆盖"))
        self.assertEqual(first, second)
        self.assertEqual(self.db.questions.count_documents({}), 1)
        self.assertEqual(self.db.question_versions.count_documents({}), 1)

    def test_creation_failure_hidden_then_retry_preserves_payload(self):
        fault_db = SimpleNamespace(questions=self.db.questions, question_versions=self.db.question_versions)
        with patch.object(library, "db", fault_db), patch.object(fault_db.question_versions, "update_one", side_effect=AutoReconnect("test")):
            response = self.browser.post("/api/questions", json={"operationId": "retry-operation", "content": self.content()})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.browser.get("/api/questions").get_json()["count"], 0)
        result = self.create("retry-operation", self.content("改过的答案"))
        self.assertEqual(result["version"]["content"]["title"], "年龄")
        self.assertNotIn("pendingVersion", self.db.questions.find_one({}))

    def test_pointer_failure_then_startup_recovery_is_repeatable(self):
        fault_db = SimpleNamespace(questions=self.db.questions, question_versions=self.db.question_versions)
        with patch.object(library, "db", fault_db), patch.object(fault_db.questions, "update_one", side_effect=AutoReconnect("test")):
            response = self.browser.post("/api/questions", json={"operationId": "pointer-failure", "content": self.content()})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.db.question_versions.count_documents({}), 1)
        library.recover_initial_questions()
        library.recover_initial_questions()
        self.assertEqual(self.db.questions.count_documents({"status": "active"}), 1)
        self.assertEqual(self.db.question_versions.count_documents({}), 1)

    def test_snapshot_instances_distinct_and_answers_keep_instance_id(self):
        item, base = self.create(), self.survey()
        one, two = self.select(base, item), self.select(base, item)
        self.assertEqual(one.status_code, 201)
        q1, q2 = one.get_json()["question"], two.get_json()["question"]
        self.assertNotEqual(q1["id"], q2["id"])
        self.assertEqual([q1["order"], q2["order"]], [1, 2])
        self.assertEqual(q1["sourceVersionId"], item["version"]["id"])
        self.browser.post(base + "/publish")
        response = self.browser.post(base + "/responses", json={"answers": {q1["id"]: 18, q2["id"]: 20}})
        self.assertEqual(response.status_code, 201, response.get_json())
        answers = self.db.responses.find_one({})["answers"]
        self.assertEqual(answers[0]["questionId"], ObjectId(q1["id"]))
        self.assertEqual(answers[0]["sourceQuestionId"], ObjectId(item["question"]["id"]))
        self.assertEqual(self.browser.get(base + "/statistics").get_json()["questions"][0]["average"], 18)

    def test_save_legacy_question_keeps_original_unlinked(self):
        base = self.survey()
        q = self.browser.post(base + "/questions", json=self.content()).get_json()["question"]
        before = self.db.surveys.find_one({})
        response = self.browser.post(base + "/questions/" + q["id"] + "/save-to-library",
                                     json={"operationId": "save-old-question"})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(self.db.surveys.find_one({}), before)
        self.assertEqual(self.db.responses.count_documents({}), 0)

    def test_version_mismatch_invalid_ids_and_null_rejected(self):
        first, second, base = self.create(), self.create("operation-0002"), self.survey()
        response = self.browser.post(base + "/questions/from-library", json={
            "questionId": first["question"]["id"], "versionId": second["version"]["id"]})
        self.assertEqual(response.status_code, 404)
        for version_id in (None, "bad", [], 4):
            self.assertEqual(self.select(base, first, versionId=version_id).status_code, 400)
        self.assertEqual(self.db.surveys.find_one({})["questions"], [])

    def test_foreign_question_and_survey_are_protected(self):
        item, base = self.create(), self.survey()
        with self.browser.session_transaction() as session:
            session["user_id"] = str(ObjectId())
        self.assertEqual(self.browser.get("/api/questions/" + item["question"]["id"]).status_code, 404)
        self.assertEqual(self.select(base, item).status_code, 404)
        self.assertEqual(self.browser.get("/api/questions").get_json()["count"], 0)

    def test_active_shared_access_copy_and_revoke(self):
        item = self.create()
        recipient = ObjectId()
        share = {"questionId": ObjectId(item["question"]["id"]), "recipientUserId": recipient,
                 "ownerId": self.user, "status": "active", "createdAt": datetime.now(timezone.utc), "revokedAt": None}
        self.db.question_shares.insert_one(share)
        with self.browser.session_transaction() as session:
            session["user_id"] = str(recipient)
        response = self.browser.post("/api/questions/" + item["question"]["id"] + "/copies", json={
            "operationId": "copy-operation", "versionId": item["version"]["id"], "content": self.content("副本")})
        self.assertEqual(response.status_code, 201, response.get_json())
        result = response.get_json()
        self.assertNotEqual(result["question"]["id"], item["question"]["id"])
        self.assertEqual(result["question"]["ownerId"], str(recipient))
        self.assertEqual(result["version"]["copiedFromVersionId"], item["version"]["id"])
        self.db.question_shares.update_one({"_id": share["_id"]}, {"$set": {
            "status": "revoked", "revokedAt": datetime.now(timezone.utc)}})
        self.assertEqual(self.browser.get("/api/questions/" + result["question"]["id"]).status_code, 200)
        self.assertEqual(self.browser.post("/api/questions/" + item["question"]["id"] + "/copies", json={
            "operationId": "copy-new-operation", "versionId": item["version"]["id"]}).status_code, 404)

    def test_source_edit_required_override_and_explicit_detach(self):
        item, base = self.create(), self.survey()
        q = self.select(base, item).get_json()["question"]
        path = base + "/questions/" + q["id"]
        response = self.browser.put(path, json={**self.content(), "required": False})
        self.assertEqual(response.status_code, 200, response.get_json())
        managed = self.browser.get(base + "/manage").get_json()["survey"]["questions"][0]
        self.assertEqual(managed["sourceVersionId"], item["version"]["id"])
        self.assertFalse(managed["required"])
        self.assertEqual(self.browser.put(path, json=self.content("不同内容")).status_code, 409)
        self.assertEqual(self.browser.put(path, json={**self.content("不同内容"), "detachSource": True}).status_code, 200)
        self.assertNotIn("sourceVersionId", self.db.surveys.find_one({})["questions"][0])
        self.assertEqual(self.db.question_versions.find_one({})["content"]["title"], "年龄")

    def test_published_snapshots_cannot_be_imported_or_modified(self):
        item, base = self.create(), self.survey()
        q = self.select(base, item).get_json()["question"]
        self.browser.post(base + "/publish")
        self.assertNotEqual(self.select(base, item).status_code, 201)
        self.assertEqual(self.browser.put(base + "/questions/" + q["id"], json={
            **self.content(), "detachSource": True}).status_code, 404)

    def test_input_validation_and_source_forgery(self):
        for data in ([], {}, {"operationId": "short", "content": self.content()},
                     {"operationId": "long-enough", "content": {**self.content(), "order": 3}}):
            self.assertEqual(self.browser.post("/api/questions", json=data).status_code, 400)
        item, base = self.create(), self.survey()
        self.assertEqual(self.select(base, item, required="true").status_code, 400)
        q = self.select(base, item).get_json()["question"]
        response = self.browser.put(base + "/questions/" + q["id"], json={
            **self.content(), "sourceVersionId": str(ObjectId())})
        self.assertEqual(response.status_code, 400)

    def test_archived_question_and_logged_out_user_rejected(self):
        item, base = self.create(), self.survey()
        self.db.questions.update_one({"_id": ObjectId(item["question"]["id"])}, {"$set": {"status": "archived"}})
        self.assertEqual(self.select(base, item).status_code, 404)
        self.browser.post("/api/logout")
        self.assertEqual(self.browser.get("/api/questions").status_code, 401)
        self.assertEqual(self.browser.post("/api/questions", json={}).status_code, 401)

    def test_same_operation_concurrent_requests_create_one_question(self):
        def create(_):
            with self.app.test_client() as client:
                with client.session_transaction() as session:
                    session["user_id"] = str(self.user)
                response = client.post("/api/questions", json={
                    "operationId": "concurrent-initial", "content": self.content()})
                return response.status_code, response.get_json()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(create, range(8)))
        self.assertTrue(all(status == 201 for status, _ in results), results)
        self.assertEqual(len({item["version"]["id"] for _, item in results}), 1)
        self.assertEqual(self.db.questions.count_documents({}), 1)
        self.assertEqual(self.db.question_versions.count_documents({}), 1)

    def test_switch_is_explicit_and_keeps_instance_identity(self):
        item, base = self.create(), self.survey()
        instance = self.select(base, item, required=False).get_json()["question"]
        # Fixture represents a future batch-3 version; no version mutation API is introduced here.
        second = self.db.question_versions.find_one({})
        second.update({"_id": ObjectId(), "versionNumber": 2})
        second["content"]["title"] = "新版本"
        self.db.question_versions.insert_one(second)
        self.db.questions.update_one({"_id": ObjectId(item["question"]["id"])}, {"$set": {
            "currentVersionId": second["_id"], "currentVersionNumber": 2, "versionCounter": 2}})
        self.assertEqual(self.db.surveys.find_one({})["questions"][0]["title"], "年龄")
        response = self.browser.put(base + "/questions/" + instance["id"] + "/source-version",
                                    json={"versionId": str(second["_id"])})
        self.assertEqual(response.status_code, 200, response.get_json())
        updated = response.get_json()["question"]
        self.assertEqual(updated["id"], instance["id"])
        self.assertFalse(updated["required"])
        self.assertEqual(updated["title"], "新版本")
        self.browser.post(base + "/publish")
        self.assertEqual(self.browser.put(base + "/questions/" + instance["id"] + "/source-version",
                                         json={"versionId": item["version"]["id"]}).status_code, 404)

    def test_rule_conflict_blocks_version_switch_and_preserves_rule(self):
        item, base = self.create(), self.survey()
        first = self.select(base, item).get_json()["question"]
        last = self.select(base, item).get_json()["question"]
        rule = {"condition": {"operator": "gte", "value": 18}, "targetQuestionId": ObjectId(last["id"])}
        survey = self.db.surveys.find_one({})
        survey["questions"][0]["jumpRules"] = [rule]
        self.db.surveys.update_one({"_id": survey["_id"]}, {"$set": {"questions": survey["questions"]}})
        second = self.db.question_versions.find_one({})
        second.update({"_id": ObjectId(), "versionNumber": 2,
                       "content": library.content_from({"type": "text", "title": "文字"})})
        self.db.question_versions.insert_one(second)
        response = self.browser.put(base + "/questions/" + first["id"] + "/source-version",
                                    json={"versionId": str(second["_id"])})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.db.surveys.find_one({})["questions"][0]["jumpRules"], [rule])


class InMemoryLibraryTests(LibraryCases, unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.db.questions.create_index([("ownerId", 1), ("operationId", 1)], unique=True)
        self.db.question_versions.create_index([("questionId", 1), ("versionNumber", 1)], unique=True)
        for module in ("models.library_model", "models.survey_model", "models.question_model",
                       "models.participation_model", "routes.survey_routes", "routes.response_routes", "routes.question_routes"):
            patcher = patch(module + ".db", self.db)
            patcher.start()
            self.addCleanup(patcher.stop)
        with patch.dict("os.environ", {"FLASK_SECRET_KEY": "batch-two-test"}):
            self.app = create_app()
        self.app.config["TESTING"] = True
        self.browser = self.app.test_client()
        self.prepare()


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置 RUN_MONGO_TESTS=1 启用真实数据库测试")
class RealLibraryTests(LibraryCases, unittest.TestCase):
    def setUp(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.setUp(self)
        self.prepare()

    def initialize(self):
        import init_schema
        for name in ("users", "surveys", "responses", "participations"):
            init_schema.apply_validator(name, getattr(init_schema, name + "_validator"))
        init_schema.init_database()
        initialize_library(self.db)

    def drop_test_database(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.drop_test_database(self)

    def test_real_schema_indexes_and_reinitialization(self):
        item = self.create()
        initialize_library(self.db)
        self.assertEqual(self.db.questions.count_documents({}), 1)
        self.assertTrue(self.db.questions.index_information()["unique_question_creation_operation"]["unique"])
        self.assertTrue(self.db.question_versions.index_information()["unique_question_version"]["unique"])
        duplicate = self.db.question_versions.find_one({})
        duplicate["_id"] = ObjectId()
        with self.assertRaises(DuplicateKeyError):
            self.db.question_versions.insert_one(duplicate)
        broken = copy.deepcopy(duplicate)
        broken["versionNumber"] = 2
        broken["content"]["order"] = 4
        with self.assertRaises(WriteError):
            self.db.question_versions.insert_one(broken)
        base = self.survey()
        instance = library.snapshot_from(*library.get_version(self.user, item["question"]["id"]))
        instance.pop("sourceVersionId")
        with self.assertRaises(WriteError):
            self.db.surveys.update_one({"_id": ObjectId(base.rsplit("/", 1)[1])}, {"$set": {"questions": [instance]}})


if __name__ == "__main__":
    unittest.main()
