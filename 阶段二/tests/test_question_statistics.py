"""Batch-5 real MongoDB permissions, counting, metric compatibility and CAS audit tests."""
import copy
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId
from pymongo.errors import AutoReconnect, DuplicateKeyError, WriteError

from models import statistics_model as stats


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "需启用独立 MongoDB 测试")
class QuestionStatisticsTests(unittest.TestCase):
    def setUp(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.setUp(self)
        self.owner, self.recipient, self.stranger = ObjectId(), ObjectId(), ObjectId()
        for uid in (self.owner, self.recipient, self.stranger):
            self.db.users.insert_one({"_id": uid, "username": str(uid), "passwordHash": "fixture",
                                      "createdAt": datetime.now(timezone.utc)})
        self.as_user(self.owner)
        self.content = {"type": "number", "title": "年龄", "required": False, "unit": "岁",
                        "semanticDescription": "填写时的周岁", "validation": {"min": 0, "max": 120}}
        created = self.browser.post("/api/questions", json={"operationId": "initial-statistics", "content": self.content})
        self.assertEqual(created.status_code, 201, created.get_json())
        result = created.get_json()
        self.qid, self.vid = result["question"]["id"], result["version"]["id"]
        self.base = "/api/questions/" + self.qid

    def initialize(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.initialize(self)

    def drop_test_database(self):
        from test_mongodb_backend import MongoDBBackendTests
        MongoDBBackendTests.drop_test_database(self)

    def as_user(self, uid):
        with self.browser.session_transaction() as session:
            session["user_id"] = str(uid)

    def version(self, content=None):
        question = self.db.questions.find_one({"_id": ObjectId(self.qid)})
        self.as_user(self.owner)
        result = self.browser.post(self.base + "/versions", json={
            "operationId": "version-" + str(ObjectId()), "content": content or self.content,
            "basedOnVersionId": str(question["currentVersionId"]),
            "expectedRevision": question["versionRevision"], "changeNote": "测试"})
        self.assertEqual(result.status_code, 201, result.get_json())
        return result.get_json()["version"]["id"]

    def survey(self, versions=None):
        result = self.browser.post("/api/surveys", json={"title": "本人问卷", "anonymousAllowed": True,
                                                        "allowMultipleResponses": True})
        self.assertEqual(result.status_code, 201, result.get_json())
        sid = result.get_json()["survey"]["id"]
        instances = []
        for vid in versions or [self.vid]:
            result = self.browser.post("/api/surveys/" + sid + "/questions/from-library",
                                       json={"questionId": self.qid, "versionId": vid, "required": False})
            self.assertEqual(result.status_code, 201, result.get_json())
            instances.append(ObjectId(result.get_json()["question"]["id"]))
        return ObjectId(sid), instances

    def answer(self, survey, values, mapped=True):
        sid, instances = survey
        document = self.db.surveys.find_one({"_id": sid})
        byid = {q["_id"]: q for q in document["questions"]}
        answers = []
        for iid, value in zip(instances, values):
            answer = {"questionId": iid, "value": value}
            if mapped:
                answer.update({"sourceQuestionId": byid[iid]["sourceQuestionId"],
                               "sourceVersionId": byid[iid]["sourceVersionId"]})
            answers.append(answer)
        return self.db.responses.insert_one({"surveyId": sid, "answers": answers,
                                              "submittedAt": datetime.now(timezone.utc)}).inserted_id

    def get(self, suffix="/statistics", **query):
        response = self.browser.get(self.base + suffix, query_string=query)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def config_body(self, versions, metric="numericMean", expected=0, operation=None):
        return {"operationId": operation or "config-" + str(ObjectId()), "expectedRevision": expected,
                "confirmed": True, "reason": "所有者确认题干调整不改变统计含义和有效范围",
                "groups": [{"metric": metric, "groupId": "same-meaning", "versionIds": versions}]}

    def configure(self, body):
        result = self.browser.put(self.base + "/statistics-configuration", json=body)
        self.assertEqual(result.status_code, 200, result.get_json())
        return result.get_json()

    def test_same_question_two_instances_counts_one_submission(self):
        first, second = self.survey([self.vid, self.vid]), self.survey()
        self.answer(first, [10, 20])
        self.answer(second, [30])
        usage, result = self.get("/usage"), self.get()
        self.assertEqual((usage["surveyCount"], usage["instanceCount"]), (2, 3))
        self.assertEqual((result["surveyCount"], result["instanceCount"], result["submissionCount"], result["answerCount"]),
                         (2, 3, 2, 3))
        self.assertEqual(result["versions"][0]["mean"], 20)
        self.assertFalse(result["independentPeopleAvailable"])
        self.assertNotIn("distinctPeople", result)

    def test_empty_unmapped_invalid_and_duplicate_answers_are_excluded(self):
        survey = self.survey()
        self.answer(survey, [""])
        self.answer(survey, [50], mapped=False)
        self.answer(survey, [999])
        rid = self.answer(survey, [20])
        response = self.db.responses.find_one({"_id": rid})
        self.db.responses.update_one({"_id": rid}, {"$push": {"answers": response["answers"][0]}})
        self.answer(survey, [])
        result = self.get()
        self.assertEqual(result["submissionCount"], 5)
        self.assertEqual(result["answerCount"], 0)
        self.assertIsNone(result["versions"][0]["mean"])
        self.assertEqual(result["excludedAnswers"], {"empty": 1, "unmappedOrMismatched": 1, "invalid": 3})

    def test_defaults_do_not_merge_versions_and_weighted_mean_is_correct(self):
        v2 = self.version({**self.content, "title": "当前年龄"})
        a, b = self.survey(), self.survey([v2])
        self.answer(a, [10])
        for _ in range(3):
            self.answer(b, [30])
        self.assertEqual(len([g for g in self.get()["overall"] if g["metric"] == "numericMean"]), 2)
        self.configure(self.config_body([self.vid, v2]))
        result = self.get()
        means = [g for g in result["overall"] if g["metric"] == "numericMean"]
        self.assertEqual((len(means), means[0]["mean"], means[0]["answerCount"]), (1, 25, 4))
        self.assertEqual(len([g for g in result["overall"] if g["metric"] == "numericDistribution"]), 2)
        self.assertEqual([v["mean"] for v in result["versions"]], [10, 30])

    def test_bins_boundary_last_inclusive_and_overflow(self):
        survey = self.survey()
        for value in (0, 10, 20, 30, 40):
            self.answer(survey, [value])
        distribution = self.get(bins="[10,20,30]")["versions"][0]["distribution"]
        self.assertEqual((distribution["counts"], distribution["underflow"], distribution["overflow"]), ([1, 2], 1, 1))

    def test_invalid_bins_are_rejected(self):
        for bins in ("null", "{}", "[]", "[0,0]", "[2,1]", "[true,2]", "[0,NaN]", "[0,Infinity]", "oops"):
            with self.subTest(bins=bins):
                self.assertEqual(self.browser.get(self.base + "/statistics", query_string={"bins": bins}).status_code, 400)

    def test_usage_version_filter_requires_same_array_element(self):
        v2 = self.version()
        survey = self.survey()
        other = ObjectId()
        snapshot = copy.deepcopy(self.db.surveys.find_one({"_id": survey[0]})["questions"][0])
        snapshot.update({"_id": ObjectId(), "sourceQuestionId": other, "sourceVersionId": ObjectId(v2), "order": 2})
        self.db.surveys.update_one({"_id": survey[0]}, {"$push": {"questions": snapshot}})
        self.assertEqual(self.get("/usage", versionId=v2)["surveyCount"], 0)
        self.assertEqual(self.get(versionId=v2)["submissionCount"], 0)

    def test_owner_and_shared_user_only_see_their_own_surveys(self):
        owner_survey = self.survey()
        self.answer(owner_survey, [10])
        grant = self.browser.post(self.base + "/shares", json={"recipientUserId": str(self.recipient)}).get_json()["share"]
        self.as_user(self.recipient)
        recipient_survey = self.survey()
        self.answer(recipient_survey, [90])
        self.assertEqual(self.get()["versions"][0]["mean"], 90)
        self.assertNotIn(str(owner_survey[0]), str(self.get("/usage")))
        self.assertEqual(self.browser.get(self.base + "/statistics-configuration").status_code, 404)
        self.as_user(self.owner)
        self.assertEqual(self.get()["versions"][0]["mean"], 10)
        self.assertNotIn(str(recipient_survey[0]), str(self.get("/usage")))
        self.browser.delete(self.base + "/shares/" + grant["id"])
        self.as_user(self.recipient)
        self.assertEqual(self.get()["versions"][0]["mean"], 90)
        self.assertEqual(self.browser.get(self.base).status_code, 404)

    def test_revoked_user_cannot_enumerate_unused_versions(self):
        grant = self.browser.post(self.base + "/shares", json={"recipientUserId": str(self.recipient)}).get_json()["share"]
        v2 = self.version()
        self.as_user(self.recipient)
        self.survey()
        self.as_user(self.owner)
        self.browser.delete(self.base + "/shares/" + grant["id"])
        self.as_user(self.recipient)
        self.assertEqual([v["versionId"] for v in self.get()["versions"]], [self.vid])
        self.assertEqual(self.browser.get(self.base + "/statistics", query_string={"versionId": v2}).status_code, 404)

    def test_unauthorized_and_unknown_return_404_and_login_required(self):
        self.as_user(self.stranger)
        for suffix in ("/usage", "/statistics", "/statistics-configuration"):
            self.assertEqual(self.browser.get(self.base + suffix).status_code, 404)
        self.assertEqual(self.browser.get("/api/questions/" + str(ObjectId()) + "/statistics").status_code, 404)
        with self.browser.session_transaction() as session:
            session.clear()
        self.assertEqual(self.browser.get(self.base + "/statistics").status_code, 401)

    def test_preview_warnings_does_not_write_or_confirm(self):
        v2 = self.version({**self.content, "title": "新表述"})
        result = self.browser.post(self.base + "/statistics-configuration/preview",
                                   json={"groups": self.config_body([self.vid, v2])["groups"]})
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(result.get_json()["warnings"][0]["changedFields"], ["title"])
        self.assertTrue(result.get_json()["requiresOwnerConfirmation"])
        self.assertEqual(self.db.question_statistics_events.count_documents({}), 0)

    def test_configuration_requires_confirmation_reason_and_valid_revision(self):
        v2 = self.version()
        original = self.config_body([self.vid, v2])
        for key, value in (("confirmed", False), ("confirmed", 1), ("reason", " "), ("expectedRevision", True),
                           ("expectedRevision", -1), ("operationId", "short")):
            data = {**original, key: value}
            self.assertEqual(self.browser.put(self.base + "/statistics-configuration", json=data).status_code, 400)
        self.assertEqual(self.db.question_statistics_events.count_documents({}), 0)

    def test_units_ranges_missing_semantics_and_different_types_cannot_merge(self):
        for content in ({**self.content, "unit": "月"}, {**self.content, "validation": {"min": 1, "max": 120}},
                        {**self.content, "semanticDescription": ""}, {"type": "text", "title": "年龄文字"}):
            v2 = self.version(content)
            self.assertEqual(self.browser.put(self.base + "/statistics-configuration",
                                              json=self.config_body([self.vid, v2])).status_code, 400)

    def test_group_overlap_unknown_metric_and_foreign_version_rejected(self):
        v2 = self.version()
        data = self.config_body([self.vid, v2])
        for groups in ([*data["groups"], {**data["groups"][0], "groupId": "other"}],
                       [{**data["groups"][0], "metric": "all"}],
                       [{**data["groups"][0], "versionIds": [self.vid, self.vid]}]):
            self.assertEqual(self.browser.put(self.base + "/statistics-configuration", json={**data, "groups": groups}).status_code, 400)
        data["groups"][0]["versionIds"] = [self.vid, str(ObjectId())]
        self.assertEqual(self.browser.put(self.base + "/statistics-configuration", json=data).status_code, 404)

    def test_append_only_audit_split_again_and_idempotent_old_retry(self):
        v2 = self.version()
        before = list(self.db.question_versions.find({}).sort("versionNumber", 1))
        body = self.config_body([self.vid, v2])
        first = self.configure(body)
        stored = self.db.question_statistics_events.find_one({"_id": ObjectId(first["event"]["id"])})
        second = self.configure({**body, "operationId": "split-config-operation", "expectedRevision": 1, "groups": []})
        self.assertEqual(second["event"]["revision"], 2)
        self.assertTrue(self.configure(body)["replayed"])
        self.assertEqual(self.get("/statistics-configuration")["revision"], 2)
        self.assertEqual(len(self.get("/statistics-configuration")["events"]), 2)
        self.assertEqual(self.db.question_statistics_events.find_one({"_id": stored["_id"]}), stored)
        self.assertEqual(list(self.db.question_versions.find({}).sort("versionNumber", 1)), before)
        self.assertEqual(self.browser.put(self.base + "/statistics-configuration", json={**body, "reason": "改变重试"}).status_code, 409)

    def test_concurrent_confirmations_one_winner_only(self):
        v2 = self.version()
        barrier = Barrier(2)
        def submit(index):
            barrier.wait()
            try:
                return stats.configure(str(self.owner), self.qid, self.config_body([self.vid, v2], operation="parallel-" + str(index)))
            except stats.LibraryError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertIn(409, results)
        self.assertEqual(len(self.get("/statistics-configuration")["events"]), 1)

    def test_same_operation_concurrent_retry_has_one_event(self):
        v2, barrier = self.version(), Barrier(2)
        body = self.config_body([self.vid, v2])
        def submit(_):
            barrier.wait()
            return stats.configure(str(self.owner), self.qid, body)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        self.assertEqual(len({r["event"]["id"] for r in results}), 1)
        self.assertEqual(self.db.question_statistics_events.count_documents({}), 1)

    def test_failure_after_event_insert_recovers_with_same_operation(self):
        v2 = self.version()
        body = self.config_body([self.vid, v2])
        fault = SimpleNamespace(questions=self.db.questions, question_statistics_events=self.db.question_statistics_events)
        with patch.object(stats, "db", fault), patch.object(fault.questions, "update_one", side_effect=AutoReconnect("injected")):
            self.assertEqual(self.browser.put(self.base + "/statistics-configuration", json=body).status_code, 500)
        self.assertEqual(self.get("/statistics-configuration")["events"], [])
        self.assertEqual(self.get()["configurationRevision"], 0)
        self.configure(body)
        self.assertEqual(len(self.get("/statistics-configuration")["events"]), 1)

    def test_lost_reply_after_pointer_update_is_idempotent(self):
        v2 = self.version()
        fault = SimpleNamespace(questions=self.db.questions, question_statistics_events=self.db.question_statistics_events)
        body, original = self.config_body([self.vid, v2]), fault.questions.update_one
        def lose_reply(*args, **kwargs):
            original(*args, **kwargs)
            raise AutoReconnect("reply lost")
        with patch.object(stats, "db", fault), patch.object(fault.questions, "update_one", side_effect=lose_reply):
            self.assertEqual(self.browser.put(self.base + "/statistics-configuration", json=body).status_code, 500)
        self.assertTrue(self.configure(body)["replayed"])
        self.assertEqual(self.get()["configurationRevision"], 1)

    def test_pending_loser_is_not_audit_history_or_reapplied(self):
        v2 = self.version()
        loser = self.config_body([self.vid, v2])
        fault = SimpleNamespace(questions=self.db.questions, question_statistics_events=self.db.question_statistics_events)
        with patch.object(stats, "db", fault), patch.object(fault.questions, "update_one", side_effect=AutoReconnect("pause")):
            self.browser.put(self.base + "/statistics-configuration", json=loser)
        self.configure(self.config_body([self.vid, v2]))
        self.assertEqual(self.browser.put(self.base + "/statistics-configuration", json=loser).status_code, 409)
        self.assertEqual(len(self.get("/statistics-configuration")["events"]), 1)

    def test_choice_distribution_rejects_changed_options_and_counts_multiselect(self):
        choice = {"type": "multiple_choice", "title": "爱好", "required": False,
                  "options": [{"value": "a", "label": "音乐"}, {"value": "b", "label": "运动"}]}
        v2, v3 = self.version(choice), self.version(choice)
        survey = self.survey([v2, v3])
        self.answer(survey, [["a", "b"], ["a"]])
        self.configure(self.config_body([v2, v3], metric="choiceDistribution"))
        group = next(g for g in self.get()["overall"] if g["metric"] == "choiceDistribution")
        self.assertEqual((group["answerCount"], group["selectionCount"]), (2, 3))
        self.assertEqual([o["count"] for o in group["options"]], [2, 1])
        changed = copy.deepcopy(choice)
        changed["options"][0]["label"] = "文学"
        v4 = self.version(changed)
        self.assertEqual(self.browser.put(self.base + "/statistics-configuration",
                                          json=self.config_body([v3, v4], metric="choiceDistribution", expected=1)).status_code, 400)

    def test_text_per_version_only_and_excerpts_bounded(self):
        v2 = self.version({"type": "text", "title": "建议"})
        survey = self.survey([v2])
        for index in range(101):
            self.answer(survey, ["建议" + str(index)])
        result = self.get(versionId=v2)
        self.assertEqual(result["answerCount"], 101)
        self.assertTrue(result["versions"][0]["textsTruncated"])
        self.assertEqual(len(result["versions"][0]["texts"]), 100)
        self.assertNotIn("texts", result["overall"][0])

    def test_tampered_snapshot_and_answer_source_not_included(self):
        survey = self.survey()
        rid = self.answer(survey, [10])
        self.db.responses.update_one({"_id": rid}, {"$set": {"answers.0.sourceVersionId": ObjectId()}})
        self.assertEqual(self.get()["answerCount"], 0)
        self.db.surveys.update_one({"_id": survey[0]}, {"$set": {"questions.0.title": "脱离来源却保留ID"}})
        self.assertEqual(self.get("/usage")["instanceCount"], 0)

    def test_usage_pagination_counts_whole_scope_and_validates_arguments(self):
        self.survey()
        self.survey()
        first = self.get("/usage", limit=1)
        second = self.get("/usage", limit=1, before=first["nextBefore"])
        self.assertEqual(first["surveyCount"], 2)
        self.assertTrue(first["hasMore"])
        self.assertFalse(second["hasMore"])
        self.assertNotEqual(first["surveys"][0]["surveyId"], second["surveys"][0]["surveyId"])
        for query in ({"limit": "0"}, {"limit": "101"}, {"limit": "1.5"}, {"before": "invalid"}, {"versionId": ""}):
            self.assertEqual(self.browser.get(self.base + "/usage", query_string=query).status_code, 400)

    def test_archived_source_preserves_historical_stats(self):
        survey = self.survey()
        self.answer(survey, [30])
        self.db.questions.update_one({"_id": ObjectId(self.qid)}, {"$set": {"status": "archived"}})
        self.assertEqual(self.get()["answerCount"], 1)

    def test_schema_indexes_repeat_initialization_and_large_number_mean(self):
        survey = self.survey()
        self.answer(survey, [10])
        self.initialize()
        self.assertEqual(self.get()["answerCount"], 1)
        self.assertIn("owned_question_usage", self.db.surveys.index_information())
        with self.assertRaises(WriteError):
            self.db.question_statistics_events.insert_one({"questionId": ObjectId(self.qid)})
        v2 = self.version()
        body = self.config_body([self.vid, v2])
        event = self.configure(body)["event"]
        doc = self.db.question_statistics_events.find_one({"_id": ObjectId(event["id"])})
        doc.pop("_id")
        with self.assertRaises(DuplicateKeyError):
            self.db.question_statistics_events.insert_one(doc)
        self.assertEqual(stats.summarize({"type": "number"}, [1e308, 1e308], None)["mean"], 1e308)

    def test_real_submission_anonymous_and_repeated_keeps_source_identity(self):
        sid, instances = self.survey([self.vid, self.vid])
        response = self.browser.post("/api/surveys/" + str(sid) + "/publish")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.as_user(self.recipient)
        for value in (10, 20):
            response = self.browser.post("/api/surveys/" + str(sid) + "/responses", json={
                "anonymous": True, "answers": {str(iid): value for iid in instances}})
            self.assertEqual(response.status_code, 201, response.get_json())
        for response in self.db.responses.find({"surveyId": sid}):
            self.assertNotIn("respondentId", response)
            self.assertEqual(response["answers"][0]["sourceQuestionId"], ObjectId(self.qid))
        self.as_user(self.owner)
        result = self.get()
        self.assertEqual((result["submissionCount"], result["answerCount"]), (2, 4))
        self.assertEqual(result["versions"][0]["mean"], 15)

    def test_independent_copy_answers_do_not_merge_into_original(self):
        created = self.browser.post(self.base + "/copies", json={
            "operationId": "independent-statistics-copy", "versionId": self.vid})
        self.assertEqual(created.status_code, 201, created.get_json())
        copy_result = created.get_json()
        original_qid, original_vid, original_base = self.qid, self.vid, self.base
        self.qid, self.vid = copy_result["question"]["id"], copy_result["version"]["id"]
        survey = self.survey()
        self.answer(survey, [80])
        self.base = "/api/questions/" + self.qid
        self.assertEqual(self.get()["answerCount"], 1)
        self.qid, self.vid, self.base = original_qid, original_vid, original_base
        self.assertEqual(self.get()["answerCount"], 0)

    def test_distribution_can_merge_separately_from_mean(self):
        v2 = self.version()
        self.answer(self.survey(), [10])
        self.answer(self.survey([v2]), [20])
        self.configure(self.config_body([self.vid, v2], metric="numericDistribution"))
        result = self.get(bins="[0,15,30]")
        groups = [g for g in result["overall"] if g["metric"] == "numericDistribution"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["distribution"]["counts"], [1, 1])
        self.assertNotIn("mean", groups[0])
        self.assertEqual(len([g for g in result["overall"] if g["metric"] == "numericMean"]), 2)

    def test_pending_participations_without_responses_do_not_count(self):
        survey = self.survey()
        self.db.participations.insert_one({"surveyId": survey[0], "userId": self.recipient,
                                           "responseId": ObjectId(), "status": "pending",
                                           "createdAt": datetime.now(timezone.utc), "payload": {}})
        self.assertEqual(self.get()["submissionCount"], 0)
