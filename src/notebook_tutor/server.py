"""The Notebook Tutor server: a small web server on this computer only.

It serves the tutor's page, runs the notebook's code in a Jupyter kernel started in
the notebook's folder, reads and writes notebooks and data files under one root
folder, and holds the connection to the language model.

Safety
- It listens on 127.0.0.1 only, so other computers cannot reach it.
- Every /api request must carry the session token (X-NT-Token), which is printed in
  the address the tutor opens; the page itself needs ?t=<token>.
- Host and Origin headers must name this server, which blocks DNS-rebinding and
  requests from other web pages.
- Paths are resolved inside the root folder; anything outside is refused.
- The kernel gets no API keys. Its language-model requests (kit.hint, kit.ask) go
  to /v1/chat/completions here, authenticated with a separate proxy token.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import os
import secrets
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import __version__
from . import kits
from . import llm_bridge
from . import settings as S
from .kernel import KernelSession

STATIC = Path(__file__).parent / "static"
NOTEBOOK_SKIP = {"answers", "__pycache__", "node_modules", "site-packages"}
MAX_UPLOAD = 300 * 1024 * 1024
MAX_JSON = 50 * 1024 * 1024
DATA_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl", ".xml", ".txt", ".md", ".xlsx", ".xls", ".parquet", ".pdf",
                 ".docx", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".npy", ".npz", ".pkl", ".pt", ".ttl", ".rdf",
                 ".graphml", ".gml", ".html", ".sqlite", ".db", ".py", ".yaml", ".yml", ".ipynb",
                 # archives and formats in which course datasets are published (Cora is cora.tgz)
                 ".tgz", ".gz", ".tar", ".bz2", ".xz", ".7z", ".h5", ".hdf5", ".feather", ".arrow", ".edgelist",
                 ".edges", ".nt", ".owl", ".jsonld", ".mat", ".tsv.gz"}


OPTIONAL_LIBS = ("torch", "torch_geometric", "transformers", "sentence_transformers", "rdflib", "spacy", "nltk")
BASE_LIBS = ("numpy", "pandas", "matplotlib", "seaborn", "sklearn", "scipy", "networkx", "openpyxl")


def installed_libs() -> list:
    """Libraries the kernel can import (checked without importing them)."""
    import importlib.util
    names = {"sklearn": "scikit-learn", "torch_geometric": "PyTorch Geometric", "torch": "PyTorch",
             "sentence_transformers": "sentence-transformers"}
    return [names.get(m, m) for m in BASE_LIBS + OPTIONAL_LIBS if importlib.util.find_spec(m) is not None]


def _prefs_path() -> Path:
    return S.config_dir() / "prefs.json"


def load_prefs() -> dict:
    try:
        return json.loads(_prefs_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_prefs(prefs: dict) -> None:
    S.config_dir().mkdir(parents=True, exist_ok=True)
    tmp = _prefs_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(prefs), encoding="utf-8")
    os.replace(tmp, _prefs_path())


STATIC_TYPES = {".js": "application/javascript", ".css": "text/css", ".html": "text/html", ".json": "application/json",
                ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".woff": "font/woff",
                ".txt": "text/plain", ".md": "text/markdown"}


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def notebook_home(data: bytes) -> str:
    """Where an added notebook is kept, relative to the tutor's folder: <topic> for a notebook built with
    ai-learning-kit, so a topic's notebooks share one folder (and the data files added for them), and notebooks
    of different topics never mix; the tutor's folder itself for any other notebook."""
    try:
        meta = json.loads(data.decode("utf-8")).get("metadata", {}).get("ai_learning_kit") or {}
    except Exception:
        return "."
    topic = re.sub(r"[^a-z0-9-]", "", str(meta.get("topic") or "").lower())
    return topic or "."


