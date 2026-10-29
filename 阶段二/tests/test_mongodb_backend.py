"""显式启用的真实 MongoDB 测试，仅使用独立临时数据库。"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, WriteError

import init_schema
from app import create_app
from models.question_model import add_question


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置 RUN_MONGO_TESTS=1 启用真实数据库测试")
class MongoDBBackendTests(unittest.TestCase):
    def setUp(self):
        self.client = MongoClient(
            os.getenv("MONGO_URI", "mongodb://localhost:27017/"),
            serverSelectionTimeoutMS=5000
        )
        self.addCleanup(self.client.close)
        self.client.admin.command("ping")
        self.database_name = "questionnaire_test_" + uuid4().hex
        self.db = self.client[self.database_name]
        self.addCleanup(self.drop_test_database)
        for module in (
            "models.database", "models.user_model", "models.survey_model",
            "models.question_model", "models.jump_model", "routes.survey_routes",
            "routes.response_routes", "init_schema",
            "models.participation_model", "routes.question_routes", "models.library_model", "models.version_model",
            "models.sharing_bank_model", "models.statistics_model"
        ):
            patcher = patch(module + ".db", self.db)
            patcher.start()
            self.addCleanup(patcher.stop)
        for module in ("models.database", "init_schema"):
            patcher = patch(module + ".client", self.client)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.initialize()
        with patch.dict("os.environ", {"FLASK_SECRET_KEY": "integration-test-only"}):
            self.app = create_app()
        self.app.config["TESTING"] = True
        self.browser = self.app.test_client()

    def drop_test_database(self):
        # 只允许清理本测试创建的完整随机库名。
        if (self.database_name.startswith("questionnaire_test_")
                and self.db.name == self.database_name
                and len(self.database_name) == len("questionnaire_test_") + 32):
            self.client.drop_database(self.database_name)
        else:
            raise RuntimeError("拒绝清理非测试数据库")

    def initialize(self):
        for name in ("users", "surveys", "responses", "participations"):
            init_schema.apply_validator(name, getattr(init_schema, name + "_validator"))
        init_schema.init_database()
        init_schema.initialize_library(self.db)

    def test_initialization_is_repeatable_and_enforces_schema_and_indexes(self):
        user = {"username": "existing", "passwordHash": "hash",
                "createdAt": datetime.now(timezone.utc)}
        self.db.users.insert_one(user)
        self.initialize()
        self.assertEqual(self.db.users.count_documents({}), 1)
        duplicate = dict(user)
        duplicate.pop("_id")
        with self.assertRaises(DuplicateKeyError):
            self.db.users.insert_one(duplicate)
        with self.assertRaises(WriteError):
            self.db.users.insert_one({"username": ""})
        self.assertIn("surveys_by_owner", self.db.surveys.index_information())
        self.assertIn("responses_by_survey", self.db.responses.index_information())

    def test_concurrent_question_additions_have_unique_complete_order(self):
        owner = ObjectId()
        now = datetime.now(timezone.utc)
        survey_id = self.db.surveys.insert_one({
            "ownerId": owner, "title": "并发测试", "description": "",
            "anonymousAllowed": False, "status": "draft", "deadline": None,
            "questions": [], "createdAt": now, "updatedAt": now
        }).inserted_id
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda i: add_question(str(survey_id), str(owner), "text", f"$题目{i}"),
                range(12)
            ))
        survey = self.db.surveys.find_one({"_id": survey_id})
        self.assertEqual([q["order"] for q in survey["questions"]], list(range(1, 13)))
        self.assertEqual(sorted(q["order"] for q in results), list(range(1, 13)))
        self.assertEqual({q["title"] for q in survey["questions"]},
                         {f"$题目{i}" for i in range(12)})

    def test_api_create_jump_submit_statistics_and_owner_isolation(self):
        def post(path, body=None, expected=200):
            result = self.browser.post(path, json=body)
            self.assertEqual(result.status_code, expected, result.get_json())
            return result.get_json()

        post("/api/register", {"username": "owner", "password": "password123"}, 201)
        post("/api/login", {"username": "owner", "password": "password123"})
        survey_id = post("/api/surveys", {
            "title": "流程测试", "anonymousAllowed": True, "allowMultipleResponses": True
        }, 201)["survey"]["id"]
        base = f"/api/surveys/{survey_id}"
        q1 = post(base + "/questions", {
            "type": "single_choice", "title": "是否跳转", "required": True,
            "options": [{"value": "yes", "label": "是"}, {"value": "no", "label": "否"}]
        }, 201)["question"]["id"]
        post(base + "/questions", {"type": "text", "title": "可跳过的必答题"}, 201)
        q3 = post(base + "/questions", {
            "type": "number", "title": "年龄", "required": True,
            "validation": {"min": 0, "max": 120, "integerOnly": True}
        }, 201)["question"]["id"]
        q4 = post(base + "/questions", {
            "type": "multiple_choice", "title": "必答多选", "required": True,
            "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]
        }, 201)["question"]["id"]
        post(base + f"/questions/{q1}/rules", {
            "operator": "equals", "value": "yes", "targetQuestionId": q3
        }, 201)
        post(base + "/publish")
        answers = {q1: "yes", q3: 18, q4: []}
        post(base + "/responses", {"answers": answers}, 400)
        self.assertEqual(self.db.responses.count_documents({}), 0)
        answers[q4] = ["a"]
        post(base + "/responses", {"answers": answers}, 201)
        answers[q3] = 20
        post(base + "/responses", {"answers": answers, "anonymous": True}, 201)
        anonymous = self.db.responses.find_one({"respondentId": {"$exists": False}})
        self.assertIsNotNone(anonymous)
        stats = self.browser.get(base + "/statistics").get_json()
        self.assertEqual(stats["responseCount"], 2)
        questions = {q["questionId"]: q for q in stats["questions"]}
        self.assertEqual(questions[q3]["average"], 19)
        self.assertEqual(questions[q4]["optionCounts"][0]["count"], 2)
        post("/api/logout")
        post("/api/register", {"username": "other", "password": "password123"}, 201)
        post("/api/login", {"username": "other", "password": "password123"})
        self.assertEqual(self.browser.get("/api/surveys").get_json()["count"], 0)
        self.assertEqual(self.browser.get(base + "/statistics").status_code, 404)

    def prepare_filling_survey(self, publish=True):
        self.browser.post("/api/register", json={"username": "filler", "password": "password123"})
        self.browser.post("/api/login", json={"username": "filler", "password": "password123"})
        response = self.browser.post("/api/surveys", json={"title": "逐题流程"})
        self.assertEqual(response.status_code, 201)
        survey_id = response.get_json()["survey"]["id"]
        base = f"/api/surveys/{survey_id}"
        questions = []
        specs = [
            {"type": "single_choice", "title": "起点", "options": [
                {"value": "yes", "label": "是"}, {"value": "no", "label": "否"}]},
            {"type": "multiple_choice", "title": "多选", "options": [
                {"value": "a", "label": "A"}, {"value": "b", "label": "B"}]},
            {"type": "number", "title": "年龄", "validation": {"integerOnly": True}},
            {"type": "text", "title": "可选说明", "required": False},
            {"type": "text", "title": "最后一题"}
        ]
        for spec in specs:
            result = self.browser.post(base + "/questions", json=spec)
            self.assertEqual(result.status_code, 201, result.get_json())
            questions.append(result.get_json()["question"]["id"])
        for source, operator, value, target in (
            (0, "equals", "yes", 2), (1, "contains", "a", 3), (2, "gte", 18, 4)
        ):
            result = self.browser.post(base + f"/questions/{questions[source]}/rules", json={
                "operator": operator, "value": value, "targetQuestionId": questions[target]
            })
            self.assertEqual(result.status_code, 201)
        if publish:
            self.assertEqual(self.browser.post(base + "/publish").status_code, 200)
        return base, questions

    def test_manage_returns_complete_configuration_only_to_owner(self):
        base, ids = self.prepare_filling_survey(publish=False)
        result = self.browser.get(base + "/manage")
        self.assertEqual(result.status_code, 200)
        survey = result.get_json()["survey"]
        self.assertTrue(survey["canEdit"])
        self.assertEqual([q["id"] for q in survey["questions"]], ids)
        self.assertEqual(survey["questions"][0]["jumpRules"][0]["targetQuestionId"], ids[2])
        self.assertEqual(survey["questions"][2]["validation"]["integerOnly"], True)
        self.assertEqual(self.browser.get("/api/surveys/invalid/manage").status_code, 400)
        self.assertEqual(self.browser.get(f"/api/surveys/{ObjectId()}/manage").status_code, 404)
        self.browser.post(base + "/publish")
        self.assertFalse(self.browser.get(base + "/manage").get_json()["survey"]["canEdit"])
        public = self.browser.get(base).get_json()["survey"]
        self.assertNotIn("ownerId", public)
        self.assertTrue(all("jumpRules" not in q for q in public["questions"]))
        self.browser.post(base + "/close")
        self.assertFalse(self.browser.get(base + "/manage").get_json()["survey"]["canEdit"])
        self.browser.post("/api/logout")
        self.assertEqual(self.browser.get(base + "/manage").status_code, 401)
        self.browser.post("/api/register", json={"username": "visitor", "password": "password123"})
        self.browser.post("/api/login", json={"username": "visitor", "password": "password123"})
        self.assertEqual(self.browser.get(base + "/manage").status_code, 404)

    def test_next_single_and_numeric_jumps_then_explicit_submit(self):
        base, q = self.prepare_filling_survey()
        answers = {}
        for expected_id, update in ((q[0], {}), (q[2], {q[0]: "yes"}),
                                    (q[4], {q[2]: 18})):
            answers.update(update)
            result = self.browser.post(base + "/next", json={"answers": answers})
            self.assertEqual(result.status_code, 200, result.get_json())
            payload = result.get_json()
            self.assertFalse(payload["completed"])
            self.assertEqual(payload["nextQuestion"]["id"], expected_id)
            self.assertNotIn("jumpRules", payload["nextQuestion"])
        answers[q[4]] = "完成"
        payload = self.browser.post(base + "/next", json={"answers": answers}).get_json()
        self.assertTrue(payload["completed"])
        self.assertIsNone(payload["nextQuestion"])
        self.assertEqual(payload["visitedQuestionIds"], [q[0], q[2], q[4]])
        self.assertEqual(self.db.responses.count_documents({}), 0)
        result = self.browser.post(base + "/responses", json={"answers": answers})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.get_json()["answerCount"], 3)

    def test_next_multiple_jump_and_explicit_optional_skip(self):
        base, q = self.prepare_filling_survey()
        answers = {q[0]: "no", q[1]: ["a"]}
        result = self.browser.post(base + "/next", json={"answers": answers})
        self.assertEqual(result.get_json()["nextQuestion"]["id"], q[3])
        answers[q[3]] = None
        result = self.browser.post(base + "/next", json={"answers": answers})
        self.assertEqual(result.get_json()["nextQuestion"]["id"], q[4])
        answers[q[4]] = "已完成"
        result = self.browser.post(base + "/responses", json={"answers": answers})
        self.assertEqual(result.status_code, 201, result.get_json())
        self.assertEqual(result.get_json()["answerCount"], 3)
        saved = self.db.responses.find_one({})["answers"]
        self.assertNotIn(ObjectId(q[3]), [a["questionId"] for a in saved])

    def test_next_rejects_bypasses_stale_answers_and_invalid_requests(self):
        base, q = self.prepare_filling_survey()
        for answers in (
            {q[2]: 18}, {q[0]: "yes", q[1]: ["a"]},
            {q[0]: "invalid"}, {str(ObjectId()): "other"},
            {"invalid-id": 1}, {q[0]: "yes", q[2]: 18.5},
            {q[0]: "yes", q[2]: 18, q[4]: ""}
        ):
            with self.subTest(answers=answers):
                result = self.browser.post(base + "/next", json={"answers": answers})
                self.assertEqual(result.status_code, 400, result.get_json())
        for body in ([], {}, {"answers": []}):
            self.assertEqual(self.browser.post(base + "/next", json=body).status_code, 400)
        self.assertEqual(self.browser.post("/api/surveys/invalid/next", json={"answers": {}}).status_code, 400)
        # 最终提交不能因为此前调用过 next 就省略必答答案。
        self.assertEqual(self.browser.post(base + "/responses", json={"answers": {q[0]: "yes"}}).status_code, 400)
        self.assertEqual(self.db.responses.count_documents({}), 0)

    def test_read_next_and_submit_share_login_status_and_deadline_checks(self):
        base, q = self.prepare_filling_survey(publish=False)

        def assert_fill_status(status):
            self.assertEqual(self.browser.get(base).status_code, status)
            self.assertEqual(self.browser.post(base + "/next", json={"answers": {}}).status_code, status)
            self.assertEqual(self.browser.post(base + "/responses", json={"answers": {}}).status_code, status)

        assert_fill_status(404)
        self.browser.post(base + "/publish")
        self.db.surveys.update_one({"_id": ObjectId(base.rsplit("/", 1)[1])}, {
            "$set": {"deadline": datetime.now(timezone.utc) - timedelta(seconds=1)}
        })
        assert_fill_status(400)
        self.browser.post(base + "/close")
        assert_fill_status(404)
        self.browser.post("/api/logout")
        assert_fill_status(401)

    def test_default_no_repeat_including_anonymous_and_unique_index(self):
        base, q = self.prepare_filling_survey(publish=False)
        managed = self.browser.get(base + "/manage").get_json()["survey"]
        self.assertFalse(managed["allowMultipleResponses"])
        result = self.browser.patch(base, json={"anonymousAllowed": True})
        self.assertEqual(result.status_code, 200)
        self.browser.post(base + "/publish")
        body = {"answers": {q[0]: "yes", q[2]: 18, q[4]: "首次"}, "anonymous": True}
        self.assertEqual(self.browser.post(base + "/responses", json=body).status_code, 201)
        self.assertNotIn("respondentId", self.db.responses.find_one({}))
        body["anonymous"] = False
        self.assertEqual(self.browser.post(base + "/responses", json=body).status_code, 409)
        self.assertEqual(self.db.responses.count_documents({}), 1)
        self.assertEqual(self.db.participations.count_documents({"status": "committed"}), 1)
        self.assertNotIn("payload", self.db.participations.find_one({}))
        self.assertTrue(self.db.participations.index_information()["unique_survey_participant"]["unique"])
        self.assertTrue(self.browser.get(base).get_json()["survey"]["alreadySubmitted"])
        self.assertEqual(self.browser.patch(base, json={"allowMultipleResponses": True}).status_code, 409)

    def test_allow_repeat_is_independent_of_anonymous_and_owner_controlled(self):
        base, q = self.prepare_filling_survey(publish=False)
        self.assertEqual(self.browser.patch(base, json={"allowMultipleResponses": "yes"}).status_code, 400)
        self.assertEqual(self.browser.patch(base, json={"allowMultipleResponses": True, "anonymousAllowed": False}).status_code, 200)
        self.browser.post(base + "/publish")
        body = {"answers": {q[0]: "yes", q[2]: 18, q[4]: "重复测试"}}
        self.assertEqual(self.browser.post(base + "/responses", json={**body, "anonymous": True}).status_code, 400)
        self.assertEqual(self.browser.post(base + "/responses", json=body).status_code, 201)
        self.assertEqual(self.browser.post(base + "/responses", json=body).status_code, 201)
        self.assertEqual(self.db.responses.count_documents({}), 2)
        self.assertEqual(self.db.participations.count_documents({}), 0)
        self.browser.post("/api/logout")
        self.browser.post("/api/register", json={"username": "stranger", "password": "password123"})
        self.browser.post("/api/login", json={"username": "stranger", "password": "password123"})
        self.assertNotEqual(self.browser.patch(base, json={"allowMultipleResponses": True}).status_code, 200)

    def test_concurrent_same_account_submissions_store_only_one_response(self):
        base, q = self.prepare_filling_survey()
        with self.browser.session_transaction() as session:
            user_id = session["user_id"]
        body = {"answers": {q[0]: "yes", q[2]: 18, q[4]: "并发"}}
        def submit(_):
            with self.app.test_client() as client:
                with client.session_transaction() as session:
                    session["user_id"] = user_id
                result = client.post(base + "/responses", json=body)
                return result.status_code, result.get_json()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(submit, range(12)))
        self.assertTrue(any(status == 201 for status, _ in results))
        self.assertTrue(all(status in (201, 409) for status, _ in results), results)
        self.assertEqual(len({body["responseId"] for status, body in results if status == 201}), 1)
        self.assertEqual(self.db.responses.count_documents({}), 1)
        self.assertEqual(self.db.participations.count_documents({}), 1)

    def test_interrupted_submission_replays_first_payload_without_loss(self):
        from pymongo.errors import AutoReconnect
        base, q = self.prepare_filling_survey()
        body = {"answers": {q[0]: "yes", q[2]: 18, q[4]: "第一次答案"}}
        with patch("models.participation_model.db") as mocked:
            mocked.participations = self.db.participations
            mocked.responses.update_one.side_effect = AutoReconnect("模拟中断")
            self.assertEqual(self.browser.post(base + "/responses", json=body).status_code, 500)
        self.assertEqual(self.db.participations.count_documents({"status": "pending"}), 1)
        body["answers"][q[4]] = "重试修改不应覆盖第一次"
        response = self.browser.post(base + "/responses", json=body)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.get_json()["recovered"])
        self.assertEqual(self.db.responses.find_one({})["answers"][-1]["value"], "第一次答案")
        self.assertEqual(self.db.participations.count_documents({"status": "committed"}), 1)

    def test_question_edit_delete_and_rule_removal_preserve_draft_integrity(self):
        base, q = self.prepare_filling_survey(publish=False)
        response = self.browser.put(base + f"/questions/{q[4]}", json={"type": "text", "title": "修改后的标题"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.browser.delete(base + f"/questions/{q[2]}").status_code, 400)
        self.assertEqual(self.browser.delete(base + f"/questions/{q[0]}/rules/0").status_code, 200)
        self.assertEqual(self.browser.delete(base + f"/questions/{q[2]}").status_code, 200)
        survey = self.browser.get(base + "/manage").get_json()["survey"]
        self.assertEqual([item["order"] for item in survey["questions"]], [1, 2, 3, 4])
        self.browser.post(base + "/publish")
        self.assertEqual(self.browser.delete(base + f"/questions/{q[4]}").status_code, 404)

    def test_backfill_preserves_legacy_answers_and_blocks_known_users(self):
        base, q = self.prepare_filling_survey()
        sid = ObjectId(base.rsplit("/", 1)[1])
        with self.browser.session_transaction() as session:
            uid = ObjectId(session["user_id"])
        self.db.responses.insert_one({"surveyId": sid, "respondentId": uid,
                                      "answers": [], "submittedAt": datetime.now(timezone.utc)})
        init_schema.backfill_participations()
        init_schema.backfill_participations()
        self.assertEqual(self.db.participations.count_documents({}), 1)
        self.assertEqual(self.db.responses.count_documents({}), 1)
        result = self.browser.post(base + "/responses", json={"answers": {q[0]: "yes", q[2]: 18, q[4]: "新答"}})
        self.assertEqual(result.status_code, 409)

    def test_startup_recovers_accepted_submission_after_survey_closes(self):
        from pymongo.errors import AutoReconnect
        base, q = self.prepare_filling_survey()
        body = {"answers": {q[0]: "yes", q[2]: 18, q[4]: "已接受的内容"}}
        with patch("models.participation_model.db") as mocked:
            mocked.participations = self.db.participations
            mocked.responses.update_one.side_effect = AutoReconnect("模拟保存中断")
            self.assertEqual(self.browser.post(base + "/responses", json=body).status_code, 500)
        self.browser.post(base + "/close")
        init_schema.recover_pending_participations()
        init_schema.recover_pending_participations()
        self.assertEqual(self.db.responses.count_documents({}), 1)
        self.assertEqual(self.db.participations.count_documents({"status": "committed"}), 1)
        self.assertEqual(self.db.responses.find_one({})["answers"][-1]["value"], "已接受的内容")


if __name__ == "__main__":
    unittest.main()
