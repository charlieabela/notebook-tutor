import os

import pytest

from notebook_tutor.kernel import KernelSession, prepare


@pytest.fixture(scope="module")
def kernel(tmp_path_factory):
    folder = tmp_path_factory.mktemp("nb")
    os.environ["GEMINI_API_KEY"] = "should-not-leak"
    os.environ["SOME_SERVICE_API_KEY"] = "should-not-leak-either"
    k = KernelSession(folder)
    k.start()
    yield k
    k.shutdown()
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("SOME_SERVICE_API_KEY", None)


def test_output_kinds(kernel):
    r = kernel.run("import pandas as pd\nprint('hello')\ndf = pd.DataFrame({'a': [1, 2]})\ndf")
    assert r["stdout"] == "hello\n" and r["error"] is None
    assert r["results"][0]["kind"] == "html" and "<table" in r["results"][0]["html"]
    assert isinstance(r["count"], int)


def test_figures_are_collected_with_a_description(kernel):
    r = kernel.run("import matplotlib.pyplot as plt\nplt.scatter([1, 2, 3], [3, 1, 2])\nplt.xlabel('x')\n"
                   "plt.title('dots')\nplt.show()")
    assert len(r["figures"]) == 1 and r["figures"][0].startswith("iVBOR")
    assert "title='dots'" in r["figure_desc"][0] and "3 points" in r["figure_desc"][0]
    assert kernel.run("1")["figures"] == []      # figures are closed after they are collected


def test_errors_carry_the_line(kernel):
    r = kernel.run("x = 1\ny = 2\nz = undefined_name")
    assert r["error"]["ename"] == "NameError" and r["error"]["line"] == 3
    assert "\x1b[" not in r["error"]["traceback"]


def test_variables_summary(kernel):
    kernel.run("import numpy as np\narr = np.zeros((2, 3))\nlabel = 'abc'")
    v = kernel.vars_summary()
    assert "arr: ndarray shape=(2, 3)" in v and "label: str = 'abc'" in v


def test_working_folder_is_the_notebook_folder(kernel):
    r = kernel.run("import os\nprint(os.getcwd())\nopen('out.txt', 'w').write('saved')")
    assert os.path.samefile(r["stdout"].strip(), kernel.folder)
    assert (kernel.folder / "out.txt").read_text() == "saved"


def test_keys_do_not_reach_the_kernel(kernel):
    r = kernel.run("import os\nprint(sorted(k for k in os.environ if k.endswith('_API_KEY')))")
    assert r["stdout"].strip() == "[]"


def test_kit_data_is_kept_in_the_clone(kernel, monkeypatch):
    """Running from a clone, the kit keeps the datasets it downloads in the clone's data/ folder."""
    import os
    from pathlib import Path
    from notebook_tutor.kernel import clone_data_dir
    repo = Path(__file__).resolve().parents[1]
    expected = repo / "data" if (repo / ".git").exists() else None
    assert clone_data_dir() == expected
    r = kernel.run("import os\nprint(os.environ.get('AILK_DATA_DIR'))")
    if os.environ.get("AILK_DATA_DIR"):
        assert r["stdout"].strip() == os.environ["AILK_DATA_DIR"]       # an explicit setting wins
    elif expected is not None:
        assert r["stdout"].strip() == str(expected)


def test_kit_reinstall_is_skipped_but_other_pip_lines_run():
    code, notes = prepare('%pip install -q "git+https://github.com/charlieabela/ai-learning-kit@v0.4.0"\nprint(1)')
    assert code.splitlines()[0] == "" and notes and "already provides" in notes[0]
    code, notes = prepare("%pip install -q seaborn")
    assert code == "%pip install -q seaborn" and notes == []
    code, notes = prepare('if True:\n    %pip install ai-learning-kit\n')
    assert code.splitlines()[1] == "    pass"
    # the release-archive forms written by ai-learning-kit 0.5 and later, with and without spaces around @
    url = "https://github.com/charlieabela/ai-learning-kit/archive/refs/tags/v0.5.0.zip"
    for line in (f'%pip install -q "ai-learning-kit[graphs]@{url}"', f'%pip install -q "ai-learning-kit[graphs] @ {url}"',
                 f'%pip install -q "ai-learning-kit@{url}"'):
        code, notes = prepare(line)
        assert code == "" and notes and "already provides" in notes[0], line
    code, notes = prepare(f'%pip install -q "ai-learning-kit@{url}" seaborn')
    assert code.startswith("%pip") and notes == []           # mixed with another package: runs as written


def test_restart_clears_variables(kernel):
    kernel.run("keep = 42")
    kernel.restart()
    r = kernel.run("print('keep' in dir())")
    assert r["stdout"].strip() == "False"


def test_interrupt_stops_a_long_cell(kernel):
    # A Python loop: interruptible everywhere. (On Windows a blocking call such as time.sleep is not
    # interrupted, because Jupyter's interrupt there only takes effect between Python steps.)
    import threading
    import time
    threading.Timer(1.5, kernel.interrupt).start()
    t0 = time.time()
    r = kernel.run("import time\nt = time.time()\nwhile time.time() - t < 60:\n    pass")
    assert time.time() - t0 < 20
    assert r["error"]["ename"] == "KeyboardInterrupt"
    assert kernel.run("print('still alive')")["stdout"] == "still alive\n"


def test_restart_rescues_a_stuck_cell(kernel):
    import threading
    import time
    threading.Timer(1.5, kernel.restart).start()
    t0 = time.time()
    r = kernel.run("import time\ntime.sleep(120)")
    assert time.time() - t0 < 30
    assert r["error"]["ename"] == "KernelRestart"
    time.sleep(0.5)
    assert kernel.run("print('fresh')")["stdout"] == "fresh\n"


def test_a_crashed_kernel_is_reported(kernel):
    r = kernel.run("import os\nos._exit(1)")
    assert r["error"]["ename"] == "KernelDied"
    assert kernel.run("print('back')")["stdout"] == "back\n"      # the next run starts a new kernel


def test_pip_magic_works_in_the_kernel(kernel):
    # uv builds environments without pip; the tutor depends on pip so that %pip in a notebook works.
    r = kernel.run("%pip --version")
    assert r["error"] is None and "pip " in r["stdout"], r
    r = kernel.run("import requests\nprint(requests.__version__)")
    assert r["error"] is None


def test_missing_libraries_say_what_to_do(kernel):
    from notebook_tutor.kernel import missing_module_hint
    assert "--extra advanced" in missing_module_hint("No module named 'torch'")
    assert "--extra advanced" in missing_module_hint("No module named 'sentence_transformers'")
    assert "%pip install opencv-python" in missing_module_hint("No module named 'cv2'")
    assert missing_module_hint("something else") == ""
    r = kernel.run("import surely_not_a_real_module_xyz")
    assert r["error"]["ename"] == "ModuleNotFoundError"
    assert "%pip install surely_not_a_real_module_xyz" in r["error"]["evalue"]
