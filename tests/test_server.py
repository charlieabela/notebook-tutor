import json
import os
import stat

from conftest import MCQ, use_fake


# ------------------------------------------------------------------ access control
def test_api_needs_token(tutor):
    assert tutor.call("GET", "/api/notebooks", token=False)[0] == 401
    assert tutor.call("GET", "/api/notebooks", headers={"X-NT-Token": "wrong"})[0] == 401
    assert tutor.call("GET", "/api/notebooks")[0] == 200


def test_page_needs_token_and_gets_boot_data(tutor):
    status, body = tutor.call("GET", "/", token=False)
    assert status == 401 and "session token" in body
    status, body = tutor.call("GET", "/?t=" + tutor.app.token, token=False)
    assert status == 200
    assert "window.NT_BOOT=" in body and "/static/host.js" in body
    assert body.index("/static/host.js") < body.index("const HOST = window.NBT_HOST")


def test_other_sites_and_rebinding_are_refused(tutor):
    assert tutor.call("GET", "/api/notebooks", headers={"Origin": "https://evil.example"})[0] == 403
    assert tutor.call("GET", "/api/notebooks", headers={"Origin": tutor.base})[0] == 200
    assert tutor.call("GET", "/api/notebooks", headers={"Host": "evil.example:80"})[0] == 403


def test_paths_stay_inside_the_folder(tutor):
    assert tutor.call("GET", "/api/notebook?path=../../etc/passwd")[0] == 403
    assert tutor.call("GET", "/api/notebook?path=/etc/passwd")[0] == 403
    assert tutor.call("PUT", "/api/notebook?path=../x.ipynb", {"text": "{}"})[0] == 403
    assert tutor.call("POST", "/api/upload?folder=..&name=a.csv", raw=b"x")[0] == 403


def test_static_files_and_traversal(tutor):
    import urllib.request
    with urllib.request.urlopen(tutor.base + "/static/host.js") as r:
        assert r.status == 200 and r.headers["Content-Type"].startswith("application/javascript")
    assert tutor.call("GET", "/static/vendor/codemirror/codemirror.js", token=False)[0] == 200
    assert tutor.call("GET", "/static/../server.py", token=False)[0] == 404


# ------------------------------------------------------------------ notebooks and files
def test_list_open_and_save_notebook(tutor):
    status, out = tutor.call("GET", "/api/notebooks")
    assert [n["path"] for n in out["notebooks"]] == ["data_formats_short.ipynb"]
    status, nb = tutor.call("GET", "/api/notebook?path=data_formats_short.ipynb")
    data = json.loads(nb["text"])
    data["cells"][0]["source"] = "# changed"
    assert tutor.call("PUT", "/api/notebook?path=data_formats_short.ipynb", {"text": json.dumps(data)})[0] == 200
    assert json.loads((tutor.app.root / "data_formats_short.ipynb").read_text())["cells"][0]["source"] == "# changed"
    # a broken save never overwrites the file
    assert tutor.call("PUT", "/api/notebook?path=data_formats_short.ipynb", {"text": "not json"})[0] == 500
    assert json.loads((tutor.app.root / "data_formats_short.ipynb").read_text())["cells"][0]["source"] == "# changed"
    assert tutor.call("PUT", "/api/notebook?path=notes.txt", {"text": "{}"})[0] == 400


def test_uploads(tutor):
    status, out = tutor.call("POST", "/api/upload?folder=.&name=houses.csv", raw=b"a,b\n1,2\n")
    assert status == 200 and (tutor.app.root / "houses.csv").read_text() == "a,b\n1,2\n"
    assert tutor.call("POST", "/api/upload?folder=.&name=run.exe", raw=b"x")[0] == 400
    status, out = tutor.call("GET", "/api/files?folder=.")
    assert "houses.csv" in out["files"] and not any(f.endswith(".ipynb") for f in out["files"])


def _nb(topic=None, marker="v1"):
    meta = {"ai_learning_kit": {"topic": topic}} if topic else {}
    return json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": meta,
                       "cells": [{"cell_type": "markdown", "id": "a", "metadata": {}, "source": marker}]}).encode()


