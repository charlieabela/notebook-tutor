"""The tutor's page in a real (headless) browser, against the local server and a fake model."""
import json
import os
import threading
import time

import pytest

from conftest import use_fake

pw = pytest.importorskip("playwright.sync_api")

SHOTS = os.environ.get("NT_SCREENSHOTS")


@pytest.fixture
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_page(browser, client):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "fonts.g" not in m.text
            and "ERR_" not in m.text else None)
    page.goto(f"{client.base}/?t={client.app.token}")
    return page, errors


def test_guided_walkthrough(browser, tutor, fake_llm):
    use_fake(tutor, fake_llm)
    page, errors = open_page(browser, tutor)
    page.wait_for_selector("#ntOpen[open]")                        # the folder's notebooks
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "open.png"))
    page.click("#ntOpen li:has-text('data_formats_short.ipynb')")
    page.wait_for_selector("#modes[open]")                         # first visit: choose a mode
    page.click("#pick-guided")
    page.wait_for_function("document.querySelector('#pyText').textContent === 'Python ready'", timeout=90000)
    assert "data-formats (test copy)" in page.inner_text("#nbTitle")
    assert page.input_value("#level") == "introductory"             # the topic's level, from the kit

    for i in range(4):                                              # pip (skipped), imports, kit.start, read CSV
        page.click("#runNext")
        page.wait_for_function(f"document.querySelector('#progText').textContent.startsWith('{i + 1} of')",
                               timeout=90000)
    page.wait_for_selector(".cell table", timeout=30000)            # the DataFrame from the CSV
    page.wait_for_selector("text=Fake explanation", timeout=60000)
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "guided.png"), full_page=False)

    # the explanation prompt carried the kit's scope for this session
    explain = [p for p in fake_llm.prompts() if "AI-LEARNING-KIT" in p]
    assert explain and "Black boxes" in explain[-1] and "Jupyter kernel" in explain[-1]

    # the notebook file is saved as the student works
    deadline = time.time() + 10
    while time.time() < deadline:
        nb = json.loads((tutor.app.root / "data_formats_short.ipynb").read_text())
        if any(c.get("outputs") for c in nb["cells"] if c["cell_type"] == "code"):
            break
        time.sleep(0.3)
    assert any(c.get("outputs") for c in nb["cells"] if c["cell_type"] == "code")
    assert (tutor.app.root / "answers" / "data-formats_Test_Student.json").is_file()

    # the setup dialog shows that a key is stored, never the key
    page.click("#settingsBtn")
    assert page.inner_text("#llmName") == "OpenAI-compatible server · fake-large"
    page.click("#llmBtn")
    page.wait_for_selector("#ntSetup[open]")
    html = page.inner_html("#ntSetup")
    assert "SECRET" not in html and "…1234" in page.get_attribute('#ntSetup [data-k="api_key"]', "placeholder")
    page.click("#ntSetup [data-test]")
    page.wait_for_selector("#ntSetup .res.ok", timeout=20000)
    assert not errors, errors


def test_first_run_without_notebooks(browser, tutor):
    (tutor.app.root / "data_formats_short.ipynb").unlink()
    page, errors = open_page(browser, tutor)
    page.wait_for_selector("#ntOpen[open]")
    assert "not added a notebook yet" in page.inner_text("#ntOpen")
    page.click("#ntOpen [data-samples]")
    page.wait_for_selector("#modes[open]")
    assert (tutor.app.root / "samples" / "guided_linear_regression.ipynb").is_file()
    page.click("#pick-guided")
    page.wait_for_function("document.querySelector('#pyText').textContent === 'Python ready'", timeout=90000)
    # no language model: Python works and the page says how to set the tutor up
    page.click("#runNext")
    page.wait_for_selector("#tutorBanner:not([hidden])")
    assert "Set up the tutor" in page.inner_text("#tutorBanner")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "first_run.png"))
    assert not errors, errors


def test_links_open_in_the_computers_browser_when_framed(browser, tutor, monkeypatch):
    """Inside VS Code's Simple Browser (a frame), notebook links go to the system browser via the server."""
    import notebook_tutor.server as srv
    opened = []
    monkeypatch.setattr(srv.webbrowser, "open", lambda url: opened.append(url) or True)
    nb = json.loads((tutor.app.root / "data_formats_short.ipynb").read_text())
    nb["cells"][0]["source"] = "# Video\n\n[Watch the video](https://www.youtube.com/watch?v=NqZA5atdg3A)"
    (tutor.app.root / "data_formats_short.ipynb").write_text(json.dumps(nb))
    page = browser.new_page()
    page.set_content(f'<iframe id="f" src="{tutor.base}/?t={tutor.app.token}" style="width:1300px;height:900px">'
                     "</iframe>")
    frame = page.frame_locator("#f")
    frame.locator("#ntOpen li:has-text('data_formats_short.ipynb')").click()
    frame.locator("#pick-guided").click()
    frame.locator("a:has-text('Watch the video')").click()
    deadline = time.time() + 10
    while not opened and time.time() < deadline:
        time.sleep(0.2)
    assert opened == ["https://www.youtube.com/watch?v=NqZA5atdg3A"]
    assert len(page.context.pages) == 1          # nothing opened inside the embedded browser


