"""后端修复回归测试；使用替身隔离数据库，不写入真实数据。"""
import contextlib
import copy
import io
import unittest
from unittest.mock import patch

from bson import ObjectId
from pymongo.errors import CollectionInvalid, ConnectionFailure

import init_schema
from app import create_app
from models.answer_validator import validate_answer
from models.jump_model import add_jump_rule
from models.question_model import add_question
import test_answer_validator
import test_jump_engine


USER_ID = "000000000000000000000001"
SURVEY_ID = "000000000000000000000002"


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.question = {
            "type": "multiple_choice",
            "required": True,
            "options": [
                {"value": "a", "label": "A"},
                {"value": "b", "label": "B"}
            ],
            "validation": {"minSelections": 0, "maxSelections": 2}
        }

    def test_required_multiple_choice_rejects_empty_array(self):
        self.assertIsNotNone(validate_answer(self.question, []))

    def test_optional_multiple_choice_can_be_skipped(self):
        self.question["required"] = False
        self.question["validation"]["minSelections"] = 2
        for value in ([], None, ""):
            with self.subTest(value=value):
                self.assertIsNone(validate_answer(self.question, value))

    def test_optional_answer_still_enforces_minimum(self):
        self.question["required"] = False
        self.question["validation"]["minSelections"] = 2
        self.assertIsNotNone(validate_answer(self.question, ["a"]))
        self.assertIsNone(validate_answer(self.question, ["a", "b"]))

    def test_number_integer_and_finite_checks(self):
        question = {"type": "number", "validation": {"integerOnly": True}}
        for value in (18, 18.0, 2 ** 63 - 1, -(2 ** 63)):
            with self.subTest(value=value):
                self.assertIsNone(validate_answer(question, value))
        for value in (True, 18.5, float("nan"), float("inf"), 2 ** 63, 10 ** 400):
            with self.subTest(value=str(value)):
                self.assertIsNotNone(validate_answer(question, value))

    def test_existing_validation_examples(self):
        with contextlib.redirect_stdout(io.StringIO()):
            test_answer_validator.main()

    def test_existing_jump_examples(self):
        with contextlib.redirect_stdout(io.StringIO()):
            test_jump_engine.main()


class InputTests(unittest.TestCase):
    def setUp(self):
        with patch.dict("os.environ", {"FLASK_SECRET_KEY": "test-only-secret"}):
            self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_auth_rejects_non_object_json(self):
        for path in ("/api/register", "/api/login"):
            for body in ([1], [], "invalid", 5, None):
                with self.subTest(path=path, body=body):
                    result = self.client.post(path, json=body)
                    self.assertEqual(result.status_code, 400)
                    self.assertIn("error", result.get_json())

    def test_question_rejects_invalid_input_before_database_access(self):
        with self.client.session_transaction() as session:
            session["user_id"] = USER_ID
        for fields in (
            {"title": None}, {"title": []}, {"type": []},
            {"options": ""}, {"options": False}, {"validation": []},
            {"validation": ""}, {"validation": {"max": float("inf")}},
            {"validation": {"min": 10 ** 400}}
        ):
            body = {"type": "number", "title": "年龄"}
            body.update(fields)
            with self.subTest(fields=fields), patch("models.question_model.db") as db:
                result = self.client.post(
                    f"/api/surveys/{SURVEY_ID}/questions", json=body
                )
                self.assertEqual(result.status_code, 400)
                db.surveys.find_one_and_update.assert_not_called()

    def test_jump_rejects_non_string_operator_before_database_access(self):
        for operator in ([], {}, None, True):
            with self.subTest(operator=operator), patch("models.jump_model.db") as db:
                with self.assertRaises(ValueError):
                    add_jump_rule(SURVEY_ID, USER_ID, USER_ID, operator, 18, SURVEY_ID)
                db.surveys.find_one.assert_not_called()

    def test_add_question_returns_saved_document_and_rejects_non_draft(self):
        # 返回数据库计算出的顺序号，而不是临时的 order=0。
        def updated_survey(query, pipeline, **kwargs):
            question = copy.deepcopy(
                pipeline[0]["$set"]["questions"]["$concatArrays"][1][0]
                ["$mergeObjects"][0]["$literal"]
            )
            question["order"] = 3
            return {"questions": [question]}

        with patch("models.question_model.db") as db:
            db.surveys.find_one_and_update.side_effect = updated_survey
            result = add_question(SURVEY_ID, USER_ID, "text", "$测试标题")
            self.assertEqual(result["order"], 3)
            self.assertEqual(result["title"], "$测试标题")
            db.surveys.update_one.assert_not_called()
            query = db.surveys.find_one_and_update.call_args.args[0]
            self.assertEqual(query["ownerId"], ObjectId(USER_ID))
            self.assertEqual(query["status"], "draft")

            db.surveys.find_one_and_update.side_effect = None
            db.surveys.find_one_and_update.return_value = None
            with self.assertRaises(ValueError):
                add_question(SURVEY_ID, USER_ID, "text", "测试题目")


class InitializationTests(unittest.TestCase):
    def test_missing_collection_created_with_validator(self):
        with patch.object(init_schema, "db") as db:
            init_schema.apply_validator("users", init_schema.users_validator)
            db.create_collection.assert_called_once_with(
                "users", validator=init_schema.users_validator,
                validationLevel="strict", validationAction="error"
            )
            db.command.assert_not_called()

    def test_existing_collection_updated_without_deleting_data(self):
        with patch.object(init_schema, "db") as db:
            db.create_collection.side_effect = CollectionInvalid("already exists")
            init_schema.apply_validator("users", init_schema.users_validator)
            self.assertEqual(db.command.call_args.args[0]["collMod"], "users")
            db.drop_collection.assert_not_called()

    def test_main_initializes_all_schemas_and_indexes(self):
        with patch.object(init_schema, "client") as client, \
                patch.object(init_schema, "apply_validator") as apply, \
                patch.object(init_schema, "backfill_participations") as backfill, \
                patch.object(init_schema, "recover_pending_participations") as recover, \
                patch.object(init_schema, "initialize_library") as library_init, \
                patch.object(init_schema, "recover_initial_questions") as library_recover, \
                patch.object(init_schema, "recover_version_operations") as version_recover, \
                patch.object(init_schema, "init_database") as indexes:
            init_schema.main()
            self.assertEqual([c.args[0] for c in apply.call_args_list],
                             ["users", "surveys", "responses", "participations"])
            indexes.assert_called_once_with()
            library_init.assert_called_once_with(init_schema.db)
            library_recover.assert_called_once_with()
            version_recover.assert_called_once_with()
            backfill.assert_called_once_with()
            recover.assert_called_once_with()
            client.close.assert_called_once_with()

    def test_failure_exits_nonzero_and_closes_client(self):
        with patch.object(init_schema, "client") as client:
            client.admin.command.side_effect = ConnectionFailure("test failure")
            with self.assertRaises(SystemExit) as raised:
                init_schema.main()
            self.assertEqual(raised.exception.code, 1)
            client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