def test_an_added_notebook_is_kept_once(tutor):
    add = lambda raw, how="": tutor.call("POST", f"/api/upload?kind=notebook&name=1_prepare.ipynb&on_exists={how}", raw=raw)
    # a kit notebook is kept in its topic's folder, with the data files added for it
    status, out = add(_nb("graph-embeddings"))
    assert status == 200 and out["saved"] == "graph-embeddings/1_prepare.ipynb"
    kept = tutor.app.root / out["saved"]
    kept.write_bytes(_nb("graph-embeddings", marker="my work"))          # the student works in it
    # adding the same file again asks first and changes nothing
    status, out = add(_nb("graph-embeddings"))
    assert status == 200 and out["exists"] and out["same_as_added"] is True
    assert out["existing"] == "graph-embeddings/1_prepare.ipynb" and b"my work" in kept.read_bytes()
    # a different file (the lecturer updated it) is reported as different
    status, out = add(_nb("graph-embeddings", marker="v2"))
    assert status == 200 and out["exists"] and out["same_as_added"] is False
    # "Open your saved copy" keeps the work; "Replace it" takes the new file; there is only ever one copy
    status, out = add(_nb("graph-embeddings", marker="v2"), "open")
    assert status == 200 and out["kept"] and b"my work" in kept.read_bytes()
    status, out = add(_nb("graph-embeddings", marker="v2"), "replace")
    assert status == 200 and out["replaced"] and b"v2" in kept.read_bytes()
    assert sorted(p.name for p in kept.parent.iterdir()) == ["1_prepare.ipynb"]
    # the bookkeeping folder is not listed as a notebook folder
    names = [n["path"] for n in tutor.call("GET", "/api/notebooks")[1]["notebooks"]]
    assert "graph-embeddings/1_prepare.ipynb" in names and not any(".tutor" in n for n in names)


def test_other_notebooks_go_in_the_tutors_folder(tutor):
    status, out = tutor.call("POST", "/api/upload?kind=notebook&name=mine.ipynb", raw=_nb())
    assert status == 200 and out["saved"] == "mine.ipynb"
    assert tutor.call("POST", "/api/upload?kind=notebook&name=bad.ipynb", raw=b"not json")[0] == 400
    assert tutor.call("POST", "/api/upload?kind=notebook&name=x.csv", raw=b"a")[0] == 400
    status, out = tutor.call("POST", "/api/upload?kind=notebook&name=odd.ipynb", raw=_nb("../.."))
    assert status == 200 and out["saved"] == "odd.ipynb"         # unusable metadata never leaves the folder


def test_the_clone_keeps_its_own_notebooks():
    from notebook_tutor import cli
    root = cli.default_root()
    repo = __import__("pathlib").Path(cli.__file__).resolve().parents[2]
    assert root == (repo / "notebooks" if (repo / ".git").exists() else cli.LEGACY_ROOT)


def test_prefs_round_trip(tutor, cfg):
    assert tutor.call("PUT", "/api/prefs", {"nbt:level": "advanced"})[0] == 200
    status, body = tutor.call("GET", "/?t=" + tutor.app.token, token=False)
    assert '"nbt:level": "advanced"' in body


# ------------------------------------------------------------------ settings: the key stays on the server
def test_settings_never_return_the_key(tutor, cfg, fake_llm):
    out = use_fake(tutor, fake_llm)
    assert out["has_key"] and out["key_hint"] == "…1234"
    assert "SECRET" not in json.dumps(out)
    status, out = tutor.call("GET", "/api/settings")
    assert "SECRET" not in json.dumps(out)
    status, page = tutor.call("GET", "/?t=" + tutor.app.token, token=False)
    assert "SECRET" not in page
    f = cfg / "settings.json"
    assert "sk-test-SECRET-1234" in f.read_text()
    if os.name == "posix":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    # an empty key field keeps the stored key; forget_key removes it
    tutor.call("PUT", "/api/settings", {"provider": "openai-compatible", "api_key": ""})
    assert tutor.call("GET", "/api/settings")[1]["has_key"]
    tutor.call("PUT", "/api/settings", {"forget_key": True})
    assert not tutor.call("GET", "/api/settings")[1]["has_key"]


def test_unknown_provider_refused(tutor):
    assert tutor.call("PUT", "/api/settings", {"provider": "skynet"})[0] == 400


