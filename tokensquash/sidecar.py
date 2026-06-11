from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .metrics import count_tokens


DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
VALID_MODES = ("prompt", "reply")
STATUS_CODES = {"done": "d", "partial": "p", "blocked": "b", "failed": "f"}
STATUS_FROM_CODES = {value: key for key, value in STATUS_CODES.items()}


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
    semantic = _normalize_semantic_payload(parse_semantic_json(response_text), mode, source_text=text)
    semantic_compact = compact_semantic_payload(semantic, mode=mode)
    semantic_wire = json.dumps(semantic_compact, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
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
        "semantic_compact": semantic_compact,
        "semantic_wire": semantic_wire,
        "raw_response": response_text,
    }


def decode_semantic(semantic: dict[str, Any], *, mode: str) -> dict[str, Any]:
    """Decode semantic JSON back into human-readable English."""

    _validate_mode(mode)
    if not isinstance(semantic, dict):
        raise ValueError("semantic payload must be a JSON object")

    semantic = _normalize_semantic_payload(semantic, mode)
    warnings: list[str] = []
    kind = semantic.get("kind")
    if kind is None:
        pass
    elif kind != mode:
        warnings.append(f"semantic.kind '{kind}' does not match requested mode '{mode}'")

    if mode == "prompt":
        text = _decode_prompt_semantic(semantic, warnings=warnings)
    else:
        text = _decode_reply_semantic(semantic, warnings=warnings)

    return {
        "schema_version": "tokensquash.sidecar.decode.v1",
        "status": "warn" if warnings else "pass",
        "mode": mode,
        "kind": kind,
        "semantic": semantic,
        "text": text,
        "warnings": warnings,
    }


def compact_semantic_payload(
    semantic: dict[str, Any],
    *,
    mode: str,
    source_text: str | None = None,
) -> dict[str, Any]:
    """Convert normalized semantic JSON into the compact measured wire shape."""

    normalized = _normalize_semantic_payload(semantic, mode, source_text=source_text)
    if mode == "prompt":
        return _compact_prompt_semantic(normalized)
    return _compact_reply_semantic(normalized)


