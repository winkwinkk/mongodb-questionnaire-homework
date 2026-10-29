"""Run the suite against a private, temporary localhost MongoDB instance.

Requires a local mongod executable. Does not use the configured business URI.
"""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from pymongo import MongoClient
from bson.codec_options import CodecOptions
from pymongo.errors import PyMongoError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongod", default=shutil.which("mongod"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.mongod:
        parser.error("mongod executable not found")
    root = Path(__file__).resolve().parents[1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="questionnaire-batch2-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([args.mongod, "--dbpath", directory, "--port", str(port),
                                    "--bind_ip", "127.0.0.1", "--logpath", str(Path(directory) / "mongod.log")],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        client = MongoClient(f"mongodb://127.0.0.1:{port}/", serverSelectionTimeoutMS=500,
                             connectTimeoutMS=500, unicode_decode_error_handler="replace")
        verified = False
        try:
            for _ in range(30):
                if process.poll() is not None:
                    raise RuntimeError("Private mongod exited during startup")
                try:
                    status = client.admin.command("serverStatus", codec_options=CodecOptions(unicode_decode_error_handler="replace"))
                    if status["pid"] != process.pid:
                        raise RuntimeError("Port is not served by the private mongod")
                    verified = True
                    break
                except PyMongoError:
                    time.sleep(0.2)
            if not verified:
                raise RuntimeError("Private mongod did not become ready")
            env = os.environ.copy()
            env.update({"MONGO_URI": f"mongodb://127.0.0.1:{port}/", "RUN_MONGO_TESTS": "1",
                        "MONGO_DATABASE": "questionnaire_stage2_isolated_guard", "PYTHONIOENCODING": "utf-8"})
            result = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                                    cwd=root, env=env, capture_output=True, text=True, encoding="utf-8")
            header = (f"Private MongoDB version: {status['version']}\n"
                      "Deployment: standalone; random localhost port and temporary data directory\n"
                      "RUN_MONGO_TESTS=1; all integration tests use random disposable databases\n\n")
            args.output.write_text(header + result.stdout + "\n" + result.stderr, encoding="utf-8")
            print(result.stderr[-500:])
            print(f"Full log: {args.output}")
            return result.returncode
        finally:
            if verified and process.poll() is None:
                try:
                    client.admin.command("shutdown", force=True)
                except PyMongoError:
                    pass
            client.close()
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