# ------------------------------------------------------------------ language model
def test_llm_not_configured(tutor):
    status, out = tutor.call("POST", "/api/llm", {"prompt": "hi"})
    assert out["error"]["code"] == "not_configured"


def test_llm_text_json_and_retry(tutor, fake_llm):
    use_fake(tutor, fake_llm)
    status, out = tutor.call("POST", "/api/llm", {"prompt": "Explain this cell."})
    assert out["text"].startswith("**Fake explanation.**")
    assert fake_llm.requests[-1]["body"]["model"] == "fake-small"
    assert fake_llm.requests[-1]["auth"] == "Bearer sk-test-SECRET-1234"
    tutor.call("POST", "/api/llm", {"prompt": "Explain.", "tier": "default"})
    assert fake_llm.requests[-1]["body"]["model"] == "fake-large"
    status, out = tutor.call("POST", "/api/llm", {"prompt": "Write a question.", "json": True})
    assert out["json"] == MCQ
    fake_llm.mode = "prose_then_json"
    status, out = tutor.call("POST", "/api/llm", {"prompt": "Write a question.", "json": True})
    assert out["json"] == MCQ
    fake_llm.mode = "never_json"
    status, out = tutor.call("POST", "/api/llm", {"prompt": "Write a question.", "json": True})
    assert out["error"]["code"] == "invalid_json"


def test_llm_bad_key_is_reported(tutor, fake_llm):
    use_fake(tutor, fake_llm)
    fake_llm.mode = "bad_key"
    status, out = tutor.call("POST", "/api/llm", {"prompt": "hi"})
    assert out["error"]["code"] == "bad_key"


def test_models_and_test_use_unsaved_settings(tutor, fake_llm):
    form = {"provider": "openai-compatible", "base_url": fake_llm.url, "model_quick": "fake-small"}
    status, out = tutor.call("POST", "/api/models", form)
    assert sorted(out["models"]) == ["fake-large", "fake-small"]
    status, out = tutor.call("POST", "/api/settings/test", form)
    assert out["text"] == "ready" and out["model"] == "fake-small"
    assert tutor.call("GET", "/api/settings")[1]["provider"] == "none"     # nothing was saved


def test_kernel_proxy_needs_its_own_token(tutor, fake_llm):
    use_fake(tutor, fake_llm)
    body = {"model": "tutor", "messages": [{"role": "system", "content": "Be brief."},
                                           {"role": "user", "content": "Explain shape."}]}
    assert tutor.call("POST", "/v1/chat/completions", body, token=False)[0] == 401
    assert tutor.call("POST", "/v1/chat/completions", body, token=False,
                      headers={"Authorization": "Bearer " + tutor.app.token})[0] == 401
    status, out = tutor.call("POST", "/v1/chat/completions", body, token=False,
                             headers={"Authorization": "Bearer " + tutor.app.proxy_token})
    assert status == 200 and "Fake explanation" in out["choices"][0]["message"]["content"]
    assert fake_llm.requests[-1]["body"]["messages"][0] == {"role": "system", "content": "Be brief."}


def test_kit_context_from_metadata(tutor):
    status, out = tutor.call("GET", "/api/kit/context?path=data_formats_short.ipynb")
    ctx = out["context"]
    assert ctx["topic"] == "data-formats" and ctx["level"] == "introductory" and "unit" not in ctx
    assert "Black boxes" in ctx["scope"] and "T1.1" in ctx["tasks"]
    # The bundled kit is the version the course notebooks are written for, so students see no mismatch notice.
    assert out["kit"] == out["notebook_meta"]["kit_version"] and "version_note" not in out, out.get("version_note")


def test_version_notice_only_when_the_notebook_needs_a_newer_kit(tutor):
    import json as _json
    nb = _json.loads((tutor.app.root / "data_formats_short.ipynb").read_text())
    for version, noted in (("0.4.0", False), ("0.5.0", False), ("9.0.0", True)):
        nb["metadata"]["ai_learning_kit"]["kit_version"] = version
        (tutor.app.root / "data_formats_short.ipynb").write_text(_json.dumps(nb))
        out = tutor.call("GET", "/api/kit/context?path=data_formats_short.ipynb")[1]
        assert ("version_note" in out) is noted, (version, out.get("version_note"))


