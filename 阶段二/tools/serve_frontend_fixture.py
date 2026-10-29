"""Serve only a disposable database selected by the browser-check runner."""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if not re.fullmatch(r"questionnaire_test_[a-f0-9]{32}", os.environ.get("MONGO_DATABASE", "")):
    raise RuntimeError("Refusing to serve frontend test against a non-disposable database")

import init_schema
from app import create_app
from werkzeug.serving import run_simple

for collection in ("users", "surveys", "responses", "participations"):
    init_schema.apply_validator(collection, getattr(init_schema, collection + "_validator"))
init_schema.init_database()
init_schema.initialize_library(init_schema.db)
run_simple("127.0.0.1", int(os.environ["FRONTEND_PORT"]), create_app(), threaded=True, use_reloader=False)
