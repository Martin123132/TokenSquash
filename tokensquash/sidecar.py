from __future__ import annotations

import json
import re
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
SCHEMA_PLACEHOLDER_VALUES = {
    "<=5 words",
    "<=6 words",
    "constraint",
    "constraints",
    "constraint1",
    "constraint2",
    "return",
    "returns",
    "verify",
    "verification",
}


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
    warnings.extend(_semantic_placeholder_warnings(semantic, mode))

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


def review_sidecar_evaluation(
    evaluation_path: Path | str,
    *,
    high_savings_pct: float = 40.0,
    short_ratio: float = 0.45,
) -> dict[str, Any]:
    """Build a human-review checklist for a saved sidecar evaluation."""

    evaluation = _load_sidecar_evaluation(evaluation_path)
    rows = [
        _review_sidecar_row(row, high_savings_pct=high_savings_pct, short_ratio=short_ratio)
        for row in evaluation.get("rows", [])
    ]
    rows.extend(_review_sidecar_failure(failure) for failure in evaluation.get("failures", []))
    rows.sort(
        key=lambda row: (
            int(row.get("risk_score", 0)),
            float(row.get("saved_pct", 0.0)),
            str(row.get("id", "")),
        ),
        reverse=True,
    )
    summary = _sidecar_review_summary(rows, evaluation.get("summary", {}))
    return {
        "schema_version": "tokensquash.sidecar.review.v1",
        "status": "warn" if summary["review_count"] else "pass",
        "source": str(Path(evaluation_path)),
        "evaluation": _sidecar_report_brief(evaluation, evaluation_path),
        "thresholds": {
            "high_savings_pct": high_savings_pct,
            "short_ratio": short_ratio,
        },
        "summary": summary,
        "rows": rows,
    }


def suggest_sidecar_review(
    review_path: Path | str,
    *,
    min_count: int = 1,
    max_examples: int = 5,
) -> dict[str, Any]:
    """Turn a sidecar review report into prioritized tuning suggestions."""

    review = _load_sidecar_review(review_path)
    return _suggest_sidecar_review_payload(
        review,
        source=str(Path(review_path)),
        min_count=min_count,
        max_examples=max_examples,
    )


def _suggest_sidecar_review_payload(
    review: dict[str, Any],
    *,
    source: str,
    min_count: int,
    max_examples: int,
) -> dict[str, Any]:
    rows = review.get("rows", [])
    flag_groups = _sidecar_review_flag_groups(rows, max_examples=max_examples)
    suggestions = [
        _sidecar_suggestion_for_flag(flag, group, review)
        for flag, group in flag_groups.items()
        if int(group.get("count", 0)) >= min_count
    ]
    suggestions.sort(
        key=lambda suggestion: (
            int(suggestion.get("priority_score", 0)),
            int(suggestion.get("count", 0)),
            str(suggestion.get("flag", "")),
        ),
        reverse=True,
    )
    return {
        "schema_version": "tokensquash.sidecar.suggestions.v1",
        "status": "pass" if suggestions else "empty",
        "source": source,
        "review": {
            "status": review.get("status"),
            "source": review.get("source"),
            "summary": review.get("summary", {}),
        },
        "parameters": {
            "min_count": min_count,
            "max_examples": max_examples,
        },
        "summary": _sidecar_suggestions_summary(review, suggestions),
        "flag_counts": {
            flag: int(group.get("count", 0))
            for flag, group in sorted(flag_groups.items())
        },
        "suggestions": suggestions,
    }


def gate_sidecar_report(
    report_path: Path | str,
    *,
    min_saved_pct: float = 0.5,
    max_review_count: int = 0,
    max_high_risk: int = 0,
    max_medium_risk: int = 0,
    max_loss_items: int = 0,
    high_savings_pct: float = 40.0,
    short_ratio: float = 0.45,
) -> dict[str, Any]:
    """Apply pass/fail quality thresholds to a sidecar review or evaluation report."""

    review, input_type, input_schema = _load_sidecar_gate_review(
        report_path,
        high_savings_pct=high_savings_pct,
        short_ratio=short_ratio,
    )
    return _gate_sidecar_review_payload(
        review,
        source=str(Path(report_path)),
        input_type=input_type,
        input_schema=input_schema,
        min_saved_pct=min_saved_pct,
        max_review_count=max_review_count,
        max_high_risk=max_high_risk,
        max_medium_risk=max_medium_risk,
        max_loss_items=max_loss_items,
        high_savings_pct=high_savings_pct,
        short_ratio=short_ratio,
    )