def test_a_failed_checkpoint_can_be_tried_again(browser, tutor, fake_llm):
    use_fake(tutor, fake_llm)
    page, errors = open_page(browser, tutor)
    page.click("#ntOpen li:has-text('data_formats_short.ipynb')")
    page.click("#pick-guided")
    page.wait_for_function("document.querySelector('#pyText').textContent === 'Python ready'", timeout=90000)
    fake_llm.mode = "never_json"
    page.locator("button:has-text('Quiz me')").first.click()
    page.wait_for_selector("text=came back garbled", timeout=30000)
    page.locator("button:has-text('Quiz me')").first.click()            # a second try replaces the failed card
    page.wait_for_function("document.body.innerText.split('came back garbled').length === 2", timeout=30000)
    fake_llm.mode = "ok"
    page.locator("button:has-text('Try again')").first.click()
    page.wait_for_selector("text=What does erp.shape show?", timeout=30000)
    assert page.locator("text=came back garbled").count() == 0
    assert not errors, errors


def _plain_nb(code, marker="v1"):
    return json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"name": "python3"}},
                       "cells": [{"cell_type": "markdown", "id": "m", "metadata": {}, "source": marker},
                                 {"cell_type": "code", "id": "c", "metadata": {}, "outputs": [],
                                  "execution_count": None, "source": code}]})


def test_recent_notebooks_and_adding_one_again(browser, tutor, tmp_path):
    for i in range(7):
        p = tutor.app.root / f"nb{i}.ipynb"
        p.write_text(_plain_nb("1 + 1"))
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    page, errors = open_page(browser, tutor)
    page.wait_for_selector("#ntOpen[open]")
    assert page.locator("#ntOpen li:visible").count() == 5             # only the five most recent are listed
    assert "Show all 8 notebooks" in page.inner_text("#ntOpen")
    page.click("#ntOpen button:has-text('Show all')")
    assert page.locator("#ntOpen li:visible").count() == 8
    # the student adds nb0.ipynb, which the tutor already keeps: it asks, and opening keeps their work
    (tutor.app.root / "nb0.ipynb").write_text(_plain_nb("1 + 1", marker="my work"))
    chosen = tmp_path / "nb0.ipynb"
    chosen.write_text(_plain_nb("1 + 1", marker="from the lecturer"))
    page.set_input_files("#ntOpen input[type=file]", str(chosen))
    page.wait_for_selector("#ntExists[open]")
    assert "Open your saved copy (keeps your work)" in page.inner_text("#ntExists")
    page.click("#ntExists [data-open]")
    page.wait_for_selector("#modes[open]")
    assert "my work" in (tutor.app.root / "nb0.ipynb").read_text()
    assert sorted(p.name for p in tutor.app.root.glob("nb0*.ipynb")) == ["nb0.ipynb"]
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "add_again.png"))
    assert not errors, errors


def test_a_missing_dataset_points_to_the_data_files_button(browser, tutor):
    code = ("from ai_learning_kit.datasets import DatasetUnavailable\n"
            "raise DatasetUnavailable('The Cora citation network is missing: it could not be downloaded from LINQS.\\n'\n"
            "                         'Add cora.tgz with the Data files button (Data files > Add data file...), then run this cell again.')")
    (tutor.app.root / "data_formats_short.ipynb").unlink()
    (tutor.app.root / "cora_test.ipynb").write_text(_plain_nb(code))
    page, errors = open_page(browser, tutor)
    page.wait_for_selector("#ntOpen[open]")
    page.click("#ntOpen li:has-text('cora_test.ipynb')")
    page.wait_for_selector("#modes[open]")
    page.click("#pick-guided")
    page.wait_for_function("document.querySelector('#pyText').textContent === 'Python ready'", timeout=90000)
    page.click("#runNext")
    page.wait_for_selector("#notice:has-text('A dataset is missing')", timeout=60000)
    assert "cora.tgz" in page.inner_text("#notice")
    assert page.locator(".out-error pre").count() == 0          # the kit's message only, not a traceback
    with page.expect_file_chooser() as fc:
        page.click("#notice button:has-text('Add data file')")
    data = tutor.app.root.parent / "cora.tgz"
    data.write_bytes(b"x")
    fc.value.set_files(str(data))
    page.wait_for_selector("#notice:has-text('Added cora.tgz')")
    assert (tutor.app.root / "cora.tgz").is_file()
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "missing_data.png"))
    assert not [e for e in errors if "DatasetUnavailable" not in e], errors


