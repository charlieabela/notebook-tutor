"""Helpers that run inside the student's Python kernel.

The tutor calls these after each cell (through user_expressions, so nothing is
printed into the notebook): post() collects the figures the cell drew, with a
short text description for the tutor, and vars_summary() describes the variables
in memory. Matplotlib uses the non-interactive Agg backend, so plt.show() draws
nothing itself and the tutor shows the figures under the cell.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import types
import warnings

_MAX_FIGS = 12


def install() -> None:
    warnings.filterwarnings("ignore", message=".*non-interactive.*")
    warnings.filterwarnings("ignore", message=".*FigureCanvasAgg.*")


def _short(o, n=300):
    try:
        r = repr(o)
    except Exception:
        r = "<" + type(o).__name__ + ">"
    return r if len(r) <= n else r[:n] + "…"


def post() -> str:
    """JSON with the figures drawn by the last cell (base64 PNG) and a description of each."""
    imgs, desc = [], []
    if "matplotlib.pyplot" in sys.modules:
        import matplotlib.pyplot as plt
        for n in plt.get_fignums()[:_MAX_FIGS]:
            fig = plt.figure(n)
            b = io.BytesIO()
            try:
                fig.savefig(b, format="png", dpi=110, bbox_inches="tight")
            except Exception as e:  # a broken figure should not break the cell
                desc.append(f"(figure {n} could not be drawn: {e})")
                continue
            imgs.append(base64.b64encode(b.getvalue()).decode())
            parts = []
            for ax in fig.get_axes():
                d = []
                if ax.get_title():
                    d.append(f"title={ax.get_title()!r}")
                d.append(f"xlabel={ax.get_xlabel()!r}")
                d.append(f"ylabel={ax.get_ylabel()!r}")
                if ax.lines:
                    d.append(f"{len(ax.lines)} line(s)")
                if ax.collections:
                    pts = sum(len(c.get_offsets()) for c in ax.collections if hasattr(c, "get_offsets"))
                    d.append(f"{len(ax.collections)} scatter/collection(s) with {pts} points")
                if ax.patches:
                    d.append(f"{len(ax.patches)} bar/patch(es)")
                leg = ax.get_legend()
                if leg:
                    d.append("legend=" + ", ".join(t.get_text() for t in leg.get_texts()))
                parts.append("axes(" + "; ".join(d) + ")")
            desc.append(f"Figure {len(imgs)}: " + " ".join(parts))
        plt.close("all")
    return json.dumps({"figures": imgs, "figure_desc": desc})


def vars_summary(ns: dict) -> str:
    rows = []
    try:
        import pandas as pd
    except Exception:
        pd = None
    try:
        import numpy as np
    except Exception:
        np = None
    skip = {"In", "Out", "exit", "quit", "get_ipython", "display"}
    for k, v in list(ns.items()):
        if k.startswith("_") or k in skip:
            continue
        if isinstance(v, types.ModuleType):
            rows.append(f"{k}: module {v.__name__}")
            continue
        try:
            if pd is not None and isinstance(v, pd.DataFrame):
                cols = ", ".join(f"{c}:{t}" for c, t in list(v.dtypes.astype(str).items())[:12])
                rows.append(f"{k}: DataFrame shape={v.shape} columns=[{cols}]")
            elif pd is not None and isinstance(v, pd.Series):
                rows.append(f"{k}: Series len={len(v)} dtype={v.dtype} name={v.name!r}")
            elif np is not None and isinstance(v, np.ndarray):
                rows.append(f"{k}: ndarray shape={v.shape} dtype={v.dtype}")
            elif type(v).__module__.startswith("torch") and hasattr(v, "shape"):
                rows.append(f"{k}: tensor shape={tuple(v.shape)} dtype={getattr(v, 'dtype', '?')}")
            elif isinstance(v, type):
                rows.append(f"{k}: class {v.__name__}")
            elif hasattr(v, "get_params") and hasattr(v, "fit"):
                fitted = any(a.endswith("_") and not a.startswith("_") for a in vars(v))
                rows.append(f"{k}: {type(v).__name__} ({'fitted' if fitted else 'not fitted'})")
            elif callable(v):
                if getattr(v, "__module__", "") == "__main__":
                    rows.append(f"{k}: function defined in the notebook")
            elif isinstance(v, (list, tuple, dict, set)):
                rows.append(f"{k}: {type(v).__name__} len={len(v)} {_short(v, 80)}")
            else:
                rows.append(f"{k}: {type(v).__name__} = {_short(v, 80)}")
        except Exception:
            rows.append(f"{k}: {type(v).__name__}")
    return "\n".join(rows[:60]) or "(no variables yet)"
