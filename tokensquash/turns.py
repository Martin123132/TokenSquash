from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

from .aliases import AliasTable, learn_reply_aliases, write_alias_table
from .corpus import redact_text, scan_privacy
from .metrics import benchmark_prompts, benchmark_replies, count_tokens
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
        raw_text = source.read_text(encoding="utf-8-sig")
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


def capture_turn_record(
    *,
    prompt: str,
    reply: str,
    raw_output_path: Path | str = Path("private-turns/real.jsonl"),
    redacted_output_path: Path | str = Path("private-turns/real.redacted-turns.jsonl"),
    item_id: str | None = None,
    status: str | None = None,
    summary: str | None = None,
    files: Iterable[str] = (),
    verification: Iterable[str] = (),
    commands: Iterable[str] = (),
    risks: Iterable[str] = (),
    next_steps: Iterable[str] = (),
    evaluate: bool = False,
    evaluation_output_dir: Path | str = Path("private-turns/eval-real"),
    counter: str = "heuristic",
    target_savings_pct: float = 0.0,
) -> dict[str, Any]:
    """Append one raw turn, regenerate its redacted corpus, and optionally evaluate it."""

    started = time.time()
    add_report = append_turn_record(
        raw_output_path,
        prompt=prompt,
        reply=reply,
        item_id=item_id,
        status=status,
        summary=summary,
        files=files,
        verification=verification,
        commands=commands,
        risks=risks,
        next_steps=next_steps,
    )
    redaction_report = redact_turn_corpus(raw_output_path, redacted_output_path)
    evaluation_report = None
    if evaluate:
        evaluation_report = evaluate_turn_corpus(
            redacted_output_path,
            counter=counter,
            target_savings_pct=target_savings_pct,
            out_dir=evaluation_output_dir,
        )

    evaluation_summary = (evaluation_report or {}).get("summary", {})
    return {
        "schema_version": "tokensquash.turns.capture.v1",
        "status": "written" if evaluation_report is None else evaluation_report.get("status", "written"),
        "raw_output": str(Path(raw_output_path)),
        "redacted_output": str(Path(redacted_output_path)),
        "evaluation_output_dir": str(Path(evaluation_output_dir)) if evaluate else None,
        "id": add_report.get("id"),
        "turns": add_report.get("turns", 0),
        "redaction_count": redaction_report.get("redaction_count", 0),
        "evaluated": evaluate,
        "summary": {
            "turn_count": add_report.get("turns", 0),
            "redaction_count": redaction_report.get("redaction_count", 0),
            "saved_pct": evaluation_summary.get("saved_pct", 0.0),
            "alias_saved_tokens_delta": evaluation_summary.get("alias_saved_tokens_delta", 0),
            "break_even_corpora": evaluation_summary.get("break_even_corpora"),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "add": add_report,
        "redaction": redaction_report,
        "evaluation": evaluation_report,
    }


def import_turn_corpus(
    input_path: Path | str,
    *,
    raw_output_path: Path | str = Path("private-turns/real.jsonl"),
    redacted_output_path: Path | str = Path("private-turns/real.redacted-turns.jsonl"),
    evaluate: bool = False,
    evaluation_output_dir: Path | str = Path("private-turns/eval-real"),
    counter: str = "heuristic",
    target_savings_pct: float = 0.0,
) -> dict[str, Any]:
    """Import a JSON/JSONL turn corpus into the private raw/redacted workflow."""

    started = time.time()
    source = Path(input_path)
    raw_target = Path(raw_output_path)
    if raw_target.suffix.lower() == ".json":
        raise ValueError("turns import writes raw storage as JSONL; use a .jsonl raw output path")
    payloads = _load_turn_payloads(source)
    records = [_normalize_turn(payload, index) for index, payload in enumerate(payloads, start=1)]
    planned_ids = _planned_import_ids(payloads, raw_target)
    import_rows = []
    for record, planned_id in zip(records, planned_ids):
        fields = dict(record.get("reply_fields") or {})
        prompt_text = _clean_text(str(record.get("prompt", "")))
        reply_text = _clean_text(str(record.get("reply_text") or fields.get("summary") or ""))
        if not prompt_text:
            raise ValueError(f"turn import row {record.get('line')} must include prompt text")
        if not reply_text:
            raise ValueError(f"turn import row {record.get('line')} must include reply text or summary")
        import_rows.append((record, planned_id, fields, prompt_text, reply_text))

    add_reports = []
    for _record, planned_id, fields, prompt_text, reply_text in import_rows:
        add_reports.append(
            append_turn_record(
                raw_target,
                prompt=prompt_text,
                reply=reply_text,
                item_id=planned_id,
                status=_optional_text(fields.get("status")),
                summary=_optional_text(fields.get("summary")),
                files=_coerce_import_items(fields.get("files")),
                verification=_coerce_import_items(fields.get("verification")),
                commands=_coerce_import_items(fields.get("commands")),
                risks=_coerce_import_items(fields.get("risks")),
                next_steps=_coerce_import_items(fields.get("next_steps")),
            )
        )

    if not payloads and not raw_target.exists():
        raw_target.parent.mkdir(parents=True, exist_ok=True)
        raw_target.write_text("", encoding="utf-8")
    redaction_report = redact_turn_corpus(raw_target, redacted_output_path)
    evaluation_report = None
    if evaluate:
        evaluation_report = evaluate_turn_corpus(
            redacted_output_path,
            counter=counter,
            target_savings_pct=target_savings_pct,
            out_dir=evaluation_output_dir,
        )

    evaluation_summary = (evaluation_report or {}).get("summary", {})
    imported_ids = [str(item.get("id")) for item in add_reports]
    total_turns = add_reports[-1].get("turns", 0) if add_reports else len(_load_raw_payloads(raw_target))
    return {
        "schema_version": "tokensquash.turns.import.v1",
        "status": "written" if evaluation_report is None else evaluation_report.get("status", "written"),
        "input": str(source),
        "raw_output": str(raw_target),
        "redacted_output": str(Path(redacted_output_path)),
        "evaluation_output_dir": str(Path(evaluation_output_dir)) if evaluate else None,
        "imported_turns": len(add_reports),
        "turns": total_turns,
        "first_id": imported_ids[0] if imported_ids else None,
        "last_id": imported_ids[-1] if imported_ids else None,
        "imported_ids": imported_ids,
        "redaction_count": redaction_report.get("redaction_count", 0),
        "evaluated": evaluate,
        "summary": {
            "imported_turns": len(add_reports),
            "turn_count": total_turns,
            "redaction_count": redaction_report.get("redaction_count", 0),
            "saved_pct": evaluation_summary.get("saved_pct", 0.0),
            "alias_saved_tokens_delta": evaluation_summary.get("alias_saved_tokens_delta", 0),
            "break_even_corpora": evaluation_summary.get("break_even_corpora"),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "imports": add_reports,
        "redaction": redaction_report,
        "evaluation": evaluation_report,
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
    aliases: AliasTable | dict[str, Any] | None = None,
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
        aliases=aliases,
    )
    reply_report = benchmark_replies(
        replies,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        source=source,
        aliases=aliases,
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
    aliases: AliasTable | dict[str, Any] | None = None,
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
        aliases=aliases,
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
    aliases: AliasTable | dict[str, Any] | None = None,
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
        aliases=aliases,
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
    aliases: AliasTable | dict[str, Any] | None = None,
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
                "reply_record_count": 0,
                "prompt_path_record_count": 0,
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
    prompt_path_records = _prompt_path_records_from_turns(records)
    report = mine_reply_patterns(
        [*replies, *prompt_path_records],
        counter=counter,
        min_count=min_count,
        limit=limit,
        source=str(Path(path)),
        source_type="turns",
        aliases=aliases,
    )
    report["schema_version"] = "tokensquash.turns.mine.v1"
    if validation["status"] == "warn" and report["status"] == "pass":
        report["status"] = "warn"
    report["summary"] = {
        **report.get("summary", {}),
        "turn_count": len(records),
        "reply_record_count": len(replies),
        "prompt_path_record_count": len(prompt_path_records),
        "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
    }
    report["validation"] = validation
    return report


def learn_turn_aliases(
    path: Path | str,
    *,
    counter: str = "heuristic",
    min_count: int = 2,
    max_path_prefixes: int = 8,
    max_field_values: int = 8,
    min_saved_tokens: int = 1,
    guess_reply_fields: bool = True,
    base_aliases: AliasTable | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Learn reply-side session aliases from a paired turn corpus."""

    validation = validate_turn_corpus(path)
    if validation["status"] == "fail":
        return {
            "schema_version": "tokensquash.aliases.v1",
            "status": "fail",
            "source_type": "turns",
            "source": str(Path(path)),
            "counter": counter,
            "min_count": max(1, int(min_count)),
            "max_path_prefixes": max(0, int(max_path_prefixes)),
            "max_field_values": max(0, int(max_field_values)),
            "min_saved_tokens": max(0, int(min_saved_tokens)),
            "include_builtins": True,
            "path_prefixes": {},
            "field_values": {},
            "summary": {
                "turn_count": validation.get("summary", {}).get("turn_count", 0),
                "record_count": 0,
                "reply_record_count": 0,
                "prompt_path_record_count": 0,
                "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
                "path_count": 0,
                "field_value_count": 0,
                "candidate_prefix_count": 0,
                "selected_path_prefix_count": 0,
                "selected_field_value_count": 0,
                "estimated_saved_tokens": 0,
            },
            "selected_path_prefixes": [],
            "selected_field_values": [],
            "validation": validation,
        }

    records = load_turn_records(path)
    replies = [_reply_record_from_turn(item, guess_reply_fields=guess_reply_fields) for item in records]
    prompt_path_records = _prompt_path_records_from_turns(records)
    report = learn_reply_aliases(
        [*replies, *prompt_path_records],
        counter=counter,
        min_count=min_count,
        max_path_prefixes=max_path_prefixes,
        max_field_values=max_field_values,
        min_saved_tokens=min_saved_tokens,
        base_aliases=base_aliases,
        source=str(Path(path)),
    )
    report["source_type"] = "turns"
    if validation["status"] == "warn" and report["status"] == "pass":
        report["status"] = "warn"
    report["summary"] = {
        **report.get("summary", {}),
        "turn_count": len(records),
        "reply_record_count": len(replies),
        "prompt_path_record_count": len(prompt_path_records),
        "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
    }
    report["validation"] = validation
    return report


def benchmark_turn_alias_impact(
    path: Path | str,
    *,
    counter: str = "heuristic",
    target_savings_pct: float = 0.5,
    adaptive: bool = True,
    guess_reply_fields: bool = True,
    min_count: int = 2,
    max_path_prefixes: int = 8,
    max_field_values: int = 8,
    min_saved_tokens: int = 1,
    base_aliases: AliasTable | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Learn aliases and compare turn benchmarks before and after using them."""

    started = time.time()
    validation = validate_turn_corpus(path)
    source = str(Path(path))
    if validation["status"] == "fail":
        return {
            "schema_version": "tokensquash.turns.alias_impact.v1",
            "status": "fail",
            "path": source,
            "counter": counter,
            "adaptive": adaptive,
            "target_savings_pct": target_savings_pct,
            "summary": {
                "turn_count": validation.get("summary", {}).get("turn_count", 0),
                "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
                "selected_path_prefix_count": 0,
                "selected_field_value_count": 0,
                "saved_tokens_delta": 0,
                "saved_pct_delta": 0.0,
                "alias_setup_tokens": 0,
                "net_saved_after_setup_tokens": 0,
                "break_even_corpora": None,
                "elapsed_seconds": round(time.time() - started, 4),
            },
            "delta": {},
            "alias_report": None,
            "baseline": None,
            "aliased": None,
            "validation": validation,
        }

    records = load_turn_records(path)
    baseline = benchmark_turns(
        records,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        source=source,
        guess_reply_fields=guess_reply_fields,
        aliases=base_aliases,
    )
    alias_report = learn_turn_aliases(
        path,
        counter=counter,
        min_count=min_count,
        max_path_prefixes=max_path_prefixes,
        max_field_values=max_field_values,
        min_saved_tokens=min_saved_tokens,
        guess_reply_fields=guess_reply_fields,
        base_aliases=base_aliases,
    )
    aliases = AliasTable.from_dict(alias_report)
    aliased = benchmark_turns(
        records,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        source=source,
        guess_reply_fields=guess_reply_fields,
        aliases=aliases,
    )
    setup_tokens = _alias_setup_tokens(alias_report, counter)
    delta = _alias_impact_delta(baseline, aliased, setup_tokens)
    saved_tokens_delta = int(delta["saved_tokens"])
    status = "empty" if not records else "improved" if saved_tokens_delta > 0 else "same" if saved_tokens_delta == 0 else "regressed"
    if validation["status"] == "warn" and status == "improved":
        status = "warn"

    alias_summary = alias_report.get("summary", {})
    baseline_summary = baseline.get("summary", {})
    aliased_summary = aliased.get("summary", {})
    return {
        "schema_version": "tokensquash.turns.alias_impact.v1",
        "status": status,
        "path": source,
        "counter": counter,
        "adaptive": adaptive,
        "target_savings_pct": target_savings_pct,
        "summary": {
            "turn_count": len(records),
            "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
            "selected_path_prefix_count": alias_summary.get("selected_path_prefix_count", 0),
            "selected_field_value_count": alias_summary.get("selected_field_value_count", 0),
            "baseline_saved_pct": baseline_summary.get("saved_pct", 0.0),
            "aliased_saved_pct": aliased_summary.get("saved_pct", 0.0),
            "saved_tokens_delta": saved_tokens_delta,
            "saved_pct_delta": delta["saved_pct"],
            "wire_tokens_delta": delta["wire_tokens"],
            "squashed_tokens_delta": delta["squashed_tokens"],
            "pass_through_delta": delta["passthroughs"],
            "alias_setup_tokens": setup_tokens,
            "net_saved_after_setup_tokens": delta["net_saved_after_setup_tokens"],
            "break_even_corpora": delta["break_even_corpora"],
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "delta": delta,
        "alias_report": alias_report,
        "baseline": baseline,
        "aliased": aliased,
        "validation": validation,
    }


def evaluate_turn_corpus(
    path: Path | str,
    *,
    counter: str = "heuristic",
    target_savings_pct: float = 0.0,
    adaptive: bool = True,
    guess_reply_fields: bool = True,
    min_count: int = 2,
    limit: int = 10,
    max_path_prefixes: int = 8,
    max_field_values: int = 8,
    min_saved_tokens: int = 1,
    base_aliases: AliasTable | dict[str, Any] | None = None,
    out_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run the full local turn-corpus measurement workflow."""

    started = time.time()
    source = str(Path(path))
    validation = validate_turn_corpus(path)
    outputs: dict[str, str] = {}
    report: dict[str, Any] = {
        "schema_version": "tokensquash.turns.evaluate.v1",
        "status": "fail" if validation["status"] == "fail" else "pass",
        "path": source,
        "counter": counter,
        "adaptive": adaptive,
        "target_savings_pct": target_savings_pct,
        "summary": {
            "turn_count": validation.get("summary", {}).get("turn_count", 0),
            "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
            "saved_pct": 0.0,
            "prompt_saved_pct": 0.0,
            "reply_saved_pct": 0.0,
            "selected_path_prefix_count": 0,
            "selected_field_value_count": 0,
            "alias_saved_tokens_delta": 0,
            "alias_saved_pct_delta": 0.0,
            "break_even_corpora": None,
            "elapsed_seconds": 0.0,
        },
        "outputs": outputs,
        "validation": validation,
        "stats": None,
        "measure": None,
        "diagnose": None,
        "mine": None,
        "aliases": None,
        "alias_impact": None,
        "bench": None,
    }
    if validation["status"] == "fail":
        report["summary"]["elapsed_seconds"] = round(time.time() - started, 4)
        if out_dir is not None:
            _write_turn_evaluation_outputs(Path(out_dir), report)
        return report

    stats = turn_stats(path)
    measure = measure_turn_corpus(
        path,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        guess_reply_fields=guess_reply_fields,
        aliases=base_aliases,
    )
    diagnose = diagnose_turn_corpus(
        path,
        counter=counter,
        adaptive=adaptive,
        guess_reply_fields=guess_reply_fields,
        aliases=base_aliases,
        limit=limit,
    )
    mine = mine_turn_patterns(
        path,
        counter=counter,
        min_count=min_count,
        limit=limit,
        guess_reply_fields=guess_reply_fields,
        aliases=base_aliases,
    )
    aliases = learn_turn_aliases(
        path,
        counter=counter,
        min_count=min_count,
        max_path_prefixes=max_path_prefixes,
        max_field_values=max_field_values,
        min_saved_tokens=min_saved_tokens,
        guess_reply_fields=guess_reply_fields,
        base_aliases=base_aliases,
    )
    alias_impact = benchmark_turn_alias_impact(
        path,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        guess_reply_fields=guess_reply_fields,
        min_count=min_count,
        max_path_prefixes=max_path_prefixes,
        max_field_values=max_field_values,
        min_saved_tokens=min_saved_tokens,
        base_aliases=base_aliases,
    )
    bench = benchmark_turns(
        load_turn_records(path),
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        source=source,
        guess_reply_fields=guess_reply_fields,
        aliases=AliasTable.from_dict(aliases),
    )

    measure_summary = measure.get("summary", {})
    alias_summary = aliases.get("summary", {})
    impact_summary = alias_impact.get("summary", {})
    status = "warn" if validation["status"] == "warn" else "pass"
    if measure.get("status") == "miss":
        status = "miss"
    if alias_impact.get("status") == "regressed":
        status = "regressed"

    report.update(
        {
            "status": status,
            "summary": {
                "turn_count": measure_summary.get("turn_count", stats.get("summary", {}).get("turn_count", 0)),
                "privacy_finding_count": validation.get("summary", {}).get("privacy_finding_count", 0),
                "saved_pct": measure_summary.get("saved_pct", 0.0),
                "prompt_saved_pct": measure_summary.get("prompt_saved_pct", 0.0),
                "reply_saved_pct": measure_summary.get("reply_saved_pct", 0.0),
                "selected_path_prefix_count": alias_summary.get("selected_path_prefix_count", 0),
                "selected_field_value_count": alias_summary.get("selected_field_value_count", 0),
                "alias_saved_tokens_delta": impact_summary.get("saved_tokens_delta", 0),
                "alias_saved_pct_delta": impact_summary.get("saved_pct_delta", 0.0),
                "break_even_corpora": impact_summary.get("break_even_corpora"),
                "elapsed_seconds": round(time.time() - started, 4),
            },
            "stats": stats,
            "measure": measure,
            "diagnose": diagnose,
            "mine": mine,
            "aliases": aliases,
            "alias_impact": alias_impact,
            "bench": bench,
        }
    )
    if out_dir is not None:
        _write_turn_evaluation_outputs(Path(out_dir), report)
    return report


def report_turn_corpus(
    path: Path | str,
    *,
    counter: str = "heuristic",
    target_savings_pct: float = 0.0,
    limit: int = 3,
    adaptive: bool = True,
    guess_reply_fields: bool = True,
    min_count: int = 2,
    max_path_prefixes: int = 8,
    max_field_values: int = 8,
    min_saved_tokens: int = 1,
    base_aliases: AliasTable | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce a compact turn-corpus feedback report for iterative compression work."""

    started = time.time()
    source = str(Path(path))
    limit = max(1, int(limit))
    evaluation = evaluate_turn_corpus(
        path,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        guess_reply_fields=guess_reply_fields,
        min_count=min_count,
        limit=limit,
        max_path_prefixes=max_path_prefixes,
        max_field_values=max_field_values,
        min_saved_tokens=min_saved_tokens,
        base_aliases=base_aliases,
    )
    measure_summary = (evaluation.get("measure") or {}).get("summary", {})
    measure_benchmark_summary = ((evaluation.get("measure") or {}).get("benchmark") or {}).get("summary", {})
    diagnosis = evaluation.get("diagnose") or {}
    mine = evaluation.get("mine") or {}
    alias_impact = evaluation.get("alias_impact") or {}
    validation = evaluation.get("validation") or {}
    validation_summary = validation.get("summary", {})
    return {
        "schema_version": "tokensquash.turns.report.v1",
        "status": evaluation.get("status", "fail"),
        "path": source,
        "counter": counter,
        "target_savings_pct": target_savings_pct,
        "adaptive": adaptive,
        "limit": limit,
        "summary": {
            "turn_count": measure_summary.get("turn_count", validation_summary.get("turn_count", 0)),
            "original_tokens": measure_summary.get("original_tokens", 0),
            "wire_tokens": measure_benchmark_summary.get("wire_tokens", 0),
            "squashed_tokens": measure_summary.get("squashed_tokens", 0),
            "saved_tokens": measure_summary.get("saved_tokens", 0),
            "saved_pct": measure_summary.get("saved_pct", 0.0),
            "prompt_saved_pct": measure_summary.get("prompt_saved_pct", 0.0),
            "reply_saved_pct": measure_summary.get("reply_saved_pct", 0.0),
            "privacy_finding_count": validation_summary.get("privacy_finding_count", 0),
            "selected_path_prefix_count": alias_impact.get("summary", {}).get("selected_path_prefix_count", 0),
            "selected_field_value_count": alias_impact.get("summary", {}).get("selected_field_value_count", 0),
            "alias_saved_tokens_delta": alias_impact.get("summary", {}).get("saved_tokens_delta", 0),
            "alias_saved_pct_delta": alias_impact.get("summary", {}).get("saved_pct_delta", 0.0),
            "break_even_corpora": alias_impact.get("summary", {}).get("break_even_corpora"),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "top_wins": list((diagnosis.get("largest_wins", []) or [])[:limit]),
        "top_raw_wire_losses": list((diagnosis.get("largest_losses", []) or [])[:limit]),
        "top_path_candidates": list((mine.get("path_patterns", []) or [])[:limit]),
        "top_field_candidates": list((mine.get("top_candidates", []) or [])[:limit]),
        "validation": validation,
        "measure": evaluation.get("measure"),
        "diagnose": evaluation.get("diagnose"),
        "mine": evaluation.get("mine"),
        "aliases": evaluation.get("aliases"),
        "alias_impact": alias_impact,
        "bench": evaluation.get("bench"),
    }


def compare_turn_reports(base: Path | str, target: Path | str) -> dict[str, Any]:
    """Compare two saved turn report JSON files."""

    base_report = _load_turn_report(base)
    target_report = _load_turn_report(target)
    base_summary = base_report.get("summary", {})
    target_summary = target_report.get("summary", {})
    saved_pct_delta = _float_value(target_summary.get("saved_pct")) - _float_value(base_summary.get("saved_pct"))
    status = "improved" if saved_pct_delta > 0 else "regressed" if saved_pct_delta < 0 else "same"

    return {
        "schema_version": "tokensquash.turns.report.compare.v1",
        "status": status,
        "base": _turn_report_identity(base, base_report),
        "target": _turn_report_identity(target, target_report),
        "delta": {
            "turn_count": _int_value(target_summary.get("turn_count")) - _int_value(base_summary.get("turn_count")),
            "original_tokens": _int_value(target_summary.get("original_tokens")) - _int_value(base_summary.get("original_tokens")),
            "wire_tokens": _int_value(target_summary.get("wire_tokens")) - _int_value(base_summary.get("wire_tokens")),
            "squashed_tokens": _int_value(target_summary.get("squashed_tokens")) - _int_value(base_summary.get("squashed_tokens")),
            "saved_tokens": _int_value(target_summary.get("saved_tokens")) - _int_value(base_summary.get("saved_tokens")),
            "saved_pct": round(saved_pct_delta, 4),
            "prompt_saved_pct": round(
                _float_value(target_summary.get("prompt_saved_pct")) - _float_value(base_summary.get("prompt_saved_pct")),
                4,
            ),
            "reply_saved_pct": round(
                _float_value(target_summary.get("reply_saved_pct")) - _float_value(base_summary.get("reply_saved_pct")),
                4,
            ),
            "privacy_finding_count": _int_value(target_summary.get("privacy_finding_count"))
            - _int_value(base_summary.get("privacy_finding_count")),
            "selected_path_prefix_count": _int_value(target_summary.get("selected_path_prefix_count"))
            - _int_value(base_summary.get("selected_path_prefix_count")),
            "selected_field_value_count": _int_value(target_summary.get("selected_field_value_count"))
            - _int_value(base_summary.get("selected_field_value_count")),
            "alias_saved_tokens_delta": _int_value(target_summary.get("alias_saved_tokens_delta"))
            - _int_value(base_summary.get("alias_saved_tokens_delta")),
            "alias_saved_pct_delta": round(
                _float_value(target_summary.get("alias_saved_pct_delta"))
                - _float_value(base_summary.get("alias_saved_pct_delta")),
                4,
            ),
        },
    }


def format_turn_evaluate_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    break_even = summary.get("break_even_corpora")
    break_even_text = "n/a" if break_even is None else str(break_even)
    lines = [
        "# TokenSquash Turn Evaluation",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Adaptive: `{report.get('adaptive')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Prompt saved percent: `{summary.get('prompt_saved_pct', 0.0)}%`",
        f"- Reply saved percent: `{summary.get('reply_saved_pct', 0.0)}%`",
        f"- Selected path aliases: `{summary.get('selected_path_prefix_count', 0)}`",
        f"- Selected field aliases: `{summary.get('selected_field_value_count', 0)}`",
        f"- Alias saved token delta: `{summary.get('alias_saved_tokens_delta', 0)}`",
        f"- Alias saved percent delta: `{summary.get('alias_saved_pct_delta', 0.0)}%`",
        f"- Break-even corpora: `{break_even_text}`",
    ]
    outputs = report.get("outputs") or {}
    if outputs:
        lines.extend(["", "## Outputs", ""])
        for name, path in sorted(outputs.items()):
            lines.append(f"- `{name}`: `{path}`")
    validation = report.get("validation") or {}
    if validation.get("status") == "warn":
        lines.append("")
        lines.append("Validation warnings or privacy findings are present; review before sharing this corpus.")
    if report.get("status") == "fail":
        lines.append("")
        lines.append("Validation failed; fix the corpus before benchmarking.")
    return "\n".join(lines).rstrip() + "\n"


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


def format_turn_alias_impact_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    alias_report = report.get("alias_report") or {}
    selected = list(alias_report.get("selected_path_prefixes", []) or [])
    selected_fields = list(alias_report.get("selected_field_values", []) or [])
    break_even = summary.get("break_even_corpora")
    break_even_text = "n/a" if break_even is None else str(break_even)
    lines = [
        "# TokenSquash Turn Alias Impact",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Adaptive: `{report.get('adaptive')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Selected path aliases: `{summary.get('selected_path_prefix_count', 0)}`",
        f"- Selected field aliases: `{summary.get('selected_field_value_count', 0)}`",
        f"- Baseline saved percent: `{summary.get('baseline_saved_pct', 0.0)}%`",
        f"- Aliased saved percent: `{summary.get('aliased_saved_pct', 0.0)}%`",
        f"- Saved token delta: `{summary.get('saved_tokens_delta', 0)}`",
        f"- Saved percent delta: `{summary.get('saved_pct_delta', 0.0)}%`",
        f"- Raw wire token reduction: `{summary.get('wire_tokens_delta', 0)}`",
        f"- Adaptive token reduction: `{summary.get('squashed_tokens_delta', 0)}`",
        f"- Pass-through row delta: `{summary.get('pass_through_delta', 0)}`",
        f"- Alias setup tokens: `{summary.get('alias_setup_tokens', 0)}`",
        f"- Net saved after one setup: `{summary.get('net_saved_after_setup_tokens', 0)}`",
        f"- Break-even corpora: `{break_even_text}`",
        "",
        "## Selected Aliases",
        "",
    ]
    if not selected:
        lines.extend(["No custom path prefixes selected.", ""])
    else:
        lines.extend(
            [
                "| Code | Prefix | Count | Est saved |",
                "|---|---|---:|---:|",
            ]
        )
        for item in selected:
            lines.append(
                f"| `{_markdown_cell(str(item.get('code')))}` | "
                f"{_markdown_cell(str(item.get('prefix')))} | "
                f"{item.get('count')} | "
                f"{item.get('estimated_saved_tokens')} |"
            )
        lines.append("")
    lines.extend(["## Selected Field Values", ""])
    if not selected_fields:
        lines.extend(["No custom field values selected.", ""])
    else:
        lines.extend(
            [
                "| Field | Code | Count | Est saved | Value |",
                "|---|---|---:|---:|---|",
            ]
        )
        for item in selected_fields:
            lines.append(
                f"| {_markdown_cell(str(item.get('field')))} | "
                f"`{_markdown_cell(str(item.get('code')))}` | "
                f"{item.get('count')} | "
                f"{item.get('estimated_saved_tokens')} | "
                f"{_markdown_cell(str(item.get('value')))} |"
            )
        lines.append("")
    if report.get("validation", {}).get("status") == "warn":
        lines.append("Validation warnings or privacy findings are present; review before sharing this corpus.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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


def format_turn_capture_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    evaluation = report.get("evaluation") or {}
    evaluation_summary = evaluation.get("summary", {})
    lines = [
        "# TokenSquash Turn Capture",
        "",
        f"- Status: `{report.get('status')}`",
        f"- ID: `{report.get('id')}`",
        f"- Turns: `{report.get('turns', 0)}`",
        f"- Raw output: `{report.get('raw_output')}`",
        f"- Redacted output: `{report.get('redacted_output')}`",
        f"- Redactions: `{report.get('redaction_count', 0)}`",
        f"- Evaluated: `{report.get('evaluated')}`",
    ]
    if report.get("evaluated"):
        break_even = summary.get("break_even_corpora")
        break_even_text = "n/a" if break_even is None else str(break_even)
        lines.extend(
            [
                f"- Evaluation output: `{report.get('evaluation_output_dir')}`",
                f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
                f"- Prompt saved percent: `{evaluation_summary.get('prompt_saved_pct', 0.0)}%`",
                f"- Reply saved percent: `{evaluation_summary.get('reply_saved_pct', 0.0)}%`",
                f"- Alias saved token delta: `{summary.get('alias_saved_tokens_delta', 0)}`",
                f"- Break-even corpora: `{break_even_text}`",
            ]
        )
        alias_impact_summary = (evaluation.get("alias_impact") or {}).get("summary", {})
        if alias_impact_summary:
            lines.extend(
                [
                    f"- Selected path aliases: `{alias_impact_summary.get('selected_path_prefix_count', 0)}`",
                    f"- Selected field aliases: `{alias_impact_summary.get('selected_field_value_count', 0)}`",
                    f"- Alias setup tokens: `{alias_impact_summary.get('alias_setup_tokens', 0)}`",
                    f"- Net saved after one setup: `{alias_impact_summary.get('net_saved_after_setup_tokens', 0)}`",
                ]
            )
        lines.append("")
        _append_capture_preview(lines, "Top Win", (evaluation.get("diagnose") or {}).get("largest_wins", []))
        _append_capture_preview(lines, "Top Raw Wire Loss", (evaluation.get("diagnose") or {}).get("largest_losses", []))
    return "\n".join(lines).rstrip() + "\n"


def format_turn_report_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    alias_impact_summary = (report.get("alias_impact") or {}).get("summary", {})
    lines = [
        "# TokenSquash Turn Report",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Original tokens: `{summary.get('original_tokens', 0)}`",
        f"- Wire tokens: `{summary.get('wire_tokens', 0)}`",
        f"- Squashed tokens: `{summary.get('squashed_tokens', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Prompt saved percent: `{summary.get('prompt_saved_pct', 0.0)}%`",
        f"- Reply saved percent: `{summary.get('reply_saved_pct', 0.0)}%`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
        f"- Selected path aliases: `{summary.get('selected_path_prefix_count', 0)}`",
        f"- Selected field aliases: `{summary.get('selected_field_value_count', 0)}`",
        f"- Alias saved token delta: `{summary.get('alias_saved_tokens_delta', 0)}`",
        f"- Alias saved percent delta: `{summary.get('alias_saved_pct_delta', 0.0)}%`",
    ]
    break_even = summary.get("break_even_corpora")
    if break_even is not None:
        lines.append(f"- Break-even corpora: `{break_even}`")
    lines.append("")
    lines.append(f"- Baseline saved percent: `{alias_impact_summary.get('baseline_saved_pct', 0.0)}%`")
    lines.append(f"- Aliased saved percent: `{alias_impact_summary.get('aliased_saved_pct', 0.0)}%`")
    lines.append(f"- Alias setup tokens: `{alias_impact_summary.get('alias_setup_tokens', 0)}`")
    lines.append(f"- Net saved after one setup: `{alias_impact_summary.get('net_saved_after_setup_tokens', 0)}`")
    lines.append("")
    _append_capture_preview(lines, "Top Win", report.get("top_wins", []))
    _append_capture_preview(lines, "Top Raw Wire Loss", report.get("top_raw_wire_losses", []))
    _append_report_candidates(lines, "Top Repeated Path Candidates", report.get("top_path_candidates", []))
    _append_report_candidates(lines, "Top Repeated Field Candidates", report.get("top_field_candidates", []), include_field=True)
    return "\n".join(lines).rstrip() + "\n"


def format_turn_report_compare_markdown(report: dict[str, Any]) -> str:
    delta = report.get("delta", {})
    base = report.get("base", {})
    target = report.get("target", {})
    return "\n".join(
        [
            "# TokenSquash Turn Report Compare",
            "",
            f"- Status: `{report.get('status')}`",
            f"- Base report: `{base.get('report_path')}` saved=`{base.get('saved_pct')}%` tokens=`{base.get('saved_tokens')}`",
            f"- Target report: `{target.get('report_path')}` saved=`{target.get('saved_pct')}%` tokens=`{target.get('saved_tokens')}`",
            f"- Saved percent delta: `{delta.get('saved_pct')}%`",
            f"- Saved token delta: `{delta.get('saved_tokens')}`",
            f"- Prompt saved percent delta: `{delta.get('prompt_saved_pct')}%`",
            f"- Reply saved percent delta: `{delta.get('reply_saved_pct')}%`",
            f"- Alias saved token delta: `{delta.get('alias_saved_tokens_delta')}`",
            f"- Alias saved percent delta: `{delta.get('alias_saved_pct_delta')}%`",
            f"- Selected path alias delta: `{delta.get('selected_path_prefix_count')}`",
            f"- Selected field alias delta: `{delta.get('selected_field_value_count')}`",
            f"- Turn count delta: `{delta.get('turn_count')}`",
            "",
        ]
    )


def format_turn_import_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Turn Import",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Input: `{report.get('input')}`",
        f"- Imported turns: `{report.get('imported_turns', 0)}`",
        f"- Total turns: `{report.get('turns', 0)}`",
        f"- First ID: `{report.get('first_id')}`",
        f"- Last ID: `{report.get('last_id')}`",
        f"- Raw output: `{report.get('raw_output')}`",
        f"- Redacted output: `{report.get('redacted_output')}`",
        f"- Redactions: `{report.get('redaction_count', 0)}`",
        f"- Evaluated: `{report.get('evaluated')}`",
    ]
    if report.get("evaluated"):
        break_even = summary.get("break_even_corpora")
        break_even_text = "n/a" if break_even is None else str(break_even)
        lines.extend(
            [
                f"- Evaluation output: `{report.get('evaluation_output_dir')}`",
                f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
                f"- Alias saved token delta: `{summary.get('alias_saved_tokens_delta', 0)}`",
                f"- Break-even corpora: `{break_even_text}`",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _load_turn_payloads(path: Path | str) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"turn corpus not found: {source}")
    return _load_raw_payloads(source)


def _load_turn_report(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "tokensquash.turns.report.v1":
        raise ValueError(f"Not a TokenSquash turn report: {source}")
    return payload


def _turn_report_identity(path: Path | str, report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    return {
        "report_path": str(path),
        "corpus_path": report.get("path"),
        "status": report.get("status"),
        "counter": report.get("counter"),
        "adaptive": report.get("adaptive"),
        "turn_count": summary.get("turn_count"),
        "original_tokens": summary.get("original_tokens"),
        "wire_tokens": summary.get("wire_tokens"),
        "squashed_tokens": summary.get("squashed_tokens"),
        "saved_tokens": summary.get("saved_tokens"),
        "saved_pct": summary.get("saved_pct"),
        "prompt_saved_pct": summary.get("prompt_saved_pct"),
        "reply_saved_pct": summary.get("reply_saved_pct"),
        "privacy_finding_count": summary.get("privacy_finding_count"),
        "selected_path_prefix_count": summary.get("selected_path_prefix_count"),
        "selected_field_value_count": summary.get("selected_field_value_count"),
        "alias_saved_tokens_delta": summary.get("alias_saved_tokens_delta"),
        "alias_saved_pct_delta": summary.get("alias_saved_pct_delta"),
        "break_even_corpora": summary.get("break_even_corpora"),
    }


def _load_raw_payloads(source: Path) -> list[dict[str, Any]]:
    text = source.read_text(encoding="utf-8-sig")
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


def _prompt_path_records_from_turns(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in records:
        prompt = str(item.get("prompt", ""))
        paths = _unique(_normalize_path(match.group(0)) for match in _PATH_RE.finditer(prompt))[:8]
        if paths:
            rows.append(
                {
                    "id": f"{item.get('id')}:prompt",
                    "summary": "prompt paths",
                    "files": paths,
                    "text": prompt,
                }
            )
    return rows


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


def _planned_import_ids(payloads: list[dict[str, Any]], raw_target: Path) -> list[str]:
    existing = _load_raw_payloads(raw_target) if raw_target.exists() else []
    seen_ids = {str(item.get("id")) for item in existing if item.get("id") is not None}
    planned = []
    total_count = len(existing)
    for payload in payloads:
        explicit_id = payload.get("id")
        planned_id = str(explicit_id) if explicit_id is not None else f"turn-{total_count + 1:04d}"
        if planned_id in seen_ids:
            raise ValueError(f"turn id already exists: {planned_id}")
        seen_ids.add(planned_id)
        planned.append(planned_id)
        total_count += 1
    return planned


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _clean_text(str(value))
    return text or None


def _float_value(value: Any) -> float:
    return float(value or 0.0)


def _int_value(value: Any) -> int:
    return int(value or 0)


def _coerce_import_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [_clean_text(value)] if value.strip() else []
    if isinstance(value, Iterable):
        return _unique(_clean_text(str(item)) for item in value)
    return [_clean_text(str(value))]


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


def _alias_impact_delta(
    baseline: dict[str, Any],
    aliased: dict[str, Any],
    setup_tokens: int,
) -> dict[str, Any]:
    baseline_summary = baseline.get("summary", {})
    aliased_summary = aliased.get("summary", {})
    saved_tokens = int(aliased_summary.get("saved_tokens", 0)) - int(baseline_summary.get("saved_tokens", 0))
    wire_tokens = int(baseline_summary.get("wire_tokens", 0)) - int(aliased_summary.get("wire_tokens", 0))
    squashed_tokens = int(baseline_summary.get("squashed_tokens", 0)) - int(aliased_summary.get("squashed_tokens", 0))
    passthroughs = int(aliased_summary.get("passthroughs", 0)) - int(baseline_summary.get("passthroughs", 0))
    break_even = None if saved_tokens <= 0 else (setup_tokens + saved_tokens - 1) // saved_tokens
    return {
        "saved_tokens": saved_tokens,
        "saved_pct": round(float(aliased_summary.get("saved_pct", 0.0)) - float(baseline_summary.get("saved_pct", 0.0)), 4),
        "wire_tokens": wire_tokens,
        "wire_saved_pct": round(
            float(aliased_summary.get("wire_saved_pct", 0.0)) - float(baseline_summary.get("wire_saved_pct", 0.0)),
            4,
        ),
        "squashed_tokens": squashed_tokens,
        "passthroughs": passthroughs,
        "alias_setup_tokens": setup_tokens,
        "net_saved_after_setup_tokens": saved_tokens - setup_tokens,
        "break_even_corpora": break_even,
    }


def _alias_setup_tokens(alias_report: dict[str, Any], counter: str) -> int:
    selected = alias_report.get("selected_path_prefixes", []) or []
    selected_fields = alias_report.get("selected_field_values", []) or []
    path_prefixes = {
        str(item.get("prefix")): str(item.get("code"))
        for item in selected
        if item.get("prefix") and item.get("code")
    }
    field_values: dict[str, dict[str, str]] = {}
    for item in selected_fields:
        field_name = item.get("field")
        value = item.get("value")
        code = item.get("code")
        if field_name and value and code:
            field_values.setdefault(str(field_name), {})
            field_values[str(field_name)][str(value)] = str(code)
    if not path_prefixes and not field_values:
        return 0
    payload = json.dumps(AliasTable(path_prefixes, field_values).to_dict(), ensure_ascii=True, separators=(",", ":"))
    return count_tokens(payload, counter)


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


def _append_capture_preview(lines: list[str], title: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        lines.extend([f"## {title}", "", "No rows.", ""])
        return

    row = rows[0]
    lines.extend(
        [
            f"## {title}",
            "",
            f"- ID: `{row.get('id')}`",
            f"- Adaptive saved: `{row.get('saved_tokens')} ({row.get('saved_pct')}%)`",
            f"- Raw wire saved: `{row.get('wire_saved_tokens')} ({row.get('wire_saved_pct')}%)`",
            f"- Prompt: `{_side_summary(row.get('prompt', {}))}`",
            f"- Reply: `{_side_summary(row.get('reply', {}))}`",
        ]
    )
    tags = row.get("tags", [])
    if tags:
        lines.append(f"- Tags: `{', '.join(tags[:5])}`")
    lines.append("")


def _append_report_candidates(
    lines: list[str],
    title: str,
    candidates: list[dict[str, Any]],
    *,
    include_field: bool = False,
) -> None:
    if not candidates:
        lines.extend([f"## {title}", "", "No candidates.", ""])
        return

    lines.extend([f"## {title}", ""])
    if include_field:
        lines.extend(["| Field | Value | Count | Est new saved |", "|---|---|---:|---:|"])
        for item in candidates:
            lines.append(
                "| "
                f"{_markdown_cell(str(item.get('field')))} | "
                f"{_markdown_cell(str(item.get('value')))} | "
                f"{item.get('count')} | "
                f"{item.get('estimated_new_saved_tokens', 0)} |"
            )
    else:
        lines.extend(["| Pattern | Count | Est new saved |", "|---|---:|---:|"])
        for item in candidates:
            lines.append(
                "| "
                f"{_markdown_cell(str(item.get('value')))} | "
                f"{item.get('count')} | "
                f"{item.get('estimated_new_saved_tokens', 0)} |"
            )
    lines.append("")


def _side_summary(side: dict[str, Any]) -> str:
    return f"{side.get('mode')} raw {side.get('wire_saved_tokens')} saved {side.get('saved_tokens')}"


def _write_turn_evaluation_outputs(target: Path, report: dict[str, Any]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    outputs = report.setdefault("outputs", {})
    components = (
        ("validation", "validation.json"),
        ("stats", "stats.json"),
        ("measure", "measure.json"),
        ("diagnose", "diagnose.json"),
        ("mine", "mine.json"),
        ("alias_impact", "alias-impact.json"),
        ("bench", "bench.json"),
    )
    for key, filename in components:
        payload = report.get(key)
        if payload is None:
            continue
        output_path = target / filename
        _write_json_report(output_path, payload)
        outputs[key] = str(output_path)

    alias_report = report.get("aliases")
    if alias_report is not None:
        alias_report_path = target / "aliases-report.json"
        _write_json_report(alias_report_path, alias_report)
        outputs["aliases_report"] = str(alias_report_path)
        alias_table_path = target / "aliases.json"
        write_alias_table(alias_table_path, alias_report)
        outputs["alias_table"] = str(alias_table_path)

    evaluation_path = target / "evaluation.json"
    outputs["evaluation"] = str(evaluation_path)
    _write_json_report(evaluation_path, report)


def _write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _pct(part: int | float, whole: int | float) -> float:
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100.0, 4)