def _open_plain(browser, tutor, name, cells):
    (tutor.app.root / "data_formats_short.ipynb").unlink()
    (tutor.app.root / name).write_text(json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"name": "python3"}},
                                                    "cells": cells}))
    page, errors = open_page(browser, tutor)
    page.wait_for_selector("#ntOpen[open]")
    page.click(f"#ntOpen li:has-text('{name}')")
    page.wait_for_selector("#modes[open]")
    page.click("#pick-guided")
    page.wait_for_function("document.querySelector('#pyText').textContent === 'Python ready'", timeout=90000)
    return page, errors


def _saved(tutor, name, pred, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        nb = json.loads((tutor.app.root / name).read_text())
        if pred(nb):
            return nb
        time.sleep(0.3)
    return nb


def test_adding_text_and_code_cells(browser, tutor):
    md = {"cell_type": "markdown", "id": "m", "metadata": {}, "source": "# Lecturer's notebook"}
    code = {"cell_type": "code", "id": "c", "metadata": {}, "outputs": [], "execution_count": None, "source": "x = 20"}
    page, errors = _open_plain(browser, tutor, "mine.ipynb", [md, code])
    # a text cell after the last cell: written in Markdown, then shown rendered
    page.click(".adder.end button:has-text('Text')")
    page.click(".mdedit .CodeMirror")                       # focus the editor before typing (a slow machine may lag)
    page.keyboard.type("## My note\n\nThe answer is **x + 22**.")
    page.click(".mdedit button:has-text('Done')")
    page.wait_for_selector(".mdcell.added h2:has-text('My note')")
    # + Code and + Text before the first cell, between every two cells and after the last, text or code
    assert page.locator(".adder").count() == page.locator(".cell").count() + 1
    assert page.locator("#cells > .adder:first-child button:has-text('Code')").is_visible()
    # a code cell between the lecturer's two cells, run like any other
    page.hover(".cell[data-i='0'] + .adder")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "adder_hover.png"), clip={"x": 0, "y": 250, "width": 1000, "height": 350})
    page.click(".cell[data-i='0'] + .adder button:has-text('Code')")
    page.click(".cell.added:not(.mdcell) .CodeMirror")
    page.keyboard.type("print('added', 1 + 1)")
    page.click(".cell[data-i='2'] .run")                 # the lecturer's code cell, now third
    page.click(".cell.added:not(.mdcell) .run")
    page.wait_for_selector(".cell.added .out-pre:has-text('added 2')", timeout=60000)
    nb = _saved(tutor, "mine.ipynb", lambda nb: len(nb["cells"]) == 4 and "".join(nb["cells"][1]["source"]).startswith("print"))
    kinds = [(c["cell_type"], (c.get("metadata", {}).get("tutor") or {}).get("added", False)) for c in nb["cells"]]
    assert kinds == [("markdown", False), ("code", True), ("code", False), ("markdown", True)]
    assert "".join(nb["cells"][3]["source"]).startswith("## My note")
    assert "original" not in nb["cells"][1]["metadata"]["tutor"]           # nothing to "undo" in the student's own cell
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "added_cells.png"))
    # reopened, the added cells are still there, editable and deletable; deleting can be undone
    page.reload()
    page.wait_for_selector(".mdcell.added h2:has-text('My note')")
    page.click(".mdcell.added .delcell")                    # the student's own cell: deleted at once, no questions
    page.wait_for_selector("#notice:has-text('Cell deleted')")
    assert page.locator(".mdcell.added").count() == 0
    page.click("#notice button:has-text('Undo')")
    page.wait_for_selector(".mdcell.added h2:has-text('My note')")
    page.click(".mdcell.added button:has-text('Edit')")
    page.click(".mdedit .CodeMirror")
    page.keyboard.press("Shift+Enter")
    page.wait_for_selector(".mdcell.added h2:has-text('My note')")
    assert not errors, errors


