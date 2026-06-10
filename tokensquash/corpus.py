from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


TEXT_KEYS = ("text", "prompt")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?\d[\d .()/-]{7,}\d)\b")
TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{16,})\b"
)
AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*([^\s,;]{6,})"
)
WINDOWS_USER_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")
HOME_PATH_RE = re.compile(r"(?<!\w)/(?:Users|home)/[A-Za-z0-9._-]+")


def load_prompt_records(path: Path | str) -> list[dict[str, Any]]:
    """Load prompt records with source line metadata."""

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"prompt corpus not found: {source}")
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".jsonl":
        return _load_jsonl_records(text)
    return _load_text_records(text)


def validate_corpus(path: Path | str) -> dict[str, Any]:
    """Validate a prompt corpus and report parse, shape, and privacy findings."""

    started = time.time()
    source = Path(path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    raw_text = ""

    if not source.exists():
        errors.append({"line": None, "code": "missing_file", "message": f"Corpus not found: {source}"})
    else:
        raw_text = source.read_text(encoding="utf-8")
        if source.suffix.lower() == ".jsonl":
            records, errors, warnings = _validate_jsonl(raw_text)
        else:
            records = _load_text_records(raw_text)
            if not records:
                warnings.append({"line": None, "code": "empty_text_corpus", "message": "No prompts found."})

    privacy = scan_privacy(records)
    status = "fail" if errors else "warn" if warnings or privacy["finding_count"] else "pass"
    stats = corpus_stats_from_records(records)

    return {
        "schema_version": "tokensquash.corpus.validate.v1",
        "status": status,
        "path": str(source),
        "format": "jsonl" if source.suffix.lower() == ".jsonl" else "text",
        "summary": {
            **stats["summary"],
            "raw_bytes": len(raw_text.encode("utf-8")) if raw_text else 0,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "privacy_finding_count": privacy["finding_count"],
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "errors": errors,
        "warnings": warnings,
        "privacy": privacy,
    }


def corpus_stats(path: Path | str) -> dict[str, Any]:
    records = load_prompt_records(path)
    report = corpus_stats_from_records(records)
    report["path"] = str(Path(path))
    return report


def corpus_stats_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    lengths = [len(str(item.get("text", ""))) for item in records]
    words = [len(str(item.get("text", "")).split()) for item in records]
    shortest = min(records, key=lambda item: len(str(item.get("text", ""))), default=None)
    longest = max(records, key=lambda item: len(str(item.get("text", ""))), default=None)
    prompt_count = len(records)
    total_chars = sum(lengths)
    total_words = sum(words)
    return {
        "schema_version": "tokensquash.corpus.stats.v1",
        "summary": {
            "prompt_count": prompt_count,
            "total_chars": total_chars,
            "total_words": total_words,
            "avg_chars": round(total_chars / prompt_count, 2) if prompt_count else 0.0,
            "avg_words": round(total_words / prompt_count, 2) if prompt_count else 0.0,
            "min_chars": min(lengths) if lengths else 0,
            "max_chars": max(lengths) if lengths else 0,
        },
        "shortest": _record_preview(shortest),
        "longest": _record_preview(longest),
    }


def scan_privacy(records: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for item in records:
        text = str(item.get("text", ""))
        line = item.get("line")
        for code, pattern in _privacy_patterns():
            for match in pattern.finditer(text):
                findings.append(
                    {
                        "line": line,
                        "id": item.get("id"),
                        "code": code,
                        "match": _redact_match(match.group(0)),
                    }
                )
    return {
        "schema_version": "tokensquash.corpus.privacy.v1",
        "finding_count": len(findings),
        "findings": findings,
    }


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    """Redact common secrets and direct identifiers from one text value."""

    counts: dict[str, int] = {}
    result = text
    replacements = [
        ("token", TOKEN_RE, "[REDACTED_TOKEN]"),
        ("aws_access_key", AWS_ACCESS_KEY_RE, "[REDACTED_AWS_KEY]"),
        ("secret_assignment", SECRET_ASSIGNMENT_RE, r"\1=[REDACTED_SECRET]"),
        ("email", EMAIL_RE, "[REDACTED_EMAIL]"),
        ("phone", PHONE_RE, "[REDACTED_PHONE]"),
        ("windows_user_path", WINDOWS_USER_PATH_RE, r"C:\\Users\\[REDACTED_USER]"),
        ("home_path", HOME_PATH_RE, "/home/[REDACTED_USER]"),
    ]
    for code, pattern, replacement in replacements:
        result, count = pattern.subn(replacement, result)
        if count:
            counts[code] = count
    return result, counts


def redact_corpus(input_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    """Write a redacted copy of a corpus."""

    source = Path(input_path)
    target = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(f"prompt corpus not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8")
    counts: dict[str, int] = {}

    if source.suffix.lower() == ".jsonl":
        output_lines = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL row {line_no} is invalid JSON: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL row {line_no} must be an object")
            key = _prompt_key(payload)
            if key is None:
                raise ValueError(f"JSONL row {line_no} must include text or prompt")
            payload[key], row_counts = redact_text(str(payload[key]))
            _merge_counts(counts, row_counts)
            output_lines.append(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
        target.write_text("\n".join(output_lines) + ("\n" if output_lines else ""), encoding="utf-8")
        row_count = len(output_lines)
    else:
        redacted, counts = redact_text(text)
        target.write_text(redacted, encoding="utf-8")
        row_count = len(_load_text_records(redacted))

    return {
        "schema_version": "tokensquash.corpus.redact.v1",
        "status": "written",
        "input": str(source),
        "output": str(target),
        "rows": row_count,
        "redactions": counts,
        "redaction_count": sum(counts.values()),
    }


def format_corpus_stats_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Corpus Stats",
        "",
        f"- Path: `{report.get('path', '')}`",
        f"- Prompts: `{summary.get('prompt_count', 0)}`",
        f"- Total chars: `{summary.get('total_chars', 0)}`",
        f"- Total words: `{summary.get('total_words', 0)}`",
        f"- Avg chars: `{summary.get('avg_chars', 0.0)}`",
        f"- Avg words: `{summary.get('avg_words', 0.0)}`",
        f"- Min/max chars: `{summary.get('min_chars', 0)}/{summary.get('max_chars', 0)}`",
    ]
    shortest = report.get("shortest")
    longest = report.get("longest")
    if shortest:
        lines.extend(["", f"Shortest: line `{shortest.get('line')}` `{shortest.get('text')}`"])
    if longest:
        lines.append(f"Longest: line `{longest.get('line')}` `{longest.get('text')}`")
    return "\n".join(lines).rstrip() + "\n"


def format_validation_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Corpus Validation",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Format: `{report.get('format')}`",
        f"- Prompts: `{summary.get('prompt_count', 0)}`",
        f"- Errors: `{summary.get('error_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
    ]
    for title, key in (("Errors", "errors"), ("Warnings", "warnings")):
        items = report.get(key, [])
        if items:
            lines.extend(["", f"## {title}", ""])
            for item in items:
                lines.append(f"- line `{item.get('line')}` `{item.get('code')}`: {item.get('message')}")
    findings = report.get("privacy", {}).get("findings", [])
    if findings:
        lines.extend(["", "## Privacy Findings", ""])
        for item in findings[:50]:
            lines.append(f"- line `{item.get('line')}` `{item.get('code')}`: `{item.get('match')}`")
        if len(findings) > 50:
            lines.append(f"- ... {len(findings) - 50} more")
    return "\n".join(lines).rstrip() + "\n"


def _load_jsonl_records(text: str) -> list[dict[str, Any]]:
    records, errors, _warnings = _validate_jsonl(text)
    if errors:
        first = errors[0]
        raise ValueError(f"JSONL row {first.get('line')} {first.get('message')}")
    return records


def _validate_jsonl(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append({"line": line_no, "code": "invalid_json", "message": exc.msg})
            continue
        if not isinstance(payload, dict):
            errors.append({"line": line_no, "code": "row_not_object", "message": "Row must be a JSON object."})
            continue
        key = _prompt_key(payload)
        if key is None:
            errors.append({"line": line_no, "code": "missing_prompt", "message": "Row must include text or prompt."})
            continue
        prompt = payload.get(key)
        if not isinstance(prompt, str):
            errors.append({"line": line_no, "code": "prompt_not_string", "message": f"`{key}` must be a string."})
            continue
        item_id = payload.get("id")
        if item_id is not None:
            item_id = str(item_id)
            if item_id in seen_ids:
                warnings.append({"line": line_no, "code": "duplicate_id", "message": f"Duplicate id: {item_id}"})
            seen_ids.add(item_id)
        records.append({"id": item_id, "line": line_no, "text": prompt})
    if not records and not errors:
        warnings.append({"line": None, "code": "empty_jsonl_corpus", "message": "No prompts found."})
    return records, errors, warnings


def _load_text_records(text: str) -> list[dict[str, Any]]:
    if "\n\n" in text:
        parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        return [{"id": None, "line": None, "text": part} for part in parts]
    return [
        {"id": None, "line": line_no, "text": line.strip()}
        for line_no, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]


def _prompt_key(payload: dict[str, Any]) -> str | None:
    for key in TEXT_KEYS:
        if key in payload:
            return key
    return None


def _record_preview(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    text = str(record.get("text", ""))
    return {
        "id": record.get("id"),
        "line": record.get("line"),
        "chars": len(text),
        "words": len(text.split()),
        "text": text[:160] + ("..." if len(text) > 160 else ""),
    }


def _privacy_patterns() -> list[tuple[str, re.Pattern[str]]]:
    return [
        ("token", TOKEN_RE),
        ("aws_access_key", AWS_ACCESS_KEY_RE),
        ("secret_assignment", SECRET_ASSIGNMENT_RE),
        ("email", EMAIL_RE),
        ("phone", PHONE_RE),
        ("windows_user_path", WINDOWS_USER_PATH_RE),
        ("home_path", HOME_PATH_RE),
    ]


def _redact_match(value: str) -> str:
    if len(value) <= 8:
        return "[REDACTED]"
    return value[:4] + "..." + value[-4:]


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value
