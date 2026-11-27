"""AC-7: server apply path against a stub HTTP server (no LightRAG server needed)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import SAMPLE_GRAPH_DIR

from lightrag_dedupe.cli import main


class Stub:
    """Records every request; can answer 409 on the n-th merge and pretend names are missing."""

    def __init__(self):
        self.requests: list[dict] = []
        self.busy_on_merge: int | None = None
        self.missing: set[str] = set()
        self.merge_count = 0
        self.server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_address[1]}"


@pytest.fixture
def stub():
    state = Stub()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            name = parse_qs(parsed.query).get("name", [""])[0]
            state.requests.append({"method": "GET", "path": parsed.path, "name": name, "key": self.headers.get("X-API-Key")})
            self._send(200, {"exists": name not in state.missing})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            state.requests.append({"method": "POST", "path": self.path, "body": body, "key": self.headers.get("X-API-Key")})
            state.merge_count += 1
            if state.busy_on_merge == state.merge_count:
                self._send(409, {"detail": "Pipeline is busy"})
            else:
                self._send(200, {"status": "success"})

        def log_message(self, *args):  # keep test output clean
            pass

    state.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=state.server.serve_forever, daemon=True)
    thread.start()
    yield state
    state.server.shutdown()
    state.server.server_close()
    thread.join(timeout=5)


def _merges(state):
    return [r for r in state.requests if r["method"] == "POST"]


def test_request_body_path_and_api_key(stub, sample_plan, tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTRAG_API_KEY", "secret-test-key")
    plan = json.loads(sample_plan.read_text(encoding="utf-8"))
    expected = [
        {"entities_to_change": g["sources"], "entity_to_change_into": g["target"]} for g in plan["groups"] if g["apply"]
    ]
    log = tmp_path / "log.jsonl"
    rc = main(["apply", str(sample_plan), "--server", stub.url, "--yes", "--no-backup", "--log", str(log), "--lang", "en"])
    assert rc == 0
    posts = _merges(stub)
    assert [p["path"] for p in posts] == ["/graph/entities/merge"] * 3
    assert [p["body"] for p in posts] == expected
    assert {r["key"] for r in stub.requests} == {"secret-test-key"}
    # the pre-check asked the server about every source name, exactly as written
    asked = {r["name"] for r in stub.requests if r["method"] == "GET"}
    assert {"OpenAI Inc.", "오픈AI의", "(주)카카오"} <= asked
    assert len(log.read_text(encoding="utf-8").splitlines()) == 3


def test_no_api_key_header_when_unset(stub, sample_plan, tmp_path):
    assert main(["apply", str(sample_plan), "--server", stub.url, "--yes", "--no-backup", "--log", str(tmp_path / "l.jsonl")]) == 0
    assert {r["key"] for r in stub.requests} == {None}


def test_409_stops_immediately_and_keeps_earlier_successes(stub, sample_plan, tmp_path, capsys):
    stub.busy_on_merge = 2
    log = tmp_path / "log.jsonl"
    rc = main(["apply", str(sample_plan), "--server", stub.url, "--yes", "--no-backup", "--log", str(log), "--lang", "en"])
    assert rc == 4
    assert len(_merges(stub)) == 2  # the third group was never sent
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [e["status"] for e in entries] == ["done", "failed"]
    assert "busy" in capsys.readouterr().err
    # run again once the server is free: only the unfinished groups are sent
    stub.busy_on_merge = None
    stub.requests.clear()
    assert main(["apply", str(sample_plan), "--server", stub.url, "--yes", "--no-backup", "--log", str(log)]) == 0
    assert len(_merges(stub)) == 2


def test_remote_server_needs_working_dir_or_no_backup(stub, sample_plan, capsys):
    assert main(["apply", str(sample_plan), "--server", stub.url, "--yes", "--lang", "en"]) == 2
    assert "without a backup" in capsys.readouterr().err
    assert stub.requests == []  # refused before any request


def test_server_with_working_dir_makes_a_backup(stub, sample_plan, tmp_path):
    import shutil

    wd = tmp_path / "rag"
    shutil.copytree(SAMPLE_GRAPH_DIR, wd)
    backups = tmp_path / "backups"
    rc = main(["apply", str(sample_plan), "--server", stub.url, "--working-dir", str(wd), "--backup-dir", str(backups), "--yes", "--log", str(tmp_path / "l.jsonl")])
    assert rc == 0
    assert len(list(backups.iterdir())) == 1
    assert len(_merges(stub)) == 3


def test_missing_source_on_server_stops_before_any_merge(stub, sample_plan, tmp_path, capsys):
    stub.missing = {"openai"}
    rc = main(["apply", str(sample_plan), "--server", stub.url, "--yes", "--no-backup", "--log", str(tmp_path / "l.jsonl"), "--lang", "en"])
    assert rc == 3
    assert _merges(stub) == []
    assert "openai" in capsys.readouterr().err


def test_dry_run_with_server_sends_no_merge(stub, sample_plan, capsys):
    assert main(["apply", str(sample_plan), "--server", stub.url, "--lang", "en"]) == 0
    assert _merges(stub) == []
    assert "POST /graph/entities/merge" in capsys.readouterr().out


def test_unreachable_server_and_bad_url(sample_plan, capsys):
    assert main(["apply", str(sample_plan), "--server", "http://127.0.0.1:1", "--lang", "en"]) == 4
    assert "Is the LightRAG server running" in capsys.readouterr().err
    assert main(["apply", str(sample_plan), "--server", "localhost:9621", "--lang", "en"]) == 2
