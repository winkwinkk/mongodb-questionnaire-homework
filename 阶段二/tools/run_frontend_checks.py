"""Run real-browser checks against owned temporary MongoDB and Flask processes."""
import argparse
from http.client import HTTPException
import os
from pathlib import Path
import socket
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, ProxyHandler
from uuid import uuid4

from bson.codec_options import CodecOptions
from pymongo import MongoClient
from pymongo.errors import PyMongoError


def free_port():
    # Avoid Windows' outbound ephemeral port range while children connect to MongoDB.
    for _ in range(100):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", 18000 + secrets.randbelow(12000)))
                return sock.getsockname()[1]
            except OSError:
                pass
    raise RuntimeError("No private test port available")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongod", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--packages", required=True)
    parser.add_argument("--browser", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/stage2-batch6-browser"
    output.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="questionnaire-ui-") as temporary:
        port, web_port = free_port(), free_port()
        while web_port == port:
            web_port = free_port()
        process = subprocess.Popen([args.mongod, "--dbpath", temporary, "--port", str(port), "--bind_ip", "127.0.0.1",
                                    "--logpath", str(Path(temporary) / "mongod.log")],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        client = MongoClient(f"mongodb://127.0.0.1:{port}/", serverSelectionTimeoutMS=500, connectTimeoutMS=500)
        server = None
        try:
            for _ in range(40):
                if process.poll() is not None:
                    raise RuntimeError("Private mongod exited")
                try:
                    status = client.admin.command("serverStatus", codec_options=CodecOptions(unicode_decode_error_handler="replace"))
                    if status["pid"] != process.pid:
                        raise RuntimeError("MongoDB PID mismatch")
                    break
                except PyMongoError:
                    time.sleep(.2)
            else:
                raise RuntimeError("Private MongoDB did not start")
            env = {**os.environ, "MONGO_URI": f"mongodb://127.0.0.1:{port}/",
                   "MONGO_DATABASE": "questionnaire_test_" + uuid4().hex,
                   "FLASK_SECRET_KEY": uuid4().hex, "FRONTEND_PORT": str(web_port),
                   "FRONTEND_BASE_URL": f"http://127.0.0.1:{web_port}", "NODE_PATH": args.packages,
                   "FRONTEND_BROWSER": args.browser, "PYTHONIOENCODING": "utf-8",
                   "FRONTEND_ARTIFACT_DIR": str(output)}
            with (output / "server.txt").open("w", encoding="utf-8") as server_log:
                server = subprocess.Popen([sys.executable, "-B", "tools/serve_frontend_fixture.py"], cwd=root, env=env,
                                          stdout=server_log, stderr=server_log, creationflags=flags)
                for _ in range(80):
                    if server.poll() is not None:
                        raise RuntimeError("Private Flask process exited; inspect server.txt")
                    try:
                        with build_opener(ProxyHandler({})).open(env["FRONTEND_BASE_URL"] + "/api/health", timeout=.5) as response:
                            if response.status == 200:
                                break
                    except (OSError, HTTPException):
                        time.sleep(.15)
                else:
                    raise RuntimeError("Private Flask process did not start")
                result = subprocess.run([args.node, "tests/frontend_stage2.cjs"], cwd=root, env=env,
                                        capture_output=True, text=True, encoding="utf-8", timeout=360)
                (output / "results.txt").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
                print(result.stdout[-1500:] + result.stderr[-2000:])
                return result.returncode
        finally:
            if server is not None and server.poll() is None:
                server.terminate()
                server.wait(timeout=10)
            if process.poll() is None:
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
