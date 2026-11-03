"""An exploring-data notebook through the tutor: stored data, SciPy for Spearman, figures, checks."""
import json
import shutil
from pathlib import Path

DATA = Path(__file__).parent / "data"


def test_explore_session_through_the_tutor(tutor):
    shutil.copy(DATA / "kit_exploring_data_short.ipynb", tutor.app.root / "exploring_data_short.ipynb")
    status, out = tutor.call("GET", "/api/kit/context?path=exploring_data_short.ipynb")
    assert out["context"]["topic"] == "exploring-data" and "Available on request" in out["context"]["scope"]
    assert "pearson_by_hand" in out["context"]["tools"]["functions"]

    assert tutor.call("POST", "/api/kernel/start", {"path": "exploring_data_short.ipynb"})[1]["started"]
    nb = json.loads((tutor.app.root / "exploring_data_short.ipynb").read_text())
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    status, r = tutor.call("POST", "/api/run", {"code": code[0]})            # the kit's install line is skipped
    assert "already provides" in r["notes"][0] and r["error"] is None
    status, r = tutor.call("POST", "/api/run", {"code": code[1]})
    assert r["error"] is None, r["error"]
    status, r = tutor.call("POST", "/api/run", {"code": code[2]})            # the penguins stored in the kit
    assert r["error"] is None and r["stdout"].split() == ["342", "4050"], r
    status, r = tutor.call("POST", "/api/run", {"code": code[3]})            # Spearman needs SciPy
    assert r["error"] is None and r["stdout"].strip() == "0.84", r
    status, r = tutor.call("POST", "/api/run", {"code": code[4]})            # a figure from a helper
    assert r["error"] is None and len(r["figures"]) == 1
    status, r = tutor.call("POST", "/api/run", {"code": code[5]})            # a practice check
    assert r["error"] is None and r["stdout"].count("Correct") == 2, r
