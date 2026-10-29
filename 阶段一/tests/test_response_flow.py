"""不连接数据库的逐题路径测试。"""
import unittest
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from models.response_flow import ResponseFlowError, check_fillable, walk_response_path


class ResponseFlowTests(unittest.TestCase):
    def setUp(self):
        self.q1, self.q2, self.q3 = [ObjectId() for _ in range(3)]
        self.survey = {"status": "published", "questions": [
            {"_id": self.q1, "type": "number", "required": True, "order": 1,
             "jumpRules": [{"condition": {"operator": "gte", "value": 18},
                            "targetQuestionId": self.q3}]},
            {"_id": self.q2, "type": "multiple_choice", "required": False, "order": 2,
             "options": [{"value": "a", "label": "A"}]},
            {"_id": self.q3, "type": "text", "required": True, "order": 3}
        ]}

    def test_empty_prefix_starts_at_first_question(self):
        result = walk_response_path(self.survey, {}, partial=True)
        self.assertEqual(result["nextQuestion"]["_id"], self.q1)
        self.assertEqual(result["visitedQuestionIds"], [])

    def test_jump_and_complete_have_same_path_as_final_submission(self):
        answers = {str(self.q1): 18, str(self.q3): "完成"}
        preview = walk_response_path(self.survey, answers, partial=True)
        final = walk_response_path(self.survey, answers)
        self.assertEqual(preview, final)
        self.assertIsNone(final["nextQuestion"])
        self.assertEqual(final["visitedQuestionIds"], [str(self.q1), str(self.q3)])

    def test_optional_question_requires_explicit_skip_in_partial_mode(self):
        answers = {str(self.q1): 16}
        self.assertEqual(walk_response_path(self.survey, answers, partial=True)
                         ["nextQuestion"]["_id"], self.q2)
        for empty in (None, [], ""):
            with self.subTest(empty=empty):
                answers[str(self.q2)] = empty
                result = walk_response_path(self.survey, answers, partial=True)
                self.assertEqual(result["nextQuestion"]["_id"], self.q3)
                self.assertEqual(len(result["answers"]), 1)

    def test_required_error_identifies_question(self):
        with self.assertRaises(ResponseFlowError) as error:
            walk_response_path(self.survey, {str(self.q1): None}, partial=True)
        self.assertEqual(error.exception.payload["questionId"], str(self.q1))

    def test_skipped_future_and_foreign_answers_are_rejected(self):
        for answers in ({str(self.q3): "抢答"},
                        {str(self.q1): 18, str(self.q2): ["a"]},
                        {str(ObjectId()): 1}, {"bad-id": 1}):
            with self.subTest(answers=answers), self.assertRaises(ResponseFlowError):
                walk_response_path(self.survey, answers, partial=True)

    def test_missing_optional_answers_not_saved_in_final_mode(self):
        result = walk_response_path(self.survey, {str(self.q1): 16, str(self.q3): "结束"})
        self.assertEqual(len(result["answers"]), 2)

    def test_shared_availability_checks(self):
        now = datetime.now(timezone.utc)
        for status in ("draft", "closed"):
            with self.subTest(status=status), self.assertRaises(ResponseFlowError):
                check_fillable({"status": status})
        for deadline in (now, (now - timedelta(seconds=1)).replace(tzinfo=None)):
            with self.subTest(deadline=deadline), self.assertRaises(ResponseFlowError):
                check_fillable({"status": "published", "deadline": deadline}, now=now)
        check_fillable({"status": "published", "deadline": now + timedelta(seconds=1)}, now=now)


if __name__ == "__main__":
    unittest.main()
