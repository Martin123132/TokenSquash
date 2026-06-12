from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metrics import (
    benchmark_prompts,
    benchmark_replies,
    format_benchmark_markdown,
    format_reply_benchmark_markdown,
    load_prompts,
    load_reply_records,
)


BASELINE_VERIFY_SCHEMA_VERSION = "tokensquash.baselines.verify.v1"


@dataclass(frozen=True)
class _BaselineSpec:
    name: str
    artifact: Path
    kind: str
    output_format: str
    source_path: Path
    source_label: str
    counter: str
    exact_tokenizer: bool = False


BASELINE_SPECS = (
    _BaselineSpec(
        "messy-heuristic-markdown",
        Path("messy-heuristic.md"),
        "prompt",
        "markdown",
        Path("examples/messy-coding-prompts.jsonl"),
        "examples\\messy-coding-prompts.jsonl",
        "heuristic",
    ),
    _BaselineSpec(
        "messy-char4-json",
        Path("messy-char4.json"),
        "prompt",
        "json",
        Path("examples/messy-coding-prompts.jsonl"),
        "examples\\messy-coding-prompts.jsonl",
        "char4",
    ),
    _BaselineSpec(
        "messy-cl100k-json",
        Path("messy-cl100k.json"),
        "prompt",
        "json",
        Path("examples/messy-coding-prompts.jsonl"),
        "examples\\messy-coding-prompts.jsonl",
        "tiktoken:cl100k_base",
        exact_tokenizer=True,
    ),
    _BaselineSpec(
        "messy-cl100k-markdown",
        Path("messy-cl100k.md"),
        "prompt",
        "markdown",
        Path("examples/messy-coding-prompts.jsonl"),
        "examples\\messy-coding-prompts.jsonl",
        "tiktoken:cl100k_base",
        exact_tokenizer=True,
    ),
    _BaselineSpec(
        "messy-o200k-json",
        Path("messy-o200k.json"),
        "prompt",
        "json",
        Path("examples/messy-coding-prompts.jsonl"),
        "examples\\messy-coding-prompts.jsonl",
        "tiktoken:o200k_base",
        exact_tokenizer=True,
    ),
    _BaselineSpec(
        "messy-o200k-markdown",
        Path("messy-o200k.md"),
        "prompt",
        "markdown",
        Path("examples/messy-coding-prompts.jsonl"),
        "examples\\messy-coding-prompts.jsonl",
        "tiktoken:o200k_base",
        exact_tokenizer=True,
    ),
    _BaselineSpec(
        "replies-cl100k-json",
        Path("replies-cl100k.json"),
        "reply",
        "json",
        Path("examples/agent-replies.jsonl"),
        "examples\\agent-replies.jsonl",
        "tiktoken:cl100k_base",
        exact_tokenizer=True,
    ),
    _BaselineSpec(
        "replies-cl100k-markdown",
        Path("replies-cl100k.md"),
        "reply",
        "markdown",
        Path("examples/agent-replies.jsonl"),
        "examples\\agent-replies.jsonl",
        "tiktoken:cl100k_base",
        exact_tokenizer=True,
    ),
    _BaselineSpec(
        "replies-o200k-json",
        Path("replies-o200k.json"),
        "reply",
        "json",
        Path("examples/agent-replies.jsonl"),
        "examples\\agent-replies.jsonl",
        "tiktoken:o200k_base",
        exact_tokenizer=True,
    ),
    _BaselineSpec(
        "replies-o200k-markdown",
        Path("replies-o200k.md"),
        "reply",
        "markdown",
        Path("examples/agent-replies.jsonl"),
        "examples\\agent-replies.jsonl",
        "tiktoken:o200k_base",
        exact_tokenizer=True,
    ),
)


