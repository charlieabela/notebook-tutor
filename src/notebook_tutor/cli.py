"""Start Notebook Tutor.

    nt                          open the tutor on its own folder of notebooks: notebooks/ in the tutor's
                                git clone (uv run nt), or ~/NotebookTutor for an installed tutor
    nt path/to/folder           work with the notebooks in that folder
    nt path/to/notebook.ipynb   open that notebook (its folder becomes the tutor's folder)
    nt --port 8890              use this port (default 8765, or a free one if 8765 is taken)
    nt --no-browser             print the address instead of opening the browser
    nt --check                  check the installation and the language-model settings, then exit

Stop the tutor with Ctrl+C in this window.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__

LEGACY_ROOT = Path.home() / "NotebookTutor"


def default_root() -> Path:
    """Where the tutor keeps the notebooks students add: notebooks/ inside its own git clone (ignored by git),
    next to the clone's data/; an installed tutor (no clone) uses ~/NotebookTutor."""
    repo = Path(__file__).resolve().parents[2]
    if (repo / ".git").exists() and (repo / "pyproject.toml").is_file():
        return repo / "notebooks"
    return LEGACY_ROOT


def _has_notebooks(folder: Path) -> bool:
    try:
        return folder.is_dir() and any(p.suffix == ".ipynb" for p in folder.rglob("*.ipynb"))
    except OSError:
        return False


def _check() -> int:
    from . import llm_bridge, settings as S
    print(f"Notebook Tutor {__version__} on Python {sys.version.split()[0]} ({sys.executable})")
    ok = True
    for mod in ("jupyter_client", "ipykernel", "numpy", "pandas", "matplotlib", "seaborn", "sklearn", "networkx",
                "requests", "bs4", "pip", "ai_learning_kit"):
        try:
            m = __import__(mod)
            print(f"  ok   {mod} {getattr(m, '__version__', '')}")
        except Exception as e:
            ok = False
            print(f"  MISSING {mod}: {e}")
    for mod in ("torch", "torch_geometric", "sentence_transformers", "transformers", "nltk"):
        try:
            m = __import__(mod)
            print(f"  ok   {mod} {getattr(m, '__version__', '')} (optional)")
        except Exception:
            print(f"  --   {mod} not installed (optional; needed only by advanced topics)")
    data = S.load()
    print(f"Settings file: {S.config_dir() / 'settings.json'}")
    print(f"Language model: {data['provider']}")
    if data["provider"] != "none":
        out = llm_bridge.ask(data, "Reply with the single word: ready")
        print("  " + (f"ok: {out['text'][:60]!r}" if "text" in out else f"problem: {out['error']['message']}"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nt", description="Notebook Tutor", epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="a folder of notebooks, or one notebook")
    ap.add_argument("--port", type=int, default=None, help="default 8765, or any free port if that is taken")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--version", action="version", version=f"Notebook Tutor {__version__}")
    args = ap.parse_args(argv)

    if args.check:
        return _check()

    from .server import serve, url_for

    initial = None
    if args.target:
        t = Path(args.target).expanduser().resolve()
        if t.suffix == ".ipynb":
            if not t.is_file():
                print(f"No notebook at {t}")
                return 2
            root, initial = t.parent, t.name
        else:
            root = t
    else:
        root = default_root()
    app, httpd = serve(root, args.port, initial)
    if not args.target and app.root != LEGACY_ROOT.resolve() and _has_notebooks(LEGACY_ROOT):
        app.legacy = LEGACY_ROOT
    url = url_for(app)
    print(f"Notebook Tutor {__version__}")
    print(f"  Folder : {app.root}")
    if app.legacy:
        print(f"  Earlier notebooks: {app.legacy} (open them with Open notebook > Add a notebook, or run nt {app.legacy})")
    print(f"  Open   : {url}")
    print("  Stop   : press Ctrl+C in this window")
    if os.environ.get("TERM_PROGRAM") == "vscode":
        print("  VS Code: to work inside VS Code, press Cmd+Shift+P (Ctrl+Shift+P on Windows), run")
        print("           'Simple Browser: Show' and paste the Open address above.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        app.shutdown()
        httpd.server_close()
    return 0
