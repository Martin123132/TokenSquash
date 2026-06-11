from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from .metrics import count_tokens


DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
VALID_MODES = ("prompt", "reply")


def build_sidecar_request(
    text: str,
    *,
    mode: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
) -> dict[str, Any]:
    """Build an Ollama request for local semantic translation without sending it."""

    _validate_mode(mode)
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("sidecar text must not be empty")
    prompt = build_semantic_prompt(clean_text, mode=mode)
    return {
        "schema_version": "tokensquash.sidecar.request.v1",
        "status": "ready",
        "backend": "ollama",
        "model": model,
        "mode": mode,
        "endpoint": endpoint.rstrip("/"),
        "url": f"{endpoint.rstrip('/')}/api/generate",
        "payload": {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
    }


def translate_with_ollama(
    text: str,
    *,
    mode: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    counter: str = "heuristic",
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Ask a local Ollama model for compact semantic JSON and measure the result."""

    request_report = build_sidecar_request(text, mode=mode, model=model, endpoint=endpoint)
    request_payload = request_report["payload"]
    request = Request(
        request_report["url"],
        data=json.dumps(request_payload, ensure_ascii=True).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        ollama_payload = json.loads(response.read().decode("utf-8"))

    response_text = str(ollama_payload.get("response", "")).strip()
    semantic = parse_semantic_json(response_text)
    semantic_wire = json.dumps(semantic, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    original_tokens = count_tokens(text, counter)
    semantic_tokens = count_tokens(semantic_wire, counter)
    saved_tokens = original_tokens - semantic_tokens
    status = "saved" if saved_tokens > 0 else "loss" if saved_tokens < 0 else "same"
    return {
        "schema_version": "tokensquash.sidecar.semantic.v1",
        "status": status,
        "backend": "ollama",
        "model": model,
        "mode": mode,
        "endpoint": endpoint.rstrip("/"),
        "counter": counter,
        "summary": {
            "original_tokens": original_tokens,
            "semantic_tokens": semantic_tokens,
            "saved_tokens": saved_tokens,
            "saved_pct": _pct(saved_tokens, original_tokens),
        },
        "semantic": semantic,
        "semantic_wire": semantic_wire,
        "raw_response": response_text,
    }


def build_semantic_prompt(text: str, *, mode: str) -> str:
    _validate_mode(mode)
    if mode == "prompt":
        schema = (
            '{"kind":"prompt","op":"fix|add|review|explain|test|docs|refactor|other",'
            '"query":"short preserved task meaning","paths":[],"constraints":[],"verify":[],"returns":[]}'
        )
    else:
        schema = (
            '{"kind":"reply","status":"done|partial|blocked|failed","summary":"short preserved result",'
            '"files":[],"verification":[],"commands":[],"risks":[],"next_steps":[]}'
        )
    return "\n".join(
        [
            "You are a TokenSquash local semantic translator.",
            "Return ONLY valid compact JSON. Do not use markdown. Do not explain.",
            "Preserve meaning. Do not invent facts. Use [] for absent lists.",
            f"Use this JSON shape: {schema}",
            "",
            "English:",
            text.strip(),
        ]
    )


def parse_semantic_json(text: str) -> dict[str, Any]:
    """Parse strict JSON, allowing fenced or prefixed model output as a fallback."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise ValueError("local semantic response did not contain a JSON object") from None
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("local semantic response must be a JSON object")
    return payload


def format_sidecar_request_markdown(report: dict[str, Any]) -> str:
    payload = report.get("payload", {})
    lines = [
        "# TokenSquash Sidecar Request",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Backend: `{report.get('backend')}`",
        f"- Model: `{report.get('model')}`",
        f"- Mode: `{report.get('mode')}`",
        f"- URL: `{report.get('url')}`",
        "",
        "## Prompt",
        "",
        "```text",
        str(payload.get("prompt", "")),
        "```",
    ]
    return "\n".join(lines).rstrip() + "\n"


def format_sidecar_translation_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    semantic = json.dumps(report.get("semantic", {}), ensure_ascii=True, indent=2)
    lines = [
        "# TokenSquash Sidecar Translation",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Backend: `{report.get('backend')}`",
        f"- Model: `{report.get('model')}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Original tokens: `{summary.get('original_tokens', 0)}`",
        f"- Semantic tokens: `{summary.get('semantic_tokens', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        "",
        "## Semantic",
        "",
        "```json",
        semantic,
        "```",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _validate_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError(f"sidecar mode must be one of: {', '.join(VALID_MODES)}")


def _pct(part: int | float, whole: int | float) -> float:
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100.0, 4)