class App:
    def __init__(self, root: Path, port: int = 0, initial: str | None = None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.proxy_token = secrets.token_urlsafe(24)
        self.initial = initial
        self.settings = S.load()
        self.settings_lock = threading.Lock()
        self.kernel: KernelSession | None = None
        self.kernel_nb: Path | None = None
        self.kernel_lock = threading.Lock()
        self._reference: dict = {}            # (kit version, page name) -> Markdown, see kit_reference()
        self.legacy = None          # a folder of notebooks from an earlier version of the tutor, if any (set by nt)

    # ------------------------------------------------------------------ paths
    def resolve(self, rel: str, must_exist: bool = True) -> Path:
        if rel is None or rel == "":
            raise HttpError(400, "No path given.")
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise HttpError(403, "That path is outside the tutor's folder.")
        if must_exist and not p.exists():
            raise HttpError(404, f"Not found: {rel}")
        return p

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.root).as_posix()

    def notebooks(self) -> list:
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in NOTEBOOK_SKIP]
            depth = Path(dirpath).relative_to(self.root).parts
            if len(depth) > 4:
                dirnames[:] = []
            for f in filenames:
                if f.endswith(".ipynb") and not f.startswith("."):
                    p = Path(dirpath) / f
                    st = p.stat()
                    out.append({"path": self.rel(p), "name": f, "folder": self.rel(p.parent) if p.parent != self.root else "",
                                "modified": st.st_mtime, "size": st.st_size})
        out.sort(key=lambda r: -r["modified"])
        return out[:500]

    # ------------------------------------------------------------------ added notebooks
    # The tutor keeps one copy of each notebook a student adds, with their work in it. It remembers the checksum
    # of the file as it was added, so that adding it again can say whether the student chose the same file or a
    # different one (for example a version the lecturer updated).
    def _added_path(self) -> Path:
        return self.root / ".tutor" / "added.json"

    def added(self) -> dict:
        try:
            return json.loads(self._added_path().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def remember_added(self, p: Path, data: bytes) -> None:
        rec = self.added()
        rec[self.rel(p)] = {"sha256": _hash(data), "added": time.time()}
        self._added_path().parent.mkdir(parents=True, exist_ok=True)
        tmp = self._added_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        os.replace(tmp, self._added_path())

    def add_notebook(self, name: str, data: bytes, on_exists: str | None) -> tuple[int, dict]:
        """Keep an added notebook in the tutor's folder. When the student already has it, nothing is written
        and the reply says so ("exists"), until they choose: on_exists="open" keeps their saved copy, "replace"
        puts this file in its place."""
        try:
            json.loads(data.decode("utf-8"))
        except Exception:
            raise HttpError(400, f"{name} is not a notebook the tutor can read (it is not valid .ipynb JSON).")
        folder = self.resolve(notebook_home(data), must_exist=False)
        dest = folder / name
        if dest.exists():
            if on_exists == "open":
                return 200, {"saved": self.rel(dest), "name": dest.name, "kept": True}
            if on_exists != "replace":
                rec = self.added().get(self.rel(dest))
                return 200, {"exists": True, "existing": self.rel(dest), "modified": dest.stat().st_mtime,
                             "added": rec["added"] if rec else None,
                             "same_as_added": (rec["sha256"] == _hash(data)) if rec else None}
        folder.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name("." + dest.name + ".saving")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        self.remember_added(dest, data)
        return 200, {"saved": self.rel(dest), "name": dest.name, "replaced": on_exists == "replace"}

    def folder_files(self, folder_rel: str) -> list:
        """Files in a notebook's folder (two levels deep), as paths relative to that folder."""
        folder = self.resolve(folder_rel or ".")
        out = []
        for dirpath, dirnames, filenames in os.walk(folder):
            rel_dir = Path(dirpath).relative_to(folder)
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in NOTEBOOK_SKIP - {"answers"}
                                 and len(rel_dir.parts) < 2)
            for f in sorted(filenames):
                if f.startswith(".") or f.endswith(".ipynb"):
                    continue
                out.append((rel_dir / f).as_posix())
                if len(out) >= 200:
                    return out
        return out

    # ------------------------------------------------------------------ kernel
    def kernel_env(self, nb: Path) -> dict:
        return {
            "AILK_LLM_PROVIDER": "openai-compatible",
            "AILK_LLM_BASE_URL": f"http://127.0.0.1:{self.port}/v1",
            "AILK_LLM_API_KEY": self.proxy_token,
            "AILK_LLM_MODEL": "tutor",
            "JPY_SESSION_NAME": str(nb),          # lets the kit find the notebook's folder exactly
        }

    def notebook_kit(self, nb: Path) -> tuple[str | None, Path | None, str]:
        """(version, folder, problem) of the kit a notebook needs when the tutor's own kit cannot run it (a notebook
        written for an earlier major version): folder is None when it could not be downloaded, with the reason."""
        try:
            data = json.loads(nb.read_text(encoding="utf-8"))
        except Exception:
            return None, None, ""
        version, url = kits.requested(data)
        if not kits.needs_own_kit(version):
            return None, None, ""
        path, problem = kits.ensure(self.root, version, url)
        return version, path, problem

    def start_kernel(self, nb_rel: str, restart: bool = False) -> dict:
        nb = self.resolve(nb_rel, must_exist=False)
        with self.kernel_lock:
            if self.kernel and self.kernel_nb == nb and self.kernel.alive():
                if restart:
                    self.kernel.restart()          # also ends a cell that is still running
                    return {"started": True, "restarted": True, "folder": str(nb.parent)}
                return {"started": False, "folder": str(nb.parent)}
            if self.kernel:
                self.kernel.shutdown()
            env = self.kernel_env(nb)
            version, path, _ = self.notebook_kit(nb) if nb.is_file() else (None, None, "")
            if path is not None:                   # the notebook's own kit version comes first on the kernel's path
                env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(path), os.environ.get("PYTHONPATH")]))
            self.kernel = KernelSession(nb.parent, env, kit_version=version if path is not None else None)
            self.kernel_nb = nb
            self.kernel.start()
            return {"started": True, "folder": str(nb.parent), **({"kit": version} if path is not None else {})}

    def need_kernel(self) -> KernelSession:
        if not self.kernel:
            raise HttpError(409, "Python has not been started for a notebook yet.")
        return self.kernel

    def shutdown(self):
        if self.kernel:
            self.kernel.shutdown()

    # ------------------------------------------------------------------ settings
    def merged_settings(self, changes: dict | None) -> dict:
        """The stored settings with unsaved changes from the setup dialog applied (for Test and model lists)."""
        data = json.loads(json.dumps(self.settings))
        if changes:
            S.update(data, changes)
        return data

    # ------------------------------------------------------------------ kit
    def kit_context(self, nb_rel: str) -> dict:
        nb = self.resolve(nb_rel)
        try:
            meta = json.loads(nb.read_text(encoding="utf-8")).get("metadata", {}).get("ai_learning_kit") or {}
        except Exception:
            meta = {}
        try:
            import ai_learning_kit
            kit_version = ai_learning_kit.__version__
        except Exception:
            return {"kit": None}
        out = {"kit": kit_version, "notebook_meta": meta}
        version, path, problem = self.notebook_kit(nb)
        if version:
            out["notebook_kit"] = version
            if path is None:
                out["version_note"] = (f"This notebook was written for ai-learning-kit {version}, which the tutor "
                                       f"runs it with, but that version could not be downloaded ({problem}). "
                                       "Connect to the internet, then open the notebook again.")
                return out
            try:
                out["context"] = kits.context(path, meta)
            except Exception as e:
                out["context_error"] = f"{type(e).__name__}: {e}"
            return out
        if meta.get("topic"):
            try:
                from ai_learning_kit.core import registry
                out["context"] = registry.tutor_context(meta["topic"], level=meta.get("level"))
            except Exception as e:
                out["context_error"] = f"{type(e).__name__}: {e}"
        nb_version = meta.get("kit_version")
        # A notebook written for an earlier kit runs on a later one (the kit never changes released helpers), so
        # only a notebook that needs a newer kit than the tutor's is worth a notice.
        if nb_version and _version_tuple(nb_version) > _version_tuple(kit_version):
            out["version_note"] = (f"This notebook was written for ai-learning-kit {nb_version}; the tutor has "
                                   f"{kit_version}. Update the tutor (git pull in its folder) if a cell refers to "
                                   f"something missing.")
        return out


    def kit_reference(self, name: str = "") -> dict:
        """A page of the kit's topic reference, as Markdown: the topic called name, or the index with no name.

        Generated by the tutor's own kit (ai_learning_kit.dev.reference.page, from kit 1.1.0), so the page always
        describes the helpers the tutor's notebooks run with. Pages are kept once generated: a topic's page imports
        its helpers, which for the advanced topics means loading PyTorch."""
        try:
            import ai_learning_kit
            from ai_learning_kit import topics
            from ai_learning_kit.dev import reference
            kit_version = ai_learning_kit.__version__
        except Exception:
            return {"kit": None, "markdown": None,
                    "note": "The topic reference comes with ai-learning-kit 1.1.0 or later. Update the tutor "
                            "(git pull in its folder), then start it again."}
        if not hasattr(reference, "page"):
            return {"kit": kit_version, "markdown": None,
                    "note": f"The tutor's ai-learning-kit ({kit_version}) has no reference for front ends yet. "
                            "Update the tutor (git pull in its folder), then start it again."}
        names = list(topics.names())
        name = (name or "README").removesuffix(".md")
        if name not in names and name not in ("README", "index"):
            raise HttpError(404, f"ai-learning-kit {kit_version} has no topic called {name}.")
        key = (kit_version, name)
        if key not in self._reference:
            self._reference[key] = reference.page(name)
        from ai_learning_kit.core import registry
        titles = {}
        for n in names:
            try:
                titles[n] = registry.topic(n).TITLE
            except Exception:
                titles[n] = n
        return {"kit": kit_version, "name": "README" if name == "index" else name, "markdown": self._reference[key],
                "topics": [{"name": n, "title": titles[n]} for n in names]}


