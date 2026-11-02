"""The tutor's connection to a language model, built on ai-learning-kit's providers.

The server holds the connection; the browser only sends prompts and receives text,
and the notebook's kernel reaches the same connection through a local
OpenAI-compatible endpoint. The student's key therefore never reaches the page,
the notebook, or anything saved next to it.
"""
from __future__ import annotations

import json
import re

from ai_learning_kit import llm as kit_llm
from ai_learning_kit.llm.providers import LLMError

from . import settings as S

# Generous limits: current models think before answering and the thinking counts against these. Only the tokens
# used are billed. (ai-learning-kit also enforces a floor of 4,096.)
MAX_TOKENS = {"quick": 6000, "default": 12000}
JSON_RULE = ("\n\nReply with only the JSON object described above: no prose before or after it, no Markdown code "
             "fences.")


def provider_from(data: dict):
    """A kit provider for the stored settings, or None when no model is configured."""
    name = data.get("provider", "none")
    if name == "none":
        return None
    key = (data.get("api_keys") or {}).get(name) or None
    model = data.get("model_thorough") or data.get("model_quick") or S.PROVIDERS[name].get("thorough") or None
    base_url = data.get("base_url") or S.PROVIDERS[name].get("default_url") or None
    if name == "openai-compatible" and not model:
        model = "default"
    return kit_llm.build(name, model=model, base_url=base_url, api_key=key)


def model_for(data: dict, tier: str) -> str | None:
    name = data.get("provider", "none")
    if tier == "quick":
        return data.get("model_quick") or S.PROVIDERS[name].get("quick") or data.get("model_thorough") or None
    return data.get("model_thorough") or S.PROVIDERS[name].get("thorough") or data.get("model_quick") or None


def _error(e: Exception) -> dict:
    if isinstance(e, LLMError):
        return {"code": e.code, "message": str(e)}
    if isinstance(e, ValueError):
        return {"code": "not_configured", "message": str(e)}
    return {"code": "error", "message": str(e)}


def extract_json(text: str):
    """The first JSON object in a model's reply (tolerates code fences and stray prose)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I | re.S)
    try:
        return json.loads(t)
    except Exception:
        pass
    start = t.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except Exception:
                        break
        start = t.find("{", start + 1)
    raise ValueError("no JSON object found")


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):          # content blocks: [{"type": "text", "text": ...}, ...]
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def flatten(prompt) -> str:
    """A prompt as one text. The page sends a follow-up conversation as a list of messages
    [{"role": "user"|"assistant", "content": ...}]; the first message holds the instructions and context."""
    if isinstance(prompt, str):
        return prompt
    if not isinstance(prompt, list):
        return str(prompt or "")
    msgs = [m for m in prompt if isinstance(m, dict)]
    if not msgs:
        return ""
    first, rest = _text_of(msgs[0].get("content")), msgs[1:]
    if not rest:
        return first
    history, last = rest[:-1], rest[-1]
    lines = [first, "", "CONVERSATION SO FAR:"] if history else [first]
    for m in history:
        who = "Tutor" if m.get("role") == "assistant" else "Student"
        lines.append(f"{who}: {_text_of(m.get('content'))}")
    lines += ["", "THE STUDENT NOW ASKS:", _text_of(last.get("content")),
              "", "Answer this question, taking the conversation above into account."]
    return "\n".join(lines)


def ask(data: dict, prompt, tier: str = "quick", want_json: bool = False, system: str | None = None) -> dict:
    """{"text": ..., "truncated": bool} or {"json": ...}, or {"error": {"code", "message"}}."""
    prompt = flatten(prompt)
    try:
        prov = provider_from(data)
    except Exception as e:
        return {"error": _error(e)}
    if prov is None:
        return {"error": {"code": "not_configured", "message": "No language model is set up."}}
    tier = tier if tier in MAX_TOKENS else "quick"
    model = model_for(data, tier)
    try:
        text = prov.complete(prompt + (JSON_RULE if want_json else ""), system=system,
                             max_tokens=MAX_TOKENS[tier], temperature=0.3, model=model)
        if not want_json:
            return {"text": text, "truncated": bool(getattr(prov, "truncated", False))}
        try:
            return {"json": extract_json(text)}
        except ValueError:
            if getattr(prov, "truncated", False):
                return {"error": {"code": "truncated", "message": "The model's reply was cut off before the end. "
                                  "Try again, or choose a faster model under Language model."}}
            text = prov.complete(prompt + JSON_RULE + "\nYour previous reply was not valid JSON. Send only the JSON.",
                                 system=system, max_tokens=MAX_TOKENS[tier], temperature=0.2, model=model)
            try:
                return {"json": extract_json(text)}
            except ValueError:
                return {"error": {"code": "invalid_json", "message": "The model's reply was not valid JSON."}}
    except Exception as e:
        return {"error": _error(e)}


def list_models(data: dict) -> dict:
    try:
        prov = provider_from(data)
        if prov is None:
            return {"models": []}
        return {"models": prov.list_models()}
    except Exception as e:
        return {"error": _error(e)}


def chat_completions(data: dict, body: dict) -> tuple[int, dict]:
    """A minimal OpenAI-compatible /v1/chat/completions for the kernel (the kit's kit.hint and kit.ask)."""
    msgs = body.get("messages") or []
    system = "\n\n".join(m.get("content", "") for m in msgs if m.get("role") == "system") or None
    prompt = "\n\n".join(m.get("content", "") for m in msgs if m.get("role") != "system")
    out = ask(data, prompt, tier="quick", system=system)
    if "error" in out:
        status = {"not_configured": 503, "bad_key": 401, "forbidden": 403, "model_not_found": 404,
                  "rate_limited": 429}.get(out["error"]["code"], 502)
        return status, {"error": {"message": out["error"]["message"], "code": out["error"]["code"]}}
    return 200, {"object": "chat.completion", "model": "notebook-tutor",
                 "choices": [{"index": 0, "message": {"role": "assistant", "content": out["text"]},
                              "finish_reason": "stop"}]}