def test_clearing_the_tutors_notes(browser, tutor, fake_llm):
    use_fake(tutor, fake_llm)
    md = {"cell_type": "markdown", "id": "m", "metadata": {}, "source": "# Notes"}
    code = {"cell_type": "code", "id": "c", "metadata": {}, "outputs": [], "execution_count": None, "source": "y = 2 * 21\ny"}
    page, errors = _open_plain(browser, tutor, "clear.ipynb", [md, code])
    page.click("#runNext")
    page.wait_for_selector(".cell .notes .card:has-text('Fake explanation')", timeout=60000)
    page.fill("#ask", "What does y hold?")
    page.click("#sendAsk")
    page.wait_for_selector("#feed .card:has-text('Fake explanation')", timeout=60000)
    # keeping them changes nothing
    assert page.locator("#clearNotes").is_visible() and "Clear notes" in page.inner_text(".thead")
    page.click("#clearNotes")
    page.wait_for_selector("#clearDlg[open]")
    page.click("#clearKeep")
    assert page.locator(".cell .notes .card").count() >= 1 and page.locator("#feed .card").count() >= 1
    # clearing them removes every note and the conversation; the code and its output stay
    page.click("#clearNotes")
    page.wait_for_selector("#clearDlg[open]")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "clear_dialog.png"))
    page.click("#clearGo")
    page.wait_for_selector("#notice:has-text('notes were cleared')")
    assert page.locator(".cell .notes .card").count() == 0 and page.locator("#feed .card").count() == 0
    assert page.locator("#feed .welcome").count() == 1
    assert "42" in page.inner_text(".cell .outputs")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "cleared.png"))
    # the tutor starts again: running the cell explains it afresh
    page.click(".cell .run")
    page.wait_for_selector(".cell .notes .card:has-text('Fake explanation')", timeout=60000)
    assert not errors, errors


def test_deleting_a_lecturer_cell_explains_first(browser, tutor):
    cells = [{"cell_type": "markdown", "id": "m", "metadata": {}, "source": "# Data\n\nWe load the table."},
             {"cell_type": "code", "id": "a", "metadata": {}, "outputs": [], "execution_count": None,
              "source": "import pandas as pd\ndf = pd.DataFrame({'v': [1, 2]})\ntotal = 3"},
             {"cell_type": "code", "id": "b", "metadata": {}, "outputs": [], "execution_count": None, "source": "df['v'].sum()"}]
    page, errors = _open_plain(browser, tutor, "lect.ipynb", cells)
    # a lecturer's code cell: the dialog says what depends on it; keeping it changes nothing
    page.click(".cell[data-i='1'] .delcell")
    page.wait_for_selector("#delDlg[open]")
    body = page.inner_html("#delBody")
    assert "code</b> cell from the notebook your lecturer gave you" in body
    assert "<code>df</code>" in body and "<code>pd</code>" not in body and "total" not in body  # only what later cells use
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "delete_dialog.png"))
    page.click("#delKeep")
    assert page.locator(".cell:not(.mdcell)").count() == 2
    # deleting it removes it from the student's copy; Undo brings it back
    page.click(".cell[data-i='1'] .delcell")
    page.click("#delGo")
    page.wait_for_selector("#notice:has-text('Cell deleted')")
    nb = _saved(tutor, "lect.ipynb", lambda nb: len(nb["cells"]) == 2)
    assert [c["cell_type"] for c in nb["cells"]] == ["markdown", "code"]
    page.click("#notice button:has-text('Undo')")
    nb = _saved(tutor, "lect.ipynb", lambda nb: len(nb["cells"]) == 3)
    assert "df = pd.DataFrame" in "".join(nb["cells"][1]["source"])
    # a lecturer's text cell asks too
    page.click(".mdcell .delcell")
    page.wait_for_selector("#delDlg[open]")
    assert "text cell from the notebook your lecturer gave you" in page.inner_text("#delBody")
    page.click("#delGo")
    _saved(tutor, "lect.ipynb", lambda nb: len(nb["cells"]) == 2 and nb["cells"][0]["cell_type"] == "code")
    assert not errors, errors


def test_the_tutor_panel_can_be_hidden(browser, tutor):
    cells = [{"cell_type": "code", "id": "a", "metadata": {}, "outputs": [], "execution_count": None, "source": "1"}]
    page, errors = _open_plain(browser, tutor, "panel.ipynb", cells)
    assert page.locator("#tutor").is_visible() and not page.locator("#fab").is_visible()
    page.click("#closeTutor")
    assert not page.locator("#tutor").is_visible() and page.locator("#fab").is_visible()
    wide = page.locator("#nbcol").bounding_box()["width"]
    assert wide > 1300                                      # the notebook takes the whole width
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "panel_hidden.png"))
    # remembered: preferences reach the server a moment after a change, so reload until the page has it
    deadline = time.time() + 20
    while True:
        page.wait_for_timeout(700)
        page.reload()
        page.wait_for_selector("#nbTitle")
        if page.evaluate("document.body.classList.contains('tutor-hidden')") or time.time() > deadline:
            break
    assert page.evaluate("document.body.classList.contains('tutor-hidden')")
    page.click("#fab")
    assert page.locator("#tutor").is_visible() and not page.locator("#fab").is_visible()
    assert not errors, errors
