"""Running each notebook with the ai-learning-kit version it names.

A notebook's first cell installs the kit version it was written for, and Colab and Jupyter run that line. The
tutor ships its own kit and skips the line, which is right while the notebook's version and the tutor's are
compatible. A notebook written for a kit of an earlier major version (0.x, when the tutor has 1.x) would fail on
the tutor's kit, so the tutor downloads the version the notebook names once, into a folder of its own
(<root>/.tutor/kits/<version>/), and starts that notebook's kernel with the folder first on its path. The tutor
itself keeps its own kit; it asks the notebook's version, in a separate process, for the scope it explains.

The download is the release archive the notebook's own install line names (only the kit itself: its libraries
are already installed with the tutor), so it needs the internet once per version, as Colab does every time.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ARCHIVE = "https://github.com/charlieabela/ai-learning-kit/archive/refs/tags/v{version}.zip"
VERSION_IN_LINE = re.compile(r"ai-learning-kit[^\s\"']*@\s*(?P<url>[^\s\"']*?v(?P<version>\d+\.\d+\.\d+)(?:\.zip)?)[\"'\s]")


def _version_tuple(v) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:3])


def bundled() -> str | None:
    """The version of the kit the tutor imports (and a kernel would import without a folder of its own)."""
    try:
        import ai_learning_kit
        return ai_learning_kit.__version__
    except Exception:
        try:
            from importlib.metadata import version
            return version("ai-learning-kit")
        except Exception:
            return None


def requested(nb: dict) -> tuple[str | None, str | None]:
    """(version, archive URL) the notebook names: its kit metadata, else its install line."""
    meta = (nb.get("metadata") or {}).get("ai_learning_kit") or {}
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        m = VERSION_IN_LINE.search(src + "\n")
        if m:
            url = m["url"] if m["url"].startswith("http") else ARCHIVE.format(version=m["version"])
            return meta.get("kit_version") or m["version"], url
        break                                   # only the first code cell holds the install line
    v = meta.get("kit_version")
    return (v, ARCHIVE.format(version=v)) if v else (None, None)


def needs_own_kit(version: str | None, tutor_version: str | None = None) -> bool:
    """True when the notebook was written for an earlier major version of the kit than the tutor ships.

    Within one major version the kit only adds (released helpers never change), so the tutor's kit runs any
    notebook written for the same or an earlier release of it."""
    tutor_version = tutor_version or bundled()
    if not version or not tutor_version:
        return False
    return _version_tuple(version)[:1] < _version_tuple(tutor_version)[:1]


def folder(root: Path, version: str) -> Path:
    return Path(root) / ".tutor" / "kits" / version


def ensure(root: Path, version: str, url: str | None = None, timeout: int = 600) -> tuple[Path | None, str]:
    """The folder holding kit `version`, downloading it the first time; (None, reason) when that fails."""
    target = folder(root, version)
    if (target / "ai_learning_kit" / "__init__.py").is_file():
        return target, ""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f"kit-{version}-", dir=target.parent))
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-deps",
           "--no-compile", "--target", str(tmp), f"ai-learning-kit@{url or ARCHIVE.format(version=version)}"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return None, f"{type(e).__name__}: {e}"
    if done.returncode != 0 or not (tmp / "ai_learning_kit" / "__init__.py").is_file():
        shutil.rmtree(tmp, ignore_errors=True)
        last = (done.stderr or done.stdout or "").strip().splitlines()
        return None, last[-1] if last else f"pip exited with {done.returncode}"
    if target.exists():                         # another request finished first
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        os.replace(tmp, target)
    return target, ""


_CONTEXT = """
import json, sys
from ai_learning_kit.core import registry
meta = json.loads(sys.argv[1])
if meta.get("topic"):
    ctx = registry.tutor_context(meta["topic"], level=meta.get("level"))
else:
    ctx = registry.tutor_context(meta["unit"], meta["session"])
print(json.dumps(ctx))
"""


def context(kit_folder: Path, meta: dict, timeout: int = 60) -> dict:
    """registry.tutor_context() as the notebook's own kit version describes it (run in a separate process)."""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(kit_folder), os.environ.get("PYTHONPATH")])))
    done = subprocess.run([sys.executable, "-c", _CONTEXT, json.dumps(meta)], capture_output=True, text=True,
                          timeout=timeout, env=env)
    if done.returncode != 0:
        last = (done.stderr or "").strip().splitlines()
        raise RuntimeError(last[-1] if last else "the notebook's kit could not describe it")
    return json.loads(done.stdout.strip().splitlines()[-1])