# ---------------------------------------------------------------------------------- HTTP
def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"NotebookTutor/{__version__}"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet by default
            if os.environ.get("NT_DEBUG"):
                super().log_message(fmt, *args)

        # ---------------------------------------------------------- helpers
        def _allowed_hosts(self):
            return {f"127.0.0.1:{app.port}", f"localhost:{app.port}"}

        def _check_host(self):
            if self.headers.get("Host", "") not in self._allowed_hosts():
                raise HttpError(403, "Unexpected Host header.")

        def _check_origin(self):
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{h}" for h in self._allowed_hosts()}:
                raise HttpError(403, "Requests from other sites are not allowed.")

        def _check_token(self):
            if not secrets.compare_digest(self.headers.get("X-NT-Token", ""), app.token):
                raise HttpError(401, "Missing or wrong session token. Open the address printed by `nt`.")

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, status: int = 200):
            self._send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

        def _body(self, limit: int = MAX_JSON) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise HttpError(413, "That upload is too large.")
            return self.rfile.read(n) if n else b""

        def _json_body(self) -> dict:
            raw = self._body()
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except Exception:
                raise HttpError(400, "The request body is not valid JSON.")

        def _query(self):
            u = urlparse(self.path)
            return u.path, {k: v[0] for k, v in parse_qs(u.query).items()}

        # ---------------------------------------------------------- dispatch
        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def _dispatch(self, method):
            try:
                self._check_host()
                path, q = self._query()
                if path.startswith("/v1/"):
                    return self._proxy(method, path)
                self._check_origin()
                if path in ("/", "/index.html"):
                    return self._index(q)
                if path.startswith("/static/"):
                    return self._static(path[len("/static/"):])
                if path == "/favicon.ico":
                    return self._send(204, b"", "image/x-icon")
                if path.startswith("/api/"):
                    self._check_token()
                    return self._api(method, path[len("/api/"):], q)
                raise HttpError(404, "Not found.")
            except HttpError as e:
                self._json({"error": {"code": "http_" + str(e.status), "message": e.message}}, e.status)
            except BrokenPipeError:
                pass
            except Exception as e:  # report, do not crash the server
                self._json({"error": {"code": "server_error", "message": f"{type(e).__name__}: {e}"}}, 500)

        # ---------------------------------------------------------- page and files
        def _index(self, q):
            if not secrets.compare_digest(q.get("t", ""), app.token):
                body = ("<!doctype html><meta charset='utf-8'><title>Notebook Tutor</title>"
                        "<body style='font-family:system-ui;max-width:36rem;margin:4rem auto;line-height:1.5'>"
                        "<h1>Notebook Tutor</h1><p>This address needs the session token. Use the full address "
                        "that <code>nt</code> printed in its window (it ends in <code>?t=…</code>), or start "
                        "<code>nt</code> again.</p></body>").encode()
                return self._send(401, body, "text/html; charset=utf-8")
            html = (STATIC / "index.html").read_text(encoding="utf-8")
            boot = {"token": app.token, "version": __version__, "root": str(app.root), "initial": app.initial,
                    "configured": app.settings.get("provider", "none") != "none", "prefs": load_prefs(),
                    "python": _py_version(), "kit": _kit_version(), "libs": installed_libs(),
                    "legacy": str(app.legacy) if app.legacy else None}
            inject = (f"<script>window.NT_BOOT={json.dumps(boot)};</script>\n"
                      f"<script src=\"/static/host.js?v={quote(__version__)}\"></script>\n")
            html = html.replace("<!--NT_HOST-->", inject, 1) if "<!--NT_HOST-->" in html else \
                html.replace("</head>", inject + "</head>", 1)
            csp = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com "
                   "https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com "
                   "https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com "
                   "https://cdn.jsdelivr.net; img-src 'self' data: blob:; connect-src 'self'")
            # No frame-ancestors restriction: VS Code's Simple Browser shows the page inside a frame. Framing by
            # another site gains nothing, because without the session token the page is only a 401 notice.
            self._send(200, html.encode(), "text/html; charset=utf-8", {"Content-Security-Policy": csp})

        def _static(self, rel):
            p = (STATIC / rel).resolve()
            if STATIC.resolve() not in p.parents or not p.is_file():
                raise HttpError(404, "Not found.")
            # Fixed types: on Windows, mimetypes reads the registry and may call .js "text/plain", which the
            # browser then refuses to run (nosniff).
            ctype = STATIC_TYPES.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self._send(200, p.read_bytes(), ctype, {"Cache-Control": "max-age=3600"})

        # ---------------------------------------------------------- the kernel's language-model endpoint
        def _proxy(self, method, path):
            auth = self.headers.get("Authorization", "")
            if not secrets.compare_digest(auth, f"Bearer {app.proxy_token}"):
                raise HttpError(401, "Wrong proxy token.")
            if path == "/v1/models" and method == "GET":
                return self._json({"object": "list", "data": [{"id": "tutor", "object": "model"}]})
            if path == "/v1/chat/completions" and method == "POST":
                with app.settings_lock:
                    data = json.loads(json.dumps(app.settings))
                status, body = llm_bridge.chat_completions(data, self._json_body())
                return self._json(body, status)
            raise HttpError(404, "Not found.")

        # ---------------------------------------------------------- API
        def _api(self, method, route, q):
            if route == "info" and method == "GET":
                return self._json({"version": __version__, "root": str(app.root), "initial": app.initial,
                                   "kit": _kit_version(), "python": _py_version()})

            if route == "open" and method == "POST":
                # Open a link from the notebook in the computer's own browser. The page asks for this when it is
                # shown inside VS Code's Simple Browser, where sites such as YouTube do not play.
                url = str(self._json_body().get("url", ""))
                if urlparse(url).scheme not in ("http", "https") or len(url) > 4000:
                    raise HttpError(400, "Only web links (http or https) can be opened.")
                return self._json({"opened": bool(webbrowser.open(url))})

            if route == "files" and method == "GET":
                return self._json({"files": app.folder_files(q.get("folder", ""))})

            if route == "prefs" and method == "PUT":
                body = self._json_body()
                if not isinstance(body, dict) or len(json.dumps(body)) > 200_000:
                    raise HttpError(400, "Preferences must be a small JSON object.")
                save_prefs(body)
                return self._json({"saved": True})

            if route == "notebooks" and method == "GET":
                return self._json({"root": str(app.root), "notebooks": app.notebooks()})

            if route == "notebook":
                if method == "GET":
                    p = app.resolve(q.get("path"))
                    return self._json({"path": app.rel(p), "name": p.name, "folder": str(p.parent),
                                       "text": p.read_text(encoding="utf-8"), "modified": p.stat().st_mtime})
                if method == "PUT":
                    body = self._json_body()
                    p = app.resolve(q.get("path"), must_exist=False)
                    if p.suffix != ".ipynb":
                        raise HttpError(400, "Only .ipynb files can be saved here.")
                    text = body.get("text", "")
                    json.loads(text)  # refuse to overwrite a notebook with something that is not JSON
                    p.parent.mkdir(parents=True, exist_ok=True)
                    tmp = p.with_name("." + p.name + ".saving")
                    tmp.write_text(text, encoding="utf-8")
                    os.replace(tmp, p)
                    return self._json({"saved": app.rel(p), "modified": p.stat().st_mtime})

            if route == "upload" and method == "POST":
                name = Path(q.get("name", "")).name
                if not name or name.startswith("."):
                    raise HttpError(400, "No file name given.")
                if q.get("kind") == "notebook":
                    if Path(name).suffix.lower() != ".ipynb":
                        raise HttpError(400, "Only .ipynb notebooks can be opened.")
                    status, out = app.add_notebook(name, self._body(MAX_UPLOAD), q.get("on_exists"))
                    return self._json(out, status)
                if Path(name).suffix.lower() not in DATA_SUFFIXES:
                    raise HttpError(400, f"Files of type {Path(name).suffix or '(none)'} are not accepted.")
                folder = app.resolve(q.get("folder") or ".", must_exist=False)
                folder.mkdir(parents=True, exist_ok=True)
                dest = folder / name
                dest.write_bytes(self._body(MAX_UPLOAD))
                return self._json({"saved": app.rel(dest), "name": dest.name, "folder": str(dest.parent)})

            if route == "kernel/start" and method == "POST":
                body = self._json_body()
                return self._json(app.start_kernel(body.get("path", ""), restart=bool(body.get("restart"))))
            if route == "kernel/restart" and method == "POST":
                k = app.need_kernel()
                k.restart()
                return self._json({"restarted": True})
            if route == "kernel/interrupt" and method == "POST":
                app.need_kernel().interrupt()
                return self._json({"interrupted": True})
            if route == "kernel/status" and method == "GET":
                k = app.kernel
                return self._json({"alive": bool(k and k.alive()),
                                   "notebook": app.rel(app.kernel_nb) if app.kernel_nb else None})
            if route == "run" and method == "POST":
                body = self._json_body()
                return self._json(app.need_kernel().run(body.get("code", "")))
            if route == "vars" and method == "GET":
                k = app.kernel
                return self._json({"text": k.vars_summary() if k else "(Python has not started yet)"})

            if route == "llm" and method == "POST":
                body = self._json_body()
                with app.settings_lock:
                    data = json.loads(json.dumps(app.settings))
                return self._json(llm_bridge.ask(data, body.get("prompt", ""), tier=body.get("tier", "quick"),
                                                 want_json=bool(body.get("json")), system=body.get("system")))

            if route == "settings":
                if method == "GET":
                    return self._json(S.public(app.settings))
                if method == "PUT":
                    body = self._json_body()
                    with app.settings_lock:
                        try:
                            S.update(app.settings, body)
                        except ValueError as e:
                            raise HttpError(400, str(e))
                        S.save(app.settings)
                        return self._json(S.public(app.settings))
            if route == "settings/test" and method == "POST":
                data = app.merged_settings(self._json_body())
                t0 = time.time()
                out = llm_bridge.ask(data, "Reply with the single word: ready", tier="quick")
                out["seconds"] = round(time.time() - t0, 1)
                out["model"] = llm_bridge.model_for(data, "quick") if data["provider"] != "none" else None
                return self._json(out)
            if route == "models" and method == "POST":
                return self._json(llm_bridge.list_models(app.merged_settings(self._json_body())))

            if route == "kit/context" and method == "GET":
                return self._json(app.kit_context(q.get("path", "")))
            if route == "kit/reference" and method == "GET":
                return self._json(app.kit_reference(q.get("topic", "")))

            raise HttpError(404, f"No such API route: {method} /api/{route}")

    return Handler


def _version_tuple(v) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def _kit_version():
    try:
        import ai_learning_kit
        return ai_learning_kit.__version__
    except Exception:
        return None


def _py_version():
    import sys
    return sys.version.split()[0]


DEFAULT_PORT = 8765


def serve(root: Path, port: int | None = None, initial: str | None = None) -> tuple[App, ThreadingHTTPServer]:
    """Create the app and server (bound to 127.0.0.1). Call httpd.serve_forever() to run it.

    port=None tries the default port and falls back to any free port; port=0 always takes a free one.
    """
    app = App(root, port or 0, initial)
    handler = make_handler(app)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", DEFAULT_PORT if port is None else port), handler)
    except OSError:
        if port is not None:
            raise
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    app.port = httpd.server_address[1]
    return app, httpd


def url_for(app: App) -> str:
    return f"http://127.0.0.1:{app.port}/?t={app.token}"