def _gate_sidecar_review_payload(
    review: dict[str, Any],
    *,
    source: str,
    input_type: str,
    input_schema: str,
    min_saved_pct: float,
    max_review_count: int,
    max_high_risk: int,
    max_medium_risk: int,
    max_loss_items: int,
    high_savings_pct: float,
    short_ratio: float,
) -> dict[str, Any]:
    summary = review.get("summary", {})
    loss_items = _sidecar_gate_loss_items(review.get("rows", []))
    checks = [
        _sidecar_gate_check("min_saved_pct", float(summary.get("saved_pct", 0.0)), min_saved_pct, ">="),
        _sidecar_gate_check("max_review_count", int(summary.get("review_count", 0)), max_review_count, "<="),
        _sidecar_gate_check("max_high_risk", int(summary.get("high_risk_count", 0)), max_high_risk, "<="),
        _sidecar_gate_check("max_medium_risk", int(summary.get("medium_risk_count", 0)), max_medium_risk, "<="),
        _sidecar_gate_check("max_loss_items", loss_items, max_loss_items, "<="),
    ]
    failures = [check for check in checks if check.get("status") == "fail"]
    status = "pass" if not failures else "fail"
    return {
        "schema_version": "tokensquash.sidecar.gate.v1",
        "status": status,
        "source": source,
        "input_type": input_type,
        "input_schema_version": input_schema,
        "review": {
            "status": review.get("status"),
            "source": review.get("source"),
            "evaluation": review.get("evaluation", {}),
            "summary": summary,
        },
        "thresholds": {
            "min_saved_pct": min_saved_pct,
            "max_review_count": max_review_count,
            "max_high_risk": max_high_risk,
            "max_medium_risk": max_medium_risk,
            "max_loss_items": max_loss_items,
            "high_savings_pct": high_savings_pct,
            "short_ratio": short_ratio,
        },
        "summary": {
            "status": status,
            "passed": status == "pass",
            "check_count": len(checks),
            "failed_check_count": len(failures),
            "review_count": int(summary.get("review_count", 0)),
            "high_risk_count": int(summary.get("high_risk_count", 0)),
            "medium_risk_count": int(summary.get("medium_risk_count", 0)),
            "loss_items": loss_items,
            "saved_tokens": int(summary.get("saved_tokens", 0)),
            "saved_pct": float(summary.get("saved_pct", 0.0)),
        },
        "checks": checks,
        "failures": failures,
    }


def certify_sidecar_report(
    report_path: Path | str,
    *,
    min_saved_pct: float = 0.5,
    max_review_count: int = 0,
    max_high_risk: int = 0,
    max_medium_risk: int = 0,
    max_loss_items: int = 0,
    high_savings_pct: float = 40.0,
    short_ratio: float = 0.45,
    min_count: int = 1,
    max_examples: int = 5,
) -> dict[str, Any]:
    """Build a review, gate, and suggestions pack for a saved sidecar report."""

    source = str(Path(report_path))
    review, input_type, input_schema = _load_sidecar_gate_review(
        report_path,
        high_savings_pct=high_savings_pct,
        short_ratio=short_ratio,
    )
    gate = _gate_sidecar_review_payload(
        review,
        source=source,
        input_type=input_type,
        input_schema=input_schema,
        min_saved_pct=min_saved_pct,
        max_review_count=max_review_count,
        max_high_risk=max_high_risk,
        max_medium_risk=max_medium_risk,
        max_loss_items=max_loss_items,
        high_savings_pct=high_savings_pct,
        short_ratio=short_ratio,
    )
    suggestions = _suggest_sidecar_review_payload(
        review,
        source=source,
        min_count=min_count,
        max_examples=max_examples,
    )
    gate_summary = gate.get("summary", {})
    review_summary = review.get("summary", {})
    suggestion_summary = suggestions.get("summary", {})
    status = "pass" if gate.get("status") == "pass" else "fail"
    return {
        "schema_version": "tokensquash.sidecar.certify.v1",
        "status": status,
        "source": source,
        "input_type": input_type,
        "input_schema_version": input_schema,
        "summary": {
            "passed": status == "pass",
            "saved_tokens": int(review_summary.get("saved_tokens", 0)),
            "saved_pct": float(review_summary.get("saved_pct", 0.0)),
            "review_count": int(review_summary.get("review_count", 0)),
            "high_risk_count": int(review_summary.get("high_risk_count", 0)),
            "medium_risk_count": int(review_summary.get("medium_risk_count", 0)),
            "loss_items": int(gate_summary.get("loss_items", 0)),
            "failed_check_count": int(gate_summary.get("failed_check_count", 0)),
            "suggestion_count": int(suggestion_summary.get("suggestion_count", 0)),
        },
        "artifacts": {
            "review": review,
            "gate": gate,
            "suggestions": suggestions,
        },
    }