def roundtrip_with_ollama(
    text: str,
    *,
    mode: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    counter: str = "heuristic",
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Translate then decode the semantic payload and report token deltas."""

    translation = translate_with_ollama(
        text,
        mode=mode,
        model=model,
        endpoint=endpoint,
        counter=counter,
        timeout_seconds=timeout_seconds,
    )
    decoded = decode_semantic(translation["semantic"], mode=mode)
    warnings = decoded.get("warnings", [])

    summary = translation["summary"]
    report_status = translation["status"]
    if warnings:
        report_status = "warn"

    return {
        "schema_version": "tokensquash.sidecar.roundtrip.v1",
        "status": report_status,
        "backend": "ollama",
        "model": model,
        "mode": mode,
        "endpoint": endpoint.rstrip("/"),
        "counter": counter,
        "original_text": text,
        "semantic": translation["semantic"],
        "semantic_wire": translation["semantic_wire"],
        "decoded_text": decoded["text"],
        "summary": summary,
        "warnings": warnings,
        "raw_response": translation["raw_response"],
    }


def evaluate_sidecar_turns(
    records: list[dict[str, Any]],
    *,
    source: str,
    part: str = "both",
    limit: int = 0,
    model: str = DEFAULT_OLLAMA_MODEL,
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    counter: str = "heuristic",
    timeout_seconds: float = 60.0,
    example_limit: int = 5,
) -> dict[str, Any]:
    """Run sidecar round-trip evaluation over prompt/reply turn records."""

    started = time.time()
    if part not in {"prompt", "reply", "both"}:
        raise ValueError("sidecar evaluation mode must be one of: prompt, reply, both")
    if limit < 0:
        raise ValueError("sidecar evaluation limit must be zero or greater")

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    attempted = 0

    for index, record in enumerate(records, start=1):
        for side, text in _sidecar_turn_items(record, part):
            if limit and attempted >= limit:
                break
            attempted += 1
            item_id = record.get("id") or f"turn-{index:04d}"
            try:
                result = roundtrip_with_ollama(
                    text,
                    mode=side,
                    model=model,
                    endpoint=endpoint,
                    counter=counter,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                failures.append(
                    {
                        "index": index,
                        "id": item_id,
                        "side": side,
                        "error": str(exc),
                        "original_preview": _preview(text),
                    }
                )
                continue

            summary = result.get("summary", {})
            rows.append(
                {
                    "index": index,
                    "id": item_id,
                    "side": side,
                    "status": result.get("status"),
                    "original_tokens": int(summary.get("original_tokens", 0)),
                    "semantic_tokens": int(summary.get("semantic_tokens", 0)),
                    "saved_tokens": int(summary.get("saved_tokens", 0)),
                    "saved_pct": float(summary.get("saved_pct", 0.0)),
                    "warning_count": len(result.get("warnings", [])),
                    "warnings": result.get("warnings", []),
                    "original_preview": _preview(result.get("original_text", text)),
                    "decoded_preview": _preview(result.get("decoded_text", "")),
                    "semantic": result.get("semantic", {}),
                }
            )
        if limit and attempted >= limit:
            break

    summary = _sidecar_evaluation_summary(
        records=records,
        rows=rows,
        failures=failures,
        attempted=attempted,
        elapsed_seconds=time.time() - started,
    )
    status = (
        "empty"
        if attempted == 0
        else "fail"
        if failures and not rows
        else "warn"
        if failures or summary["warning_count"]
        else "pass"
    )
    return {
        "schema_version": "tokensquash.sidecar.evaluate.v1",
        "status": status,
        "backend": "ollama",
        "model": model,
        "endpoint": endpoint.rstrip("/"),
        "counter": counter,
        "source": source,
        "mode": part,
        "limit": limit,
        "summary": summary,
        "best_examples": _rank_sidecar_examples(rows, reverse=True, limit=example_limit),
        "worst_examples": _rank_sidecar_examples(rows, reverse=False, limit=example_limit),
        "warning_examples": [row for row in rows if row.get("warnings")][:example_limit],
        "failures": failures,
        "rows": rows,
    }


def compare_sidecar_evaluations(base_path: Path | str, target_path: Path | str) -> dict[str, Any]:
    """Compare two saved sidecar evaluation reports."""

    base = _load_sidecar_evaluation(base_path)
    target = _load_sidecar_evaluation(target_path)
    base_summary = base.get("summary", {})
    target_summary = target.get("summary", {})
    delta = _sidecar_summary_delta(base_summary, target_summary)
    status = _sidecar_comparison_status(delta)
    return {
        "schema_version": "tokensquash.sidecar.evaluate.compare.v1",
        "status": status,
        "base": _sidecar_report_brief(base, base_path),
        "target": _sidecar_report_brief(target, target_path),
        "delta": delta,
        "notes": _sidecar_comparison_notes(delta),
    }


def build_semantic_prompt(text: str, *, mode: str) -> str:
    _validate_mode(mode)
    if mode == "prompt":
        schema = (
            '{"o":"fix|add|review|explain|test|docs|refactor|other",'
            '"q":"<=5 words","p":["paths"],"c":["constraints"],"v":["verify"],"r":["returns"]}'
        )
        legend = "prompt keys: o operation, q task gist, p paths, c constraints, v verification, r return wants."
    else:
        schema = (
            '{"s":"d|p|b|f","m":"<=6 words","f":["files"],"v":["verification"],'
            '"c":["commands"],"r":["risks"],"n":["next steps"]}'
        )
        legend = "reply keys: s status (d done, p partial, b blocked, f failed), m result gist, f files, v verification, c commands, r risks, n next steps."
    return "\n".join(
        [
            "You are a TokenSquash local semantic translator.",
            "Return ONLY valid compact JSON. Do not use markdown. Do not explain.",
            "Use ONLY the short keys shown below. Do not use long key names.",
            "The mode is already known; do not include a kind key.",
            "Preserve meaning, but do not copy whole sentences.",
            "Keep q/m very short. Move paths, commands, tests, risks, and returns into their fields.",
            "Only include exact file paths; never use placeholders like files, code, test, or path.",
            "Omit empty optional arrays instead of writing []. Do not invent facts.",
            legend,
            f"Use this compact JSON shape: {schema}",
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


def format_sidecar_decode_markdown(report: dict[str, Any]) -> str:
    warnings = report.get("warnings", [])
    payload = json.dumps(report.get("semantic", {}), ensure_ascii=True, indent=2)
    lines = [
        "# TokenSquash Sidecar Decode",
        "",
        f"- Mode: `{report.get('mode')}`",
        f"- Kind: `{report.get('kind')}`",
        f"- Status: `{report.get('status')}`",
        "",
        "## English",
        "",
        str(report.get("text", "")),
        "",
        "## Semantic",
        "",
        "```json",
        payload,
        "```",
    ]
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines).rstrip() + "\n"


def format_sidecar_roundtrip_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    semantic = json.dumps(report.get("semantic", {}), ensure_ascii=True, indent=2)
    warnings = report.get("warnings", [])
    lines = [
        "# TokenSquash Sidecar Roundtrip",
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
        "## Original",
        "",
        "```text",
        str(report.get("original_text", "")),
        "```",
        "",
        "## Semantic",
        "",
        "```json",
        semantic,
        "```",
        "",
        "## Decoded",
        "",
        str(report.get("decoded_text", "")),
    ]
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines).rstrip() + "\n"


def format_sidecar_evaluation_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Sidecar Evaluation",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source')}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Model: `{report.get('model')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Evaluated items: `{summary.get('item_count', 0)}`",
        f"- Failures: `{summary.get('failure_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Original tokens: `{summary.get('original_tokens', 0)}`",
        f"- Semantic tokens: `{summary.get('semantic_tokens', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        "",
        "## Outcomes",
        "",
        f"- Wins: `{summary.get('win_items', 0)}`",
        f"- Losses: `{summary.get('loss_items', 0)}`",
        f"- Ties: `{summary.get('tie_items', 0)}`",
        f"- Prompt items: `{summary.get('prompt_items', 0)}`",
        f"- Reply items: `{summary.get('reply_items', 0)}`",
        "",
    ]
    outputs = report.get("outputs", {})
    if outputs:
        lines.extend(["## Outputs", ""])
        for key, path in sorted(outputs.items()):
            lines.append(f"- {key}: `{path}`")
        lines.append("")
    _append_sidecar_example_table(lines, "Best Examples", report.get("best_examples", []))
    _append_sidecar_example_table(lines, "Worst Examples", report.get("worst_examples", []))
    _append_sidecar_failure_table(lines, report.get("failures", []))
    return "\n".join(lines).rstrip() + "\n"


def format_sidecar_evaluation_compare_markdown(report: dict[str, Any]) -> str:
    base = report.get("base", {})
    target = report.get("target", {})
    delta = report.get("delta", {})
    lines = [
        "# TokenSquash Sidecar Evaluation Compare",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Base: `{base.get('path')}`",
        f"- Target: `{target.get('path')}`",
        f"- Saved tokens delta: `{delta.get('saved_tokens', 0)}`",
        f"- Saved percent delta: `{delta.get('saved_pct', 0.0)}%`",
        f"- Warning delta: `{delta.get('warning_count', 0)}`",
        f"- Failure delta: `{delta.get('failure_count', 0)}`",
        "",
        "## Summary Delta",
        "",
        "| Metric | Base | Target | Delta |",
        "|---|---:|---:|---:|",
    ]
    for key in (
        "item_count",
        "success_count",
        "failure_count",
        "warning_count",
        "original_tokens",
        "semantic_tokens",
        "saved_tokens",
        "saved_pct",
        "win_items",
        "loss_items",
        "tie_items",
    ):
        lines.append(
            "| "
            f"{key} | "
            f"{base.get('summary', {}).get(key, 0)} | "
            f"{target.get('summary', {}).get(key, 0)} | "
            f"{delta.get(key, 0)} |"
        )
    notes = report.get("notes", [])
    if notes:
        lines.extend(["", "## Notes", ""])
        for note in notes:
            lines.append(f"- {note}")
    return "\n".join(lines).rstrip() + "\n"


def format_sidecar_experiment_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs", {})
    lines = [
        "# TokenSquash Sidecar Experiment",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Name: `{report.get('name')}`",
        f"- Run ID: `{report.get('run_id')}`",
        f"- Source: `{report.get('source')}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Model: `{report.get('model')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Output: `{report.get('output_dir')}`",
        "",
        "## Summary",
        "",
        f"- Evaluated items: `{summary.get('item_count', 0)}`",
        f"- Failures: `{summary.get('failure_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Original tokens: `{summary.get('original_tokens', 0)}`",
        f"- Semantic tokens: `{summary.get('semantic_tokens', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        "",
        "## Outputs",
        "",
    ]
    for key in ("run", "summary", "evaluation", "rows"):
        if key in outputs:
            lines.append(f"- {key}: `{outputs[key]}`")
    return "\n".join(lines).rstrip() + "\n"


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


def _load_sidecar_evaluation(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("sidecar evaluation report must be a JSON object")
    if payload.get("schema_version") != "tokensquash.sidecar.evaluate.v1":
        raise ValueError(f"not a sidecar evaluation report: {source}")
    return payload


def _sidecar_report_brief(report: dict[str, Any], path: Path | str) -> dict[str, Any]:
    return {
        "path": str(Path(path)),
        "status": report.get("status"),
        "source": report.get("source"),
        "mode": report.get("mode"),
        "model": report.get("model"),
        "counter": report.get("counter"),
        "summary": report.get("summary", {}),
    }


def _sidecar_summary_delta(base: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "turn_count",
        "attempted_items",
        "item_count",
        "success_count",
        "failure_count",
        "warning_count",
        "original_tokens",
        "semantic_tokens",
        "saved_tokens",
        "saved_pct",
        "win_items",
        "loss_items",
        "tie_items",
        "prompt_items",
        "reply_items",
    )
    delta: dict[str, Any] = {}
    for field in fields:
        delta[field] = _numeric(target.get(field, 0)) - _numeric(base.get(field, 0))
        if isinstance(delta[field], float):
            delta[field] = round(delta[field], 4)
    delta["quality_signal_delta"] = int(delta.get("failure_count", 0)) + int(delta.get("warning_count", 0))
    return delta


def _sidecar_comparison_status(delta: dict[str, Any]) -> str:
    savings_delta = float(delta.get("saved_pct", 0.0))
    token_delta = int(delta.get("saved_tokens", 0))
    quality_delta = int(delta.get("quality_signal_delta", 0))
    savings_better = savings_delta > 0 or token_delta > 0
    savings_worse = savings_delta < 0 or token_delta < 0
    quality_better = quality_delta < 0
    quality_worse = quality_delta > 0

    if (savings_better and not quality_worse) or (quality_better and not savings_worse):
        return "improved"
    if (savings_worse and not quality_better) or (quality_worse and not savings_better):
        return "regressed"
    if (savings_better and quality_worse) or (savings_worse and quality_better):
        return "mixed"
    return "same"


def _sidecar_comparison_notes(delta: dict[str, Any]) -> list[str]:
    notes = []
    saved_tokens = int(delta.get("saved_tokens", 0))
    saved_pct = float(delta.get("saved_pct", 0.0))
    quality_delta = int(delta.get("quality_signal_delta", 0))
    if saved_tokens > 0 or saved_pct > 0:
        notes.append("Target saves more tokens than base.")
    elif saved_tokens < 0 or saved_pct < 0:
        notes.append("Target saves fewer tokens than base.")
    else:
        notes.append("Target token savings are unchanged.")

    if quality_delta < 0:
        notes.append("Target has fewer warning/failure signals.")
    elif quality_delta > 0:
        notes.append("Target has more warning/failure signals.")
    else:
        notes.append("Target warning/failure signals are unchanged.")
    return notes


def _numeric(value: Any) -> int | float:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return value
    try:
        text = str(value)
        return float(text) if "." in text else int(text)
    except (TypeError, ValueError):
        return 0


def _normalize_semantic_payload(
    payload: dict[str, Any],
    mode: str,
    *,
    source_text: str | None = None,
) -> dict[str, Any]:
    _validate_mode(mode)
    if mode == "prompt":
        return _normalize_prompt_semantic(payload, source_text=source_text)
    return _normalize_reply_semantic(payload, source_text=source_text)


def _normalize_prompt_semantic(payload: dict[str, Any], *, source_text: str | None = None) -> dict[str, Any]:
    paths = _semantic_list(_semantic_value(payload, "paths", "p", default=[]))
    return {
        "kind": _normalize_kind(_semantic_value(payload, "kind", "k")),
        "op": str(_semantic_value(payload, "op", "o", default="other")).strip() or "other",
        "query": str(_semantic_value(payload, "query", "q", default="")).strip(),
        "paths": _source_anchored_items(paths, source_text),
        "constraints": _semantic_list(_semantic_value(payload, "constraints", "c", default=[])),
        "verify": _semantic_list(_semantic_value(payload, "verify", "v", default=[])),
        "returns": _semantic_list(_semantic_value(payload, "returns", "r", default=[])),
    }


def _normalize_reply_semantic(payload: dict[str, Any], *, source_text: str | None = None) -> dict[str, Any]:
    status = str(_semantic_value(payload, "status", "s", default="done")).strip()
    status = STATUS_FROM_CODES.get(status, status)
    files = _semantic_list(_semantic_value(payload, "files", "f", default=[]))
    next_steps = _semantic_list(_semantic_value(payload, "next_steps", "n", default=[]))
    return {
        "kind": _normalize_kind(_semantic_value(payload, "kind", "k")),
        "status": status or "done",
        "summary": str(_semantic_value(payload, "summary", "m", default="")).strip(),
        "files": _source_anchored_items(files, source_text),
        "verification": _semantic_list(_semantic_value(payload, "verification", "v", default=[])),
        "commands": _semantic_list(_semantic_value(payload, "commands", "c", default=[])),
        "risks": _semantic_list(_semantic_value(payload, "risks", "r", default=[])),
        "next_steps": _source_anchored_items(next_steps, source_text),
    }


def _semantic_value(payload: dict[str, Any], long_key: str, short_key: str, default: Any = None) -> Any:
    if long_key in payload:
        return payload[long_key]
    if short_key in payload:
        return payload[short_key]
    return default


def _semantic_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_kind(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text == "p":
        return "prompt"
    if text == "r":
        return "reply"
    if text in VALID_MODES:
        return text
    return None


def _source_anchored_items(items: list[str], source_text: str | None) -> list[str]:
    if source_text is None:
        return items
    return [item for item in items if _source_contains_item(source_text, item)]


def _source_contains_item(source_text: str, item: str) -> bool:
    clean_item = item.strip().strip("`'\"")
    if not clean_item:
        return False
    source_variants = _path_text_variants(source_text)
    item_variants = _path_text_variants(clean_item)
    return any(item_variant in source_variant for source_variant in source_variants for item_variant in item_variants)


def _path_text_variants(text: str) -> set[str]:
    lowered = text.lower()
    return {lowered, lowered.replace("\\", "/"), lowered.replace("/", "\\")}


def _compact_prompt_semantic(semantic: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "o": semantic.get("op") or "other",
    }
    _compact_optional_text(compact, "q", semantic.get("query"))
    _compact_optional_list(compact, "p", semantic.get("paths"))
    _compact_optional_list(compact, "c", semantic.get("constraints"))
    _compact_optional_list(compact, "v", semantic.get("verify"))
    _compact_optional_list(compact, "r", semantic.get("returns"))
    return compact


def _compact_reply_semantic(semantic: dict[str, Any]) -> dict[str, Any]:
    status = str(semantic.get("status") or "done").strip()
    compact: dict[str, Any] = {
        "s": STATUS_CODES.get(status, status),
    }
    _compact_optional_text(compact, "m", semantic.get("summary"))
    _compact_optional_list(compact, "f", semantic.get("files"))
    _compact_optional_list(compact, "v", semantic.get("verification"))
    _compact_optional_list(compact, "c", semantic.get("commands"))
    _compact_optional_list(compact, "r", semantic.get("risks"))
    _compact_optional_list(compact, "n", semantic.get("next_steps"))
    return compact


def _compact_optional_text(payload: dict[str, Any], key: str, value: Any) -> None:
    text = str(value or "").strip()
    if text:
        payload[key] = text


def _compact_optional_list(payload: dict[str, Any], key: str, value: Any) -> None:
    items = [_compact_list_item(item) for item in _semantic_list(value)]
    items = [item for item in items if item]
    if items:
        payload[key] = items


def _compact_list_item(item: str) -> str:
    text = item.strip()
    lowered = text.lower()
    for prefix in ("verified with ", "verified: "):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _sidecar_turn_items(record: dict[str, Any], part: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if part in {"prompt", "both"}:
        prompt = str(record.get("prompt", "")).strip()
        if prompt:
            items.append(("prompt", prompt))
    if part in {"reply", "both"}:
        reply = str(record.get("reply_text") or record.get("reply") or "").strip()
        if reply:
            items.append(("reply", reply))
    return items


def _sidecar_evaluation_summary(
    *,
    records: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    attempted: int,
    elapsed_seconds: float,
) -> dict[str, Any]:
    original_tokens = sum(int(row["original_tokens"]) for row in rows)
    semantic_tokens = sum(int(row["semantic_tokens"]) for row in rows)
    saved_tokens = sum(int(row["saved_tokens"]) for row in rows)
    return {
        "turn_count": len(records),
        "attempted_items": attempted,
        "item_count": len(rows),
        "success_count": len(rows),
        "failure_count": len(failures),
        "warning_count": sum(int(row.get("warning_count", 0)) for row in rows),
        "original_tokens": original_tokens,
        "semantic_tokens": semantic_tokens,
        "saved_tokens": saved_tokens,
        "saved_pct": _pct(saved_tokens, original_tokens),
        "win_items": sum(1 for row in rows if int(row["saved_tokens"]) > 0),
        "loss_items": sum(1 for row in rows if int(row["saved_tokens"]) < 0),
        "tie_items": sum(1 for row in rows if int(row["saved_tokens"]) == 0),
        "prompt_items": sum(1 for row in rows if row.get("side") == "prompt"),
        "reply_items": sum(1 for row in rows if row.get("side") == "reply"),
        "elapsed_seconds": round(elapsed_seconds, 4),
    }


def _rank_sidecar_examples(rows: list[dict[str, Any]], *, reverse: bool, limit: int) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: (int(row.get("saved_tokens", 0)), str(row.get("id"))), reverse=reverse)
    return ranked[:limit]


def _append_sidecar_example_table(lines: list[str], title: str, rows: list[dict[str, Any]]) -> None:
    lines.extend([f"## {title}", ""])
    if not rows:
        lines.extend(["No rows.", ""])
        return
    lines.extend(["| ID | Side | Saved | Original | Semantic | Preview |", "|---|---|---:|---:|---:|---|"])
    for row in rows:
        lines.append(
            "| "
            f"{_markdown_cell(str(row.get('id')))} | "
            f"{row.get('side')} | "
            f"{row.get('saved_tokens')} ({row.get('saved_pct')}%) | "
            f"{row.get('original_tokens')} | "
            f"{row.get('semantic_tokens')} | "
            f"{_markdown_cell(str(row.get('original_preview', '')))} |"
        )
    lines.append("")


def _append_sidecar_failure_table(lines: list[str], failures: list[dict[str, Any]]) -> None:
    lines.extend(["## Failures", ""])
    if not failures:
        lines.extend(["No failures.", ""])
        return
    lines.extend(["| ID | Side | Error | Preview |", "|---|---|---|---|"])
    for row in failures[:10]:
        lines.append(
            "| "
            f"{_markdown_cell(str(row.get('id')))} | "
            f"{row.get('side')} | "
            f"{_markdown_cell(str(row.get('error', '')))} | "
            f"{_markdown_cell(str(row.get('original_preview', '')))} |"
        )
    lines.append("")


def _markdown_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _preview(text: Any, limit: int = 140) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _coerce_semantic_text(
    value: Any,
    field: str,
    *,
    warnings: list[str],
    required: bool = False,
    default: str = "",
) -> str:
    if value is None:
        if required:
            warnings.append(f"semantic.{field} is missing")
        return default

    if isinstance(value, str):
        text = value.strip()
        if required and not text:
            warnings.append(f"semantic.{field} is empty")
        return text

    warnings.append(f"semantic.{field} should be a string")
    return str(value).strip()


def _coerce_semantic_list(value: Any, field: str, warnings: list[str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        out = [str(item).strip() for item in value if str(item).strip()]
        if not out:
            return []
        return out
    warnings.append(f"semantic.{field} should be a list")
    text = str(value).strip()
    return [text] if text else []


def _decode_prompt_semantic(semantic: dict[str, Any], *, warnings: list[str]) -> str:
    op = _coerce_semantic_text(
        semantic.get("op"),
        "op",
        required=True,
        warnings=warnings,
        default="handle",
    )
    query = _coerce_semantic_text(
        semantic.get("query"),
        "query",
        required=True,
        warnings=warnings,
        default="a request",
    )
    paths = _coerce_semantic_list(semantic.get("paths"), "paths", warnings)
    constraints = _coerce_semantic_list(semantic.get("constraints"), "constraints", warnings)
    verify = _coerce_semantic_list(semantic.get("verify"), "verify", warnings)
    returns = _coerce_semantic_list(semantic.get("returns"), "returns", warnings)

    pieces = [f"{op.capitalize()} {query}."]
    if paths:
        pieces.append("Paths: " + ", ".join(paths) + ".")
    if constraints:
        pieces.append("Constraints: " + ", ".join(constraints) + ".")
    if verify:
        pieces.append("Verify: " + ", ".join(verify) + ".")
    if returns:
        pieces.append("Return: " + ", ".join(returns) + ".")
    return " ".join(piece for piece in pieces if piece.strip())


def _decode_reply_semantic(semantic: dict[str, Any], *, warnings: list[str]) -> str:
    status = _coerce_semantic_text(
        semantic.get("status"),
        "status",
        required=True,
        warnings=warnings,
        default="done",
    )
    summary = _coerce_semantic_text(
        semantic.get("summary"),
        "summary",
        required=True,
        warnings=warnings,
        default="completed",
    )
    files = _coerce_semantic_list(semantic.get("files"), "files", warnings)
    verification = _coerce_semantic_list(semantic.get("verification"), "verification", warnings)
    commands = _coerce_semantic_list(semantic.get("commands"), "commands", warnings)
    risks = _coerce_semantic_list(semantic.get("risks"), "risks", warnings)
    next_steps = _coerce_semantic_list(semantic.get("next_steps"), "next_steps", warnings)

    status_label = {
        "done": "Done",
        "partial": "Partially done",
        "blocked": "Blocked",
        "failed": "Failed",
    }.get(status.lower(), status.title() if status else "Done")
    pieces = [f"{status_label}: {summary}."]
    if files:
        pieces.append("Files: " + ", ".join(files) + ".")
    if verification:
        pieces.append("Verification: " + ", ".join(verification) + ".")
    if commands:
        pieces.append("Commands: " + ", ".join(commands) + ".")
    if risks:
        pieces.append("Risks: " + ", ".join(risks) + ".")
    if next_steps:
        pieces.append("Next: " + ", ".join(next_steps) + ".")
    return " ".join(piece for piece in pieces if piece.strip())


def _pct(part: int | float, whole: int | float) -> float:
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100.0, 4)
