from __future__ import annotations

import json
import re
import time
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable

from .aliases import AliasTable, learn_reply_aliases, write_alias_table
from .corpus import redact_text, scan_privacy
from .metrics import benchmark_prompts, benchmark_replies, count_tokens
from .mining import mine_reply_patterns
from .workspace import STARTER_PROMPT_TEXT, STARTER_REPLY_TEXT


PROMPT_KEYS = ("prompt", "input", "request", "user", "human", "text")
REPLY_KEYS = ("reply", "response", "assistant", "output", "answer")
REPLY_FIELD_KEYS = ("status", "summary", "files", "verification", "commands", "risks", "next_steps", "warnings")
TURN_CLAIM_SCHEMA_VERSION = "tokensquash.turns.claim.v1"

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


def first_run_turn_workflow(
    *,
    prompt: str,
    reply: str,
    raw_output_path: Path | str = Path("private-turns/real.jsonl"),
    redacted_output_path: Path | str = Path("private-turns/real.redacted-turns.jsonl"),
    out_dir: Path | str = Path("private-turns/first-run"),
    item_id: str | None = None,
    status: str | None = None,
    summary: str | None = None,
    files: Iterable[str] = (),
    verification: Iterable[str] = (),
    commands: Iterable[str] = (),
    risks: Iterable[str] = (),
    next_steps: Iterable[str] = (),
    counter: str = "heuristic",
    target_savings_pct: float = 0.0,
    limit: int = 5,
) -> dict[str, Any]:
    """Capture one real turn and write a beginner-friendly evidence bundle."""

    started = time.time()
    _validate_first_run_inputs(prompt, reply)
    target_dir = Path(out_dir)
    evaluation_dir = target_dir / "evaluation"
    capture = capture_turn_record(
        prompt=prompt,
        reply=reply,
        raw_output_path=raw_output_path,
        redacted_output_path=redacted_output_path,
        item_id=item_id,
        status=status,
        summary=summary,
        files=files,
        verification=verification,
        commands=commands,
        risks=risks,
        next_steps=next_steps,
        evaluate=True,
        evaluation_output_dir=evaluation_dir,
        counter=counter,
        target_savings_pct=target_savings_pct,
    )
    scorecard = score_turn_corpus(
        redacted_output_path,
        counter=counter,
        target_savings_pct=target_savings_pct,
        limit=limit,
    )

    target_dir.mkdir(parents=True, exist_ok=True)
    scorecard_json = target_dir / "scorecard.json"
    scorecard_markdown = target_dir / "scorecard.md"
    first_run_json = target_dir / "first-run.json"
    first_run_markdown = target_dir / "first-run.md"
    scorecard_json.write_text(json.dumps(scorecard, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    scorecard_markdown.write_text(format_turn_scorecard_markdown(scorecard), encoding="utf-8")

    capture_summary = capture.get("summary", {})
    scorecard_summary = scorecard.get("summary", {})
    report = {
        "schema_version": "tokensquash.turns.first_run.v1",
        "status": _first_run_status(capture, scorecard),
        "raw_output": str(Path(raw_output_path)),
        "redacted_output": str(Path(redacted_output_path)),
        "out_dir": str(target_dir),
        "counter": counter,
        "target_savings_pct": target_savings_pct,
        "id": capture.get("id"),
        "summary": {
            "turn_count": scorecard_summary.get("turn_count", capture_summary.get("turn_count", 0)),
            "redaction_count": capture_summary.get("redaction_count", 0),
            "saved_pct": scorecard_summary.get("saved_pct", 0.0),
            "prompt_saved_pct": scorecard_summary.get("prompt_saved_pct", 0.0),
            "reply_saved_pct": scorecard_summary.get("reply_saved_pct", 0.0),
            "privacy_finding_count": scorecard_summary.get("privacy_finding_count", 0),
            "milestone": scorecard_summary.get("milestone"),
            "next_milestone_turns": scorecard_summary.get("next_milestone_turns"),
            "recommendation": scorecard_summary.get("recommendation"),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "outputs": {
            "output_dir": str(target_dir),
            "first_run_json": str(first_run_json),
            "first_run_markdown": str(first_run_markdown),
            "evaluation_dir": str(evaluation_dir),
            "scorecard_json": str(scorecard_json),
            "scorecard_markdown": str(scorecard_markdown),
        },
        "commands": _first_run_next_commands(redacted_output_path, out_dir=target_dir),
        "capture": {
            "schema_version": capture.get("schema_version"),
            "status": capture.get("status"),
            "summary": capture_summary,
        },
        "scorecard": {
            "schema_version": scorecard.get("schema_version"),
            "status": scorecard.get("status"),
            "summary": scorecard_summary,
            "recommendations": scorecard.get("recommendations", []),
        },
    }
    first_run_markdown.write_text(format_turn_first_run_markdown(report), encoding="utf-8")
    first_run_json.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return report


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
    return _turn_report_from_evaluation(
        evaluation,
        source=source,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        limit=limit,
        elapsed_seconds=round(time.time() - started, 4),
    )


def score_turn_corpus(
    path: Path | str,
    *,
    counter: str = "heuristic",
    target_savings_pct: float = 0.0,
    limit: int = 5,
    adaptive: bool = True,
    guess_reply_fields: bool = True,
    min_count: int = 2,
    max_path_prefixes: int = 8,
    max_field_values: int = 8,
    min_saved_tokens: int = 1,
    base_aliases: AliasTable | dict[str, Any] | None = None,
    sidecar_review: Path | str | None = None,
    sidecar_evaluation: Path | str | None = None,
    auto_sidecar: bool = True,
) -> dict[str, Any]:
    """Summarize whether a real turn corpus is ready to expand or tune."""

    started = time.time()
    source = str(Path(path))
    capped_limit = max(1, int(limit))
    turn_report = report_turn_corpus(
        path,
        counter=counter,
        target_savings_pct=target_savings_pct,
        limit=capped_limit,
        adaptive=adaptive,
        guess_reply_fields=guess_reply_fields,
        min_count=min_count,
        max_path_prefixes=max_path_prefixes,
        max_field_values=max_field_values,
        min_saved_tokens=min_saved_tokens,
        base_aliases=base_aliases,
    )
    report_summary = turn_report.get("summary", {})
    diagnose_summary = (turn_report.get("diagnose") or {}).get("summary", {})
    milestone = _scorecard_milestone(_int_value(report_summary.get("turn_count")))
    sidecar = _scorecard_sidecar_summary(
        sidecar_review=sidecar_review,
        sidecar_evaluation=sidecar_evaluation,
        auto_sidecar=auto_sidecar,
    )
    recommendations = _scorecard_recommendations(turn_report, milestone, sidecar)
    score_status = _scorecard_status(turn_report, sidecar)
    return {
        "schema_version": "tokensquash.turns.scorecard.v1",
        "status": score_status,
        "path": source,
        "counter": counter,
        "target_savings_pct": target_savings_pct,
        "adaptive": adaptive,
        "summary": {
            "turn_count": report_summary.get("turn_count", 0),
            "milestone": milestone.get("name"),
            "next_milestone_turns": milestone.get("next_turns"),
            "original_tokens": report_summary.get("original_tokens", 0),
            "squashed_tokens": report_summary.get("squashed_tokens", 0),
            "saved_tokens": report_summary.get("saved_tokens", 0),
            "saved_pct": report_summary.get("saved_pct", 0.0),
            "prompt_saved_pct": report_summary.get("prompt_saved_pct", 0.0),
            "reply_saved_pct": report_summary.get("reply_saved_pct", 0.0),
            "pass_through_rows": diagnose_summary.get("pass_through_rows", 0),
            "raw_wire_loss_turns": diagnose_summary.get("raw_wire_loss_turns", 0),
            "privacy_finding_count": report_summary.get("privacy_finding_count", 0),
            "selected_path_prefix_count": report_summary.get("selected_path_prefix_count", 0),
            "selected_field_value_count": report_summary.get("selected_field_value_count", 0),
            "alias_saved_tokens_delta": report_summary.get("alias_saved_tokens_delta", 0),
            "break_even_corpora": report_summary.get("break_even_corpora"),
            "sidecar_status": sidecar.get("status"),
            "sidecar_pass_count": sidecar.get("pass_count", 0),
            "sidecar_watch_count": sidecar.get("watch_count", 0),
            "sidecar_fail_count": sidecar.get("fail_count", 0),
            "recommendation": recommendations[0]["code"] if recommendations else "inspect",
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "milestone": milestone,
        "sidecar": sidecar,
        "top_repeated_patterns": {
            "paths": turn_report.get("top_path_candidates", []),
            "fields": turn_report.get("top_field_candidates", []),
        },
        "turn_report": {
            "schema_version": turn_report.get("schema_version"),
            "status": turn_report.get("status"),
            "summary": report_summary,
            "top_wins": turn_report.get("top_wins", []),
            "top_raw_wire_losses": turn_report.get("top_raw_wire_losses", []),
        },
        "recommendations": recommendations,
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


def compare_turn_scorecards(base: Path | str, target: Path | str) -> dict[str, Any]:
    """Compare two saved real-corpus scorecard JSON files."""

    base_report = _load_turn_scorecard(base)
    target_report = _load_turn_scorecard(target)
    base_summary = base_report.get("summary", {})
    target_summary = target_report.get("summary", {})
    saved_pct_delta = _float_value(target_summary.get("saved_pct")) - _float_value(base_summary.get("saved_pct"))
    delta = {
        "turn_count": _int_value(target_summary.get("turn_count")) - _int_value(base_summary.get("turn_count")),
        "original_tokens": _int_value(target_summary.get("original_tokens")) - _int_value(base_summary.get("original_tokens")),
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
        "pass_through_rows": _int_value(target_summary.get("pass_through_rows"))
        - _int_value(base_summary.get("pass_through_rows")),
        "raw_wire_loss_turns": _int_value(target_summary.get("raw_wire_loss_turns"))
        - _int_value(base_summary.get("raw_wire_loss_turns")),
        "selected_path_prefix_count": _int_value(target_summary.get("selected_path_prefix_count"))
        - _int_value(base_summary.get("selected_path_prefix_count")),
        "selected_field_value_count": _int_value(target_summary.get("selected_field_value_count"))
        - _int_value(base_summary.get("selected_field_value_count")),
        "alias_saved_tokens_delta": _int_value(target_summary.get("alias_saved_tokens_delta"))
        - _int_value(base_summary.get("alias_saved_tokens_delta")),
        "break_even_corpora": _nullable_int_delta(
            target_summary.get("break_even_corpora"),
            base_summary.get("break_even_corpora"),
        ),
        "sidecar_pass_count": _int_value(target_summary.get("sidecar_pass_count"))
        - _int_value(base_summary.get("sidecar_pass_count")),
        "sidecar_watch_count": _int_value(target_summary.get("sidecar_watch_count"))
        - _int_value(base_summary.get("sidecar_watch_count")),
        "sidecar_fail_count": _int_value(target_summary.get("sidecar_fail_count"))
        - _int_value(base_summary.get("sidecar_fail_count")),
        "milestone_rank": _scorecard_milestone_rank(str(target_summary.get("milestone", "")))
        - _scorecard_milestone_rank(str(base_summary.get("milestone", ""))),
    }
    return {
        "schema_version": "tokensquash.turns.scorecard.compare.v1",
        "status": _scorecard_compare_status(target_report, delta),
        "base": _turn_scorecard_identity(base, base_report),
        "target": _turn_scorecard_identity(target, target_report),
        "delta": delta,
        "recommendations": _scorecard_compare_recommendations(target_report, delta),
    }


def build_turn_scorecard_history(scorecards: Iterable[Path | str]) -> dict[str, Any]:
    """Summarize trend history across saved turn scorecard JSON files."""

    if isinstance(scorecards, (str, Path)):
        paths = [Path(scorecards)]
    else:
        paths = [Path(path) for path in scorecards]
    if len(paths) < 2:
        raise ValueError("turn scorecard history requires at least two scorecard files")

    reports = [_load_turn_scorecard(path) for path in paths]
    entries: list[dict[str, Any]] = []
    for index, (path, report) in enumerate(zip(paths, reports), start=1):
        identity = _turn_scorecard_identity(path, report)
        identity["index"] = index
        entries.append(identity)

    steps: list[dict[str, Any]] = []
    for index in range(1, len(paths)):
        comparison = compare_turn_scorecards(paths[index - 1], paths[index])
        steps.append(
            {
                "from_index": index,
                "to_index": index + 1,
                "status": comparison.get("status"),
                "base": comparison.get("base"),
                "target": comparison.get("target"),
                "delta": comparison.get("delta", {}),
                "recommendations": comparison.get("recommendations", []),
            }
        )

    net_comparison = compare_turn_scorecards(paths[0], paths[-1])
    latest = entries[-1]
    best = max(entries, key=lambda item: _float_value(item.get("saved_pct")))
    worst = min(entries, key=lambda item: _float_value(item.get("saved_pct")))
    pass_step_count = sum(1 for step in steps if step.get("status") == "pass")
    watch_step_count = sum(1 for step in steps if step.get("status") == "watch")
    fail_step_count = sum(1 for step in steps if step.get("status") == "fail")
    pass_scorecard_count = sum(1 for entry in entries if entry.get("status") == "pass")
    watch_scorecard_count = sum(1 for entry in entries if entry.get("status") in {"watch", "warn"})
    fail_scorecard_count = sum(1 for entry in entries if entry.get("status") == "fail")
    saved_pct_drop_from_best = round(
        _float_value(latest.get("saved_pct")) - _float_value(best.get("saved_pct")),
        4,
    )
    warnings: list[str] = []
    if latest.get("status") == "fail":
        warnings.append("latest scorecard is failing")
    elif latest.get("status") in {"watch", "warn"}:
        warnings.append(f"latest scorecard is {latest.get('status')}")
    if fail_step_count:
        warnings.append(f"history contains {fail_step_count} adjacent failing comparison(s)")
    if watch_step_count:
        warnings.append(f"history contains {watch_step_count} adjacent watch comparison(s)")
    if saved_pct_drop_from_best < 0:
        warnings.append(f"latest saved_pct is {abs(saved_pct_drop_from_best)}% below best observed")

    return {
        "schema_version": "tokensquash.turns.scorecard.history.v1",
        "status": _scorecard_history_status(latest, fail_step_count, watch_step_count),
        "summary": {
            "scorecard_count": len(entries),
            "first_scorecard_path": entries[0].get("scorecard_path"),
            "latest_scorecard_path": latest.get("scorecard_path"),
            "first_status": entries[0].get("status"),
            "latest_status": latest.get("status"),
            "first_milestone": entries[0].get("milestone"),
            "latest_milestone": latest.get("milestone"),
            "first_turn_count": entries[0].get("turn_count"),
            "latest_turn_count": latest.get("turn_count"),
            "turn_count_delta": (net_comparison.get("delta") or {}).get("turn_count"),
            "first_saved_pct": entries[0].get("saved_pct"),
            "latest_saved_pct": latest.get("saved_pct"),
            "saved_pct_delta": (net_comparison.get("delta") or {}).get("saved_pct"),
            "first_saved_tokens": entries[0].get("saved_tokens"),
            "latest_saved_tokens": latest.get("saved_tokens"),
            "saved_tokens_delta": (net_comparison.get("delta") or {}).get("saved_tokens"),
            "privacy_finding_delta": (net_comparison.get("delta") or {}).get("privacy_finding_count"),
            "raw_wire_loss_turn_delta": (net_comparison.get("delta") or {}).get("raw_wire_loss_turns"),
            "pass_through_row_delta": (net_comparison.get("delta") or {}).get("pass_through_rows"),
            "sidecar_pass_delta": (net_comparison.get("delta") or {}).get("sidecar_pass_count"),
            "sidecar_watch_delta": (net_comparison.get("delta") or {}).get("sidecar_watch_count"),
            "sidecar_fail_delta": (net_comparison.get("delta") or {}).get("sidecar_fail_count"),
            "milestone_rank_delta": (net_comparison.get("delta") or {}).get("milestone_rank"),
            "pass_scorecard_count": pass_scorecard_count,
            "watch_scorecard_count": watch_scorecard_count,
            "fail_scorecard_count": fail_scorecard_count,
            "pass_step_count": pass_step_count,
            "watch_step_count": watch_step_count,
            "fail_step_count": fail_step_count,
            "best_saved_pct": best.get("saved_pct"),
            "best_scorecard_path": best.get("scorecard_path"),
            "worst_saved_pct": worst.get("saved_pct"),
            "worst_scorecard_path": worst.get("scorecard_path"),
            "saved_pct_drop_from_best": saved_pct_drop_from_best,
        },
        "scorecards": entries,
        "steps": steps,
        "net": net_comparison,
        "warnings": warnings,
    }


def write_turn_scorecard_pack(
    path: Path | str,
    *,
    out_dir: Path | str,
    counter: str = "heuristic",
    target_savings_pct: float = 0.0,
    limit: int = 5,
    adaptive: bool = True,
    guess_reply_fields: bool = True,
    min_count: int = 2,
    max_path_prefixes: int = 8,
    max_field_values: int = 8,
    min_saved_tokens: int = 1,
    base_aliases: AliasTable | dict[str, Any] | None = None,
    sidecar_review: Path | str | None = None,
    sidecar_evaluation: Path | str | None = None,
    auto_sidecar: bool = True,
    history_scorecards: Iterable[Path | str] | None = None,
) -> dict[str, Any]:
    """Write a reusable scorecard evidence pack for a real turn corpus."""

    started = time.time()
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    scorecard = score_turn_corpus(
        path,
        counter=counter,
        target_savings_pct=target_savings_pct,
        limit=limit,
        adaptive=adaptive,
        guess_reply_fields=guess_reply_fields,
        min_count=min_count,
        max_path_prefixes=max_path_prefixes,
        max_field_values=max_field_values,
        min_saved_tokens=min_saved_tokens,
        base_aliases=base_aliases,
        sidecar_review=sidecar_review,
        sidecar_evaluation=sidecar_evaluation,
        auto_sidecar=auto_sidecar,
    )
    scorecard_json = target_dir / "scorecard.json"
    scorecard_markdown = target_dir / "scorecard.md"
    scorecard_json.write_text(json.dumps(scorecard, indent=2) + "\n", encoding="utf-8")
    scorecard_markdown.write_text(format_turn_scorecard_markdown(scorecard), encoding="utf-8")

    history_report: dict[str, Any] | None = None
    history_json: Path | None = None
    history_markdown: Path | None = None
    history_inputs = [Path(item) for item in history_scorecards or []]
    if history_inputs:
        history_json = target_dir / "history.json"
        history_markdown = target_dir / "history.md"
        history_report = build_turn_scorecard_history([*history_inputs, scorecard_json])
        history_json.write_text(json.dumps(history_report, indent=2) + "\n", encoding="utf-8")
        history_markdown.write_text(format_turn_scorecard_history_markdown(history_report), encoding="utf-8")

    pack_status = _scorecard_pack_status(scorecard, history_report)
    outputs = {
        "output_dir": str(target_dir),
        "scorecard_json": str(scorecard_json),
        "scorecard_markdown": str(scorecard_markdown),
    }
    if history_json and history_markdown:
        outputs["history_json"] = str(history_json)
        outputs["history_markdown"] = str(history_markdown)
    return {
        "schema_version": "tokensquash.turns.scorecard.pack.v1",
        "status": pack_status,
        "path": str(Path(path)),
        "counter": counter,
        "target_savings_pct": target_savings_pct,
        "adaptive": adaptive,
        "summary": {
            "scorecard_status": scorecard.get("status"),
            "history_status": history_report.get("status") if history_report else None,
            "history_included": history_report is not None,
            "history_input_count": len(history_inputs),
            "artifact_count": len(outputs) - 1,
            "turn_count": (scorecard.get("summary") or {}).get("turn_count", 0),
            "milestone": (scorecard.get("summary") or {}).get("milestone"),
            "saved_pct": (scorecard.get("summary") or {}).get("saved_pct", 0.0),
            "privacy_finding_count": (scorecard.get("summary") or {}).get("privacy_finding_count", 0),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "outputs": outputs,
        "scorecard": {
            "schema_version": scorecard.get("schema_version"),
            "status": scorecard.get("status"),
            "summary": scorecard.get("summary", {}),
        },
        "history": (
            {
                "schema_version": history_report.get("schema_version"),
                "status": history_report.get("status"),
                "summary": history_report.get("summary", {}),
            }
            if history_report
            else None
        ),
    }


def compare_turn_certifications(base: Path | str, target: Path | str) -> dict[str, Any]:
    """Compare two saved turn certification JSON files."""

    base_report = _load_turn_certification(base)
    target_report = _load_turn_certification(target)
    base_summary = base_report.get("summary", {})
    target_summary = target_report.get("summary", {})
    saved_pct_delta = _float_value(target_summary.get("saved_pct")) - _float_value(base_summary.get("saved_pct"))
    failed_check_delta = _int_value(target_summary.get("failed_check_count")) - _int_value(
        base_summary.get("failed_check_count")
    )
    if target_report.get("status") != "pass" or _int_value(target_summary.get("failed_check_count")) > 0:
        status = "failed"
    elif failed_check_delta < 0:
        status = "improved"
    elif failed_check_delta > 0:
        status = "regressed"
    elif saved_pct_delta > 0:
        status = "improved"
    elif saved_pct_delta < 0:
        status = "regressed"
    else:
        status = "same"

    return {
        "schema_version": "tokensquash.turns.certify.compare.v1",
        "status": status,
        "base": _turn_certification_identity(base, base_report),
        "target": _turn_certification_identity(target, target_report),
        "delta": {
            "turn_count": _int_value(target_summary.get("turn_count")) - _int_value(base_summary.get("turn_count")),
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
            "pass_through_rows": _int_value(target_summary.get("pass_through_rows"))
            - _int_value(base_summary.get("pass_through_rows")),
            "raw_wire_loss_turns": _int_value(target_summary.get("raw_wire_loss_turns"))
            - _int_value(base_summary.get("raw_wire_loss_turns")),
            "failed_check_count": failed_check_delta,
            "suggestion_count": _int_value(target_summary.get("suggestion_count"))
            - _int_value(base_summary.get("suggestion_count")),
        },
    }


def build_turn_certification_history(certifications: Iterable[Path | str]) -> dict[str, Any]:
    """Summarize trend history across saved turn certification JSON files."""

    if isinstance(certifications, (str, Path)):
        paths = [Path(certifications)]
    else:
        paths = [Path(path) for path in certifications]
    if len(paths) < 2:
        raise ValueError("turn certification history requires at least two certification files")

    reports = [_load_turn_certification(path) for path in paths]
    entries: list[dict[str, Any]] = []
    for index, (path, report) in enumerate(zip(paths, reports), start=1):
        identity = _turn_certification_identity(path, report)
        identity["index"] = index
        entries.append(identity)

    steps: list[dict[str, Any]] = []
    for index in range(1, len(paths)):
        comparison = compare_turn_certifications(paths[index - 1], paths[index])
        steps.append(
            {
                "from_index": index,
                "to_index": index + 1,
                "status": comparison.get("status"),
                "base": comparison.get("base"),
                "target": comparison.get("target"),
                "delta": comparison.get("delta", {}),
            }
        )

    net_comparison = compare_turn_certifications(paths[0], paths[-1])
    latest = entries[-1]
    best = max(entries, key=lambda item: _float_value(item.get("saved_pct")))
    worst = min(entries, key=lambda item: _float_value(item.get("saved_pct")))
    latest_failed = _turn_certification_failed(latest)
    failed_count = sum(1 for entry in entries if _turn_certification_failed(entry))
    improved_step_count = sum(1 for step in steps if step.get("status") == "improved")
    regressed_step_count = sum(1 for step in steps if step.get("status") == "regressed")
    failed_step_count = sum(1 for step in steps if step.get("status") == "failed")
    same_step_count = sum(1 for step in steps if step.get("status") == "same")

    if latest_failed:
        status = "failed"
    elif failed_step_count or (improved_step_count and regressed_step_count):
        status = "mixed"
    elif regressed_step_count:
        status = "regressed"
    elif improved_step_count:
        status = "improved"
    else:
        status = "same"

    saved_pct_drop_from_best = round(
        _float_value(latest.get("saved_pct")) - _float_value(best.get("saved_pct")),
        4,
    )
    warnings: list[str] = []
    if latest_failed:
        warnings.append("latest certification is failing")
    elif failed_count:
        warnings.append(f"history contains {failed_count} failing certification(s)")
    if regressed_step_count:
        warnings.append(f"history contains {regressed_step_count} adjacent regression(s)")
    if saved_pct_drop_from_best < 0:
        warnings.append(f"latest saved_pct is {abs(saved_pct_drop_from_best)}% below best observed")

    return {
        "schema_version": "tokensquash.turns.certify.history.v1",
        "status": status,
        "summary": {
            "certification_count": len(entries),
            "first_certification_path": entries[0].get("certification_path"),
            "latest_certification_path": latest.get("certification_path"),
            "first_saved_pct": entries[0].get("saved_pct"),
            "latest_saved_pct": latest.get("saved_pct"),
            "saved_pct_delta": (net_comparison.get("delta") or {}).get("saved_pct"),
            "first_saved_tokens": entries[0].get("saved_tokens"),
            "latest_saved_tokens": latest.get("saved_tokens"),
            "saved_tokens_delta": (net_comparison.get("delta") or {}).get("saved_tokens"),
            "first_failed_check_count": entries[0].get("failed_check_count"),
            "latest_failed_check_count": latest.get("failed_check_count"),
            "failed_check_delta": (net_comparison.get("delta") or {}).get("failed_check_count"),
            "failed_certification_count": failed_count,
            "improved_step_count": improved_step_count,
            "regressed_step_count": regressed_step_count,
            "failed_step_count": failed_step_count,
            "same_step_count": same_step_count,
            "best_saved_pct": best.get("saved_pct"),
            "best_certification_path": best.get("certification_path"),
            "worst_saved_pct": worst.get("saved_pct"),
            "worst_certification_path": worst.get("certification_path"),
            "saved_pct_drop_from_best": saved_pct_drop_from_best,
        },
        "certifications": entries,
        "steps": steps,
        "net": net_comparison,
        "warnings": warnings,
    }


def gate_turn_report(
    report_path: Path | str,
    *,
    min_saved_pct: float = 0.5,
    max_privacy_findings: int = 0,
    max_pass_through_rows: int = 0,
    max_raw_wire_loss_turns: int = 0,
) -> dict[str, Any]:
    """Apply pass/fail quality thresholds to a saved turn report or evaluation."""

    source_report, input_type, input_schema = _load_turn_gate_report(report_path)
    return _gate_turn_report_payload(
        source_report,
        source=str(Path(report_path)),
        input_type=input_type,
        input_schema=input_schema,
        min_saved_pct=min_saved_pct,
        max_privacy_findings=max_privacy_findings,
        max_pass_through_rows=max_pass_through_rows,
        max_raw_wire_loss_turns=max_raw_wire_loss_turns,
    )


def certify_turn_corpus(
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
    min_saved_pct: float = 0.5,
    max_privacy_findings: int = 0,
    max_pass_through_rows: int = 0,
    max_raw_wire_loss_turns: int = 0,
    suggestion_limit: int = 5,
    suggestion_min_saved_tokens: int = 1,
) -> dict[str, Any]:
    """Build an evaluation, gate, and suggestions pack for one turn corpus."""

    started = time.time()
    source = str(Path(path))
    capped_limit = max(1, int(limit))
    evaluation = evaluate_turn_corpus(
        path,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        guess_reply_fields=guess_reply_fields,
        min_count=min_count,
        limit=capped_limit,
        max_path_prefixes=max_path_prefixes,
        max_field_values=max_field_values,
        min_saved_tokens=min_saved_tokens,
        base_aliases=base_aliases,
    )
    report = _turn_report_from_evaluation(
        evaluation,
        source=source,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        limit=capped_limit,
        elapsed_seconds=round(time.time() - started, 4),
    )
    gate = _gate_turn_report_payload(
        report,
        source="report.json",
        input_type="report",
        input_schema="tokensquash.turns.report.v1",
        min_saved_pct=min_saved_pct,
        max_privacy_findings=max_privacy_findings,
        max_pass_through_rows=max_pass_through_rows,
        max_raw_wire_loss_turns=max_raw_wire_loss_turns,
    )
    suggestions = _suggest_turn_improvements_from_report(
        report,
        report_path="report.json",
        limit=suggestion_limit,
        min_saved_tokens=suggestion_min_saved_tokens,
    )
    gate_summary = gate.get("summary", {})
    suggestions_summary = suggestions.get("summary", {})
    status = "pass" if gate.get("status") == "pass" else "fail"
    return {
        "schema_version": "tokensquash.turns.certify.v1",
        "status": status,
        "path": source,
        "counter": counter,
        "adaptive": adaptive,
        "target_savings_pct": target_savings_pct,
        "parameters": {
            "min_count": max(1, int(min_count)),
            "limit": capped_limit,
            "max_path_prefixes": max(0, int(max_path_prefixes)),
            "max_field_values": max(0, int(max_field_values)),
            "min_saved_tokens": max(0, int(min_saved_tokens)),
            "suggestion_limit": max(1, int(suggestion_limit)),
            "suggestion_min_saved_tokens": max(0, int(suggestion_min_saved_tokens)),
        },
        "thresholds": gate.get("thresholds", {}),
        "summary": {
            "status": status,
            "passed": status == "pass",
            "turn_count": gate_summary.get("turn_count", 0),
            "saved_tokens": gate_summary.get("saved_tokens", 0),
            "saved_pct": gate_summary.get("saved_pct", 0.0),
            "prompt_saved_pct": gate_summary.get("prompt_saved_pct", 0.0),
            "reply_saved_pct": gate_summary.get("reply_saved_pct", 0.0),
            "privacy_finding_count": gate_summary.get("privacy_finding_count", 0),
            "pass_through_rows": gate_summary.get("pass_through_rows", 0),
            "raw_wire_loss_turns": gate_summary.get("raw_wire_loss_turns", 0),
            "failed_check_count": gate_summary.get("failed_check_count", 0),
            "suggestion_count": suggestions_summary.get("suggestion_count", 0),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "artifacts": {
            "evaluation": evaluation,
            "report": report,
            "gate": gate,
            "suggestions": suggestions,
        },
    }


def suggest_turn_improvements(
    report_path: Path | str,
    *,
    limit: int = 5,
    min_saved_tokens: int = 1,
) -> dict[str, Any]:
    """Rank concrete next improvement ideas from a saved turn report."""

    source_report = _load_turn_report(report_path)
    return _suggest_turn_improvements_from_report(
        source_report,
        report_path=report_path,
        limit=limit,
        min_saved_tokens=min_saved_tokens,
    )


def build_turn_claim(
    evidence_path: Path | str,
    *,
    corpus_label: str | None = None,
    evidence_label: str | None = None,
    command: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Build a public-safe claim block from saved turn or sidecar evidence."""

    source = _resolve_claim_evidence_path(Path(evidence_path))
    payload = _load_json_object(source)
    schema = str(payload.get("schema_version", ""))
    if schema.startswith("tokensquash.sidecar."):
        normalized = _normalize_sidecar_claim_source(payload, source)
        scope = "experimental_sidecar"
    else:
        normalized = _normalize_turn_claim_source(payload, source)
        scope = "deterministic_turns"

    product_version = version or _claim_package_version(Path.cwd())
    if product_version and not str(product_version).startswith("v"):
        product_version_text = f"v{product_version}"
    else:
        product_version_text = str(product_version or "unknown")
    corpus = corpus_label or normalized["corpus"] or "the measured corpus"
    evidence = evidence_label or str(source)
    limitations = _claim_limitations(normalized, scope=scope)
    status, classification = _claim_status(normalized, scope=scope)
    claim_text = _claim_text(
        normalized,
        corpus=corpus,
        evidence=evidence,
        product_version=product_version_text,
        scope=scope,
    )
    short_claim = _short_claim(
        normalized,
        corpus=corpus,
        product_version=product_version_text,
        scope=scope,
    )

    return {
        "schema_version": TURN_CLAIM_SCHEMA_VERSION,
        "status": status,
        "classification": classification,
        "scope": scope,
        "evidence": {
            "path": str(source),
            "label": evidence,
            "schema_version": schema,
            "input_type": normalized["input_type"],
            "source_status": normalized["source_status"],
            "command": command,
        },
        "metrics": {
            "corpus": corpus,
            "source_corpus": normalized["corpus"],
            "counter": normalized["counter"],
            "version": product_version_text,
            "turn_count": normalized["turn_count"],
            "original_tokens": normalized["original_tokens"],
            "compact_tokens": normalized["compact_tokens"],
            "saved_tokens": normalized["saved_tokens"],
            "saved_pct": normalized["saved_pct"],
            "pass_through_rows": normalized["pass_through_rows"],
            "raw_wire_loss_turns": normalized["raw_wire_loss_turns"],
            "warning_count": normalized["warning_count"],
            "privacy_finding_count": normalized["privacy_finding_count"],
            "failed_check_count": normalized["failed_check_count"],
            "gate_status": normalized["gate_status"],
            "review_status": normalized["review_status"],
            "review_count": normalized["review_count"],
            "high_risk_count": normalized["high_risk_count"],
            "medium_risk_count": normalized["medium_risk_count"],
            "loss_items": normalized["loss_items"],
        },
        "claim": {
            "short": short_claim,
            "text": claim_text,
            "limitations": limitations,
        },
    }


def write_turn_claim_pack(
    evidence_path: Path | str,
    out_dir: Path | str,
    *,
    corpus_label: str | None = None,
    evidence_label: str | None = None,
    command: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Write all public-safe claim views for saved evidence."""

    claim = build_turn_claim(
        evidence_path,
        corpus_label=corpus_label,
        evidence_label=evidence_label,
        command=command,
        version=version,
    )
    return write_turn_claim_outputs(out_dir, claim)


def _suggest_turn_improvements_from_report(
    source_report: dict[str, Any],
    *,
    report_path: Path | str,
    limit: int,
    min_saved_tokens: int,
) -> dict[str, Any]:
    summary = source_report.get("summary", {})
    limit = max(1, int(limit))
    min_saved_tokens = max(0, int(min_saved_tokens))
    candidates = []

    alias_saved_tokens = _int_value(summary.get("alias_saved_tokens_delta"))
    selected_aliases = _int_value(summary.get("selected_path_prefix_count")) + _int_value(
        summary.get("selected_field_value_count")
    )
    if alias_saved_tokens > 0 and selected_aliases > 0:
        candidates.append(
            _turn_suggestion(
                "alias_impact",
                "Use the learned alias table for this corpus",
                "The report's alias-impact run found net token savings from selected path/field aliases.",
                "Run `turns aliases` to write a session alias table, then benchmark with `--aliases`.",
                priority=alias_saved_tokens,
                estimated_saved_tokens=alias_saved_tokens,
                evidence={
                    "selected_path_prefix_count": summary.get("selected_path_prefix_count", 0),
                    "selected_field_value_count": summary.get("selected_field_value_count", 0),
                    "alias_saved_pct_delta": summary.get("alias_saved_pct_delta", 0.0),
                    "break_even_corpora": summary.get("break_even_corpora"),
                },
            )
        )

    for item in source_report.get("top_path_candidates", []) or []:
        estimated = _int_value(item.get("estimated_new_saved_tokens"))
        if estimated < min_saved_tokens:
            continue
        value = str(item.get("value", ""))
        candidates.append(
            _turn_suggestion(
                "path_alias_candidate",
                f"Add or keep a compact alias for `{value}`",
                "This repeated path/prefix appears often enough to be worth compacting.",
                "Promote the prefix into a session alias or built-in alias only if it recurs across real turns.",
                priority=estimated,
                estimated_saved_tokens=estimated,
                evidence={
                    "value": value,
                    "count": item.get("count", 0),
                    "existing_code": item.get("existing_code"),
                },
            )
        )

    for item in source_report.get("top_field_candidates", []) or []:
        estimated = _int_value(item.get("estimated_new_saved_tokens"))
        if estimated < min_saved_tokens:
            continue
        field = str(item.get("field", ""))
        value = str(item.get("value", ""))
        candidates.append(
            _turn_suggestion(
                "field_alias_candidate",
                f"Alias repeated `{field}` value `{value}`",
                "This repeated reply field value is a candidate for a compact field alias.",
                "Add it to a session alias table first; only make it built-in if it appears across projects.",
                priority=estimated,
                estimated_saved_tokens=estimated,
                evidence={
                    "field": field,
                    "value": value,
                    "count": item.get("count", 0),
                    "existing_code": item.get("existing_code"),
                },
            )
        )

    for row in source_report.get("top_raw_wire_losses", []) or []:
        raw_saved_tokens = _int_value(row.get("wire_saved_tokens"))
        loss_tokens = abs(raw_saved_tokens) if raw_saved_tokens < 0 else 0
        if loss_tokens < min_saved_tokens:
            continue
        candidates.append(
            _turn_suggestion(
                "raw_wire_loss",
                f"Inspect raw-wire loss `{row.get('id')}`",
                "The raw compact wire is longer than the original before adaptive passthrough protects the result.",
                "Look for repeated wording or missing aliases before adding a codec rule for this shape.",
                priority=loss_tokens,
                estimated_saved_tokens=loss_tokens,
                evidence={
                    "id": row.get("id"),
                    "wire_saved_tokens": row.get("wire_saved_tokens"),
                    "saved_tokens": row.get("saved_tokens"),
                    "tags": row.get("tags", []),
                    "prompt_preview": row.get("prompt_preview"),
                    "reply_preview": row.get("reply_preview"),
                },
            )
        )

    privacy_findings = _int_value(summary.get("privacy_finding_count"))
    if privacy_findings:
        candidates.append(
            _turn_suggestion(
                "privacy_review",
                "Review privacy findings before sharing this corpus",
                "The report still has privacy findings; token metrics are useful locally but the corpus needs review before sharing.",
                "Inspect `turns validate` output and keep raw data under ignored private storage.",
                priority=0,
                estimated_saved_tokens=0,
                evidence={"privacy_finding_count": privacy_findings},
            )
        )

    candidates.sort(key=lambda item: (-_int_value(item.get("priority")), str(item.get("type")), str(item.get("title"))))
    suggestions = candidates[:limit]
    for index, item in enumerate(suggestions, start=1):
        item["rank"] = index

    return {
        "schema_version": "tokensquash.turns.suggestions.v1",
        "status": "pass" if suggestions else "empty",
        "report": _turn_report_identity(report_path, source_report),
        "limit": limit,
        "min_saved_tokens": min_saved_tokens,
        "summary": {
            "suggestion_count": len(suggestions),
            "candidate_count": len(candidates),
            "report_saved_pct": summary.get("saved_pct", 0.0),
            "report_saved_tokens": summary.get("saved_tokens", 0),
            "privacy_finding_count": privacy_findings,
        },
        "suggestions": suggestions,
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


def format_turn_first_run_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs") or {}
    commands = report.get("commands") or {}
    scorecard = report.get("scorecard") or {}
    lines = [
        "# TokenSquash First Run",
        "",
        f"- Status: `{report.get('status')}`",
        f"- ID: `{report.get('id')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Raw output: `{report.get('raw_output')}`",
        f"- Redacted output: `{report.get('redacted_output')}`",
        f"- Redactions: `{summary.get('redaction_count', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Prompt saved percent: `{summary.get('prompt_saved_pct', 0.0)}%`",
        f"- Reply saved percent: `{summary.get('reply_saved_pct', 0.0)}%`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
        f"- Milestone: `{summary.get('milestone')}`",
        f"- Next milestone turns: `{summary.get('next_milestone_turns')}`",
        f"- Recommendation: `{summary.get('recommendation')}`",
    ]

    recommendations = scorecard.get("recommendations") or []
    if recommendations:
        lines.extend(["", "## What This Means", ""])
        for item in recommendations[:5]:
            lines.append(f"- `{item.get('code')}`: {item.get('message')}")

    if commands:
        lines.extend(["", "## Next Commands", ""])
        for label, command in commands.items():
            lines.append(f"- `{label}`: `{command}`")

    if outputs:
        lines.extend(["", "## Outputs", ""])
        for label, path in sorted(outputs.items()):
            lines.append(f"- `{label}`: `{path}`")
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


def format_turn_claim_markdown(report: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    evidence = report.get("evidence", {})
    claim = report.get("claim", {})
    lines = [
        "# TokenSquash Claim",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Classification: `{report.get('classification')}`",
        f"- Scope: `{report.get('scope')}`",
        f"- Evidence: `{evidence.get('label')}`",
        f"- Evidence schema: `{evidence.get('schema_version')}`",
        f"- Input type: `{evidence.get('input_type')}`",
        f"- Source status: `{evidence.get('source_status')}`",
        f"- Corpus: `{metrics.get('corpus')}`",
        f"- Counter: `{metrics.get('counter')}`",
        f"- Version: `{metrics.get('version')}`",
        f"- Turns/items: `{metrics.get('turn_count', 0)}`",
        f"- Original tokens: `{metrics.get('original_tokens', 0)}`",
        f"- Compact tokens: `{metrics.get('compact_tokens', 0)}`",
        f"- Saved tokens: `{metrics.get('saved_tokens', 0)}`",
        f"- Saved percent: `{metrics.get('saved_pct', 0.0)}%`",
        f"- Pass-through rows: `{metrics.get('pass_through_rows', 0)}`",
        f"- Raw wire loss turns: `{metrics.get('raw_wire_loss_turns', 0)}`",
        f"- Warnings: `{metrics.get('warning_count', 0)}`",
        f"- Privacy findings: `{metrics.get('privacy_finding_count', 0)}`",
        f"- Failed checks: `{metrics.get('failed_check_count', 0)}`",
        f"- Gate status: `{metrics.get('gate_status') or 'n/a'}`",
        f"- Review status: `{metrics.get('review_status') or 'n/a'}`",
    ]
    command = evidence.get("command")
    if command:
        lines.append(f"- Command: `{_markdown_cell(str(command))}`")
    lines.extend(["", "## Claim", "", str(claim.get("text", "")).strip(), ""])
    limitations = claim.get("limitations") or []
    lines.extend(["## Known Limits", ""])
    if not limitations:
        lines.append("No known limits were reported by the claim generator.")
    else:
        for item in limitations:
            lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_claim_text(report: dict[str, Any]) -> str:
    return str((report.get("claim") or {}).get("text", "")).strip() + "\n"


def format_turn_claim_limits_markdown(report: dict[str, Any]) -> str:
    limitations = (report.get("claim") or {}).get("limitations") or []
    if not limitations:
        return "No known limits were reported by the claim generator.\n"
    return "\n".join(f"- {item}" for item in limitations) + "\n"


def format_turn_scorecard_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    milestone = report.get("milestone", {})
    sidecar = report.get("sidecar", {})
    patterns = report.get("top_repeated_patterns", {})
    lines = [
        "# TokenSquash Turn Scorecard",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Milestone: `{summary.get('milestone')}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Prompt saved percent: `{summary.get('prompt_saved_pct', 0.0)}%`",
        f"- Reply saved percent: `{summary.get('reply_saved_pct', 0.0)}%`",
        f"- Pass-through rows: `{summary.get('pass_through_rows', 0)}`",
        f"- Raw wire loss turns: `{summary.get('raw_wire_loss_turns', 0)}`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
        f"- Sidecar status: `{summary.get('sidecar_status')}`",
        f"- Recommendation: `{summary.get('recommendation')}`",
        "",
        "## Corpus Milestone",
        "",
        f"- Name: `{milestone.get('name')}`",
        f"- Label: `{milestone.get('label')}`",
        f"- Minimum turns: `{milestone.get('minimum_turns')}`",
        f"- Next milestone turns: `{milestone.get('next_turns')}`",
        f"- Message: {milestone.get('message')}",
        "",
        "## Sidecar Meaning",
        "",
        f"- Source: `{sidecar.get('source')}`",
        f"- Input type: `{sidecar.get('input_type')}`",
        f"- Pass: `{sidecar.get('pass_count', 0)}`",
        f"- Watch: `{sidecar.get('watch_count', 0)}`",
        f"- Fail: `{sidecar.get('fail_count', 0)}`",
        f"- Review rows: `{sidecar.get('review_count', 0)}`",
        f"- Warnings: `{sidecar.get('warning_count', 0)}`",
    ]
    flag_counts = sidecar.get("flag_counts", {})
    if flag_counts:
        lines.extend(["", "### Sidecar Flags", ""])
        for flag, count in sorted(flag_counts.items(), key=lambda item: (-int(item[1]), item[0])):
            lines.append(f"- `{flag}`: `{count}`")
    lines.append("")

    _append_scorecard_candidates(lines, "Repeated Path Candidates", patterns.get("paths", []))
    _append_scorecard_candidates(lines, "Repeated Field Candidates", patterns.get("fields", []), include_field=True)

    recommendations = report.get("recommendations", [])
    lines.extend(["## Recommendations", ""])
    if not recommendations:
        lines.extend(["No recommendations.", ""])
    else:
        for item in recommendations:
            lines.append(f"- `{item.get('code')}`: {item.get('message')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_scorecard_compare_markdown(report: dict[str, Any]) -> str:
    delta = report.get("delta", {})
    base = report.get("base", {})
    target = report.get("target", {})
    lines = [
        "# TokenSquash Turn Scorecard Compare",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Base scorecard: `{base.get('scorecard_path')}` saved=`{base.get('saved_pct')}%` milestone=`{base.get('milestone')}`",
        f"- Target scorecard: `{target.get('scorecard_path')}` saved=`{target.get('saved_pct')}%` milestone=`{target.get('milestone')}`",
        f"- Saved percent delta: `{delta.get('saved_pct')}%`",
        f"- Saved token delta: `{delta.get('saved_tokens')}`",
        f"- Turn count delta: `{delta.get('turn_count')}`",
        f"- Privacy finding delta: `{delta.get('privacy_finding_count')}`",
        f"- Sidecar fail delta: `{delta.get('sidecar_fail_count')}`",
        "",
        "## Delta Table",
        "",
        "| Metric | Delta |",
        "|---|---:|",
    ]
    for key in (
        "turn_count",
        "milestone_rank",
        "original_tokens",
        "squashed_tokens",
        "saved_tokens",
        "saved_pct",
        "prompt_saved_pct",
        "reply_saved_pct",
        "privacy_finding_count",
        "pass_through_rows",
        "raw_wire_loss_turns",
        "selected_path_prefix_count",
        "selected_field_value_count",
        "alias_saved_tokens_delta",
        "break_even_corpora",
        "sidecar_pass_count",
        "sidecar_watch_count",
        "sidecar_fail_count",
    ):
        value = delta.get(key)
        suffix = "%" if key.endswith("_pct") else ""
        rendered = "n/a" if value is None else f"{value}{suffix}"
        lines.append(f"| `{key}` | `{rendered}` |")
    recommendations = report.get("recommendations", [])
    lines.extend(["", "## Recommendations", ""])
    if not recommendations:
        lines.append("No recommendations.")
    else:
        for item in recommendations:
            lines.append(f"- `{item.get('code')}`: {item.get('message')}")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_scorecard_history_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Turn Scorecard History",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Scorecards: `{summary.get('scorecard_count', 0)}`",
        f"- First: `{summary.get('first_scorecard_path')}` saved=`{summary.get('first_saved_pct')}%` milestone=`{summary.get('first_milestone')}`",
        f"- Latest: `{summary.get('latest_scorecard_path')}` saved=`{summary.get('latest_saved_pct')}%` milestone=`{summary.get('latest_milestone')}`",
        f"- Net saved percent delta: `{summary.get('saved_pct_delta')}%`",
        f"- Net saved token delta: `{summary.get('saved_tokens_delta')}`",
        f"- Net turn count delta: `{summary.get('turn_count_delta')}`",
        f"- Net privacy finding delta: `{summary.get('privacy_finding_delta')}`",
        f"- Net sidecar fail delta: `{summary.get('sidecar_fail_delta')}`",
        f"- Best saved percent: `{summary.get('best_saved_pct')}%` at `{summary.get('best_scorecard_path')}`",
        f"- Worst saved percent: `{summary.get('worst_saved_pct')}%` at `{summary.get('worst_scorecard_path')}`",
        f"- Adjacent passes: `{summary.get('pass_step_count', 0)}`",
        f"- Adjacent watches: `{summary.get('watch_step_count', 0)}`",
        f"- Adjacent failures: `{summary.get('fail_step_count', 0)}`",
        "",
        "## Scorecard Timeline",
        "",
        "| # | Scorecard | Status | Milestone | Turns | Saved % | Saved Tokens | Privacy | Sidecar P/W/F |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for entry in report.get("scorecards", []):
        sidecar = (
            f"{entry.get('sidecar_pass_count', 0)}/"
            f"{entry.get('sidecar_watch_count', 0)}/"
            f"{entry.get('sidecar_fail_count', 0)}"
        )
        lines.append(
            "| "
            f"{entry.get('index')} | "
            f"{_markdown_cell(str(entry.get('scorecard_path', '')))} | "
            f"`{entry.get('status')}` | "
            f"`{entry.get('milestone')}` | "
            f"{entry.get('turn_count')} | "
            f"{entry.get('saved_pct')}% | "
            f"{entry.get('saved_tokens')} | "
            f"{entry.get('privacy_finding_count')} | "
            f"{sidecar} |"
        )
    lines.extend(
        [
            "",
            "## Adjacent Steps",
            "",
            "| From | To | Status | Saved % Delta | Turn Delta | Privacy Delta | Sidecar Fail Delta |",
            "|---:|---:|---|---:|---:|---:|---:|",
        ]
    )
    for step in report.get("steps", []):
        delta = step.get("delta", {})
        lines.append(
            "| "
            f"{step.get('from_index')} | "
            f"{step.get('to_index')} | "
            f"`{step.get('status')}` | "
            f"{delta.get('saved_pct')}% | "
            f"{delta.get('turn_count')} | "
            f"{delta.get('privacy_finding_count')} | "
            f"{delta.get('sidecar_fail_count')} |"
        )
    warnings = report.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_scorecard_pack_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs", {})
    lines = [
        "# TokenSquash Turn Scorecard Pack",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Corpus: `{report.get('path')}`",
        f"- Output directory: `{outputs.get('output_dir')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Scorecard status: `{summary.get('scorecard_status')}`",
        f"- History status: `{summary.get('history_status')}`",
        f"- History included: `{summary.get('history_included')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Milestone: `{summary.get('milestone')}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
        "",
        "## Artifacts",
        "",
        f"- Scorecard JSON: `{outputs.get('scorecard_json')}`",
        f"- Scorecard Markdown: `{outputs.get('scorecard_markdown')}`",
    ]
    if outputs.get("history_json") or outputs.get("history_markdown"):
        lines.extend(
            [
                f"- History JSON: `{outputs.get('history_json')}`",
                f"- History Markdown: `{outputs.get('history_markdown')}`",
            ]
        )
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


def format_turn_certification_compare_markdown(report: dict[str, Any]) -> str:
    delta = report.get("delta", {})
    base = report.get("base", {})
    target = report.get("target", {})
    lines = [
        "# TokenSquash Turn Certification Compare",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Base certification: `{base.get('certification_path')}` saved=`{base.get('saved_pct')}%` gate=`{base.get('gate_status')}`",
        f"- Target certification: `{target.get('certification_path')}` saved=`{target.get('saved_pct')}%` gate=`{target.get('gate_status')}`",
        f"- Saved percent delta: `{delta.get('saved_pct')}%`",
        f"- Saved token delta: `{delta.get('saved_tokens')}`",
        f"- Failed check delta: `{delta.get('failed_check_count')}`",
        f"- Privacy finding delta: `{delta.get('privacy_finding_count')}`",
        f"- Pass-through row delta: `{delta.get('pass_through_rows')}`",
        f"- Raw wire loss turn delta: `{delta.get('raw_wire_loss_turns')}`",
        f"- Suggestion count delta: `{delta.get('suggestion_count')}`",
        "",
        "## Delta Table",
        "",
        "| Metric | Delta |",
        "|---|---:|",
    ]
    for key in (
        "turn_count",
        "saved_tokens",
        "saved_pct",
        "prompt_saved_pct",
        "reply_saved_pct",
        "privacy_finding_count",
        "pass_through_rows",
        "raw_wire_loss_turns",
        "failed_check_count",
        "suggestion_count",
    ):
        value = delta.get(key)
        suffix = "%" if key.endswith("_pct") else ""
        lines.append(f"| `{key}` | `{value}{suffix}` |")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_certification_history_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Turn Certification History",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Certifications: `{summary.get('certification_count', 0)}`",
        f"- First: `{summary.get('first_certification_path')}` saved=`{summary.get('first_saved_pct')}%`",
        f"- Latest: `{summary.get('latest_certification_path')}` saved=`{summary.get('latest_saved_pct')}%`",
        f"- Net saved percent delta: `{summary.get('saved_pct_delta')}%`",
        f"- Net saved token delta: `{summary.get('saved_tokens_delta')}`",
        f"- Net failed check delta: `{summary.get('failed_check_delta')}`",
        f"- Best saved percent: `{summary.get('best_saved_pct')}%` at `{summary.get('best_certification_path')}`",
        f"- Worst saved percent: `{summary.get('worst_saved_pct')}%` at `{summary.get('worst_certification_path')}`",
        f"- Adjacent improvements: `{summary.get('improved_step_count', 0)}`",
        f"- Adjacent regressions: `{summary.get('regressed_step_count', 0)}`",
        f"- Adjacent failures: `{summary.get('failed_step_count', 0)}`",
        "",
        "## Certification Timeline",
        "",
        "| # | Certification | Status | Gate | Saved % | Saved Tokens | Failed Checks | Privacy Findings | Suggestions |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for entry in report.get("certifications", []):
        lines.append(
            "| "
            f"{entry.get('index')} | "
            f"{_markdown_cell(str(entry.get('certification_path', '')))} | "
            f"`{entry.get('status')}` | "
            f"`{entry.get('gate_status')}` | "
            f"{entry.get('saved_pct')}% | "
            f"{entry.get('saved_tokens')} | "
            f"{entry.get('failed_check_count')} | "
            f"{entry.get('privacy_finding_count')} | "
            f"{entry.get('suggestion_count')} |"
        )
    lines.extend(
        [
            "",
            "## Adjacent Steps",
            "",
            "| From | To | Status | Saved % Delta | Saved Token Delta | Failed Check Delta |",
            "|---:|---:|---|---:|---:|---:|",
        ]
    )
    for step in report.get("steps", []):
        delta = step.get("delta", {})
        lines.append(
            "| "
            f"{step.get('from_index')} | "
            f"{step.get('to_index')} | "
            f"`{step.get('status')}` | "
            f"{delta.get('saved_pct')}% | "
            f"{delta.get('saved_tokens')} | "
            f"{delta.get('failed_check_count')} |"
        )
    warnings = report.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_gate_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    thresholds = report.get("thresholds", {})
    lines = [
        "# TokenSquash Turn Gate",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source')}`",
        f"- Input type: `{report.get('input_type')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
        f"- Pass-through rows: `{summary.get('pass_through_rows', 0)}`",
        f"- Raw wire loss turns: `{summary.get('raw_wire_loss_turns', 0)}`",
        f"- Failed checks: `{summary.get('failed_check_count', 0)}`",
        "",
        "## Thresholds",
        "",
        f"- Min saved percent: `{thresholds.get('min_saved_pct', 0.0)}%`",
        f"- Max privacy findings: `{thresholds.get('max_privacy_findings', 0)}`",
        f"- Max pass-through rows: `{thresholds.get('max_pass_through_rows', 0)}`",
        f"- Max raw wire loss turns: `{thresholds.get('max_raw_wire_loss_turns', 0)}`",
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


def format_turn_certification_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    artifacts = report.get("artifacts", {})
    gate = artifacts.get("gate", {})
    suggestions = artifacts.get("suggestions", {})
    outputs = report.get("outputs", {})
    lines = [
        "# TokenSquash Turn Certification",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Adaptive: `{report.get('adaptive')}`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Prompt saved percent: `{summary.get('prompt_saved_pct', 0.0)}%`",
        f"- Reply saved percent: `{summary.get('reply_saved_pct', 0.0)}%`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
        f"- Pass-through rows: `{summary.get('pass_through_rows', 0)}`",
        f"- Raw wire loss turns: `{summary.get('raw_wire_loss_turns', 0)}`",
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
    suggestion_items = suggestions.get("suggestions", []) or []
    lines.extend(
        [
            "",
            "## Suggestions",
            "",
            f"- Status: `{suggestions.get('status')}`",
            f"- Count: `{(suggestions.get('summary') or {}).get('suggestion_count', 0)}`",
        ]
    )
    if suggestion_items:
        lines.extend(["", "| Rank | Type | Estimated saved | Suggestion |", "|---:|---|---:|---|"])
        for item in suggestion_items[:10]:
            lines.append(
                "| "
                f"{item.get('rank')} | "
                f"`{_markdown_cell(str(item.get('type', '')))}` | "
                f"{item.get('estimated_saved_tokens', 0)} | "
                f"{_markdown_cell(str(item.get('title', '')))} |"
            )
    if outputs:
        lines.extend(["", "## Outputs", ""])
        for key, path in sorted(outputs.items()):
            lines.append(f"- `{key}`: `{path}`")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_suggestions_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    source = report.get("report", {})
    lines = [
        "# TokenSquash Turn Suggestions",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Report: `{source.get('report_path')}`",
        f"- Corpus: `{source.get('corpus_path')}`",
        f"- Saved percent: `{summary.get('report_saved_pct', 0.0)}%`",
        f"- Saved tokens: `{summary.get('report_saved_tokens', 0)}`",
        f"- Suggestions: `{summary.get('suggestion_count', 0)}`",
        "",
        "## Suggestions",
        "",
    ]
    suggestions = report.get("suggestions", [])
    if not suggestions:
        lines.extend(["No suggestions met the current thresholds.", ""])
        return "\n".join(lines).rstrip() + "\n"

    for item in suggestions:
        lines.extend(
            [
                f"### {item.get('rank')}. {item.get('title')}",
                "",
                f"- Type: `{item.get('type')}`",
                f"- Estimated saved tokens: `{item.get('estimated_saved_tokens', 0)}`",
                f"- Why: {item.get('rationale')}",
                f"- Next: {item.get('next_step')}",
            ]
        )
        evidence = item.get("evidence") or {}
        if evidence:
            evidence_text = ", ".join(f"{key}={value}" for key, value in evidence.items() if value not in (None, "", []))
            if evidence_text:
                lines.append(f"- Evidence: `{_markdown_cell(evidence_text)}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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


def _load_turn_scorecard(path: Path | str) -> dict[str, Any]:
    source = _resolve_turn_scorecard_path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "tokensquash.turns.scorecard.v1":
        raise ValueError(f"Not a TokenSquash turn scorecard: {source}")
    return payload


def _resolve_turn_scorecard_path(path: Path | str) -> Path:
    source = Path(path)
    if source.is_dir():
        return source / "scorecard.json"
    return source


def _load_turn_certification(path: Path | str) -> dict[str, Any]:
    source = _resolve_turn_certification_path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "tokensquash.turns.certify.v1":
        raise ValueError(f"Not a TokenSquash turn certification: {source}")
    return payload


def _resolve_turn_certification_path(path: Path | str) -> Path:
    source = Path(path)
    if source.is_dir():
        return source / "certification.json"
    return source


def _load_turn_gate_report(path: Path | str) -> tuple[dict[str, Any], str, str]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("turn gate input must be a JSON object")
    schema = str(payload.get("schema_version", ""))
    if schema == "tokensquash.turns.report.v1":
        return payload, "report", schema
    if schema == "tokensquash.turns.evaluate.v1":
        return payload, "evaluation", schema
    raise ValueError(f"not a TokenSquash turn report or evaluation: {source}")


def _turn_report_from_evaluation(
    evaluation: dict[str, Any],
    *,
    source: str,
    counter: str,
    target_savings_pct: float,
    adaptive: bool,
    limit: int,
    elapsed_seconds: float,
) -> dict[str, Any]:
    measure_summary = (evaluation.get("measure") or {}).get("summary", {})
    measure_benchmark_summary = ((evaluation.get("measure") or {}).get("benchmark") or {}).get("summary", {})
    diagnosis = evaluation.get("diagnose") or {}
    mine = evaluation.get("mine") or {}
    alias_impact = evaluation.get("alias_impact") or {}
    validation = evaluation.get("validation") or {}
    validation_summary = validation.get("summary", {})
    capped_limit = max(1, int(limit))
    return {
        "schema_version": "tokensquash.turns.report.v1",
        "status": evaluation.get("status", "fail"),
        "path": source,
        "counter": counter,
        "target_savings_pct": target_savings_pct,
        "adaptive": adaptive,
        "limit": capped_limit,
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
            "elapsed_seconds": elapsed_seconds,
        },
        "top_wins": list((diagnosis.get("largest_wins", []) or [])[:capped_limit]),
        "top_raw_wire_losses": list((diagnosis.get("largest_losses", []) or [])[:capped_limit]),
        "top_path_candidates": list((mine.get("path_patterns", []) or [])[:capped_limit]),
        "top_field_candidates": list((mine.get("top_candidates", []) or [])[:capped_limit]),
        "validation": validation,
        "measure": evaluation.get("measure"),
        "diagnose": evaluation.get("diagnose"),
        "mine": evaluation.get("mine"),
        "aliases": evaluation.get("aliases"),
        "alias_impact": alias_impact,
        "bench": evaluation.get("bench"),
    }


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


def _turn_scorecard_identity(path: Path | str, report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    return {
        "scorecard_path": str(_resolve_turn_scorecard_path(path)),
        "corpus_path": report.get("path"),
        "status": report.get("status"),
        "counter": report.get("counter"),
        "adaptive": report.get("adaptive"),
        "turn_count": summary.get("turn_count"),
        "milestone": summary.get("milestone"),
        "original_tokens": summary.get("original_tokens"),
        "squashed_tokens": summary.get("squashed_tokens"),
        "saved_tokens": summary.get("saved_tokens"),
        "saved_pct": summary.get("saved_pct"),
        "prompt_saved_pct": summary.get("prompt_saved_pct"),
        "reply_saved_pct": summary.get("reply_saved_pct"),
        "privacy_finding_count": summary.get("privacy_finding_count"),
        "pass_through_rows": summary.get("pass_through_rows"),
        "raw_wire_loss_turns": summary.get("raw_wire_loss_turns"),
        "selected_path_prefix_count": summary.get("selected_path_prefix_count"),
        "selected_field_value_count": summary.get("selected_field_value_count"),
        "alias_saved_tokens_delta": summary.get("alias_saved_tokens_delta"),
        "break_even_corpora": summary.get("break_even_corpora"),
        "sidecar_status": summary.get("sidecar_status"),
        "sidecar_pass_count": summary.get("sidecar_pass_count"),
        "sidecar_watch_count": summary.get("sidecar_watch_count"),
        "sidecar_fail_count": summary.get("sidecar_fail_count"),
        "recommendation": summary.get("recommendation"),
    }


def _turn_certification_identity(path: Path | str, report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    artifacts = report.get("artifacts", {})
    gate = artifacts.get("gate", {})
    return {
        "certification_path": str(_resolve_turn_certification_path(path)),
        "corpus_path": report.get("path"),
        "status": report.get("status"),
        "counter": report.get("counter"),
        "adaptive": report.get("adaptive"),
        "gate_status": gate.get("status"),
        "turn_count": summary.get("turn_count"),
        "saved_tokens": summary.get("saved_tokens"),
        "saved_pct": summary.get("saved_pct"),
        "prompt_saved_pct": summary.get("prompt_saved_pct"),
        "reply_saved_pct": summary.get("reply_saved_pct"),
        "privacy_finding_count": summary.get("privacy_finding_count"),
        "pass_through_rows": summary.get("pass_through_rows"),
        "raw_wire_loss_turns": summary.get("raw_wire_loss_turns"),
        "failed_check_count": summary.get("failed_check_count"),
        "suggestion_count": summary.get("suggestion_count"),
    }


def _turn_certification_failed(identity: dict[str, Any]) -> bool:
    return (
        identity.get("status") != "pass"
        or identity.get("gate_status") == "fail"
        or _int_value(identity.get("failed_check_count")) > 0
    )


def _gate_turn_report_payload(
    source_report: dict[str, Any],
    *,
    source: str,
    input_type: str,
    input_schema: str,
    min_saved_pct: float,
    max_privacy_findings: int,
    max_pass_through_rows: int,
    max_raw_wire_loss_turns: int,
) -> dict[str, Any]:
    gate_summary = _turn_gate_summary(source_report)
    checks = [
        _turn_gate_check("min_saved_pct", gate_summary["saved_pct"], min_saved_pct, ">="),
        _turn_gate_check(
            "max_privacy_findings",
            gate_summary["privacy_finding_count"],
            max(0, int(max_privacy_findings)),
            "<=",
        ),
        _turn_gate_check(
            "max_pass_through_rows",
            gate_summary["pass_through_rows"],
            max(0, int(max_pass_through_rows)),
            "<=",
        ),
        _turn_gate_check(
            "max_raw_wire_loss_turns",
            gate_summary["raw_wire_loss_turns"],
            max(0, int(max_raw_wire_loss_turns)),
            "<=",
        ),
    ]
    failures = [check for check in checks if check.get("status") == "fail"]
    status = "pass" if not failures else "fail"
    return {
        "schema_version": "tokensquash.turns.gate.v1",
        "status": status,
        "source": source,
        "input_type": input_type,
        "input_schema_version": input_schema,
        "report": {
            **_turn_report_identity(source, source_report),
            "schema_version": input_schema,
        },
        "thresholds": {
            "min_saved_pct": float(min_saved_pct),
            "max_privacy_findings": max(0, int(max_privacy_findings)),
            "max_pass_through_rows": max(0, int(max_pass_through_rows)),
            "max_raw_wire_loss_turns": max(0, int(max_raw_wire_loss_turns)),
        },
        "summary": {
            **gate_summary,
            "status": status,
            "passed": status == "pass",
            "check_count": len(checks),
            "failed_check_count": len(failures),
        },
        "checks": checks,
        "failures": failures,
    }


def _turn_gate_summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {}) or {}
    validation_summary = ((report.get("validation") or {}).get("summary") or {})
    measure = report.get("measure") or {}
    measure_summary = measure.get("summary", {}) or {}
    measure_benchmark_summary = ((measure.get("benchmark") or {}).get("summary") or {})
    diagnose_summary = ((report.get("diagnose") or {}).get("summary") or {})
    bench_summary = ((report.get("bench") or {}).get("summary") or {})
    raw_loss_default = len(report.get("top_raw_wire_losses") or [])
    pass_through_rows = _summary_value(
        "pass_through_rows",
        summary,
        measure_summary,
        diagnose_summary,
        default=None,
    )
    if pass_through_rows is None:
        pass_through_rows = _summary_value("passthroughs", bench_summary, measure_benchmark_summary, default=0)
    return {
        "turn_count": _int_value(
            _summary_value("turn_count", summary, measure_summary, diagnose_summary, validation_summary, bench_summary, default=0)
        ),
        "original_tokens": _int_value(
            _summary_value("original_tokens", summary, measure_summary, diagnose_summary, bench_summary, default=0)
        ),
        "wire_tokens": _int_value(
            _summary_value("wire_tokens", summary, diagnose_summary, measure_benchmark_summary, bench_summary, default=0)
        ),
        "squashed_tokens": _int_value(
            _summary_value("squashed_tokens", summary, measure_summary, diagnose_summary, bench_summary, default=0)
        ),
        "saved_tokens": _int_value(
            _summary_value("saved_tokens", summary, measure_summary, diagnose_summary, bench_summary, default=0)
        ),
        "saved_pct": _float_value(
            _summary_value("saved_pct", summary, measure_summary, diagnose_summary, bench_summary, default=0.0)
        ),
        "prompt_saved_pct": _float_value(
            _summary_value("prompt_saved_pct", summary, measure_summary, bench_summary, default=0.0)
        ),
        "reply_saved_pct": _float_value(
            _summary_value("reply_saved_pct", summary, measure_summary, bench_summary, default=0.0)
        ),
        "privacy_finding_count": _int_value(
            _summary_value(
                "privacy_finding_count",
                summary,
                validation_summary,
                measure_summary,
                diagnose_summary,
                default=0,
            )
        ),
        "pass_through_rows": _int_value(pass_through_rows),
        "raw_wire_loss_turns": _int_value(
            _summary_value("raw_wire_loss_turns", summary, diagnose_summary, default=raw_loss_default)
        ),
    }


def _summary_value(key: str, *summaries: dict[str, Any], default: Any = None) -> Any:
    for summary in summaries:
        if isinstance(summary, dict) and key in summary and summary[key] is not None:
            return summary[key]
    return default


def _turn_gate_check(name: str, actual: float | int, limit: float | int, operator: str) -> dict[str, Any]:
    if operator == ">=":
        passed = actual >= limit
    elif operator == "<=":
        passed = actual <= limit
    else:
        raise ValueError(f"unsupported turn gate operator: {operator}")
    return {
        "name": name,
        "actual": actual,
        "operator": operator,
        "limit": limit,
        "status": "pass" if passed else "fail",
    }


def _turn_suggestion(
    suggestion_type: str,
    title: str,
    rationale: str,
    next_step: str,
    *,
    priority: int,
    estimated_saved_tokens: int,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": suggestion_type,
        "title": title,
        "priority": priority,
        "estimated_saved_tokens": estimated_saved_tokens,
        "rationale": rationale,
        "next_step": next_step,
        "evidence": evidence,
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


def _scorecard_milestone(turn_count: int) -> dict[str, Any]:
    if turn_count < 10:
        return {
            "name": "seed",
            "label": "Seed capture",
            "minimum_turns": 0,
            "next_turns": 10,
            "message": "Keep capturing until the first 10-turn smoke pass is available.",
        }
    if turn_count < 25:
        return {
            "name": "smoke",
            "label": "10-turn smoke evidence",
            "minimum_turns": 10,
            "next_turns": 25,
            "message": "Enough for a smoke read; keep expanding before treating patterns as strong.",
        }
    if turn_count < 100:
        return {
            "name": "early_pattern",
            "label": "25-turn early pattern evidence",
            "minimum_turns": 25,
            "next_turns": 100,
            "message": "Useful for finding repeated workflow language; still not production-scale evidence.",
        }
    return {
        "name": "benchmark_ready",
        "label": "100-turn benchmark candidate",
        "minimum_turns": 100,
        "next_turns": None,
        "message": "Large enough for a serious local benchmark pass, subject to privacy and meaning review.",
    }


def _scorecard_sidecar_summary(
    *,
    sidecar_review: Path | str | None,
    sidecar_evaluation: Path | str | None,
    auto_sidecar: bool,
) -> dict[str, Any]:
    review_path = Path(sidecar_review) if sidecar_review is not None else None
    evaluation_path = Path(sidecar_evaluation) if sidecar_evaluation is not None else None
    if auto_sidecar:
        if review_path is None and Path("private-turns/sidecar-eval/review.json").exists():
            review_path = Path("private-turns/sidecar-eval/review.json")
        if evaluation_path is None and Path("private-turns/sidecar-eval/evaluation.json").exists():
            evaluation_path = Path("private-turns/sidecar-eval/evaluation.json")

    if review_path is not None and review_path.exists():
        return _scorecard_sidecar_review_summary(review_path)
    if sidecar_review is not None:
        return _scorecard_missing_sidecar(str(review_path), "review")
    if evaluation_path is not None and evaluation_path.exists():
        return _scorecard_sidecar_evaluation_summary(evaluation_path)
    if sidecar_evaluation is not None:
        return _scorecard_missing_sidecar(str(evaluation_path), "evaluation")
    return {
        "status": "missing",
        "source": None,
        "input_type": None,
        "message": "No sidecar review or evaluation evidence was provided.",
        "pass_count": 0,
        "watch_count": 0,
        "fail_count": 0,
        "review_count": 0,
        "warning_count": 0,
        "saved_pct": 0.0,
        "flag_counts": {},
    }


def _scorecard_missing_sidecar(source: str, input_type: str) -> dict[str, Any]:
    return {
        "status": "missing",
        "source": source,
        "input_type": input_type,
        "message": f"Sidecar {input_type} evidence was requested but not found.",
        "pass_count": 0,
        "watch_count": 0,
        "fail_count": 0,
        "review_count": 0,
        "warning_count": 0,
        "saved_pct": 0.0,
        "flag_counts": {},
    }


def _scorecard_sidecar_review_summary(path: Path) -> dict[str, Any]:
    report = _load_json_object(path)
    if report.get("schema_version") != "tokensquash.sidecar.review.v1":
        raise ValueError(f"not a sidecar review report: {path}")
    summary = report.get("summary", {})
    review_count = _int_value(summary.get("review_count"))
    pass_count = _int_value(summary.get("pass_count", summary.get("ok_count")))
    fail_count = _int_value(summary.get("fail_count", summary.get("high_risk_count")))
    watch_count = _int_value(summary.get("watch_count", max(0, review_count - fail_count)))
    flag_counts: dict[str, int] = {}
    for row in report.get("rows", []):
        for flag in row.get("flags", []):
            flag_text = str(flag)
            flag_counts[flag_text] = flag_counts.get(flag_text, 0) + 1
    status = "fail" if fail_count else "watch" if watch_count or _int_value(summary.get("warning_count")) else "pass"
    return {
        "status": status,
        "source": str(path),
        "input_type": "review",
        "message": "Sidecar meaning review evidence loaded.",
        "pass_count": pass_count,
        "watch_count": watch_count,
        "fail_count": fail_count,
        "review_count": review_count,
        "warning_count": _int_value(summary.get("warning_count")),
        "saved_pct": _float_value(summary.get("saved_pct")),
        "flag_counts": dict(sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))),
        "summary": summary,
    }


def _scorecard_sidecar_evaluation_summary(path: Path) -> dict[str, Any]:
    report = _load_json_object(path)
    if report.get("schema_version") != "tokensquash.sidecar.evaluate.v1":
        raise ValueError(f"not a sidecar evaluation report: {path}")
    summary = report.get("summary", {})
    item_count = _int_value(summary.get("item_count"))
    failure_count = _int_value(summary.get("failure_count"))
    warning_count = _int_value(summary.get("warning_count"))
    pass_count = max(0, item_count - failure_count - warning_count)
    status = "fail" if failure_count else "watch" if warning_count else "pass" if item_count else "missing"
    return {
        "status": status,
        "source": str(path),
        "input_type": "evaluation",
        "message": "Sidecar evaluation loaded; run sidecar review for stronger meaning evidence.",
        "pass_count": pass_count,
        "watch_count": warning_count,
        "fail_count": failure_count,
        "review_count": 0,
        "warning_count": warning_count,
        "saved_pct": _float_value(summary.get("saved_pct")),
        "flag_counts": {},
        "summary": summary,
    }


def _scorecard_recommendations(
    turn_report: dict[str, Any],
    milestone: dict[str, Any],
    sidecar: dict[str, Any],
) -> list[dict[str, str]]:
    summary = turn_report.get("summary", {})
    diagnose_summary = (turn_report.get("diagnose") or {}).get("summary", {})
    recommendations: list[dict[str, str]] = []

    if _int_value(summary.get("privacy_finding_count")):
        recommendations.append(
            {
                "code": "fix_privacy",
                "message": "Review and redact privacy findings before sharing or using this evidence outside local storage.",
            }
        )
    if milestone.get("name") == "seed":
        recommendations.append(
            {
                "code": "capture_10",
                "message": "Capture enough real turns to reach the 10-turn smoke milestone.",
            }
        )
    elif milestone.get("name") == "smoke":
        recommendations.append(
            {
                "code": "expand_25",
                "message": "Expand toward 25 turns before treating repeated patterns as codec input.",
            }
        )
    elif milestone.get("name") == "early_pattern":
        recommendations.append(
            {
                "code": "expand_100",
                "message": "Continue toward 100 turns for a more useful local benchmark.",
            }
        )

    if sidecar.get("status") == "missing":
        recommendations.append(
            {
                "code": "run_sidecar_review",
                "message": "Run sidecar evaluate and sidecar review if local-AI semantic compression is being considered.",
            }
        )
    elif sidecar.get("status") == "fail":
        recommendations.append(
            {
                "code": "fix_sidecar_meaning",
                "message": "Inspect high-risk sidecar rows before using sidecar savings as evidence.",
            }
        )
    elif sidecar.get("status") == "watch":
        recommendations.append(
            {
                "code": "inspect_sidecar_watch",
                "message": "Review sidecar watch rows and warnings before claiming meaning preservation.",
            }
        )

    if _int_value(summary.get("alias_saved_tokens_delta")) > 0:
        recommendations.append(
            {
                "code": "promote_alias_candidates",
                "message": "Alias-impact evidence shows net token savings; inspect candidates before changing deterministic rules.",
            }
        )
    elif turn_report.get("top_path_candidates") or turn_report.get("top_field_candidates"):
        recommendations.append(
            {
                "code": "inspect_patterns",
                "message": "Repeated path or field candidates exist; check whether they recur across more turns.",
            }
        )

    if _int_value(diagnose_summary.get("raw_wire_loss_turns")):
        recommendations.append(
            {
                "code": "keep_adaptive_fallback",
                "message": "Raw wire losses are present; keep adaptive passthrough enabled for honest savings.",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "code": "benchmark_ready",
                "message": "Corpus evidence is clean enough for the next benchmark or certification pass.",
            }
        )
    return recommendations


def _scorecard_status(turn_report: dict[str, Any], sidecar: dict[str, Any]) -> str:
    if turn_report.get("status") == "fail":
        return "fail"
    summary = turn_report.get("summary", {})
    if _int_value(summary.get("privacy_finding_count")):
        return "warn"
    if sidecar.get("status") == "fail":
        return "warn"
    if turn_report.get("status") in {"warn", "miss", "regressed"} or sidecar.get("status") in {"watch", "missing"}:
        return "watch"
    return "pass"


def _scorecard_compare_status(target_report: dict[str, Any], delta: dict[str, Any]) -> str:
    target_status = str(target_report.get("status", "fail"))
    if target_status == "fail":
        return "fail"
    if _int_value(delta.get("privacy_finding_count")) > 0:
        return "fail"
    if _int_value(delta.get("sidecar_fail_count")) > 0:
        return "fail"
    if _int_value(delta.get("raw_wire_loss_turns")) > 0:
        return "fail"
    if target_status in {"watch", "warn"}:
        return "watch"
    if _float_value(delta.get("saved_pct")) < 0:
        return "watch"
    if _int_value(delta.get("saved_tokens")) < 0:
        return "watch"
    if _int_value(delta.get("pass_through_rows")) > 0:
        return "watch"
    if _int_value(delta.get("sidecar_watch_count")) > 0:
        return "watch"
    if _int_value(delta.get("sidecar_pass_count")) < 0:
        return "watch"
    if _int_value(delta.get("turn_count")) < 0:
        return "watch"
    return "pass"


def _scorecard_history_status(latest: dict[str, Any], fail_step_count: int, watch_step_count: int) -> str:
    latest_status = str(latest.get("status", "fail"))
    if latest_status == "fail" or fail_step_count:
        return "fail"
    if latest_status in {"watch", "warn"} or watch_step_count:
        return "watch"
    return "pass"


def _scorecard_pack_status(scorecard: dict[str, Any], history: dict[str, Any] | None) -> str:
    scorecard_status = str(scorecard.get("status", "fail"))
    history_status = str(history.get("status")) if history else None
    if scorecard_status == "fail" or history_status == "fail":
        return "fail"
    if scorecard_status in {"watch", "warn"} or history_status in {"watch", "warn"}:
        return "watch"
    return "pass"


def _scorecard_compare_recommendations(target_report: dict[str, Any], delta: dict[str, Any]) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    target_summary = target_report.get("summary", {})
    if str(target_report.get("status")) == "fail":
        recommendations.append(
            {
                "code": "fix_target_scorecard",
                "message": "Target scorecard failed; resolve its underlying corpus or evaluation issue before release.",
            }
        )
    if _int_value(delta.get("privacy_finding_count")) > 0:
        recommendations.append(
            {
                "code": "fix_privacy_regression",
                "message": "Privacy findings increased; inspect redaction before using this scorecard as release evidence.",
            }
        )
    if _int_value(delta.get("sidecar_fail_count")) > 0:
        recommendations.append(
            {
                "code": "fix_sidecar_regression",
                "message": "Sidecar fail count increased; review meaning-risk rows before promoting local-AI semantics.",
            }
        )
    if _int_value(delta.get("raw_wire_loss_turns")) > 0:
        recommendations.append(
            {
                "code": "inspect_wire_losses",
                "message": "Raw wire loss turns increased; inspect adaptive behavior and repeated long fields.",
            }
        )
    if _float_value(delta.get("saved_pct")) < 0:
        recommendations.append(
            {
                "code": "inspect_savings_regression",
                "message": "Saved percent decreased; compare top wins and repeated candidates before changing claims.",
            }
        )
    if _int_value(delta.get("turn_count")) < 0:
        recommendations.append(
            {
                "code": "restore_corpus_size",
                "message": "Turn count decreased; compare against the same corpus scope or explain the smaller sample.",
            }
        )
    if str(target_report.get("status")) in {"watch", "warn"}:
        recommendations.append(
            {
                "code": "clear_target_watch_status",
                "message": f"Target scorecard status is {target_report.get('status')}; clear its top recommendation before release.",
            }
        )
    if not recommendations and _int_value(delta.get("milestone_rank")) > 0:
        recommendations.append(
            {
                "code": "promote_release_evidence",
                "message": "Corpus milestone improved without new hard-risk deltas; keep this scorecard in the release evidence pack.",
            }
        )
    if not recommendations and _int_value(target_summary.get("sidecar_fail_count")) == 0:
        recommendations.append(
            {
                "code": "keep_monitoring",
                "message": "No scorecard regression detected; keep growing the corpus and compare again before tagging.",
            }
        )
    return recommendations


def _scorecard_milestone_rank(value: str) -> int:
    ranks = {
        "seed": 0,
        "smoke": 1,
        "early_pattern": 2,
        "benchmark_ready": 3,
    }
    return ranks.get(value, -1)


def _nullable_int_delta(target: Any, base: Any) -> int | None:
    if target is None or base is None:
        return None
    return _int_value(target) - _int_value(base)


def _resolve_claim_evidence_path(path: Path) -> Path:
    if path.is_dir():
        for name in (
            "certification.json",
            "scorecard.json",
            "report.json",
            "gate.json",
            "review.json",
            "evaluation.json",
            "release-check.json",
        ):
            candidate = path / name
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"no supported claim evidence JSON found in directory: {path}")
    return path


def _normalize_turn_claim_source(payload: dict[str, Any], source: Path) -> dict[str, Any]:
    schema = str(payload.get("schema_version", ""))
    supported = {
        "tokensquash.turns.report.v1": "report",
        "tokensquash.turns.scorecard.v1": "scorecard",
        "tokensquash.turns.scorecard.pack.v1": "scorecard_pack",
        "tokensquash.turns.gate.v1": "gate",
        "tokensquash.turns.certify.v1": "certification",
        "tokensquash.turns.release_check.v1": "release_check",
        "tokensquash.turns.evaluate.v1": "evaluation",
    }
    input_type = supported.get(schema)
    if input_type is None:
        raise ValueError(f"unsupported claim evidence schema: {schema or 'missing'}")

    artifacts = payload.get("artifacts") or {}
    nested_report = artifacts.get("report") or payload.get("turn_report") or {}
    nested_gate = artifacts.get("gate") or payload.get("gate") or {}
    summaries = [
        payload.get("summary") or {},
        nested_gate.get("summary") or {},
        nested_report.get("summary") or {},
        (payload.get("bench") or {}).get("summary") or {},
        ((payload.get("measure") or {}).get("benchmark") or {}).get("summary") or {},
    ]
    corpus = payload.get("path") or payload.get("source") or nested_report.get("path")
    counter = payload.get("counter") or nested_report.get("counter")
    gate_status = nested_gate.get("status") or (payload.get("status") if input_type == "gate" else None)
    return {
        "input_type": input_type,
        "source_status": str(payload.get("status", "unknown")),
        "corpus": str(corpus) if corpus is not None else None,
        "counter": str(counter) if counter is not None else None,
        "turn_count": _first_int(summaries, "turn_count", "item_count"),
        "original_tokens": _first_int(summaries, "original_tokens"),
        "compact_tokens": _first_int(summaries, "squashed_tokens", "semantic_tokens", "wire_tokens"),
        "saved_tokens": _first_int(summaries, "saved_tokens"),
        "saved_pct": _first_float(summaries, "saved_pct"),
        "pass_through_rows": _first_int(summaries, "pass_through_rows", "passthroughs"),
        "raw_wire_loss_turns": _first_int(summaries, "raw_wire_loss_turns"),
        "warning_count": _first_int(summaries, "warning_count"),
        "privacy_finding_count": _first_int(summaries, "privacy_finding_count"),
        "failed_check_count": _first_int(summaries, "failed_check_count", "failure_count"),
        "gate_status": str(gate_status) if gate_status else None,
        "review_status": None,
        "review_count": 0,
        "high_risk_count": 0,
        "medium_risk_count": 0,
        "loss_items": 0,
        "evidence_path": str(source),
    }


def _normalize_sidecar_claim_source(payload: dict[str, Any], source: Path) -> dict[str, Any]:
    schema = str(payload.get("schema_version", ""))
    supported = {
        "tokensquash.sidecar.evaluate.v1": "sidecar_evaluation",
        "tokensquash.sidecar.review.v1": "sidecar_review",
        "tokensquash.sidecar.gate.v1": "sidecar_gate",
        "tokensquash.sidecar.certify.v1": "sidecar_certification",
        "tokensquash.sidecar.experiment.v1": "sidecar_experiment",
        "tokensquash.sidecar.sweep.v1": "sidecar_sweep",
    }
    input_type = supported.get(schema)
    if input_type is None:
        raise ValueError(f"unsupported sidecar claim evidence schema: {schema or 'missing'}")

    artifacts = payload.get("artifacts") or {}
    nested_review = artifacts.get("review") or payload.get("review") or {}
    nested_gate = artifacts.get("gate") or payload.get("gate") or {}
    summaries = [
        payload.get("summary") or {},
        nested_gate.get("summary") or {},
        nested_review.get("summary") or {},
        (payload.get("evaluation") or {}).get("summary") or {},
    ]
    corpus = payload.get("source") or payload.get("path") or (payload.get("evaluation") or {}).get("source")
    counter = payload.get("counter") or (payload.get("evaluation") or {}).get("counter")
    gate_status = nested_gate.get("status") or (payload.get("status") if input_type == "sidecar_gate" else None)
    review_status = nested_review.get("status") or (payload.get("status") if input_type == "sidecar_review" else None)
    return {
        "input_type": input_type,
        "source_status": str(payload.get("status", "unknown")),
        "corpus": str(corpus) if corpus is not None else None,
        "counter": str(counter) if counter is not None else None,
        "turn_count": _first_int(summaries, "item_count", "row_count", "turn_count"),
        "original_tokens": _first_int(summaries, "original_tokens"),
        "compact_tokens": _first_int(summaries, "semantic_tokens"),
        "saved_tokens": _first_int(summaries, "saved_tokens"),
        "saved_pct": _first_float(summaries, "saved_pct"),
        "pass_through_rows": 0,
        "raw_wire_loss_turns": 0,
        "warning_count": _first_int(summaries, "warning_count"),
        "privacy_finding_count": 0,
        "failed_check_count": _first_int(summaries, "failed_check_count", "failure_count"),
        "gate_status": str(gate_status) if gate_status else None,
        "review_status": str(review_status) if review_status else None,
        "review_count": _first_int(summaries, "review_count"),
        "high_risk_count": _first_int(summaries, "high_risk_count"),
        "medium_risk_count": _first_int(summaries, "medium_risk_count"),
        "loss_items": _first_int(summaries, "loss_items", "loss_count"),
        "evidence_path": str(source),
    }


def _claim_status(normalized: dict[str, Any], *, scope: str) -> tuple[str, str]:
    failed = (
        normalized["source_status"] == "fail"
        or normalized["gate_status"] == "fail"
        or _int_value(normalized["failed_check_count"]) > 0
        or _int_value(normalized["privacy_finding_count"]) > 0
        or _int_value(normalized["high_risk_count"]) > 0
        or _int_value(normalized["loss_items"]) > 0
    )
    if failed:
        return "fail", "blocked"
    if scope == "experimental_sidecar":
        return "watch", "experimental"
    if normalized["input_type"] in {"certification", "gate", "release_check"} and normalized["gate_status"] == "pass":
        return "pass", "supported"
    return "watch", "caution"


def _claim_text(
    normalized: dict[str, Any],
    *,
    corpus: str,
    evidence: str,
    product_version: str,
    scope: str,
) -> str:
    counter = normalized["counter"] or "unknown"
    turn_count = _int_value(normalized["turn_count"])
    saved_tokens = _int_value(normalized["saved_tokens"])
    saved_pct = _float_value(normalized["saved_pct"])
    original_tokens = _int_value(normalized["original_tokens"])
    compact_tokens = _int_value(normalized["compact_tokens"])
    token_span = (
        f" from {original_tokens} original tokens to {compact_tokens} compact tokens"
        if original_tokens and compact_tokens
        else ""
    )
    if scope == "experimental_sidecar":
        review = normalized["review_status"] or "not provided"
        gate = normalized["gate_status"] or "not provided"
        return (
            f"Experimental TokenSquash sidecar evidence for {corpus} reported {saved_tokens} saved tokens "
            f"({saved_pct}%){token_span} with the `{counter}` counter across {turn_count} item(s). "
            f"Review status: `{review}`. Gate status: `{gate}`. This is not a deterministic codec claim; "
            f"meaning preservation depends on sidecar review evidence. Evidence: {evidence}."
        )
    gate = normalized["gate_status"] or "not provided"
    return (
        f"On {corpus}, TokenSquash {product_version} saved {saved_tokens} tokens ({saved_pct}%){token_span} "
        f"with the `{counter}` counter across {turn_count} turn(s). Gate status: `{gate}`; "
        f"privacy findings: {_int_value(normalized['privacy_finding_count'])}; "
        f"pass-through rows: {_int_value(normalized['pass_through_rows'])}; "
        f"raw wire loss turns: {_int_value(normalized['raw_wire_loss_turns'])}. Evidence: {evidence}."
    )


def _short_claim(normalized: dict[str, Any], *, corpus: str, product_version: str, scope: str) -> str:
    saved_tokens = _int_value(normalized["saved_tokens"])
    saved_pct = _float_value(normalized["saved_pct"])
    counter = normalized["counter"] or "unknown"
    if scope == "experimental_sidecar":
        return f"Experimental sidecar: {corpus} saved {saved_tokens} tokens ({saved_pct}%) with `{counter}`."
    return f"TokenSquash {product_version}: {corpus} saved {saved_tokens} tokens ({saved_pct}%) with `{counter}`."


def _claim_limitations(normalized: dict[str, Any], *, scope: str) -> list[str]:
    limits: list[str] = []
    turn_count = _int_value(normalized["turn_count"])
    if turn_count and turn_count < 10:
        limits.append("Small corpus: treat this as smoke evidence until at least 10 real turns are captured.")
    if not normalized["counter"]:
        limits.append("Counter was not present in the evidence; do not compare this claim across tokenizers.")
    if not normalized["gate_status"]:
        limits.append("No gate status was present; treat this as measurement evidence, not a passed certification.")
    if _int_value(normalized["privacy_finding_count"]):
        limits.append("Privacy findings are present; do not publish raw or insufficiently redacted source data.")
    if _int_value(normalized["warning_count"]):
        limits.append(f"{_int_value(normalized['warning_count'])} warning(s) were present in the source evidence.")
    if _int_value(normalized["pass_through_rows"]):
        limits.append(
            f"{_int_value(normalized['pass_through_rows'])} row(s) used adaptive pass-through because compact output was not shorter."
        )
    if _int_value(normalized["raw_wire_loss_turns"]):
        limits.append(f"{_int_value(normalized['raw_wire_loss_turns'])} raw-wire-loss turn(s) were present.")
    if _int_value(normalized["failed_check_count"]):
        limits.append(f"{_int_value(normalized['failed_check_count'])} failed check(s) block a supported claim.")
    if scope == "experimental_sidecar":
        limits.append("Sidecar output is experimental semantic JSON, not the deterministic `ts1` or `tr1` codec.")
        if not normalized["review_status"]:
            limits.append("No sidecar review status was present; inspect decoded meaning before making meaning claims.")
        if _int_value(normalized["review_count"]):
            limits.append(f"{_int_value(normalized['review_count'])} sidecar row(s) still need human review.")
        if _int_value(normalized["high_risk_count"]) or _int_value(normalized["medium_risk_count"]):
            limits.append(
                "Sidecar risk findings are present; do not claim meaning preservation without resolving them."
            )
    return limits


def _first_int(summaries: Iterable[dict[str, Any]], *keys: str) -> int:
    for summary in summaries:
        for key in keys:
            value = summary.get(key)
            if value is not None:
                return _int_value(value)
    return 0


def _first_float(summaries: Iterable[dict[str, Any]], *keys: str) -> float:
    for summary in summaries:
        for key in keys:
            value = summary.get(key)
            if value is not None:
                return _float_value(value)
    return 0.0


def _claim_package_version(cwd: Path) -> str:
    pyproject = _find_upwards(cwd, "pyproject.toml")
    if pyproject is not None:
        match = re.search(
            r"^version\s*=\s*\"([^\"]+)\"",
            pyproject.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            return match.group(1)
    try:
        return metadata.version("tokensquash")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def _find_upwards(start: Path, filename: str) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        path = candidate / filename
        if path.exists():
            return path
    return None


def _load_json_object(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON report must be an object: {path}")
    return payload


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


def _first_run_status(capture: dict[str, Any], scorecard: dict[str, Any]) -> str:
    capture_status = capture.get("status")
    scorecard_status = scorecard.get("status")
    if capture_status not in {"written", "pass", "warn", "miss", "empty"}:
        return "fail"
    if scorecard_status in {"pass", "watch", "warn", "empty"}:
        return str(scorecard_status)
    return "fail"


def _validate_first_run_inputs(prompt: str, reply: str) -> None:
    starter_prompt = _clean_text(STARTER_PROMPT_TEXT)
    starter_reply = _clean_text(STARTER_REPLY_TEXT)
    if _clean_text(prompt) == starter_prompt or _clean_text(reply) == starter_reply:
        raise ValueError(
            "starter prompt/reply files still contain placeholder text; replace both files with a real prompt and reply"
        )


def _first_run_next_commands(redacted_output_path: Path | str, *, out_dir: Path | str) -> dict[str, str]:
    corpus = _quote_cli_arg(str(Path(redacted_output_path)))
    private_dir = Path(out_dir).parent
    certification_dir = _quote_cli_arg(str(private_dir / "certification"))
    claim_pack_dir = _quote_cli_arg(str(private_dir / "claim-pack"))
    return {
        "capture_next": (
            "python -m tokensquash turns first-run "
            "--prompt-file private-turns/prompt.example.txt --reply-file private-turns/reply.example.txt"
        ),
        "scorecard": f"python -m tokensquash turns scorecard {corpus}",
        "certify": f"python -m tokensquash turns certify {corpus} --out-dir {certification_dir}",
        "claim_pack": f"python -m tokensquash turns claim-pack {certification_dir} --out-dir {claim_pack_dir}",
    }


def _quote_cli_arg(value: str) -> str:
    if any(char.isspace() for char in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


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


def _append_scorecard_candidates(
    lines: list[str],
    title: str,
    candidates: list[dict[str, Any]],
    *,
    include_field: bool = False,
) -> None:
    lines.extend([f"## {title}", ""])
    if not candidates:
        lines.extend(["No candidates.", ""])
        return
    if include_field:
        lines.extend(["| Field | Value | Count | Est new saved |", "|---|---|---:|---:|"])
        for item in candidates:
            lines.append(
                "| "
                f"{_markdown_cell(str(item.get('field', '')))} | "
                f"{_markdown_cell(str(item.get('value', '')))} | "
                f"{item.get('count', 0)} | "
                f"{item.get('estimated_new_saved_tokens', 0)} |"
            )
    else:
        lines.extend(["| Pattern | Count | Est new saved |", "|---|---:|---:|"])
        for item in candidates:
            lines.append(
                "| "
                f"{_markdown_cell(str(item.get('value', '')))} | "
                f"{item.get('count', 0)} | "
                f"{item.get('estimated_new_saved_tokens', 0)} |"
            )
    lines.append("")


def _side_summary(side: dict[str, Any]) -> str:
    return f"{side.get('mode')} raw {side.get('wire_saved_tokens')} saved {side.get('saved_tokens')}"


def write_turn_claim_outputs(target: Path | str, report: dict[str, Any]) -> dict[str, Any]:
    target_path = Path(target)
    target_path.mkdir(parents=True, exist_ok=True)
    claim_path = target_path / "claim.json"
    markdown_path = target_path / "claim.md"
    text_path = target_path / "claim.txt"
    limits_path = target_path / "limits.md"
    report.setdefault("outputs", {})
    report["outputs"].update(
        {
            "output_dir": str(target_path),
            "claim": str(claim_path),
            "markdown": str(markdown_path),
            "text": str(text_path),
            "limits": str(limits_path),
        }
    )
    markdown_path.write_text(format_turn_claim_markdown(report), encoding="utf-8")
    text_path.write_text(format_turn_claim_text(report), encoding="utf-8")
    limits_path.write_text(format_turn_claim_limits_markdown(report), encoding="utf-8")
    _write_json_report(claim_path, report)
    return report


def write_turn_certification_outputs(target: Path | str, report: dict[str, Any]) -> None:
    target_path = Path(target)
    target_path.mkdir(parents=True, exist_ok=True)
    artifacts = report.get("artifacts", {})
    evaluation = artifacts.get("evaluation", {})
    turn_report = artifacts.get("report", {})
    gate = artifacts.get("gate", {})
    suggestions = artifacts.get("suggestions", {})

    evaluation_dir = target_path / "evaluation"
    report_path = target_path / "report.json"
    report_markdown_path = target_path / "report.md"
    gate_path = target_path / "gate.json"
    gate_markdown_path = target_path / "gate.md"
    suggestions_path = target_path / "suggestions.json"
    suggestions_markdown_path = target_path / "suggestions.md"
    certification_path = target_path / "certification.json"
    certification_markdown_path = target_path / "certification.md"
    claim_path = target_path / "claim.json"
    claim_markdown_path = target_path / "claim.md"
    claim_text_path = target_path / "claim.txt"
    claim_limits_path = target_path / "limits.md"

    if evaluation:
        _write_turn_evaluation_outputs(evaluation_dir, evaluation)
    turn_report.setdefault("outputs", {})
    turn_report["outputs"]["report"] = str(report_path)
    turn_report["outputs"]["markdown"] = str(report_markdown_path)
    gate.setdefault("outputs", {})
    gate["outputs"]["gate"] = str(gate_path)
    gate["outputs"]["markdown"] = str(gate_markdown_path)
    suggestions.setdefault("outputs", {})
    suggestions["outputs"]["suggestions"] = str(suggestions_path)
    suggestions["outputs"]["markdown"] = str(suggestions_markdown_path)
    report.setdefault("outputs", {})
    report["outputs"].update(
        {
            "output_dir": str(target_path),
            "certification": str(certification_path),
            "markdown": str(certification_markdown_path),
            "evaluation_dir": str(evaluation_dir),
            "evaluation": str(evaluation_dir / "evaluation.json"),
            "report": str(report_path),
            "report_markdown": str(report_markdown_path),
            "gate": str(gate_path),
            "gate_markdown": str(gate_markdown_path),
            "suggestions": str(suggestions_path),
            "suggestions_markdown": str(suggestions_markdown_path),
            "claim": str(claim_path),
            "claim_markdown": str(claim_markdown_path),
            "claim_text": str(claim_text_path),
            "claim_limits": str(claim_limits_path),
        }
    )

    report_markdown_path.write_text(format_turn_report_markdown(turn_report), encoding="utf-8")
    _write_json_report(report_path, turn_report)
    gate_markdown_path.write_text(format_turn_gate_markdown(gate), encoding="utf-8")
    _write_json_report(gate_path, gate)
    suggestions_markdown_path.write_text(format_turn_suggestions_markdown(suggestions), encoding="utf-8")
    _write_json_report(suggestions_path, suggestions)
    certification_markdown_path.write_text(format_turn_certification_markdown(report), encoding="utf-8")
    _write_json_report(certification_path, report)
    claim = build_turn_claim(certification_path, evidence_label=str(certification_path))
    write_turn_claim_outputs(target_path, claim)


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
