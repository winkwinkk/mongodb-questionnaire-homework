"""Read-only source inventory and optional MongoDB metadata inspection.

Never runs init_schema, creates indexes, reads answers, or changes database data.
JSON is written to stdout; redirect it explicitly to retain a report.
"""
import argparse
import ast
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


COLLECTIONS = (
    "users", "surveys", "responses", "participations", "questions",
    "question_versions", "question_shares", "question_banks", "question_bank_items", "question_version_operations",
)


def literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing literal assignment: {name}")


def source_report(root):
    files = []
    paths = [root / name for name in ("app.py", "init_schema.py", "start.ps1", "requirements.txt")]
    for folder in ("models", "routes", "templates", "static", "tests"):
        paths.extend(path for path in (root / folder).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    for path in sorted(paths):
        files.append({"path": path.relative_to(root).as_posix(),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    test_methods = {}
    for path in sorted((root / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        test_methods[path.name] = sum(
            isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
            for node in ast.walk(tree)
        )
    return {
        "files": files,
        "testDefinitionCounts": test_methods,
        "testCountNote": "AST definitions only; inherited unittest methods may run more than once. See execution logs for actual counts.",
        "schemaDefinitions": {
            name: literal_assignment(root / "init_schema.py", name + "_validator")
            for name in COLLECTIONS[:4]
        },
        "databaseDefault": "questionnaire_system",
        "databaseDefaultSource": "models/database.py (batch-1 reviewed default)",
        "configuredDatabase": os.environ.get("MONGO_DATABASE", "questionnaire_system"),
    }


def database_report():
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    client = MongoClient(os.environ.get("MONGO_URI", "mongodb://localhost:27017/"),
                         serverSelectionTimeoutMS=2000, connectTimeoutMS=2000,
                         socketTimeoutMS=2000)
    report = {"reachable": False, "metadataInspected": False}
    try:
        hello = client.admin.command("hello")
        report.update({"reachable": True, "replicaSet": bool(hello.get("setName")),
                       "mongos": hello.get("msg") == "isdbgrid",
                       "sessionsAdvertised": "logicalSessionTimeoutMinutes" in hello,
                       "transactionsVerified": False})
        database = client[os.environ.get("MONGO_DATABASE", "questionnaire_system")]
        present = set(database.list_collection_names())
        report["collections"] = {}
        for name in COLLECTIONS:
            if name not in present:
                report["collections"][name] = {"exists": False}
                continue
            options = database[name].options()
            indexes = []
            for index in database[name].list_indexes():
                indexes.append({field: index[field] for field in
                                ("name", "key", "unique", "partialFilterExpression")
                                if field in index})
            report["collections"][name] = {"exists": True, "options": options,
                                            "indexes": indexes}
        report["metadataInspected"] = True
    except PyMongoError as error:
        # Error text may contain connection credentials or hostnames. Do not emit it.
        report["errorType"] = type(error).__name__
    finally:
        client.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mongo", action="store_true", help="Inspect deployment and collection metadata")
    args = parser.parse_args()
    root = args.root.resolve()
    report = {"generatedAt": datetime.now(timezone.utc).isoformat(), "root": str(root),
              "source": source_report(root),
              "database": database_report() if args.mongo else {"requested": False}}
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if not args.mongo or report["database"].get("metadataInspected") else 2


if __name__ == "__main__":
    sys.exit(main())
