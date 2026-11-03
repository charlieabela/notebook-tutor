"""A kit notebook run through the tutor: answers next to the notebook, hints through the tutor's connection."""
import json

from conftest import use_fake


def cells(client):
    nb = json.loads((client.app.root / "data_formats_short.ipynb").read_text())
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def test_kit_topic_through_the_tutor(tutor, fake_llm):
    use_fake(tutor, fake_llm)
    assert tutor.call("POST", "/api/kernel/start", {"path": "data_formats_short.ipynb"})[1]["started"]
    code = cells(tutor)

    status, r = tutor.call("POST", "/api/run", {"code": code[0]})           # %pip install ai-learning-kit
    assert "already provides" in r["notes"][0] and r["error"] is None and r["count"]
    status, r = tutor.call("POST", "/api/run", {"code": code[1]})           # imports
    assert r["stdout"].startswith("kit ")
    status, r = tutor.call("POST", "/api/run", {"code": code[2]})           # kit.start
    assert r["error"] is None, r["error"]
    assert str(tutor.app.root) in r["stdout"]
    assert (tutor.app.root / "answers" / "data-formats_Test_Student.json").is_file()
    assert (tutor.app.root / "brightwater_q3" / "erp_payments_q3.csv").is_file()
    status, r = tutor.call("POST", "/api/run", {"code": code[3]})           # read the ERP file by relative path
    assert r["error"] is None and r["results"]
    status, r = tutor.call("POST", "/api/run", {"code": code[4]})           # a figure
    assert len(r["figures"]) == 1

    # kit.hint goes to the tutor's proxy, which uses the student's settings; the kernel never sees the key
    n = len(fake_llm.requests)
    status, r = tutor.call("POST", "/api/run", {"code": "kit.hint('T1.1')"})
    assert "Fake explanation" in r["stdout"], r
    assert len(fake_llm.requests) == n + 1
    sent = fake_llm.prompts()[-1]
    assert "Task T1.1" in sent and "SCOPE OF THIS TOPIC" in sent
    assert fake_llm.requests[-1]["auth"] == "Bearer sk-test-SECRET-1234"     # the real key, added by the server
    status, r = tutor.call("POST", "/api/run", {"code": "import os\nprint(os.environ.get('AILK_LLM_API_KEY'))"})
    assert r["stdout"].strip() == tutor.app.proxy_token and "SECRET" not in r["stdout"]

    # the variables summary sees the kernel's objects
    status, out = tutor.call("GET", "/api/vars")
    assert "erp: DataFrame" in out["text"]

    status, out = tutor.call("GET", "/api/files?folder=.")
    assert "answers/data-formats_Test_Student.json" in out["files"]
