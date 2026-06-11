from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

from .corpus import redact_text, scan_privacy
from .metrics import benchmark_prompts, benchmark_replies
from .mining import mine_reply_patterns


PROMPT_KEYS = ("prompt", "input", "request", "user", "human", "text")
REPLY_KEYS = ("reply", "response", "assistant", "output", "answer")
REPLY_FIELD_KEYS = ("status", "summary", "files", "verification", "commands", "risks", "next_steps", "warnings")

_SPACE_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_PATH_RE = re.compile(
    r"(?<![\w.-])(?:[A-Za-z]:)?(?:[\w.-]+[\\/])+[\w.@()-]+|(?<![\w.-])[\w.-]+\.(?:py|js|ts|tsx|jsx|md|json|toml|yaml|yml|css|html|sql|go|rs|java|cs|cpp|c|h)(?![\w.-])",
    re.IGNORECASE,
)
_COMMAND_PREFIXES = (
    "python ",
    "python -m ",
    "pytest",
    "npm ",
    "pnpm ",
    "yarn ",
    "git ",
    "gh ",
    "ruff ",
    "mypy",
    "tsc",
    "cargo ",
    "go test",
)


def load_turn_records(path: Path | str) -> list[dict[str, Any]]:
    """Load normalized prompt/reply turn records from JSON or JSONL."""

    rows = _load_turn_payloads(path)
    records = []
    for index, payload in enumerate(rows, start=1):
        records.append(_normalize_turn(payload, index))
    return records


