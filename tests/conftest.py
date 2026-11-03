import json
import shutil
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"

MCQ = {"type": "mcq", "question": "What does erp.shape show?", "options": ["Rows and columns", "Column names",
       "The first rows", "The data types"], "answer": 0, "explanation": "shape is (rows, columns)."}


class FakeLLM:
    """An OpenAI-compatible server that records prompts and answers with canned replies."""

    def __init__(self):
        self.requests = []
        self.mode = "ok"            # "ok" | "bad_key" | "prose_then_json" | "never_json" | "cut"
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, obj):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.endswith("/models"):
                    return self._send(200, {"data": [{"id": "fake-small"}, {"id": "fake-large"}]})
                self._send(404, {"error": {"message": "no"}})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                fake.requests.append({"auth": self.headers.get("Authorization"), "body": body})
                if fake.mode == "bad_key":
                    return self._send(401, {"error": {"message": "Incorrect API key provided"}})
                prompt = "\n".join(m["content"] for m in body["messages"])
                wants_json = "Reply with only the JSON object" in prompt
                if wants_json and fake.mode == "never_json":
                    text = "Sorry, here is some prose."
                elif wants_json and fake.mode == "prose_then_json" and "was not valid JSON" not in prompt:
                    text = "Here you go!"
                elif wants_json:
                    text = "```json\n" + json.dumps(MCQ) + "\n```"
                elif "single word: ready" in prompt:
                    text = "ready"
                else:
                    text = "**Fake explanation.** The cell reads the ERP payments into a DataFrame called `erp`."
                finish = "length" if fake.mode == "cut" and not wants_json else "stop"
                self._send(200, {"choices": [{"message": {"role": "assistant", "content": text},
                                              "finish_reason": finish}]})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def prompts(self):
        return ["\n".join(m["content"] for m in r["body"]["messages"]) for r in self.requests]


@pytest.fixture
def fake_llm():
    f = FakeLLM()
    yield f
    f.httpd.shutdown()


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    d = tmp_path / "config"
    monkeypatch.setenv("NT_CONFIG_DIR", str(d))
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AILK_LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    return d


class Client:
    def __init__(self, app):
        self.app = app
        self.base = f"http://127.0.0.1:{app.port}"

    def call(self, method, path, body=None, token=True, headers=None, raw=None):
        h = {}
        if token:
            h["X-NT-Token"] = self.app.token
        data = None
        if raw is not None:
            data = raw
        elif body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                ct = r.headers.get("Content-Type", "")
                payload = r.read()
                return r.status, (json.loads(payload) if "json" in ct else payload.decode())
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, json.loads(payload)
            except Exception:
                return e.code, payload.decode()


@pytest.fixture
def tutor(tmp_path, cfg):
    from notebook_tutor.server import serve
    root = tmp_path / "work"
    root.mkdir()
    shutil.copy(DATA / "kit_data_formats_short.ipynb", root / "data_formats_short.ipynb")
    app, httpd = serve(root, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield Client(app)
    app.shutdown()
    httpd.shutdown()
    httpd.server_close()


def use_fake(client, fake):
    status, out = client.call("PUT", "/api/settings", {"provider": "openai-compatible", "base_url": fake.url,
                                                        "model_quick": "fake-small", "model_thorough": "fake-large",
                                                        "api_key": "sk-test-SECRET-1234"})
    assert status == 200, out
    return out
