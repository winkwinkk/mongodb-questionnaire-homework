"""Incremental library, version, sharing and bank validators; never drop data."""
from pymongo.errors import CollectionInvalid


def schema(required, properties):
    return {"$jsonSchema": {"bsonType": "object", "required": required, "properties": properties}}


OID = {"bsonType": "objectId"}
DATE = {"bsonType": "date"}
STRING = {"bsonType": "string"}
POSITIVE = {"bsonType": ["int", "long"], "minimum": 1}
NULLABLE_ID = {"bsonType": ["objectId", "null"]}
CONTENT = {"bsonType": "object", "required": ["type", "title", "required", "unit", "semanticDescription"],
           "properties": {"type": {"enum": ["single_choice", "multiple_choice", "text", "number"]},
                          "title": {"bsonType": "string", "minLength": 1},
                          "required": {"bsonType": "bool"}, "options": {"bsonType": "array"},
                          "validation": {"bsonType": "object"}, "unit": STRING,
                          "semanticDescription": STRING}, "additionalProperties": False}

QUESTIONS_VALIDATOR = schema(
    ["ownerId", "title", "status", "versionCounter", "operationId", "createdAt", "updatedAt"],
    {"ownerId": OID, "title": {"bsonType": "string", "minLength": 1},
     "status": {"enum": ["creating", "active", "archived"]}, "versionCounter": POSITIVE,
     "operationId": {"bsonType": "string", "minLength": 8, "maxLength": 128},
     "currentVersionId": OID, "initialVersionId": OID, "currentVersionNumber": POSITIVE,
     "pendingVersion": {"bsonType": "object"}, "createdAt": DATE, "updatedAt": DATE})
QUESTIONS_VALIDATOR["$jsonSchema"]["properties"].update({
    "versionRevision": {"bsonType": ["int", "long"], "minimum": 0},
    "operationSequence": {"bsonType": ["int", "long"], "minimum": 0},
    "pendingVersionOperation": {"bsonType": "object", "required": ["_id", "operationId", "phase"],
                                "properties": {"_id": OID, "operationId": STRING,
                                               "phase": {"enum": ["prepared", "decided"]}}}})
QUESTIONS_VALIDATOR["$jsonSchema"]["oneOf"] = [
    {"properties": {"status": {"enum": ["creating"]}}, "required": ["pendingVersion"]},
    {"properties": {"status": {"enum": ["active", "archived"]}},
     "required": ["currentVersionId", "currentVersionNumber"]}]

VERSIONS_VALIDATOR = schema(
    ["questionId", "versionNumber", "content", "createdBy", "createdAt", "changeNote", "statisticsGroups"],
    {"questionId": OID, "versionNumber": POSITIVE, "content": CONTENT,
     "basedOnVersionId": NULLABLE_ID, "restoredFromVersionId": NULLABLE_ID,
     "copiedFromQuestionId": NULLABLE_ID, "copiedFromVersionId": NULLABLE_ID,
     "createdBy": OID, "createdAt": DATE, "changeNote": STRING,
     "statisticsGroups": {"bsonType": "object"}})

OPERATIONS_VALIDATOR = schema(
    ["questionId", "operationId", "actorId", "kind", "versionId", "versionNumber", "expectedVersionId",
     "expectedRevision", "outcome", "createdAt", "completedAt"],
    {"questionId": OID, "operationId": {"bsonType": "string", "minLength": 8, "maxLength": 128},
     "actorId": OID, "kind": {"enum": ["edit", "restore", "select"]}, "versionId": OID,
     "versionNumber": POSITIVE, "expectedVersionId": OID,
     "expectedRevision": {"bsonType": ["int", "long"], "minimum": 0},
     "outcome": {"enum": ["adopted", "branch", "selected", "conflict"]}, "changeNote": STRING,
     "createdAt": DATE, "completedAt": DATE})

SHARES_VALIDATOR = schema(
    ["questionId", "ownerId", "recipientUserId", "status", "createdAt", "revokedAt"],
    {"questionId": OID, "ownerId": OID, "recipientUserId": OID,
     "status": {"enum": ["active", "revoked"]}, "createdAt": DATE,
     "revokedAt": {"bsonType": ["date", "null"]}, "displayTitleSnapshot": STRING})
SHARES_VALIDATOR["$jsonSchema"]["oneOf"] = [
    {"properties": {"status": {"enum": ["active"]}, "revokedAt": {"bsonType": "null"}}},
    {"properties": {"status": {"enum": ["revoked"]}, "revokedAt": DATE}}]

BANKS_VALIDATOR = schema(
    ["ownerId", "name", "description", "status", "revision", "createdAt", "updatedAt"],
    {"ownerId": OID, "name": {"bsonType": "string", "minLength": 1, "maxLength": 200},
     "description": STRING, "status": {"enum": ["active", "deleted"]},
     "revision": {"bsonType": ["int", "long"], "minimum": 0}, "createdAt": DATE, "updatedAt": DATE})

