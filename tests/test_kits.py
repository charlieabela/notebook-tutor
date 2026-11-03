"""Each notebook runs with the ai-learning-kit version it names, when the tutor's own kit is of a later major version."""
import json

import pytest

from notebook_tutor import kits


def _nb(line, meta=None):
    return {"cells": [{"cell_type": "code", "source": line}], "metadata": {"ai_learning_kit": meta or {}}}


def test_the_version_comes_from_the_metadata_or_the_install_line():
    line = '%pip install -q "ai-learning-kit[graphs]@https://github.com/charlieabela/ai-learning-kit/archive/refs/tags/v0.6.0.zip"'
    assert kits.requested(_nb(line)) == ("0.6.0", "https://github.com/charlieabela/ai-learning-kit/archive/refs/tags/v0.6.0.zip")
    assert kits.requested(_nb("import pandas", {"kit_version": "0.8.0"}))[0] == "0.8.0"
    assert kits.requested(_nb("import pandas")) == (None, None)


@pytest.mark.parametrize("notebook, tutor, own", [
    ("0.6.0", "1.0.0", True),          # an earlier major version: the notebook's own kit
    ("1.0.0", "1.0.1", False),         # the same major version: the tutor's kit runs it
    ("1.2.0", "1.0.1", False),         # a newer notebook: the tutor's kit, with a notice to update the tutor
    (None, "1.0.0", False),
])
def test_only_an_earlier_major_version_gets_its_own_kit(notebook, tutor, own):
    assert kits.needs_own_kit(notebook, tutor) is own


def test_a_notebook_for_an_earlier_kit_runs_on_that_kit(tutor, monkeypatch):
    """Downloads kit 0.6.0 once (skipped when GitHub cannot be reached), then runs the notebook's kernel with it."""
    monkeypatch.setattr(kits, "bundled", lambda: "1.0.0")
    line = '%pip install -q "ai-learning-kit@https://github.com/charlieabela/ai-learning-kit/archive/refs/tags/v0.6.0.zip"'
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {"ai_learning_kit": {"kit_version": "0.6.0"}},
          "cells": [{"cell_type": "code", "id": "a", "metadata": {}, "outputs": [], "execution_count": None, "source": line},
                    {"cell_type": "code", "id": "b", "metadata": {}, "outputs": [], "execution_count": None,
                     "source": "import ai_learning_kit as kit\nprint(kit.__version__)"}]}
    (tutor.app.root / "old.ipynb").write_text(json.dumps(nb))
    path, problem = kits.ensure(tutor.app.root, "0.6.0")
    if path is None:
        pytest.skip(f"kit 0.6.0 could not be downloaded here: {problem}")
    assert tutor.call("POST", "/api/kernel/start", {"path": "old.ipynb"})[1]["kit"] == "0.6.0"
    status, r = tutor.call("POST", "/api/run", {"code": line})
    assert "ai-learning-kit 0.6.0" in " ".join(r["notes"])              # the install line is skipped, not run
    status, r = tutor.call("POST", "/api/run", {"code": nb["cells"][1]["source"]})
    assert r["error"] is None and r["stdout"].strip() == "0.6.0"
    out = tutor.call("GET", "/api/kit/context?path=old.ipynb")[1]
    assert out["notebook_kit"] == "0.6.0" and "version_note" not in out