def build_semantic_prompt(text: str, *, mode: str) -> str:
    _validate_mode(mode)
    if mode == "prompt":
        key_rules = (
            "Required prompt keys: o, q. Optional array keys: p paths, c constraints, "
            "v verification, r return wants."
        )
        value_rules = (
            "o must be one of: fix, add, review, explain, test, docs, refactor, other. "
            "q must be the actual task gist in 1-5 words. "
            "For prompt q, preserve the main object and action. "
            "If the request contains a safety or quality guardrail, put the original condition in c. "
            "If the request has scope dimensions, comparisons, or output artifacts, preserve them in c or r."
        )
    else:
        key_rules = (
            "Required reply keys: s, m. Optional array keys: f files, v verification, "
            "c commands, r risks, n next steps."
        )
        value_rules = (
            "s must be one of: d done, p partial, b blocked, f failed. "
            "m must be the actual result gist in 1-6 words."
        )
    return "\n".join(
        [
            "You are a TokenSquash local semantic translator.",
            "Return ONLY valid compact JSON. Do not use markdown. Do not explain.",
            "Use ONLY the short keys shown below. Do not use long key names.",
            "The mode is already known; do not include a kind key.",
            "Preserve meaning, but do not copy whole sentences.",
            "Values must come from the English text only, never from these instructions.",
            "Keep q/m very short. Move paths, commands, tests, risks, and returns into their fields.",
            "Only include exact file paths; never use placeholders like files, code, test, or path.",
            "Never output schema placeholders as values: <=5 words, <=6 words, constraints, constraint1, constraint2, verify, verification, returns.",
            "Omit empty optional arrays instead of writing []. Do not invent facts.",
            key_rules,
            value_rules,
            "Return a single JSON object using only those keys.",
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


def format_sidecar_review_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    thresholds = report.get("thresholds", {})
    outputs = report.get("outputs", {})
    lines = [
        "# TokenSquash Sidecar Review",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source')}`",
        f"- Rows: `{summary.get('row_count', 0)}`",
        f"- Needs review: `{summary.get('review_count', 0)}`",
        f"- High risk: `{summary.get('high_risk_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- High-savings threshold: `{thresholds.get('high_savings_pct', 0.0)}%`",
        f"- Short-decoded ratio: `{thresholds.get('short_ratio', 0.0)}`",
        "",
        "## Risk Table",
        "",
    ]
    rows = report.get("rows", [])
    if not rows:
        lines.extend(["No rows.", ""])
    else:
        lines.extend(
            [
                "| ID | Side | Verdict | Risk | Saved | Flags |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for row in rows:
            flags = ", ".join(str(flag) for flag in row.get("flags", [])) or "none"
            lines.append(
                "| "
                f"{_markdown_cell(str(row.get('id', '')))} | "
                f"{row.get('side')} | "
                f"`{row.get('verdict')}` | "
                f"{row.get('risk_score')} | "
                f"{row.get('saved_tokens', 0)} ({row.get('saved_pct', 0.0)}%) | "
                f"{_markdown_cell(flags)} |"
            )
        lines.append("")

    if rows:
        lines.extend(["## Row Details", ""])
        for row in rows:
            semantic = json.dumps(row.get("semantic", {}), ensure_ascii=True, indent=2)
            lines.extend(
                [
                    f"### {row.get('id')} / {row.get('side')}",
                    "",
                    f"- Verdict: `{row.get('verdict')}`",
                    f"- Risk score: `{row.get('risk_score')}`",
                    f"- Risk level: `{row.get('risk_level')}`",
                    f"- Saved: `{row.get('saved_tokens', 0)}` (`{row.get('saved_pct', 0.0)}%`)",
                    f"- Flags: `{', '.join(str(flag) for flag in row.get('flags', [])) or 'none'}`",
                    "",
                    "Original preview:",
                    "",
                    "```text",
                    str(row.get("original_preview", "")),
                    "```",
                    "",
                    "Decoded preview:",
                    "",
                    "```text",
                    str(row.get("decoded_preview", "")),
                    "```",
                    "",
                    "Semantic:",
                    "",
                    "```json",
                    semantic,
                    "```",
                    "",
                ]
            )

    if outputs:
        lines.extend(["## Outputs", ""])
        for key, path in sorted(outputs.items()):
            lines.append(f"- {key}: `{path}`")
    return "\n".join(lines).rstrip() + "\n"


def format_sidecar_gate_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    thresholds = report.get("thresholds", {})
    lines = [
        "# TokenSquash Sidecar Gate",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source')}`",
        f"- Input type: `{report.get('input_type')}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Review rows: `{summary.get('review_count', 0)}`",
        f"- High risk: `{summary.get('high_risk_count', 0)}`",
        f"- Medium risk: `{summary.get('medium_risk_count', 0)}`",
        f"- Loss items: `{summary.get('loss_items', 0)}`",
        f"- Failed checks: `{summary.get('failed_check_count', 0)}`",
        "",
        "## Thresholds",
        "",
        f"- Min saved percent: `{thresholds.get('min_saved_pct', 0.0)}%`",
        f"- Max review rows: `{thresholds.get('max_review_count', 0)}`",
        f"- Max high risk: `{thresholds.get('max_high_risk', 0)}`",
        f"- Max medium risk: `{thresholds.get('max_medium_risk', 0)}`",
        f"- Max loss items: `{thresholds.get('max_loss_items', 0)}`",
        "",
        "## Checks",
        "",
        "| Check | Actual | Limit | Result |",
        "|---|---:|---:|---|",
    ]
    for check in report.get("checks", []):
        lines.append(
            "| "
            f"{_markdown_cell(str(check.get('name', '')))} | "
            f"{check.get('actual')} | "
            f"{check.get('operator')} {check.get('limit')} | "
            f"`{check.get('status')}` |"
        )
    failures = report.get("failures", [])
    if failures:
        lines.extend(["", "## Failed Checks", ""])
        for failure in failures:
            lines.append(
                "- "
                f"{failure.get('name')}: actual `{failure.get('actual')}` "
                f"must be {failure.get('operator')} `{failure.get('limit')}`"
            )
    return "\n".join(lines).rstrip() + "\n"


def format_sidecar_certification_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    artifacts = report.get("artifacts", {})
    review = artifacts.get("review", {})
    gate = artifacts.get("gate", {})
    suggestions = artifacts.get("suggestions", {})
    outputs = report.get("outputs", {})
    lines = [
        "# TokenSquash Sidecar Certification",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source')}`",
        f"- Input type: `{report.get('input_type')}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Review rows: `{summary.get('review_count', 0)}`",
        f"- High risk: `{summary.get('high_risk_count', 0)}`",
        f"- Medium risk: `{summary.get('medium_risk_count', 0)}`",
        f"- Loss items: `{summary.get('loss_items', 0)}`",
        f"- Failed checks: `{summary.get('failed_check_count', 0)}`",
        f"- Suggestions: `{summary.get('suggestion_count', 0)}`",
        "",
        "## Gate",
        "",
        f"- Status: `{gate.get('status')}`",
        f"- Failed checks: `{(gate.get('summary') or {}).get('failed_check_count', 0)}`",
        "",
        "| Check | Actual | Limit | Result |",
        "|---|---:|---:|---|",
    ]
    for check in gate.get("checks", []):
        lines.append(
            "| "
            f"{_markdown_cell(str(check.get('name', '')))} | "
            f"{check.get('actual')} | "
            f"{check.get('operator')} {check.get('limit')} | "
            f"`{check.get('status')}` |"
        )
    lines.extend(
        [
            "",
            "## Review",
            "",
            f"- Status: `{review.get('status')}`",
            f"- Rows: `{(review.get('summary') or {}).get('row_count', 0)}`",
            f"- Needs review: `{(review.get('summary') or {}).get('review_count', 0)}`",
            "",
            "## Suggestions",
            "",
            f"- Status: `{suggestions.get('status')}`",
            f"- Count: `{(suggestions.get('summary') or {}).get('suggestion_count', 0)}`",
        ]
    )
    if outputs:
        lines.extend(["", "## Outputs", ""])
        for key, path in sorted(outputs.items()):
            lines.append(f"- {key}: `{path}`")
    return "\n".join(lines).rstrip() + "\n"


def format_sidecar_suggestions_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs", {})
    lines = [
        "# TokenSquash Sidecar Suggestions",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source')}`",
        f"- Suggestions: `{summary.get('suggestion_count', 0)}`",
        f"- Review rows: `{summary.get('review_count', 0)}`",
        f"- High priority: `{summary.get('high_priority_count', 0)}`",
        f"- Medium priority: `{summary.get('medium_priority_count', 0)}`",
        f"- Saved tokens at review risk: `{summary.get('review_saved_tokens', 0)}`",
        "",
    ]
    suggestions = report.get("suggestions", [])
    if not suggestions:
        lines.extend(["No suggestions met the threshold.", ""])
    else:
        lines.extend(
            [
                "## Priority Table",
                "",
                "| Priority | Flag | Count | Score | Suggestion |",
                "|---|---|---:|---:|---|",
            ]
        )
        for suggestion in suggestions:
            lines.append(
                "| "
                f"`{suggestion.get('priority')}` | "
                f"`{suggestion.get('flag')}` | "
                f"{suggestion.get('count', 0)} | "
                f"{suggestion.get('priority_score', 0)} | "
                f"{_markdown_cell(str(suggestion.get('title', '')))} |"
            )
        lines.append("")

        lines.extend(["## Suggestions", ""])
        for suggestion in suggestions:
            examples = suggestion.get("examples", [])
            lines.extend(
                [
                    f"### {suggestion.get('title')}",
                    "",
                    f"- Flag: `{suggestion.get('flag')}`",
                    f"- Priority: `{suggestion.get('priority')}`",
                    f"- Count: `{suggestion.get('count', 0)}`",
                    f"- Affected saved tokens: `{suggestion.get('affected_saved_tokens', 0)}`",
                    f"- Recommendation: {suggestion.get('recommendation')}",
                    f"- Rationale: {suggestion.get('rationale')}",
                    f"- Suggested check: `{suggestion.get('suggested_check')}`",
                    "",
                ]
            )
            if examples:
                lines.extend(["Examples:", ""])
                for example in examples:
                    lines.append(
                        "- "
                        f"`{example.get('id')}` / `{example.get('side')}` "
                        f"saved `{example.get('saved_tokens', 0)}` (`{example.get('saved_pct', 0.0)}%`): "
                        f"{_markdown_cell(str(example.get('decoded_preview', '')))}"
                    )
                lines.append("")

    flag_counts = report.get("flag_counts", {})
    if flag_counts:
        lines.extend(["## Flag Counts", ""])
        for flag, count in sorted(flag_counts.items()):
            lines.append(f"- `{flag}`: `{count}`")
        lines.append("")

    if outputs:
        lines.extend(["## Outputs", ""])
        for key, path in sorted(outputs.items()):
            lines.append(f"- {key}: `{path}`")
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


def format_sidecar_sweep_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs", {})
    lines = [
        "# TokenSquash Sidecar Sweep",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Name: `{report.get('name')}`",
        f"- Run ID: `{report.get('run_id')}`",
        f"- Output: `{report.get('output_dir')}`",
        f"- Runs: `{summary.get('run_count', 0)}`",
        f"- Comparisons: `{summary.get('comparison_count', 0)}`",
        f"- Skipped comparisons: `{summary.get('skipped_comparison_count', 0)}`",
        "",
        "## Runs",
        "",
        "| Run | Source | Model | Counter | Status | Items | Saved | Saved % | Warnings | Failures |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for run in report.get("runs", []):
        run_summary = run.get("summary", {})
        lines.append(
            "| "
            f"`{run.get('run_id')}` | "
            f"`{run.get('source')}` | "
            f"`{run.get('model')}` | "
            f"`{run.get('counter')}` | "
            f"`{run.get('status')}` | "
            f"{run_summary.get('item_count', 0)} | "
            f"{run_summary.get('saved_tokens', 0)} | "
            f"{run_summary.get('saved_pct', 0.0)} | "
            f"{run_summary.get('warning_count', 0)} | "
            f"{run_summary.get('failure_count', 0)} |"
        )

    best_run = summary.get("best_run")
    if best_run:
        lines.extend(
            [
                "",
                "## Best Run",
                "",
                f"- Run: `{best_run.get('run_id')}`",
                f"- Saved tokens: `{best_run.get('summary', {}).get('saved_tokens', 0)}`",
                f"- Saved percent: `{best_run.get('summary', {}).get('saved_pct', 0.0)}%`",
            ]
        )

    comparisons = report.get("comparisons", [])
    if comparisons:
        lines.extend(
            [
                "",
                "## Comparisons",
                "",
                "| Target | Status | Saved Delta | Warning Delta | Failure Delta |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for comparison in comparisons:
            delta = comparison.get("delta", {})
            target = comparison.get("target", {})
            lines.append(
                "| "
                f"`{target.get('run_id')}` | "
                f"`{comparison.get('status')}` | "
                f"{delta.get('saved_tokens', 0)} | "
                f"{delta.get('warning_count', 0)} | "
                f"{delta.get('failure_count', 0)} |"
            )

    if outputs:
        lines.extend(["", "## Outputs", ""])
        for key, path in sorted(outputs.items()):
            lines.append(f"- {key}: `{path}`")
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


def _load_sidecar_review(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("sidecar review report must be a JSON object")
    if payload.get("schema_version") != "tokensquash.sidecar.review.v1":
        raise ValueError(f"not a sidecar review report: {source}")
    return payload


def _load_sidecar_gate_review(
    path: Path | str,
    *,
    high_savings_pct: float,
    short_ratio: float,
) -> tuple[dict[str, Any], str, str]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("sidecar gate input must be a JSON object")
    schema = str(payload.get("schema_version", ""))
    if schema == "tokensquash.sidecar.review.v1":
        return payload, "review", schema
    if schema == "tokensquash.sidecar.evaluate.v1":
        review = review_sidecar_evaluation(
            source,
            high_savings_pct=high_savings_pct,
            short_ratio=short_ratio,
        )
        return review, "evaluation", schema
    raise ValueError(f"not a sidecar review or evaluation report: {source}")


def _sidecar_gate_check(name: str, actual: float | int, limit: float | int, operator: str) -> dict[str, Any]:
    if operator == ">=":
        passed = actual >= limit
    elif operator == "<=":
        passed = actual <= limit
    else:
        raise ValueError(f"unsupported sidecar gate operator: {operator}")
    return {
        "name": name,
        "actual": actual,
        "operator": operator,
        "limit": limit,
        "status": "pass" if passed else "fail",
    }


def _sidecar_gate_loss_items(rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if row.get("status") == "loss" or int(row.get("saved_tokens", 0)) < 0
    )


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


def _review_sidecar_row(row: dict[str, Any], *, high_savings_pct: float, short_ratio: float) -> dict[str, Any]:
    flags: list[str] = []
    reasons: list[str] = []
    side = str(row.get("side", ""))
    semantic = row.get("semantic", {}) if isinstance(row.get("semantic", {}), dict) else {}
    original_preview = str(row.get("original_preview", ""))
    decoded_preview = str(row.get("decoded_preview", ""))
    saved_pct = float(row.get("saved_pct", 0.0))
    warning_count = int(row.get("warning_count", 0))

    if warning_count or row.get("warnings"):
        flags.append("warnings")
        reasons.extend(str(warning) for warning in row.get("warnings", []))
    if str(row.get("status")) == "loss" or int(row.get("saved_tokens", 0)) < 0:
        flags.append("token_loss")
        reasons.append("semantic payload is longer than the original text")
    if _sidecar_review_short_decoded(row, high_savings_pct=high_savings_pct, short_ratio=short_ratio):
        flags.append("high_savings_short_decoded")
        reasons.append("high savings with a much shorter decoded preview needs meaning review")
    if side == "prompt" and not str(semantic.get("query", "")).strip():
        flags.append("missing_prompt_query")
        reasons.append("prompt semantic query is empty")
    if side == "reply" and _sidecar_review_generic_summary(semantic.get("summary")):
        flags.append("generic_summary")
        reasons.append("reply summary is too generic to prove meaning survived")
    if side == "reply" and _mentions_path(original_preview) and not semantic.get("files"):
        flags.append("missing_files")
        reasons.append("original preview mentions file-like text but semantic files are empty")
    if side == "reply" and _mentions_command(original_preview) and not (semantic.get("commands") or semantic.get("verification")):
        flags.append("missing_command_or_verification")
        reasons.append("original preview mentions command/test text but semantic command and verification fields are empty")
    if side == "reply" and _mentions_risk(original_preview) and not semantic.get("risks"):
        flags.append("missing_risks")
        reasons.append("original preview mentions risk text but semantic risks are empty")

    risk_score = _sidecar_review_risk_score(flags, warning_count=warning_count, saved_pct=saved_pct)
    return {
        "index": row.get("index"),
        "id": row.get("id"),
        "side": side,
        "verdict": "review" if flags else "ok",
        "risk_level": _sidecar_review_risk_level(risk_score),
        "risk_score": risk_score,
        "flags": flags,
        "reasons": reasons,
        "status": row.get("status"),
        "original_tokens": int(row.get("original_tokens", 0)),
        "semantic_tokens": int(row.get("semantic_tokens", 0)),
        "saved_tokens": int(row.get("saved_tokens", 0)),
        "saved_pct": saved_pct,
        "warning_count": warning_count,
        "warnings": row.get("warnings", []),
        "original_preview": original_preview,
        "decoded_preview": decoded_preview,
        "semantic": semantic,
    }


def _review_sidecar_failure(failure: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": failure.get("index"),
        "id": failure.get("id"),
        "side": failure.get("side"),
        "verdict": "review",
        "risk_level": "high",
        "risk_score": 100,
        "flags": ["failure"],
        "reasons": [str(failure.get("error", "sidecar evaluation failed"))],
        "status": "fail",
        "original_tokens": 0,
        "semantic_tokens": 0,
        "saved_tokens": 0,
        "saved_pct": 0.0,
        "warning_count": 0,
        "warnings": [],
        "original_preview": str(failure.get("original_preview", "")),
        "decoded_preview": "",
        "semantic": {},
    }


def _sidecar_review_summary(rows: list[dict[str, Any]], evaluation_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_count": len(rows),
        "ok_count": sum(1 for row in rows if row.get("verdict") == "ok"),
        "review_count": sum(1 for row in rows if row.get("verdict") == "review"),
        "high_risk_count": sum(1 for row in rows if row.get("risk_level") == "high"),
        "medium_risk_count": sum(1 for row in rows if row.get("risk_level") == "medium"),
        "low_risk_count": sum(1 for row in rows if row.get("risk_level") == "low"),
        "warning_count": sum(int(row.get("warning_count", 0)) for row in rows),
        "original_tokens": int(evaluation_summary.get("original_tokens", 0)),
        "semantic_tokens": int(evaluation_summary.get("semantic_tokens", 0)),
        "saved_tokens": int(evaluation_summary.get("saved_tokens", 0)),
        "saved_pct": float(evaluation_summary.get("saved_pct", 0.0)),
    }


def _sidecar_review_flag_groups(rows: list[dict[str, Any]], *, max_examples: int) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        for flag in row.get("flags", []):
            group = groups.setdefault(
                str(flag),
                {
                    "count": 0,
                    "affected_saved_tokens": 0,
                    "max_risk_score": 0,
                    "examples": [],
                },
            )
            group["count"] = int(group["count"]) + 1
            group["affected_saved_tokens"] = int(group["affected_saved_tokens"]) + int(row.get("saved_tokens", 0))
            group["max_risk_score"] = max(int(group["max_risk_score"]), int(row.get("risk_score", 0)))
            if len(group["examples"]) < max_examples:
                group["examples"].append(_sidecar_suggestion_example(row))
    return groups


def _sidecar_suggestion_for_flag(flag: str, group: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    guidance = _sidecar_suggestion_guidance(flag)
    count = int(group.get("count", 0))
    affected_saved_tokens = int(group.get("affected_saved_tokens", 0))
    max_risk_score = int(group.get("max_risk_score", 0))
    priority_score = max_risk_score + count * 10 + min(max(affected_saved_tokens, 0), 50)
    priority = _sidecar_suggestion_priority(priority_score)
    return {
        "flag": flag,
        "priority": priority,
        "priority_score": priority_score,
        "count": count,
        "affected_saved_tokens": affected_saved_tokens,
        "title": guidance["title"],
        "recommendation": guidance["recommendation"],
        "rationale": guidance["rationale"],
        "suggested_check": guidance["suggested_check"],
        "review_source": review.get("source"),
        "examples": group.get("examples", []),
    }


def _sidecar_suggestions_summary(review: dict[str, Any], suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    review_summary = review.get("summary", {})
    return {
        "suggestion_count": len(suggestions),
        "review_count": int(review_summary.get("review_count", 0)),
        "high_priority_count": sum(1 for suggestion in suggestions if suggestion.get("priority") == "high"),
        "medium_priority_count": sum(1 for suggestion in suggestions if suggestion.get("priority") == "medium"),
        "low_priority_count": sum(1 for suggestion in suggestions if suggestion.get("priority") == "low"),
        "review_saved_tokens": sum(
            max(int(row.get("saved_tokens", 0)), 0)
            for row in review.get("rows", [])
            if row.get("verdict") == "review"
        ),
        "review_status": review.get("status"),
        "review_row_count": int(review_summary.get("row_count", 0)),
        "saved_tokens": int(review_summary.get("saved_tokens", 0)),
        "saved_pct": float(review_summary.get("saved_pct", 0.0)),
    }


def _sidecar_suggestion_example(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "side": row.get("side"),
        "risk_level": row.get("risk_level"),
        "risk_score": row.get("risk_score"),
        "saved_tokens": row.get("saved_tokens", 0),
        "saved_pct": row.get("saved_pct", 0.0),
        "original_preview": row.get("original_preview", ""),
        "decoded_preview": row.get("decoded_preview", ""),
    }


def _sidecar_suggestion_priority(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _sidecar_suggestion_guidance(flag: str) -> dict[str, str]:
    guidance = {
        "failure": {
            "title": "Fix sidecar evaluation failures first",
            "recommendation": "Inspect failed rows before tuning token savings; failures can hide model, endpoint, or parsing problems.",
            "rationale": "A failed row has no reliable semantic payload to compare.",
            "suggested_check": "sidecar evaluate with a small --limit and inspect failures",
        },
        "warnings": {
            "title": "Remove warning-producing semantic fields",
            "recommendation": "Prioritize prompt or normalization fixes for rows that already emit decoder warnings.",
            "rationale": "Warnings are explicit quality signals and should not be averaged away by token savings.",
            "suggested_check": "sidecar review then inspect warnings in review.json",
        },
        "high_savings_short_decoded": {
            "title": "Preserve more meaning on high-savings rows",
            "recommendation": "Tighten the prompt so very short decoded text still preserves the object, action, constraints, verification, and expected return.",
            "rationale": "Large savings paired with a much shorter decoded preview may mean the model dropped task details.",
            "suggested_check": "rerun sidecar sweep and review high_savings_short_decoded count",
        },
        "missing_command_or_verification": {
            "title": "Extract commands and verification explicitly",
            "recommendation": "Strengthen reply translation so test and command mentions are placed in c or v instead of only summary text.",
            "rationale": "Commands and verification are important evidence in assistant replies and are easy to lose during compression.",
            "suggested_check": "review rows with python/pytest/npm/test mentions and confirm c or v is populated",
        },
        "missing_files": {
            "title": "Preserve file references when present",
            "recommendation": "Tune prompt wording or source anchoring so exact file paths in replies land in f.",
            "rationale": "File references are high-value context for code work and should survive round trips.",
            "suggested_check": "review rows with path-like previews and confirm semantic f contains exact paths",
        },
        "missing_risks": {
            "title": "Preserve risk and caveat fields",
            "recommendation": "Strengthen reply translation so risk/caveat mentions are placed in r.",
            "rationale": "Risks are compact but important; dropping them can make a reply sound safer than it was.",
            "suggested_check": "review rows with risk/caveat text and confirm semantic r is populated",
        },
        "generic_summary": {
            "title": "Reject generic reply summaries",
            "recommendation": "Require m to include the concrete object and action, not just Done, fixed, updated, or reviewed.",
            "rationale": "Generic summaries can create strong savings while preserving very little meaning.",
            "suggested_check": "rerun review and confirm generic_summary count is zero",
        },
        "token_loss": {
            "title": "Shorten verbose semantic payloads",
            "recommendation": "Inspect loss rows for overlong q/m values or arrays that duplicate the original wording.",
            "rationale": "A semantic sidecar should pass through or improve rows that are longer than source text.",
            "suggested_check": "sort review rows by token_loss and inspect semantic JSON length",
        },
        "missing_prompt_query": {
            "title": "Require prompt task gist",
            "recommendation": "Ensure prompt translations always include q with the concrete task object.",
            "rationale": "A prompt without q cannot be decoded into a useful task request.",
            "suggested_check": "review prompt rows and confirm q is non-empty",
        },
    }
    return guidance.get(
        flag,
        {
            "title": f"Investigate {flag}",
            "recommendation": "Inspect affected rows and decide whether the prompt, normalizer, or review heuristic needs adjustment.",
            "rationale": "Unknown review flags still indicate rows that need human attention.",
            "suggested_check": "open review.md and inspect affected examples",
        },
    )


def _sidecar_review_short_decoded(row: dict[str, Any], *, high_savings_pct: float, short_ratio: float) -> bool:
    saved_pct = float(row.get("saved_pct", 0.0))
    if saved_pct < high_savings_pct:
        return False
    original_preview = str(row.get("original_preview", "")).strip()
    decoded_preview = str(row.get("decoded_preview", "")).strip()
    if not original_preview or not decoded_preview:
        return False
    return len(decoded_preview) / max(len(original_preview), 1) < short_ratio


def _sidecar_review_generic_summary(value: Any) -> bool:
    text = str(value or "").strip().lower().strip(".")
    return text in {"", "done", "fixed", "updated", "changed", "checked", "reviewed", "added"}


def _sidecar_review_risk_score(flags: list[str], *, warning_count: int, saved_pct: float) -> int:
    weights = {
        "failure": 100,
        "warnings": 35 + min(warning_count * 5, 25),
        "high_savings_short_decoded": 30,
        "token_loss": 20,
        "generic_summary": 20,
        "missing_files": 15,
        "missing_command_or_verification": 15,
        "missing_risks": 15,
        "missing_prompt_query": 15,
    }
    score = sum(weights.get(flag, 10) for flag in flags)
    if flags and saved_pct >= 60:
        score += 10
    return min(score, 100)


def _sidecar_review_risk_level(score: int) -> str:
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    if score > 0:
        return "low"
    return "ok"


def _mentions_path(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("/", "\\", ".py", ".js", ".ts", ".tsx", ".json", ".md"))


def _mentions_command(text: str) -> bool:
    lowered = f" {text.lower()} "
    return any(
        marker in lowered
        for marker in (
            " python -m",
            " pytest",
            " npm ",
            " pnpm ",
            " yarn ",
            " ran tests",
            " run tests",
            " tests pass",
            " tests passed",
        )
    )


def _mentions_risk(text: str) -> bool:
    lowered = text.lower()
    return "risk" in lowered or "risks" in lowered


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
    constraints = _semantic_list(_semantic_value(payload, "constraints", "c", default=[]))
    verify = _semantic_list(_semantic_value(payload, "verify", "v", default=[]))
    returns = _semantic_list(_semantic_value(payload, "returns", "r", default=[]))
    return {
        "kind": _normalize_kind(_semantic_value(payload, "kind", "k")),
        "op": str(_semantic_value(payload, "op", "o", default="other")).strip() or "other",
        "query": str(_semantic_value(payload, "query", "q", default="")).strip(),
        "paths": _source_anchored_items(paths, source_text),
        "constraints": _source_related_items(constraints, source_text),
        "verify": _source_related_items(verify, source_text),
        "returns": _source_related_items(returns, source_text),
    }


def _normalize_reply_semantic(payload: dict[str, Any], *, source_text: str | None = None) -> dict[str, Any]:
    status = str(_semantic_value(payload, "status", "s", default="done")).strip()
    status = STATUS_FROM_CODES.get(status, status)
    files = _semantic_list(_semantic_value(payload, "files", "f", default=[]))
    verification = _source_related_items(_semantic_list(_semantic_value(payload, "verification", "v", default=[])), source_text)
    commands = _source_related_items(_semantic_list(_semantic_value(payload, "commands", "c", default=[])), source_text)
    risks = _source_related_items(_semantic_list(_semantic_value(payload, "risks", "r", default=[])), source_text)
    next_steps = _semantic_list(_semantic_value(payload, "next_steps", "n", default=[]))
    if source_text is not None:
        extracted_commands = _extract_reply_commands(source_text)
        commands = _merge_unique_items(commands, extracted_commands)
        commands = _drop_prefix_redundant_items(commands)
        verification = _merge_unique_items(verification, _extract_reply_verification(source_text, commands=extracted_commands))
    return {
        "kind": _normalize_kind(_semantic_value(payload, "kind", "k")),
        "status": status or "done",
        "summary": _semantic_short_text(_semantic_value(payload, "summary", "m", default=""), max_words=6),
        "files": _source_anchored_items(files, source_text),
        "verification": verification,
        "commands": commands,
        "risks": risks,
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


def _semantic_placeholder_warnings(semantic: dict[str, Any], mode: str) -> list[str]:
    fields = (
        ("op",),
        ("query",),
        ("paths",),
        ("constraints",),
        ("verify",),
        ("returns",),
    )
    if mode == "reply":
        fields = (
            ("status",),
            ("summary",),
            ("files",),
            ("verification",),
            ("commands",),
            ("risks",),
            ("next_steps",),
        )

    warnings: list[str] = []
    for field_tuple in fields:
        field = field_tuple[0]
        for item in _semantic_warning_values(semantic.get(field)):
            if _looks_like_schema_placeholder(item, field=field):
                warnings.append(f"semantic.{field} looks like schema placeholder: {item}")
    return warnings


def _semantic_warning_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _looks_like_schema_placeholder(value: str, *, field: str) -> bool:
    text = value.strip().strip("`'\"").lower()
    compact = text.replace(" ", "")
    if field in {"paths", "files"} and text in {"file", "files", "path", "paths"}:
        return True
    if text in SCHEMA_PLACEHOLDER_VALUES or compact in SCHEMA_PLACEHOLDER_VALUES:
        return True
    if compact.startswith("<=") and compact.endswith("words"):
        return True
    if text.startswith(("returns:", "return:")):
        return True
    for stem in ("constraint", "verify", "verification"):
        suffix = text.removeprefix(stem)
        if suffix.isdigit():
            return True
    return False


def _source_anchored_items(items: list[str], source_text: str | None) -> list[str]:
    if source_text is None:
        return [item for item in items if _looks_like_path_item(item)]
    return [item for item in items if _looks_like_path_item(item) and _source_contains_item(source_text, item)]


def _source_related_items(items: list[str], source_text: str | None) -> list[str]:
    if source_text is None:
        return items
    source_tokens = _meaningful_tokens(source_text)
    return [
        item
        for item in items
        if _source_contains_item(source_text, item) or bool(_meaningful_tokens(item) & source_tokens)
    ]


def _extract_reply_commands(source_text: str) -> list[str]:
    commands: list[str] = []
    for match in re.finditer(r"\b((?:python\s+-m|pytest|npm|pnpm|yarn)\b[^;,\n]*)", source_text, re.IGNORECASE):
        command = _clean_extracted_command(match.group(1))
        if command:
            commands.append(command)
    return _merge_unique_items(commands)


def _extract_reply_verification(source_text: str, *, commands: list[str] | None = None) -> list[str]:
    verification: list[str] = []
    for command in commands or _extract_reply_commands(source_text):
        lowered = command.lower()
        if "pytest" in lowered:
            verification.append("pytest")
        elif "test" in lowered:
            verification.append("tests")

    lowered_source = source_text.lower()
    if re.search(r"\btests?\s+pass(?:ed)?\b", lowered_source):
        verification.append("tests pass")
    if re.search(r"\bran\s+tests?\b", lowered_source) or re.search(r"\brun\s+tests?\b", lowered_source):
        verification.append("tests")
    for match in re.finditer(r"\bverified\s+(?:with|via|using)\s+([^\.;,\n]+)", source_text, re.IGNORECASE):
        item = _clean_extracted_command(match.group(1))
        if item:
            verification.append(item)
    return _merge_unique_items(verification)


def _clean_extracted_command(value: str) -> str:
    text = " ".join(value.strip().strip("`'\"").split())
    text = re.split(r"\.\s+(?=[A-Z])", text, maxsplit=1)[0]
    text = text.rstrip(".")
    text = re.sub(r"\s+(?:and\s+)?(?:committed|pushed|updated|documented|wrote|added)$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _semantic_short_text(value: Any, *, max_words: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",;:.")


def _merge_unique_items(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            text = str(item).strip()
            key = _compact_list_item(text).casefold()
            if text and key not in seen:
                seen.add(key)
                merged.append(text)
    return merged


def _drop_prefix_redundant_items(items: list[str]) -> list[str]:
    output: list[str] = []
    lowered = [item.casefold() for item in items]
    for index, item in enumerate(items):
        key = lowered[index]
        if any(other != key and other.startswith(f"{key} ") for other in lowered):
            continue
        output.append(item)
    return output


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


def _looks_like_path_item(item: str) -> bool:
    text = item.strip().strip("`'\"").lower()
    if not text:
        return False
    if "/" in text or "\\" in text:
        return True
    if text in {"makefile", "dockerfile"}:
        return True
    return any(
        text.endswith(suffix)
        for suffix in (
            ".cfg",
            ".css",
            ".html",
            ".ini",
            ".js",
            ".json",
            ".jsx",
            ".md",
            ".py",
            ".toml",
            ".ts",
            ".tsx",
            ".txt",
            ".yaml",
            ".yml",
        )
    )


def _meaningful_tokens(text: str) -> set[str]:
    tokens = set()
    for raw in str(text).lower().replace("\\", "/").replace("-", " ").replace("_", " ").split():
        token = "".join(char for char in raw if char.isalnum())
        if len(token) < 4 or token in {"true", "false", "none", "null", "with", "from", "into", "that", "this", "only"}:
            continue
        tokens.add(_simple_stem(token))
    return tokens


def _simple_stem(token: str) -> str:
    for suffix in ("ingly", "edly", "ing", "ed", "ly", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


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
