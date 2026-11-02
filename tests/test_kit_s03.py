"""A Session 03 notebook (web pages and APIs) through the tutor: requests, Beautiful Soup and the kit's saved copies."""
import json
import shutil
from pathlib import Path

DATA = Path(__file__).parent / "data"


def test_web_session_through_the_tutor(tutor):
    shutil.copy(DATA / "kit_s03_short.ipynb", tutor.app.root / "S03_short.ipynb")
    status, out = tutor.call("GET", "/api/kit/context?path=S03_short.ipynb")
    assert out["context"]["session"] == "S03" and "Available on request" in out["context"]["scope"]
    assert "scrape_listings" in out["context"]["tools"]["functions"]

    assert tutor.call("POST", "/api/kernel/start", {"path": "S03_short.ipynb"})[1]["started"]
    nb = json.loads((tutor.app.root / "S03_short.ipynb").read_text())
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    status, r = tutor.call("POST", "/api/run", {"code": code[0]})            # the kit's install line is skipped
    assert "already provides" in r["notes"][0] and r["error"] is None
    status, r = tutor.call("POST", "/api/run", {"code": code[1]})            # kit.start, Beautiful Soup
    assert r["error"] is None, r["error"]
    status, r = tutor.call("POST", "/api/run", {"code": code[2]})            # a page, live or the kit's copy
    assert r["error"] is None and r["stdout"].split() == ["200", "12"], r
    status, r = tutor.call("POST", "/api/run", {"code": code[3]})            # every page, saved next to the notebook
    assert r["error"] is None and "(36, 8)" in r["stdout"]
    assert (tutor.app.root / "listings_raw.csv").is_file()
    status, r = tutor.call("POST", "/api/run", {"code": code[4]})            # the Open-Meteo API
    assert r["error"] is None and r["stdout"].split() == ["200", "31"], r