def test_kit_context_for_a_topic_without_tasks(tutor):
    """graph-embeddings: no answer book; the tutor gets the helpers, the datasets and the scope instead."""
    import shutil
    from pathlib import Path
    shutil.copy(Path(__file__).parent / "data" / "kit_graph_embeddings_short.ipynb", tutor.app.root / "graph_embeddings_short.ipynb")
    status, out = tutor.call("GET", "/api/kit/context?path=graph_embeddings_short.ipynb")
    ctx = out["context"]
    assert ctx["topic"] == "graph-embeddings" and ctx["level"] == "advanced" and ctx["problem"] is None and ctx["tasks"] == {}
    assert "load_cora" in ctx["tools"]["functions"] and ctx["datasets"][0]["owner"].startswith("LINQS")
    assert "SCOPE OF THIS TOPIC" in ctx["scope"] and "version_note" not in out


def test_restart_button_ends_a_running_cell(tutor):
    import threading
    import time
    tutor.call("POST", "/api/kernel/start", {"path": "data_formats_short.ipynb"})
    out = {}
    t = threading.Thread(target=lambda: out.update(r=tutor.call("POST", "/api/run",
                                                                {"code": "import time\ntime.sleep(120)"})[1]))
    t.start()
    time.sleep(2)
    t0 = time.time()
    assert tutor.call("POST", "/api/kernel/start", {"path": "data_formats_short.ipynb", "restart": True})[1]["restarted"]
    t.join(30)
    assert not t.is_alive() and time.time() - t0 < 30
    assert out["r"]["error"]["ename"] == "KernelRestart"
    assert tutor.call("POST", "/api/run", {"code": "print(1)"})[1]["stdout"] == "1\n"


def test_open_link_in_the_computers_browser(tutor, monkeypatch):
    import notebook_tutor.server as srv
    opened = []
    monkeypatch.setattr(srv.webbrowser, "open", lambda url: opened.append(url) or True)
    assert tutor.call("POST", "/api/open", {"url": "https://www.youtube.com/watch?v=x"})[1]["opened"]
    assert opened == ["https://www.youtube.com/watch?v=x"]
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "/Applications/Calculator.app"):
        assert tutor.call("POST", "/api/open", {"url": bad})[0] == 400
    assert tutor.call("POST", "/api/open", {"url": "https://x.org"}, token=False)[0] == 401
    assert opened == ["https://www.youtube.com/watch?v=x"]


def test_follow_up_conversations_are_accepted(tutor, fake_llm):
    use_fake(tutor, fake_llm)
    turns = [{"role": "user", "content": "RULES AND CONTEXT"},
             {"role": "user", "content": "What does pos hold?"},
             {"role": "assistant", "content": "A dictionary of positions."},
             {"role": "user", "content": "Explain further and then ask me a question"}]
    status, out = tutor.call("POST", "/api/llm", {"prompt": turns})
    assert "text" in out, out
    sent = fake_llm.prompts()[-1]
    assert sent.startswith("RULES AND CONTEXT") and "Tutor: A dictionary of positions." in sent
    assert "THE STUDENT NOW ASKS:\nExplain further and then ask me a question" in sent


def test_a_cut_off_reply_is_flagged(tutor, fake_llm):
    use_fake(tutor, fake_llm)
    fake_llm.mode = "cut"
    status, out = tutor.call("POST", "/api/llm", {"prompt": "Explain."})
    assert out["truncated"] is True and out["text"]
    assert fake_llm.requests[-1]["body"]["max_tokens"] >= 4096


def test_a_notebooks_own_level_overrides_the_topics(tutor):
    import json as _json
    nb = _json.loads((tutor.app.root / "data_formats_short.ipynb").read_text())
    nb["metadata"]["ai_learning_kit"]["level"] = "research"
    (tutor.app.root / "data_formats_short.ipynb").write_text(_json.dumps(nb))
    ctx = tutor.call("GET", "/api/kit/context?path=data_formats_short.ipynb")[1]["context"]
    assert ctx["level"] == "research" and ctx["cohort"].startswith("Research level")
