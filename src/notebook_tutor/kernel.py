"""One Python kernel on the student's computer, started in the notebook's folder.

The kernel is the ordinary Jupyter kernel (ipykernel) of the environment Notebook
Tutor is installed in, so every installed library (pandas, scikit-learn,
ai-learning-kit, PyTorch, ...) imports normally, and files are read and written in
the notebook's folder exactly as in Jupyter.

run() returns a dictionary in the shape the tutor's interface expects:
    {count, notes, stdout, stderr, results: [{kind, text, html?}], figures: [b64 PNG],
     figure_desc: [...], error: {ename, evalue, traceback, line} | None}
"""
from __future__ import annotations

import ast
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpec, KernelSpecManager

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LINE_RE = re.compile(r"Cell In\[\d+\], line (\d+)")
KIT_PIN = re.compile(r"^\s*[%!]\s*pip\s+install\b(?P<args>.*)$")
KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "AILK_LLM_PROVIDER", "AILK_LLM_MODEL", "AILK_LLM_BASE_URL", "AILK_LLM_API_KEY")
MAX_TEXT = 20000
MISSING_RE = re.compile(r"No module named '([^'.]+)")
# Libraries in the tutor's "advanced" install option (pyproject.toml), by the name used in import.
ADVANCED = {"torch", "torchvision", "torch_geometric", "transformers", "sentence_transformers", "nltk",
            "huggingface_hub", "tokenizers", "safetensors"}
# Import names whose package has a different name on PyPI.
PIP_NAMES = {"sklearn": "scikit-learn", "cv2": "opencv-python", "PIL": "pillow", "yaml": "pyyaml",
             "bs4": "beautifulsoup4", "sentence_transformers": "sentence-transformers", "docx": "python-docx",
             "fitz": "pymupdf", "dotenv": "python-dotenv"}


def missing_module_hint(evalue: str) -> str:
    """What to do about 'No module named X' in the tutor (Colab preinstalls many libraries; the tutor does not)."""
    m = MISSING_RE.search(evalue or "")
    if not m:
        return ""
    name = m.group(1)
    if name in ADVANCED:
        return (f"{name} is not installed in Notebook Tutor. It comes with the tutor's advanced option (PyTorch, "
                "sentence-transformers, PyTorch Geometric, NLTK): stop the tutor with Ctrl+C and start it with "
                "`uv run --extra advanced nt` in the tutor's folder (about 1 GB the first time). If you installed the tutor "
                "with `uv tool install`, install it again with the advanced option shown in the README.")
    return (f"{name} is not installed in Notebook Tutor (Colab preinstalls many libraries; the tutor does not). "
            f"Add a cell with `%pip install {PIP_NAMES.get(name, name)}`, run it, then click Restart Python and run "
            "the cells again.")
HELPERS = Path(__file__).with_name("kernel_helpers.py")
# Loaded by file path, so the kernel finds the helpers however the tutor was installed.
INSTALL_HELPERS = (
    "import importlib.util as _u, sys as _s\n"
    f"_spec = _u.spec_from_file_location('_nt_helpers', {str(HELPERS)!r})\n"
    "_nt_helpers = _u.module_from_spec(_spec); _spec.loader.exec_module(_nt_helpers)\n"
    "_s.modules['_nt_helpers'] = _nt_helpers; _nt_helpers.install(); del _u, _s, _spec\n"
)