BANK_ITEMS_VALIDATOR = schema(
    ["bankId", "questionId", "defaultVersionId", "addedBy", "addedAt", "displayTitleSnapshot", "revision"],
    {"bankId": OID, "questionId": OID, "defaultVersionId": OID, "addedBy": OID, "addedAt": DATE,
     "displayTitleSnapshot": STRING, "revision": {"bsonType": ["int", "long"], "minimum": 0}})


STATISTICS_EVENTS_VALIDATOR = schema(
    ["questionId", "operationId", "actorId", "createdAt", "revision", "expectedRevision",
     "previousEventId", "groups", "reason", "warnings"],
    {"questionId": OID, "operationId": {"bsonType": "string", "minLength": 8, "maxLength": 128},
     "actorId": OID, "createdAt": DATE, "revision": POSITIVE,
     "expectedRevision": {"bsonType": ["int", "long"], "minimum": 0},
     "previousEventId": NULLABLE_ID, "reason": {"bsonType": "string", "minLength": 1, "maxLength": 2000},
     "groups": {"bsonType": "array", "maxItems": 100, "items": {
         "bsonType": "object", "required": ["metric", "groupId", "versionIds"],
         "properties": {"metric": {"enum": ["choiceDistribution", "numericMean", "numericDistribution", "textResponses"]},
                        "groupId": {"bsonType": "string", "minLength": 1, "maxLength": 100},
                        "versionIds": {"bsonType": "array", "minItems": 2, "maxItems": 100,
                                       "uniqueItems": True, "items": STRING}}, "additionalProperties": False}},
     "warnings": {"bsonType": "array"}})
QUESTIONS_VALIDATOR["$jsonSchema"]["properties"].update({
    "statisticsRevision": {"bsonType": ["int", "long"], "minimum": 0}, "statisticsEventId": OID})


def initialize_library(database):
    for name, validator in (("questions", QUESTIONS_VALIDATOR), ("question_versions", VERSIONS_VALIDATOR),
                            ("question_version_operations", OPERATIONS_VALIDATOR),
                            ("question_shares", SHARES_VALIDATOR), ("question_banks", BANKS_VALIDATOR),
                            ("question_bank_items", BANK_ITEMS_VALIDATOR),
                            ("question_statistics_events", STATISTICS_EVENTS_VALIDATOR)):
        try:
            database.create_collection(name, validator=validator, validationLevel="strict", validationAction="error")
        except CollectionInvalid:
            database.command({"collMod": name, "validator": validator,
                              "validationLevel": "strict", "validationAction": "error"})
    database.questions.create_index([("ownerId", 1), ("operationId", 1)], unique=True,
                                    name="unique_question_creation_operation")
    database.questions.create_index([("ownerId", 1), ("updatedAt", -1)], name="questions_by_owner")
    database.question_versions.create_index([("questionId", 1), ("versionNumber", 1)], unique=True,
                                            name="unique_question_version")
    database.question_versions.create_index([("questionId", 1), ("createdAt", -1)], name="question_version_history")
    database.question_versions.create_index([("questionId", 1), ("operationId", 1)], unique=True,
                                            partialFilterExpression={"operationId": {"$exists": True}},
                                            name="unique_version_operation")
    database.question_version_operations.create_index([("questionId", 1), ("operationId", 1)], unique=True,
                                                       name="unique_version_operation_receipt")
    database.question_shares.create_index([("questionId", 1), ("recipientUserId", 1)], unique=True,
                                          partialFilterExpression={"status": "active"}, name="unique_active_question_share")
    database.question_shares.create_index([("recipientUserId", 1), ("status", 1)], name="received_question_shares")
    database.question_shares.create_index([("questionId", 1), ("status", 1)], name="question_share_history")
    database.question_banks.create_index([("ownerId", 1)], name="banks_by_owner")
    database.question_bank_items.create_index([("bankId", 1), ("questionId", 1)], unique=True,
                                              name="unique_bank_question")
    database.question_bank_items.create_index([("questionId", 1)], name="banks_by_question")
    database.question_statistics_events.create_index([("questionId", 1), ("operationId", 1)], unique=True,
                                                      name="unique_statistics_operation")
    database.question_statistics_events.create_index([("questionId", 1), ("revision", -1)],
                                                      name="statistics_event_candidates")
    database.surveys.create_index([("ownerId", 1), ("questions.sourceQuestionId", 1)],
                                  name="owned_question_usage")
    database.surveys.create_index([("ownerId", 1), ("questions.sourceVersionId", 1)],
                                  name="owned_version_usage")