def validate_turn_corpus(path: Path | str) -> dict[str, Any]:
    """Validate paired prompt/reply turns and flag common privacy risks."""

    started = time.time()
    source = Path(path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    raw_text = ""

    if not source.exists():
        errors.append({"line": None, "code": "missing_file", "message": f"Turn corpus not found: {source}"})
    else:
        raw_text = source.read_text(encoding="utf-8")
        payloads, errors, warnings = _validate_turn_payloads(raw_text, source.suffix.lower())
        records = [_normalize_turn(payload, index + 1) for index, payload in enumerate(payloads)]

    privacy = _scan_turn_privacy(records)
    stats = turn_stats_from_records(records)
    status = "fail" if errors else "warn" if warnings or privacy["finding_count"] else "pass"
    return {
        "schema_version": "tokensquash.turns.validate.v1",
        "status": status,
        "path": str(source),
        "format": "json" if source.suffix.lower() == ".json" else "jsonl",
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


def turn_stats(path: Path | str) -> dict[str, Any]:
    records = load_turn_records(path)
    report = turn_stats_from_records(records)
    report["path"] = str(Path(path))
    return report


def turn_stats_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    prompt_lengths = [len(item["prompt"]) for item in records]
    reply_lengths = [len(item["reply_text"]) for item in records]
    turn_count = len(records)
    return {
        "schema_version": "tokensquash.turns.stats.v1",
        "summary": {
            "turn_count": turn_count,
            "prompt_chars": sum(prompt_lengths),
            "reply_chars": sum(reply_lengths),
            "avg_prompt_chars": round(sum(prompt_lengths) / turn_count, 2) if turn_count else 0.0,
            "avg_reply_chars": round(sum(reply_lengths) / turn_count, 2) if turn_count else 0.0,
            "min_prompt_chars": min(prompt_lengths) if prompt_lengths else 0,
            "max_prompt_chars": max(prompt_lengths) if prompt_lengths else 0,
            "min_reply_chars": min(reply_lengths) if reply_lengths else 0,
            "max_reply_chars": max(reply_lengths) if reply_lengths else 0,
        },
        "shortest_prompt": _turn_preview(min(records, key=lambda item: len(item["prompt"]), default=None), "prompt"),
        "longest_prompt": _turn_preview(max(records, key=lambda item: len(item["prompt"]), default=None), "prompt"),
        "shortest_reply": _turn_preview(min(records, key=lambda item: len(item["reply_text"]), default=None), "reply_text"),
        "longest_reply": _turn_preview(max(records, key=lambda item: len(item["reply_text"]), default=None), "reply_text"),
    }


def redact_turn_corpus(input_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    """Write a redacted copy of a paired turn corpus."""

    source = Path(input_path)
    target = Path(output_path)
    if not source.exists():
        raise FileNotFoundError(f"turn corpus not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payloads = _load_raw_payloads(source)
    counts: dict[str, int] = {}
    redacted_payloads = []
    for payload in payloads:
        redacted, item_counts = _redact_payload(payload)
        _merge_counts(counts, item_counts)
        redacted_payloads.append(redacted)

    if source.suffix.lower() == ".json":
        target.write_text(json.dumps(redacted_payloads, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    else:
        lines = [json.dumps(item, ensure_ascii=True, separators=(",", ":")) for item in redacted_payloads]
        target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    return {
        "schema_version": "tokensquash.turns.redact.v1",
        "status": "written",
        "input": str(source),
        "output": str(target),
        "rows": len(redacted_payloads),
        "redactions": counts,
        "redaction_count": sum(counts.values()),
    }


def append_turn_record(
    output_path: Path | str,
    *,
    prompt: str,
    reply: str,
    item_id: str | None = None,
    status: str | None = None,
    summary: str | None = None,
    files: Iterable[str] = (),
    verification: Iterable[str] = (),
    commands: Iterable[str] = (),
    risks: Iterable[str] = (),
    next_steps: Iterable[str] = (),
) -> dict[str, Any]:
    """Append one prompt/reply turn to a JSONL corpus."""

    target = Path(output_path)
    if target.suffix.lower() == ".json":
        raise ValueError("turns add writes JSONL; use a .jsonl output path")
    existing = _load_raw_payloads(target) if target.exists() else []
    existing_ids = {str(item.get("id")) for item in existing if item.get("id") is not None}
    record_id = item_id or _next_turn_id(existing)
    if record_id in existing_ids:
        raise ValueError(f"turn id already exists: {record_id}")

    clean_prompt = _clean_text(prompt)
    clean_reply = _clean_text(reply)
    if not clean_prompt:
        raise ValueError("prompt must not be empty")
    if not clean_reply:
        raise ValueError("reply must not be empty")

    record: dict[str, Any] = {
        "id": record_id,
        "prompt": clean_prompt,
        "reply": clean_reply,
    }
    if status:
        record["status"] = status
    if summary:
        record["summary"] = _clean_text(summary)
    _append_optional_list(record, "files", files)
    _append_optional_list(record, "verification", verification)
    _append_optional_list(record, "commands", commands)
    _append_optional_list(record, "risks", risks)
    _append_optional_list(record, "next_steps", next_steps)

    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
    newline = ""
    if target.exists() and target.stat().st_size > 0:
        text = target.read_text(encoding="utf-8")
        newline = "" if text.endswith("\n") else "\n"
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(newline + line + "\n")

    return {
        "schema_version": "tokensquash.turns.add.v1",
        "status": "written",
        "output": str(target),
        "id": record_id,
        "turns": len(existing) + 1,
    }


def split_turn_corpus(
    input_path: Path | str,
    prompts_output: Path | str,
    replies_output: Path | str,
    *,
    guess_reply_fields: bool = True,
) -> dict[str, Any]:
    """Split paired turns into prompt and reply corpora."""

    records = load_turn_records(input_path)
    prompt_rows = [{"id": item.get("id"), "text": item["prompt"]} for item in records]
    reply_rows = [_reply_record_from_turn(item, guess_reply_fields=guess_reply_fields) for item in records]
    prompt_target = Path(prompts_output)
    reply_target = Path(replies_output)
    prompt_target.parent.mkdir(parents=True, exist_ok=True)
    reply_target.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(prompt_target, prompt_rows)
    _write_jsonl(reply_target, reply_rows)
    return {
        "schema_version": "tokensquash.turns.split.v1",
        "status": "written",
        "input": str(input_path),
        "prompts_output": str(prompt_target),
        "replies_output": str(reply_target),
        "turns": len(records),
        "reply_fields": "guessed" if guess_reply_fields else "source_only",
    }


def benchmark_turns(
    records: Iterable[dict[str, Any]],
    *,
    counter: str = "heuristic",
    target_savings_pct: float = 0.5,
    adaptive: bool = True,
    source: str | None = None,
    guess_reply_fields: bool = True,
) -> dict[str, Any]:
    """Benchmark prompt and reply savings for paired turns."""

    rows = list(records)
    prompts = [item["prompt"] for item in rows]
    replies = [_reply_record_from_turn(item, guess_reply_fields=guess_reply_fields) for item in rows]
    prompt_report = benchmark_prompts(
        prompts,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        source=source,
    )
    reply_report = benchmark_replies(
        replies,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        source=source,
    )
    prompt_summary = prompt_report["summary"]
    reply_summary = reply_report["summary"]
    original_tokens = int(prompt_summary["original_tokens"]) + int(reply_summary["original_tokens"])
    wire_tokens = int(prompt_summary["wire_tokens"]) + int(reply_summary["wire_tokens"])
    squashed_tokens = int(prompt_summary["squashed_tokens"]) + int(reply_summary["squashed_tokens"])
    wire_saved_tokens = int(prompt_summary["wire_saved_tokens"]) + int(reply_summary["wire_saved_tokens"])
    saved_tokens = int(prompt_summary["saved_tokens"]) + int(reply_summary["saved_tokens"])
    saved_pct = _pct(saved_tokens, original_tokens)
    status = "pass" if saved_pct >= target_savings_pct else "miss"
    if original_tokens <= 0:
        status = "empty"

    return {
        "schema_version": "tokensquash.turns.bench.v1",
        "status": status,
        "counter": counter,
        "adaptive": adaptive,
        "source": source,
        "target_savings_pct": target_savings_pct,
        "summary": {
            "turn_count": len(rows),
            "original_tokens": original_tokens,
            "wire_tokens": wire_tokens,
            "squashed_tokens": squashed_tokens,
            "wire_saved_tokens": wire_saved_tokens,
            "wire_saved_pct": _pct(wire_saved_tokens, original_tokens),
            "saved_tokens": saved_tokens,
            "saved_pct": saved_pct,
            "passthroughs": int(prompt_summary["passthroughs"]) + int(reply_summary["passthroughs"]),
            "prompt_saved_pct": prompt_summary["saved_pct"],
            "reply_saved_pct": reply_summary["saved_pct"],
        },
        "prompt_report": prompt_report,
        "reply_report": reply_report,
    }


def measure_turn_corpus(
    path: Path | str,
    *,
    counter: str = "heuristic",
    target_savings_pct: float = 0.5,
    adaptive: bool = True,
    guess_reply_fields: bool = True,
) -> dict[str, Any]:
    """Validate, summarize, and benchmark a paired turn corpus."""

    started = time.time()
    validation = validate_turn_corpus(path)
    if validation["status"] == "fail":
        return {
            "schema_version": "tokensquash.turns.measure.v1",
            "status": "fail",
            "path": str(Path(path)),
            "counter": counter,
            "adaptive": adaptive,
            "summary": {
                "turn_count": validation.get("summary", {}).get("turn_count", 0),
                "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
                "saved_pct": 0.0,
                "prompt_saved_pct": 0.0,
                "reply_saved_pct": 0.0,
                "elapsed_seconds": round(time.time() - started, 4),
            },
            "validation": validation,
            "stats": None,
            "benchmark": None,
        }

    stats = turn_stats(path)
    benchmark = benchmark_turns(
        load_turn_records(path),
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        source=str(path),
        guess_reply_fields=guess_reply_fields,
    )
    validation_status = validation["status"]
    benchmark_status = benchmark["status"]
    if benchmark_status == "miss":
        status = "miss"
    elif validation_status == "warn":
        status = "warn"
    else:
        status = benchmark_status

    bench_summary = benchmark["summary"]
    return {
        "schema_version": "tokensquash.turns.measure.v1",
        "status": status,
        "path": str(Path(path)),
        "counter": counter,
        "adaptive": adaptive,
        "target_savings_pct": target_savings_pct,
        "summary": {
            "turn_count": bench_summary.get("turn_count", 0),
            "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
            "original_tokens": bench_summary.get("original_tokens", 0),
            "squashed_tokens": bench_summary.get("squashed_tokens", 0),
            "saved_tokens": bench_summary.get("saved_tokens", 0),
            "saved_pct": bench_summary.get("saved_pct", 0.0),
            "prompt_saved_pct": bench_summary.get("prompt_saved_pct", 0.0),
            "reply_saved_pct": bench_summary.get("reply_saved_pct", 0.0),
            "pass_through_rows": bench_summary.get("passthroughs", 0),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "validation": validation,
        "stats": stats,
        "benchmark": benchmark,
    }


def diagnose_turn_corpus(
    path: Path | str,
    *,
    counter: str = "heuristic",
    adaptive: bool = True,
    guess_reply_fields: bool = True,
    limit: int = 5,
) -> dict[str, Any]:
    """Diagnose which paired turns save tokens, lose raw wire tokens, or pass through."""

    started = time.time()
    validation = validate_turn_corpus(path)
    if validation["status"] == "fail":
        return {
            "schema_version": "tokensquash.turns.diagnose.v1",
            "status": "fail",
            "path": str(Path(path)),
            "counter": counter,
            "adaptive": adaptive,
            "limit": limit,
            "summary": {
                "turn_count": validation.get("summary", {}).get("turn_count", 0),
                "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
                "elapsed_seconds": round(time.time() - started, 4),
            },
            "issue_counts": {},
            "largest_wins": [],
            "largest_losses": [],
            "pass_throughs": [],
            "rows": [],
            "validation": validation,
            "benchmark_summary": None,
        }

    records = load_turn_records(path)
    benchmark = benchmark_turns(
        records,
        counter=counter,
        target_savings_pct=0.0,
        adaptive=adaptive,
        source=str(path),
        guess_reply_fields=guess_reply_fields,
    )
    prompt_rows = {int(row.get("index", 0)): row for row in benchmark.get("prompt_report", {}).get("rows", [])}
    reply_rows = {int(row.get("index", 0)): row for row in benchmark.get("reply_report", {}).get("rows", [])}
    rows = [
        _turn_diagnostic_row(record, index, prompt_rows.get(index, {}), reply_rows.get(index, {}))
        for index, record in enumerate(records, start=1)
    ]
    capped_limit = max(1, int(limit))
    summary = _turn_diagnostics_summary(rows, validation, time.time() - started)
    status = "empty" if not rows else "warn" if validation["status"] == "warn" else "pass"

    return {
        "schema_version": "tokensquash.turns.diagnose.v1",
        "status": status,
        "path": str(Path(path)),
        "counter": counter,
        "adaptive": adaptive,
        "limit": capped_limit,
        "summary": summary,
        "issue_counts": _diagnostic_issue_counts(rows),
        "largest_wins": _diagnostic_briefs(
            sorted((row for row in rows if row["saved_tokens"] > 0), key=lambda row: row["saved_tokens"], reverse=True),
            capped_limit,
        ),
        "largest_losses": _diagnostic_briefs(
            sorted((row for row in rows if row["wire_saved_tokens"] < 0), key=lambda row: row["wire_saved_tokens"]),
            capped_limit,
        ),
        "pass_throughs": _diagnostic_briefs(
            sorted(
                (row for row in rows if row["prompt"]["mode"] == "passthrough" or row["reply"]["mode"] == "passthrough"),
                key=lambda row: (row["wire_saved_tokens"], -row["original_tokens"]),
            ),
            capped_limit,
        ),
        "rows": rows,
        "validation": validation,
        "benchmark_summary": benchmark.get("summary"),
    }


def mine_turn_patterns(
    path: Path | str,
    *,
    counter: str = "heuristic",
    min_count: int = 2,
    limit: int = 10,
    guess_reply_fields: bool = True,
) -> dict[str, Any]:
    """Mine paired turns for repeated reply patterns worth compacting."""

    started = time.time()
    validation = validate_turn_corpus(path)
    if validation["status"] == "fail":
        return {
            "schema_version": "tokensquash.turns.mine.v1",
            "status": "fail",
            "source_type": "turns",
            "source": str(Path(path)),
            "counter": counter,
            "min_count": max(1, int(min_count)),
            "limit": max(1, int(limit)),
            "summary": {
                "turn_count": validation.get("summary", {}).get("turn_count", 0),
                "record_count": 0,
                "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
                "estimated_new_saved_tokens": 0,
                "elapsed_seconds": round(time.time() - started, 4),
            },
            "top_candidates": [],
            "existing_codes": [],
            "path_patterns": [],
            "fields": {},
            "validation": validation,
        }

    records = load_turn_records(path)
    replies = [_reply_record_from_turn(item, guess_reply_fields=guess_reply_fields) for item in records]
    report = mine_reply_patterns(
        replies,
        counter=counter,
        min_count=min_count,
        limit=limit,
        source=str(Path(path)),
        source_type="turns",
    )
    report["schema_version"] = "tokensquash.turns.mine.v1"
    if validation["status"] == "warn" and report["status"] == "pass":
        report["status"] = "warn"
    report["summary"] = {
        **report.get("summary", {}),
        "turn_count": len(records),
        "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
    }
    report["validation"] = validation
    return report


def format_turn_validation_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Turn Validation",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Format: `{report.get('format')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
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
            lines.append(f"- line `{item.get('line')}` `{item.get('id')}` `{item.get('code')}`: `{item.get('match')}`")
        if len(findings) > 50:
            lines.append(f"- ... {len(findings) - 50} more")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_stats_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Turn Stats",
        "",
        f"- Path: `{report.get('path', '')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Prompt chars: `{summary.get('prompt_chars', 0)}`",
        f"- Reply chars: `{summary.get('reply_chars', 0)}`",
        f"- Avg prompt chars: `{summary.get('avg_prompt_chars', 0.0)}`",
        f"- Avg reply chars: `{summary.get('avg_reply_chars', 0.0)}`",
    ]
    for label, key in (
        ("Shortest prompt", "shortest_prompt"),
        ("Longest prompt", "longest_prompt"),
        ("Shortest reply", "shortest_reply"),
        ("Longest reply", "longest_reply"),
    ):
        item = report.get(key)
        if item:
            lines.append(f"{label}: line `{item.get('line')}` `{item.get('text')}`")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_benchmark_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    prompt_summary = report.get("prompt_report", {}).get("summary", {})
    reply_summary = report.get("reply_report", {}).get("summary", {})
    lines = [
        "# TokenSquash Turn Benchmark",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Adaptive: `{report.get('adaptive')}`",
        f"- Source: `{report.get('source') or 'inline'}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Original tokens: `{summary.get('original_tokens', 0)}`",
        f"- Raw wire tokens: `{summary.get('wire_tokens', 0)}`",
        f"- Squashed tokens: `{summary.get('squashed_tokens', 0)}`",
        f"- Raw wire saved: `{summary.get('wire_saved_tokens', 0)} ({summary.get('wire_saved_pct', 0.0)}%)`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Prompt saved percent: `{prompt_summary.get('saved_pct', 0.0)}%`",
        f"- Reply saved percent: `{reply_summary.get('saved_pct', 0.0)}%`",
        f"- Pass-through rows: `{summary.get('passthroughs', 0)}`",
        "",
    ]
    return "\n".join(lines)


def format_turn_measure_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Turn Measure",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Adaptive: `{report.get('adaptive')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
        f"- Original tokens: `{summary.get('original_tokens', 0)}`",
        f"- Squashed tokens: `{summary.get('squashed_tokens', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Prompt saved percent: `{summary.get('prompt_saved_pct', 0.0)}%`",
        f"- Reply saved percent: `{summary.get('reply_saved_pct', 0.0)}%`",
        f"- Pass-through rows: `{summary.get('pass_through_rows', 0)}`",
        "",
    ]
    validation = report.get("validation") or {}
    if validation.get("status") == "warn":
        lines.append("Validation warnings or privacy findings are present; review before sharing this corpus.")
        lines.append("")
    if report.get("status") == "miss":
        lines.append("The corpus did not meet the target savings threshold. Use `--target 0` for exploratory runs.")
        lines.append("")
    return "\n".join(lines)


def format_turn_diagnose_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    issue_counts = report.get("issue_counts", {})
    lines = [
        "# TokenSquash Turn Diagnose",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Adaptive: `{report.get('adaptive')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Original tokens: `{summary.get('original_tokens', 0)}`",
        f"- Squashed tokens: `{summary.get('squashed_tokens', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Raw wire saved: `{summary.get('wire_saved_tokens', 0)} ({summary.get('wire_saved_pct', 0.0)}%)`",
        f"- Win/loss/tie turns: `{summary.get('win_turns', 0)}/{summary.get('loss_turns', 0)}/{summary.get('tie_turns', 0)}`",
        f"- Pass-through rows: `{summary.get('pass_through_rows', 0)}`",
    ]
    if issue_counts:
        lines.append(f"- Top tags: `{_format_issue_counts(issue_counts)}`")
    lines.append("")

    if report.get("validation", {}).get("status") == "warn":
        lines.append("Validation warnings or privacy findings are present; review before sharing this corpus.")
        lines.append("")

    _append_diagnostic_table(lines, "Largest Wins", report.get("largest_wins", []))
    _append_diagnostic_table(lines, "Raw Wire Losses", report.get("largest_losses", []))
    _append_diagnostic_table(lines, "Pass-Through Rows", report.get("pass_throughs", []))
    return "\n".join(lines).rstrip() + "\n"


def format_turn_split_markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# TokenSquash Turn Split",
            "",
            f"- Status: `{report.get('status')}`",
            f"- Turns: `{report.get('turns', 0)}`",
            f"- Prompts: `{report.get('prompts_output')}`",
            f"- Replies: `{report.get('replies_output')}`",
            f"- Reply fields: `{report.get('reply_fields')}`",
            "",
        ]
    )


def format_turn_add_markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# TokenSquash Turn Add",
            "",
            f"- Status: `{report.get('status')}`",
            f"- Output: `{report.get('output')}`",
            f"- ID: `{report.get('id')}`",
            f"- Turns: `{report.get('turns', 0)}`",
            "",
        ]
    )


def _load_turn_payloads(path: Path | str) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"turn corpus not found: {source}")
    return _load_raw_payloads(source)


def _load_raw_payloads(source: Path) -> list[dict[str, Any]]:
    text = source.read_text(encoding="utf-8")
    payloads, errors, _warnings = _validate_turn_payloads(text, source.suffix.lower())
    if errors:
        first = errors[0]
        raise ValueError(f"turn corpus row {first.get('line')} {first.get('message')}")
    return payloads


def _validate_turn_payloads(
    text: str,
    suffix: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return [], [{"line": None, "code": "invalid_json", "message": exc.msg}], []
        if not isinstance(payload, list):
            return [], [{"line": None, "code": "json_not_list", "message": "JSON turn corpus must contain a list."}], []
        rows = payload
    else:
        rows = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                errors.append({"line": line_no, "code": "invalid_json", "message": exc.msg})

    payloads: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        line = index if suffix != ".json" else None
        if not isinstance(row, dict):
            errors.append({"line": line, "code": "row_not_object", "message": "Row must be a JSON object."})
            continue
        prompt = _extract_text_value(row, PROMPT_KEYS)
        reply_text, reply_fields = _extract_reply(row)
        if not prompt:
            errors.append({"line": line, "code": "missing_prompt", "message": "Row must include a prompt/input/user value."})
            continue
        if not reply_text and not reply_fields:
            errors.append({"line": line, "code": "missing_reply", "message": "Row must include a reply/response/assistant value."})
            continue
        item_id = row.get("id")
        if item_id is not None:
            item_id = str(item_id)
            if item_id in seen_ids:
                warnings.append({"line": line, "code": "duplicate_id", "message": f"Duplicate id: {item_id}"})
            seen_ids.add(item_id)
        payloads.append(row)
    if not payloads and not errors:
        warnings.append({"line": None, "code": "empty_turn_corpus", "message": "No turns found."})
    return payloads, errors, warnings


def _normalize_turn(payload: dict[str, Any], index: int) -> dict[str, Any]:
    prompt = _extract_text_value(payload, PROMPT_KEYS)
    reply_text, reply_fields = _extract_reply(payload)
    item_id = str(payload.get("id", f"turn-{index:04d}"))
    return {
        "id": item_id,
        "line": payload.get("line", index),
        "prompt": prompt,
        "reply_text": reply_text,
        "reply_fields": reply_fields,
    }


def _extract_reply(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    reply_fields = {key: payload[key] for key in REPLY_FIELD_KEYS if key in payload}
    for key in REPLY_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, str):
            return _clean_text(value), reply_fields
        if isinstance(value, dict):
            nested = {**value, **reply_fields}
            text = _extract_text_value(value, ("text", "reply", "response", "assistant", "output"))
            return text, nested
    return "", reply_fields


def _extract_text_value(payload: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_text(value)
    return ""


def _reply_record_from_turn(item: dict[str, Any], *, guess_reply_fields: bool) -> dict[str, Any]:
    fields = dict(item.get("reply_fields") or {})
    reply_text = str(item.get("reply_text", "")).strip()
    if guess_reply_fields:
        guessed = _guess_reply_fields(reply_text)
        fields = {**guessed, **fields}
    fields.setdefault("status", "done")
    fields.setdefault("summary", _first_sentence(reply_text))
    return {"id": item.get("id"), "text": reply_text, **fields}


def _guess_reply_fields(text: str) -> dict[str, Any]:
    lower = text.lower()
    status = "done"
    if "blocked" in lower[:160] or "cannot proceed" in lower[:240]:
        status = "blocked"
    elif "failed" in lower[:160] or "could not" in lower[:240]:
        status = "failed"
    elif "partial" in lower[:160]:
        status = "partial"

    return {
        "status": status,
        "summary": _summary_from_text(text),
        "files": _unique(_normalize_path(match.group(0)) for match in _PATH_RE.finditer(text))[:8],
        "verification": _extract_verification(text),
        "commands": _extract_commands(text),
        "risks": _extract_tagged_sentences(text, ("risk", "caveat", "limitation", "not proof"))[:4],
        "next_steps": _extract_tagged_sentences(text, ("next step", "next we", "next:"))[:4],
    }


def _summary_from_text(text: str) -> str:
    for sentence in _SENTENCE_RE.split(_clean_text(text)):
        summary = re.sub(
            r"^(done|blocked for now|blocked|failed|partially done)\.?\s*",
            "",
            sentence,
            flags=re.IGNORECASE,
        )
        summary = _strip_summary_details(summary)
        summary = _clean_text(summary)
        if summary:
            return _truncate(summary, 120)
    return _first_sentence(text)


def _strip_summary_details(text: str) -> str:
    summary = re.sub(r"`[^`]+`", "", text)
    summary = re.sub(r"\b(?:and\s+)?(?:verified|validated|tested|ran|checked)\b.*$", "", summary, flags=re.IGNORECASE)
    summary = re.sub(r"\b(?:risks?|caveats?|limitations?)\s*:.*$", "", summary, flags=re.IGNORECASE)
    summary = _PATH_RE.sub("", summary)
    summary = re.sub(r"\b(?:in|at|within|with)\s*([,.]|$)", r"\1", summary, flags=re.IGNORECASE)
    return _clean_text(summary).strip(" ,.;:")


def _first_sentence(text: str) -> str:
    sentences = _SENTENCE_RE.split(_clean_text(text), maxsplit=1)
    return _truncate(sentences[0] if sentences else "", 120)


def _extract_verification(text: str) -> list[str]:
    lower = text.lower()
    checks = [
        ("unit tests pass", ("unit tests passed", "unit tests pass", "tests passed", "tests pass")),
        ("ci pass", ("ci passed", "github actions passed", "actions passed")),
        ("build pass", ("build passed", "build pass", "compiled successfully")),
        ("lint pass", ("lint passed", "lint pass")),
        ("exact benchmark pass", ("exact tokenizer benchmark", "exact benchmark")),
    ]
    return [label for label, patterns in checks if any(pattern in lower for pattern in patterns)]


def _extract_commands(text: str) -> list[str]:
    commands = []
    for value in re.findall(r"`([^`\n]+)`", text):
        if _looks_like_command(value):
            commands.append(value.strip())
    for line in text.splitlines():
        stripped = line.strip().lstrip("$").strip()
        if _looks_like_command(stripped):
            commands.append(stripped)
    return _unique(commands)[:6]


def _looks_like_command(value: str) -> bool:
    lowered = value.lower()
    return any(lowered.startswith(prefix) for prefix in _COMMAND_PREFIXES)


def _extract_tagged_sentences(text: str, tags: tuple[str, ...]) -> list[str]:
    result = []
    for sentence in _SENTENCE_RE.split(_clean_text(text)):
        lowered = sentence.lower()
        if any(tag in lowered for tag in tags):
            result.append(_truncate(_strip_tag_prefix(sentence), 140))
    return _unique(result)


def _strip_tag_prefix(text: str) -> str:
    return _clean_text(
        re.sub(
            r"^(?:the\s+)?(?:main\s+)?(?:risks?|caveats?|limitations?|next\s+steps?|next\s+step)\s*(?:is|are)?\s*:\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
    ).strip(" .;:")


def _scan_turn_privacy(records: list[dict[str, Any]]) -> dict[str, Any]:
    scan_records = []
    for item in records:
        scan_records.append({"id": f"{item.get('id')}:prompt", "line": item.get("line"), "text": item.get("prompt", "")})
        scan_records.append({"id": f"{item.get('id')}:reply", "line": item.get("line"), "text": item.get("reply_text", "")})
    return scan_privacy(scan_records)


def _redact_payload(value: Any) -> tuple[Any, dict[str, int]]:
    counts: dict[str, int] = {}
    if isinstance(value, str):
        redacted, counts = redact_text(value)
        return redacted, counts
    if isinstance(value, list):
        items = []
        for item in value:
            redacted, item_counts = _redact_payload(item)
            _merge_counts(counts, item_counts)
            items.append(redacted)
        return items, counts
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            redacted, item_counts = _redact_payload(item)
            _merge_counts(counts, item_counts)
            result[key] = redacted
        return result, counts
    return value, counts


def _turn_preview(record: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if record is None:
        return None
    text = str(record.get(key, ""))
    return {
        "id": record.get("id"),
        "line": record.get("line"),
        "chars": len(text),
        "text": _truncate(text, 160),
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=True, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _append_optional_list(record: dict[str, Any], key: str, values: Iterable[str]) -> None:
    items = _unique(_clean_text(str(value)) for value in values)
    if items:
        record[key] = items


def _next_turn_id(records: list[dict[str, Any]]) -> str:
    return f"turn-{len(records) + 1:04d}"


def _clean_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text.strip())


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _truncate(text: str, limit: int) -> str:
    return text[: limit - 3].rstrip() + "..." if len(text) > limit else text


def _unique(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def _turn_diagnostic_row(
    record: dict[str, Any],
    index: int,
    prompt: dict[str, Any],
    reply: dict[str, Any],
) -> dict[str, Any]:
    prompt_diag = _side_diagnostic(prompt)
    reply_diag = _side_diagnostic(reply)
    original_tokens = prompt_diag["original_tokens"] + reply_diag["original_tokens"]
    wire_tokens = prompt_diag["wire_tokens"] + reply_diag["wire_tokens"]
    squashed_tokens = prompt_diag["squashed_tokens"] + reply_diag["squashed_tokens"]
    wire_saved_tokens = prompt_diag["wire_saved_tokens"] + reply_diag["wire_saved_tokens"]
    saved_tokens = prompt_diag["saved_tokens"] + reply_diag["saved_tokens"]
    tags = _turn_diagnostic_tags(record, prompt_diag, reply_diag, wire_saved_tokens, saved_tokens)
    return {
        "index": index,
        "id": record.get("id", f"turn-{index:04d}"),
        "line": record.get("line", index),
        "original_tokens": original_tokens,
        "wire_tokens": wire_tokens,
        "squashed_tokens": squashed_tokens,
        "wire_saved_tokens": wire_saved_tokens,
        "wire_saved_pct": _pct(wire_saved_tokens, original_tokens),
        "saved_tokens": saved_tokens,
        "saved_pct": _pct(saved_tokens, original_tokens),
        "prompt": {**prompt_diag, "op": prompt.get("op")},
        "reply": {**reply_diag, "status": reply.get("status")},
        "tags": tags,
        "prompt_preview": _truncate(str(record.get("prompt", "")), 100),
        "reply_preview": _truncate(str(record.get("reply_text", "")), 100),
    }


def _side_diagnostic(row: dict[str, Any]) -> dict[str, Any]:
    original_tokens = int(row.get("original_tokens", 0))
    wire_tokens = int(row.get("wire_tokens", 0))
    squashed_tokens = int(row.get("squashed_tokens", 0))
    wire_saved_tokens = int(row.get("wire_saved_tokens", original_tokens - wire_tokens))
    saved_tokens = int(row.get("saved_tokens", original_tokens - squashed_tokens))
    return {
        "mode": row.get("mode", "missing"),
        "original_tokens": original_tokens,
        "wire_tokens": wire_tokens,
        "squashed_tokens": squashed_tokens,
        "wire_saved_tokens": wire_saved_tokens,
        "wire_saved_pct": _pct(wire_saved_tokens, original_tokens),
        "saved_tokens": saved_tokens,
        "saved_pct": _pct(saved_tokens, original_tokens),
    }


def _turn_diagnostic_tags(
    record: dict[str, Any],
    prompt: dict[str, Any],
    reply: dict[str, Any],
    wire_saved_tokens: int,
    saved_tokens: int,
) -> list[str]:
    tags: list[str] = []
    if saved_tokens > 0:
        tags.append("adaptive_win")
    elif saved_tokens == 0:
        tags.append("no_adaptive_saving")
    else:
        tags.append("adaptive_loss")
    if wire_saved_tokens < 0:
        tags.append("raw_wire_loss")
    if prompt["wire_saved_tokens"] < 0:
        tags.append("prompt_wire_loss")
    if reply["wire_saved_tokens"] < 0:
        tags.append("reply_wire_loss")
    if prompt["mode"] == "passthrough":
        tags.append("prompt_passthrough")
    if reply["mode"] == "passthrough":
        tags.append("reply_passthrough")
    if prompt["original_tokens"] <= 8:
        tags.append("short_prompt")
    if reply["original_tokens"] <= 12:
        tags.append("short_reply")
    combined_text = f"{record.get('prompt', '')} {record.get('reply_text', '')}"
    if _PATH_RE.search(combined_text):
        tags.append("path_heavy")
    if _extract_commands(str(record.get("reply_text", ""))) or (record.get("reply_fields") or {}).get("commands"):
        tags.append("command_heavy")
    if not record.get("reply_fields"):
        tags.append("guessed_reply_fields")
    return tags


def _turn_diagnostics_summary(
    rows: list[dict[str, Any]],
    validation: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    original_tokens = sum(int(row["original_tokens"]) for row in rows)
    wire_tokens = sum(int(row["wire_tokens"]) for row in rows)
    squashed_tokens = sum(int(row["squashed_tokens"]) for row in rows)
    wire_saved_tokens = sum(int(row["wire_saved_tokens"]) for row in rows)
    saved_tokens = sum(int(row["saved_tokens"]) for row in rows)
    return {
        "turn_count": len(rows),
        "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
        "original_tokens": original_tokens,
        "wire_tokens": wire_tokens,
        "squashed_tokens": squashed_tokens,
        "wire_saved_tokens": wire_saved_tokens,
        "wire_saved_pct": _pct(wire_saved_tokens, original_tokens),
        "saved_tokens": saved_tokens,
        "saved_pct": _pct(saved_tokens, original_tokens),
        "win_turns": sum(1 for row in rows if int(row["saved_tokens"]) > 0),
        "loss_turns": sum(1 for row in rows if int(row["saved_tokens"]) < 0),
        "tie_turns": sum(1 for row in rows if int(row["saved_tokens"]) == 0),
        "raw_wire_loss_turns": sum(1 for row in rows if int(row["wire_saved_tokens"]) < 0),
        "prompt_passthroughs": sum(1 for row in rows if row["prompt"]["mode"] == "passthrough"),
        "reply_passthroughs": sum(1 for row in rows if row["reply"]["mode"] == "passthrough"),
        "pass_through_rows": sum(
            1 for row in rows if row["prompt"]["mode"] == "passthrough" or row["reply"]["mode"] == "passthrough"
        ),
        "elapsed_seconds": round(elapsed_seconds, 4),
    }


def _diagnostic_issue_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for tag in row.get("tags", []):
            counts[tag] = counts.get(tag, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _diagnostic_briefs(rows: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        result.append(
            {
                "index": row.get("index"),
                "id": row.get("id"),
                "line": row.get("line"),
                "original_tokens": row.get("original_tokens"),
                "wire_tokens": row.get("wire_tokens"),
                "squashed_tokens": row.get("squashed_tokens"),
                "wire_saved_tokens": row.get("wire_saved_tokens"),
                "wire_saved_pct": row.get("wire_saved_pct"),
                "saved_tokens": row.get("saved_tokens"),
                "saved_pct": row.get("saved_pct"),
                "prompt": row.get("prompt"),
                "reply": row.get("reply"),
                "tags": row.get("tags", []),
                "prompt_preview": row.get("prompt_preview"),
                "reply_preview": row.get("reply_preview"),
            }
        )
        if len(result) >= limit:
            break
    return result


def _format_issue_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in list(counts.items())[:8])


def _append_diagnostic_table(lines: list[str], title: str, rows: list[dict[str, Any]]) -> None:
    lines.extend([f"## {title}", ""])
    if not rows:
        lines.extend(["No rows.", ""])
        return
    lines.extend(
        [
            "| ID | Original | Raw saved | Adaptive saved | Prompt | Reply | Tags |",
            "|---|---:|---:|---:|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            f"{_markdown_cell(str(row.get('id')))} | "
            f"{row.get('original_tokens')} | "
            f"{row.get('wire_saved_tokens')} ({row.get('wire_saved_pct')}%) | "
            f"{row.get('saved_tokens')} ({row.get('saved_pct')}%) | "
            f"{_markdown_cell(_side_summary(row.get('prompt', {})))} | "
            f"{_markdown_cell(_side_summary(row.get('reply', {})))} | "
            f"{_markdown_cell(', '.join(row.get('tags', [])[:5]))} |"
        )
    lines.append("")


def _side_summary(side: dict[str, Any]) -> str:
    return f"{side.get('mode')} raw {side.get('wire_saved_tokens')} saved {side.get('saved_tokens')}"


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _pct(part: int | float, whole: int | float) -> float:
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100.0, 4)