class _SpecManager(KernelSpecManager):
    """Always launch the kernel with the Python that runs Notebook Tutor."""

    def get_kernel_spec(self, kernel_name):
        return KernelSpec(argv=[sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                          display_name="Python (Notebook Tutor)", language="python")


def clone_data_dir():
    """The data/ folder of the tutor's own git clone, when the tutor runs from one (uv run nt); else None.

    ai-learning-kit keeps the datasets it downloads or imports there (AILK_DATA_DIR), so that a clone holds
    its own copies; data/ is ignored by git. An installed tutor (uv tool install) leaves the kit's default.
    """
    repo = Path(__file__).resolve().parents[2]
    if (repo / ".git").exists() and (repo / "pyproject.toml").is_file():
        return repo / "data"
    return None


def _kit_version():
    try:
        from importlib.metadata import version
        return version("ai-learning-kit")
    except Exception:
        return None


def prepare(code: str) -> tuple[str, list]:
    """Skip pip lines that would only reinstall ai-learning-kit, which the tutor already provides.

    A notebook written for Colab starts with %pip install "...ai-learning-kit[graphs]@https://.../v0.5.0.zip". Here the kit is
    installed with the tutor; reinstalling it from inside the kernel could change the version under the
    tutor's feet. Any other pip line runs as written.
    """
    out, notes = [], []
    installed = _kit_version()
    for ln in code.split("\n"):
        m = KIT_PIN.match(ln)
        if m and "ai-learning-kit" in m["args"] and installed:
            pkgs = [a for a in m["args"].split() if not a.startswith("-") and a.strip("\"'") != "@"]
            if all("ai-learning-kit" in a for a in pkgs):
                notes.append(f"the tutor already provides ai-learning-kit {installed}, so nothing needs installing ({ln.strip()})")
                indent = ln[: len(ln) - len(ln.lstrip())]
                out.append(indent + "pass" if indent else "")
                continue
        out.append(ln)
    return "\n".join(out), notes


class KernelSession:
    def __init__(self, folder: Path, env_extra: dict | None = None):
        self.folder = Path(folder).resolve()   # long, absolute path (Windows temp paths can be 8.3 short names)
        self.env_extra = dict(env_extra or {})
        self.km = None
        self.kc = None
        self.lock = threading.Lock()
        self.generation = 0      # bumped by restart(), so a cell that is still waiting gives up at once

    # ------------------------------------------------------------------ lifecycle
    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items()                          # the student's keys stay out
               if k not in KEY_VARS and not k.endswith("_API_KEY")}
        data = clone_data_dir()
        if data is not None and not env.get("AILK_DATA_DIR"):
            env["AILK_DATA_DIR"] = str(data)            # datasets the kit downloads stay inside this clone
        env["MPLBACKEND"] = "Agg"
        env["NOTEBOOK_TUTOR"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env.update(self.env_extra)
        return env

    def start(self) -> None:
        if os.name == "posix":
            # Private socket files instead of local network ports: nothing else on the computer can connect,
            # and ipykernel no longer warns about unencrypted TCP. (Windows has no such sockets, so it keeps
            # TCP on 127.0.0.1.)
            self._ipc_dir = tempfile.mkdtemp(prefix="nt-")
            os.chmod(self._ipc_dir, 0o700)
            self.km = KernelManager(kernel_spec_manager=_SpecManager(), kernel_name="nt", transport="ipc",
                                    ip=os.path.join(self._ipc_dir, "k"))
        else:
            self.km = KernelManager(kernel_spec_manager=_SpecManager(), kernel_name="nt")
        self.km.start_kernel(cwd=str(self.folder), env=self._env())
        self.kc = self.km.client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=90)
        self._install_helpers()

    def _install_helpers(self) -> None:
        content = self._silent(INSTALL_HELPERS)
        if content.get("status") != "ok":
            raise RuntimeError(f"Could not prepare the kernel: {content.get('ename')}: {content.get('evalue')}")

    def alive(self) -> bool:
        return bool(self.km and self.km.is_alive())

    def restart(self) -> None:
        """Restart Python, also while a cell is stuck: the waiting run() sees the new generation and returns."""
        self.generation += 1
        if self.km is None:
            with self.lock:
                self.start()
            return
        self.km.restart_kernel(now=True)
        with self.lock:                       # run() has returned by now (it polls every half second)
            self.kc.wait_for_ready(timeout=90)
            self._drain()
            self._install_helpers()

    def interrupt(self) -> None:
        if self.km:
            self.km.interrupt_kernel()

    def shutdown(self) -> None:
        try:
            if self.kc:
                self.kc.stop_channels()
            if self.km:
                self.km.shutdown_kernel(now=True)
        except Exception:
            pass
        self.km = self.kc = None
        if getattr(self, "_ipc_dir", None):
            shutil.rmtree(self._ipc_dir, ignore_errors=True)
            self._ipc_dir = None

    # ------------------------------------------------------------------ messaging
    def _drain(self):
        while True:
            try:
                self.kc.get_iopub_msg(timeout=0.05)
            except queue.Empty:
                return

    def _reply(self, msg_id, timeout=None):
        while True:
            msg = self.kc.get_shell_msg(timeout=timeout)
            if msg["parent_header"].get("msg_id") == msg_id:
                return msg

    def _silent(self, code: str, user_expressions: dict | None = None, timeout: float = 60) -> dict:
        msg_id = self.kc.execute(code, silent=True, store_history=False, user_expressions=user_expressions or {},
                                 allow_stdin=False)
        reply = self._reply(msg_id, timeout=timeout)
        self._drain()
        return reply["content"]

    def _expr(self, expr: str, timeout: float = 60):
        content = self._silent("", {"r": expr}, timeout=timeout)
        r = (content.get("user_expressions") or {}).get("r") or {}
        if r.get("status") != "ok":
            return None
        text = (r.get("data") or {}).get("text/plain", "")
        try:
            return ast.literal_eval(text)
        except Exception:
            return text

    def run(self, code: str) -> dict:
        """Run one cell and collect everything it produced."""
        with self.lock:
            if not self.alive():
                if self.km is not None:
                    self.shutdown()            # tidy up after a kernel that died
                self.start()
            src, notes = prepare(code)
            if not src.strip():
                src = "pass"      # an empty cell still gets an execution count, so the page counts it as run
            msg_id = self.kc.execute(src, store_history=True, allow_stdin=False)
            stdout, stderr, results, figures, figdesc = [], [], [], [], []
            error = None
            gen = self.generation
            while True:
                try:
                    msg = self.kc.get_iopub_msg(timeout=0.5)
                except queue.Empty:
                    # the cell is still running, unless Python was restarted or has died (a crash, out of memory)
                    stopped = ("restarted" if self.generation != gen else
                               "stopped unexpectedly" if not self.km.is_alive() else None)
                    if stopped:
                        return {"count": None, "notes": notes, "stdout": "".join(stdout)[:MAX_TEXT],
                                "stderr": ANSI.sub("", "".join(stderr))[:5000], "results": results,
                                "figures": figures, "figure_desc": figdesc,
                                "error": {"ename": "KernelRestart" if stopped == "restarted" else "KernelDied",
                                          "evalue": f"Python {stopped} while this cell was running. Its variables "
                                                    "are gone: run the cells above again.",
                                          "traceback": "", "line": None}}
                    continue
                if msg["parent_header"].get("msg_id") != msg_id:
                    continue
                t, c = msg["msg_type"], msg["content"]
                if t == "status" and c.get("execution_state") == "idle":
                    break
                if t == "stream":
                    (stdout if c.get("name") == "stdout" else stderr).append(c.get("text", ""))
                elif t in ("execute_result", "display_data"):
                    data = c.get("data", {})
                    if "image/png" in data:
                        figures.append(data["image/png"].replace("\n", ""))
                        figdesc.append("Image displayed by the code")
                    if "text/html" in data:
                        results.append({"kind": "html", "html": data["text/html"], "text": data.get("text/plain", "")})
                    elif "text/markdown" in data:
                        results.append({"kind": "markdown", "text": data["text/markdown"]})
                    elif "text/plain" in data and "image/png" not in data:
                        results.append({"kind": "text", "text": data["text/plain"]})
                elif t == "clear_output":
                    stdout, results = [], []
                elif t == "error":
                    tb = ANSI.sub("", "\n".join(c.get("traceback", [])))
                    lines = LINE_RE.findall(tb)
                    error = {"ename": c.get("ename", "Error"), "evalue": c.get("evalue", ""), "traceback": tb,
                             "line": int(lines[-1]) if lines else None}
                    hint = missing_module_hint(error["evalue"]) if error["ename"] == "ModuleNotFoundError" else ""
                    if hint:
                        error["evalue"] += "\n\n" + hint
            reply = self._reply(msg_id)["content"]
            post = self._expr("_nt_helpers.post()") or "{}"
            try:
                import json
                extra = json.loads(post) if isinstance(post, str) else {}
            except Exception:
                extra = {}
            figures += extra.get("figures", [])
            figdesc += extra.get("figure_desc", [])
            so, se = "".join(stdout), ANSI.sub("", "".join(stderr))
            return {
                "count": reply.get("execution_count"),
                "notes": notes,
                "stdout": so[:MAX_TEXT] + ("\n…(output truncated)" if len(so) > MAX_TEXT else ""),
                "stderr": se[:5000],
                "results": results,
                "figures": figures,
                "figure_desc": figdesc,
                "error": error,
            }

    def vars_summary(self) -> str:
        with self.lock:
            if not self.alive():
                return "(Python has not started yet)"
            out = self._expr("_nt_helpers.vars_summary(globals())", timeout=30)
            return out if isinstance(out, str) else "(unavailable)"