def verify_benchmark_baselines(
    *,
    benchmarks_dir: Path | str = Path("benchmarks"),
    include_exact_tokenizer: bool = False,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Regenerate public benchmark baselines and compare them with committed artifacts."""

    started = time.time()
    repo_root = Path(root) if root is not None else Path.cwd()
    target_display_dir = Path(benchmarks_dir)
    target_dir = target_display_dir if target_display_dir.is_absolute() else repo_root / target_display_dir
    rows = []
    for spec in BASELINE_SPECS:
        rows.append(
            _verify_baseline_spec(
                spec,
                repo_root=repo_root,
                benchmarks_dir=target_dir,
                display_dir=target_display_dir,
                include_exact_tokenizer=include_exact_tokenizer,
            )
        )
    failed = [row for row in rows if row.get("status") == "fail"]
    skipped = [row for row in rows if row.get("status") == "skip"]
    status = "fail" if failed else "partial" if skipped else "pass"
    return {
        "schema_version": BASELINE_VERIFY_SCHEMA_VERSION,
        "status": status,
        "benchmarks_dir": str(target_display_dir),
        "include_exact_tokenizer": include_exact_tokenizer,
        "summary": {
            "artifact_count": len(rows),
            "verified_count": sum(1 for row in rows if row.get("status") == "pass"),
            "failed_count": len(failed),
            "skipped_count": len(skipped),
            "exact_tokenizer_artifact_count": sum(1 for row in rows if row.get("exact_tokenizer")),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "artifacts": rows,
    }


def format_benchmark_baseline_verify_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Benchmark Baseline Verify",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Benchmarks dir: `{report.get('benchmarks_dir')}`",
        f"- Include exact tokenizer: `{report.get('include_exact_tokenizer')}`",
        f"- Artifacts: `{summary.get('artifact_count', 0)}`",
        f"- Verified: `{summary.get('verified_count', 0)}`",
        f"- Failed: `{summary.get('failed_count', 0)}`",
        f"- Skipped: `{summary.get('skipped_count', 0)}`",
        "",
        "## Artifacts",
        "",
        "| Artifact | Status | Counter | Format | Detail |",
        "|---|---|---|---|---|",
    ]
    for row in report.get("artifacts", []):
        lines.append(
            "| "
            f"`{_markdown_cell(str(row.get('path', '')))}` | "
            f"`{row.get('status')}` | "
            f"`{row.get('counter')}` | "
            f"`{row.get('format')}` | "
            f"{_markdown_cell(str(row.get('message', '')))} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _verify_baseline_spec(
    spec: _BaselineSpec,
    *,
    repo_root: Path,
    benchmarks_dir: Path,
    display_dir: Path,
    include_exact_tokenizer: bool,
) -> dict[str, Any]:
    target = benchmarks_dir / spec.artifact
    display_target = display_dir / spec.artifact
    base = {
        "name": spec.name,
        "path": str(display_target),
        "kind": spec.kind,
        "format": spec.output_format,
        "counter": spec.counter,
        "source": spec.source_label,
        "exact_tokenizer": spec.exact_tokenizer,
    }
    if spec.exact_tokenizer and not include_exact_tokenizer:
        return {
            **base,
            "status": "skip",
            "message": "Exact-tokenizer baseline skipped. Pass --include-exact-tokenizer to verify it.",
        }
    if spec.exact_tokenizer and not _tiktoken_available():
        return {
            **base,
            "status": "fail",
            "message": "Exact-tokenizer baseline requires the tiktoken extra.",
        }
    if not target.exists():
        return {**base, "status": "fail", "message": f"Missing baseline artifact: {target}."}
    try:
        generated_report = _generate_baseline_report(spec, repo_root=repo_root)
        if spec.output_format == "json":
            return _verify_json_baseline(base, target, generated_report)
        return _verify_markdown_baseline(base, target, generated_report, spec)
    except Exception as exc:
        return {**base, "status": "fail", "message": f"Could not verify baseline: {exc}"}


def _generate_baseline_report(spec: _BaselineSpec, *, repo_root: Path) -> dict[str, Any]:
    source = repo_root / spec.source_path
    if spec.kind == "prompt":
        return benchmark_prompts(
            load_prompts(source),
            counter=spec.counter,
            source=spec.source_label,
        )
    if spec.kind == "reply":
        return benchmark_replies(
            load_reply_records(source),
            counter=spec.counter,
            source=spec.source_label,
        )
    raise ValueError(f"unsupported baseline kind: {spec.kind}")


def _verify_json_baseline(base: dict[str, Any], target: Path, generated_report: dict[str, Any]) -> dict[str, Any]:
    actual = json.loads(target.read_text(encoding="utf-8-sig"))
    expected = _normalize_benchmark_report(generated_report)
    observed = _normalize_benchmark_report(actual)
    if observed == expected:
        summary = generated_report.get("summary", {})
        return {
            **base,
            "status": "pass",
            "message": "Committed JSON baseline matches regenerated output.",
            "summary": _baseline_summary(summary),
        }
    return {
        **base,
        "status": "fail",
        "message": "Committed JSON baseline is stale.",
        "mismatch": _json_mismatch(observed, expected),
    }


def _verify_markdown_baseline(
    base: dict[str, Any],
    target: Path,
    generated_report: dict[str, Any],
    spec: _BaselineSpec,
) -> dict[str, Any]:
    if spec.kind == "prompt":
        expected_text = format_benchmark_markdown(generated_report)
    else:
        expected_text = format_reply_benchmark_markdown(generated_report)
    actual_text = _normalize_text(target.read_text(encoding="utf-8-sig"))
    expected_text = _normalize_text(expected_text)
    if actual_text == expected_text:
        summary = generated_report.get("summary", {})
        return {
            **base,
            "status": "pass",
            "message": "Committed Markdown baseline matches regenerated output.",
            "summary": _baseline_summary(summary),
        }
    return {
        **base,
        "status": "fail",
        "message": "Committed Markdown baseline is stale.",
        "mismatch": _text_mismatch(actual_text, expected_text),
    }


def _normalize_benchmark_report(report: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(report, ensure_ascii=True, sort_keys=True))
    summary = clone.get("summary")
    if isinstance(summary, dict):
        summary.pop("elapsed_seconds", None)
    return clone


def _baseline_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "saved_pct": summary.get("saved_pct"),
        "wire_saved_pct": summary.get("wire_saved_pct"),
        "saved_tokens": summary.get("saved_tokens"),
        "passthroughs": summary.get("passthroughs"),
        "item_count": summary.get("prompt_count", summary.get("reply_count")),
    }


def _json_mismatch(observed: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    for key in ("schema_version", "status", "counter", "adaptive", "source", "target_savings_pct"):
        if observed.get(key) != expected.get(key):
            return {"field": key, "actual": observed.get(key), "expected": expected.get(key)}
    observed_summary = observed.get("summary", {})
    expected_summary = expected.get("summary", {})
    if observed_summary != expected_summary:
        return {"field": "summary", "actual": observed_summary, "expected": expected_summary}
    observed_rows = observed.get("rows", [])
    expected_rows = expected.get("rows", [])
    if len(observed_rows) != len(expected_rows):
        return {"field": "rows", "actual_count": len(observed_rows), "expected_count": len(expected_rows)}
    for index, (observed_row, expected_row) in enumerate(zip(observed_rows, expected_rows), start=1):
        if observed_row != expected_row:
            return {"field": f"rows[{index}]", "actual": observed_row, "expected": expected_row}
    return {"field": "report", "actual": "differs", "expected": "regenerated output"}


def _text_mismatch(actual: str, expected: str) -> dict[str, Any]:
    actual_lines = actual.splitlines()
    expected_lines = expected.splitlines()
    for index, (actual_line, expected_line) in enumerate(zip(actual_lines, expected_lines), start=1):
        if actual_line != expected_line:
            return {"line": index, "actual": actual_line, "expected": expected_line}
    return {"line": min(len(actual_lines), len(expected_lines)) + 1, "actual_count": len(actual_lines), "expected_count": len(expected_lines)}


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip() + "\n"


def _tiktoken_available() -> bool:
    try:
        import tiktoken  # type: ignore[import-not-found]
    except Exception:
        return False
    return tiktoken is not None


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
