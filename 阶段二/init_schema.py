
from pymongo.errors import CollectionInvalid, PyMongoError

from models.database import db, client, init_database
from models.participation_model import recover_pending_participations
from models.library_schema import initialize_library
from models.library_model import recover_initial_questions
from models.version_model import recover_version_operations


# 1. 用户集合：检查用户名和密码哈希
users_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["username", "passwordHash", "createdAt"],
        "properties": {
            "username": {
                "bsonType": "string",
                "minLength": 1,
                "description": "用户名不能为空"
            },
            "passwordHash": {
                "bsonType": "string",
                "minLength": 1
            },
            "createdAt": {
                "bsonType": "date"
            }
        }
    }
}


# 2. 问卷集合：检查基本字段和嵌入式题目
surveys_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "ownerId",
            "title",
            "description",
            "anonymousAllowed",
            "status",
            "questions",
            "createdAt",
            "updatedAt"
        ],
        "properties": {
            "ownerId": {
                "bsonType": "objectId"
            },
            "title": {
                "bsonType": "string",
                "minLength": 1
            },
            "description": {
                "bsonType": "string"
            },
            "anonymousAllowed": {
                "bsonType": "bool"
            },
            "allowMultipleResponses": {"bsonType": "bool"},
            "status": {
                "bsonType": "string",
                "enum": ["draft", "published", "closed"]
            },
            "deadline": {
                "bsonType": ["date", "null"]
            },
            "createdAt": {
                "bsonType": "date"
            },
            "updatedAt": {
                "bsonType": "date"
            },
            "questions": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "required": [
                        "_id", "type", "title", "required",
                        "order"
                    ],
                    "oneOf": [
                        {"required": ["sourceQuestionId", "sourceVersionId"]},
                        {"not": {"anyOf": [{"required": ["sourceQuestionId"]},
                                           {"required": ["sourceVersionId"]}]}}
                    ],
                    "properties": {
                        "sourceQuestionId": {"bsonType": "objectId"},
                        "sourceVersionId": {"bsonType": "objectId"},
                        "unit": {"bsonType": "string"},
                        "semanticDescription": {"bsonType": "string"},
                        "_id": {
                            "bsonType": "objectId"
                        },
                        "type": {
                            "bsonType": "string",
                            "enum": [
                                "single_choice",
                                "multiple_choice",
                                "text",
                                "number"
                            ]
                        },
                        "title": {
                            "bsonType": "string",
                            "minLength": 1
                        },
                        "required": {
                            "bsonType": "bool"
                        },
                        "order": {
                            "bsonType": ["int", "long", "double"]
                        },
                        "options": {
                            "bsonType": "array",
                            "items": {
                                "bsonType": "object",
                                "required": ["value", "label"],
                                "properties": {
                                    "value": {
                                        "bsonType": "string"
                                    },
                                    "label": {
                                        "bsonType": "string"
                                    }
                                }
                            }
                        },
                        "validation": {
                            "bsonType": "object"
                        },
                        "jumpRules": {
                            "bsonType": "array"
                        }
                    }
                }
            }
        }
    }
}


# 3. 回答集合：检查提交记录和答案结构
responses_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["surveyId", "answers", "submittedAt"],
        "properties": {
            "surveyId": {
                "bsonType": "objectId"
            },
            "respondentId": {
                "bsonType": "objectId"
            },
            "submittedAt": {
                "bsonType": "date"
            },
            "answers": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "required": ["questionId", "value"],
                    "oneOf": [
                        {"required": ["sourceQuestionId", "sourceVersionId"]},
                        {"not": {"anyOf": [{"required": ["sourceQuestionId"]},
                                           {"required": ["sourceVersionId"]}]}}
                    ],
                    "properties": {
                        "sourceQuestionId": {"bsonType": "objectId"},
                        "sourceVersionId": {"bsonType": "objectId"},
                        "questionId": {
                            "bsonType": "objectId"
                        },
                        "value": {
                            "bsonType": [
                                "string",
                                "int",
                                "long",
                                "double",
                                "decimal",
                                "array"
                            ]
                        }
                    }
                }
            }
        }
    }
}


participations_validator = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["surveyId", "userId", "responseId", "status", "createdAt"],
        "properties": {
            "surveyId": {"bsonType": "objectId"},
            "userId": {"bsonType": "objectId"},
            "responseId": {"bsonType": "objectId"},
            "status": {"enum": ["pending", "committed"]},
            "payload": {"bsonType": "object"},
            "createdAt": {"bsonType": "date"},
            "submittedAt": {"bsonType": "date"}
        }
    }
}


def apply_validator(collection_name, validator):
    """创建集合或更新已有集合的校验规则，不删除现有数据。"""
    try:
        db.create_collection(
            collection_name,
            validator=validator,
            validationLevel="strict",
            validationAction="error"
        )
    except CollectionInvalid:
        pass
    else:
        print(f"{collection_name}：集合及校验规则创建成功")
        return

    db.command({
        "collMod": collection_name,
        "validator": validator,
        "validationLevel": "strict",
        "validationAction": "error"
    })
    print(f"{collection_name}：校验规则配置成功")


def backfill_participations():
    """仅为可识别用户的旧回答补建参与记录，不改动历史答案。"""
    for response in db.responses.find({"respondentId": {"$exists": True}}).sort("submittedAt", 1):
        survey = db.surveys.find_one({"_id": response["surveyId"]})
        if not survey or survey.get("allowMultipleResponses", False):
            continue
        key = {"surveyId": response["surveyId"], "userId": response["respondentId"]}
        db.participations.update_one(key, {"$setOnInsert": {
            **key, "responseId": response["_id"], "status": "committed",
            "createdAt": response["submittedAt"], "submittedAt": response["submittedAt"]
        }}, upsert=True)


def main():
    try:
        client.admin.command("ping")

        apply_validator("users", users_validator)
        apply_validator("surveys", surveys_validator)
        apply_validator("responses", responses_validator)
        apply_validator("participations", participations_validator)

        init_database()
        initialize_library(db)
        recover_initial_questions()
        recover_version_operations()
        backfill_participations()
        recover_pending_participations()
        print("原有集合、题目版本、共享、题库及操作回执初始化完成！")

    except PyMongoError as exc:
        print(f"数据库操作失败：{exc}")
        raise SystemExit(1)

    finally:
        client.close()


if __name__ == "__main__":
    main()
