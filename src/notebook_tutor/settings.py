"""The tutor's settings on this computer: which language model to use, and the student's key.

Settings live in the user's own configuration folder, never in the repository or
next to notebooks, so a key cannot end up in a notebook, an answer book or a git
commit. On macOS and Linux the file is readable by its owner only.

    Windows : %APPDATA%\\notebook-tutor\\settings.json
    macOS   : ~/Library/Application Support/notebook-tutor/settings.json
    Linux   : ~/.config/notebook-tutor/settings.json   (or $XDG_CONFIG_HOME)

NT_CONFIG_DIR overrides the folder (used by the tests).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROVIDERS = {
    "gemini": {"label": "Google Gemini (API key from Google AI Studio)", "needs_key": True, "needs_url": False,
               "key_url": "https://aistudio.google.com/apikey",
               "quick": "gemini-3.5-flash-lite", "thorough": "gemini-3.8-flash"},
    "anthropic": {"label": "Anthropic Claude (API key from the Claude Console)", "needs_key": True, "needs_url": False,
                  "key_url": "https://console.anthropic.com/settings/keys",
                  "quick": "claude-haiku-5-5", "thorough": "claude-sonnet-5-5"},
    "openai": {"label": "OpenAI (API key from the OpenAI platform)", "needs_key": True, "needs_url": False,
               "key_url": "https://platform.openai.com/api-keys", "quick": "", "thorough": ""},
    "ollama": {"label": "A model on this computer (Ollama)", "needs_key": False, "needs_url": True,
               "default_url": "http://localhost:11434", "quick": "", "thorough": ""},
    "openai-compatible": {"label": "Another server (OpenAI-compatible: LM Studio, vLLM, a course server)",
                          "needs_key": False, "needs_url": True, "default_url": "http://localhost:1234/v1",
                          "quick": "", "thorough": ""},
    "none": {"label": "No language model (Python and the kit's checks still work)", "needs_key": False,
             "needs_url": False, "quick": "", "thorough": ""},
}


def config_dir() -> Path:
    if os.environ.get("NT_CONFIG_DIR"):
        return Path(os.environ["NT_CONFIG_DIR"])
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "notebook-tutor"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "notebook-tutor"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "notebook-tutor"


def _path() -> Path:
    return config_dir() / "settings.json"


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("provider", "none")
    data.setdefault("model_quick", "")
    data.setdefault("model_thorough", "")
    data.setdefault("base_url", "")
    data.setdefault("api_keys", {})          # one key per provider, so switching back and forth keeps them
    return data


def save(data: dict) -> None:
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def public(data: dict) -> dict:
    """The settings as the browser may see them: keys are never sent, only whether one is stored."""
    key = (data.get("api_keys") or {}).get(data.get("provider"), "")
    return {"provider": data["provider"], "model_quick": data["model_quick"], "model_thorough": data["model_thorough"],
            "base_url": data["base_url"], "has_key": bool(key), "key_hint": ("…" + key[-4:]) if len(key) >= 8 else "",
            "providers": PROVIDERS, "config_file": str(_path())}


def update(data: dict, changes: dict) -> dict:
    provider = changes.get("provider", data["provider"])
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}")
    data["provider"] = provider
    for k in ("model_quick", "model_thorough", "base_url"):
        if k in changes and changes[k] is not None:
            data[k] = str(changes[k]).strip()
    if changes.get("api_key"):                         # an empty field keeps the stored key
        data["api_keys"][provider] = str(changes["api_key"]).strip()
    if changes.get("forget_key"):
        data["api_keys"].pop(provider, None)
    return data
