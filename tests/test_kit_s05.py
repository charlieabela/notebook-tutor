"""A Session 05 notebook (modelling) through the tutor: scikit-learn, a look-inside helper, a figure, a check."""
import json
import shutil
from pathlib import Path

DATA = Path(__file__).parent / "data"


def test_modelling_session_through_the_tutor(tutor):
    shutil.copy(DATA / "kit_s05_short.ipynb", tutor.app.root / "S05_short.ipynb")
    status, out = tutor.call("GET", "/api/kit/context?path=S05_short.ipynb")
    assert out["context"]["session"] == "S05" and "Available on request" in out["context"]["scope"]
    assert "line_by_hand" in out["context"]["tools"]["functions"]

    assert tutor.call("POST", "/api/kernel/start", {"path": "S05_short.ipynb"})[1]["started"]
    nb = json.loads((tutor.app.root / "S05_short.ipynb").read_text())
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    status, r = tutor.call("POST", "/api/run", {"code": code[0]})            # the kit's install line is skipped
    assert "already provides" in r["notes"][0] and r["error"] is None
    status, r = tutor.call("POST", "/api/run", {"code": code[1]})
    assert r["error"] is None, r["error"]
    status, r = tutor.call("POST", "/api/run", {"code": code[2]})            # a stratified 60/20/20 split
    assert r["error"] is None and r["stdout"].split() == ["199", "67", "67"], r
    status, r = tutor.call("POST", "/api/run", {"code": code[3]})            # the helper agrees with scikit-learn
    assert r["error"] is None and r["stdout"].split() == ["49.4", "49.4"], r
    status, r = tutor.call("POST", "/api/run", {"code": code[4]})            # a figure from a helper
    assert r["error"] is None and len(r["figures"]) == 1
    status, r = tutor.call("POST", "/api/run", {"code": code[5]})            # k-NN on scaled measurements
    assert r["error"] is None and r["stdout"].strip() == "0.97", r
    status, r = tutor.call("POST", "/api/run", {"code": code[6]})            # a practice check
    assert r["error"] is None and r["stdout"].count("Correct") == 2, r
