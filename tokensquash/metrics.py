from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any, Iterable

from .codec import encode_intent
from .corpus import load_prompt_records


_WORD_OR_PUNCT_RE = re.compile(r"[A-Za-z0-9_/-]+|[^\w\s]", re.UNICODE)


def count_tokens(text: str, counter: str = "heuristic") -> int:
    """Count tokens with a dependency-free estimator.

    `heuristic` is not a model tokenizer. It approximates BPE-ish behavior well
    enough for local before/after comparisons and keeps the MVP dependency-free.
    """

    if counter == "chars":
        return len(text)
    if counter == "char4":
        return max(1, math.ceil(len(text) / 4))
    if counter == "heuristic":
        total = 0
        for item in _WORD_OR_PUNCT_RE.findall(text):
            if re.fullmatch(r"[A-Za-z0-9_/-]+", item):
                total += max(1, math.ceil(len(item) / 4))
            else:
                total += 1
        return total
    if counter.startswith("tiktoken:"):
        return _count_tiktoken(text, counter.split(":", 1)[1] or "cl100k_base")
    raise ValueError("counter must be one of: heuristic, chars, char4, tiktoken:<encoding>")


def benchmark_prompts(
    prompts: Iterable[str],
    *,
    counter: str = "heuristic",
    target_savings_pct: float = 0.5,
    adaptive: bool = True,
    source: str | None = None,
) -> dict[str, Any]:
    """Benchmark original prompts against TokenSquash wire prompts."""

    started = time.time()
    rows = []
    totals = {
        "original_tokens": 0,
        "wire_tokens": 0,
        "squashed_tokens": 0,
        "wire_saved_tokens": 0,
        "saved_tokens": 0,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "wire_wins": 0,
        "wire_losses": 0,
        "wire_ties": 0,
        "passthroughs": 0,
    }

    for index, prompt in enumerate(prompts, start=1):
        text = prompt.strip()
        if not text:
            continue
        intent = encode_intent(text)
        wire = intent.to_wire()
        original_tokens = count_tokens(text, counter)
        wire_tokens = count_tokens(wire, counter)
        mode = "compact"
        squashed_tokens = wire_tokens
        payload = wire
        wire_saved_tokens = original_tokens - wire_tokens
        if adaptive and wire_tokens >= original_tokens:
            mode = "passthrough"
            squashed_tokens = original_tokens
            payload = text
            totals["passthroughs"] += 1
        saved_tokens = original_tokens - squashed_tokens
        if wire_saved_tokens > 0:
            totals["wire_wins"] += 1
        elif wire_saved_tokens < 0:
            totals["wire_losses"] += 1
        else:
            totals["wire_ties"] += 1
        if saved_tokens > 0:
            totals["wins"] += 1
        elif saved_tokens < 0:
            totals["losses"] += 1
        else:
            totals["ties"] += 1
        totals["original_tokens"] += original_tokens
        totals["wire_tokens"] += wire_tokens
        totals["squashed_tokens"] += squashed_tokens
        totals["wire_saved_tokens"] += wire_saved_tokens
        totals["saved_tokens"] += saved_tokens
        rows.append(
            {
                "index": index,
                "original": text,
                "wire": wire,
                "payload": payload,
                "mode": mode,
                "op": intent.op,
                "original_tokens": original_tokens,
                "wire_tokens": wire_tokens,
                "squashed_tokens": squashed_tokens,
                "wire_saved_tokens": wire_saved_tokens,
                "wire_saved_pct": _pct(wire_saved_tokens, original_tokens),
                "saved_tokens": saved_tokens,
                "saved_pct": _pct(saved_tokens, original_tokens),
            }
        )

    total_original = totals["original_tokens"]
    saved_pct = _pct(totals["saved_tokens"], total_original)
    wire_saved_pct = _pct(totals["wire_saved_tokens"], total_original)
    status = "pass" if saved_pct >= target_savings_pct else "miss"
    if total_original <= 0:
        status = "empty"

    return {
        "schema_version": "tokensquash.bench.v1",
        "status": status,
        "counter": counter,
        "adaptive": adaptive,
        "source": source,
        "target_savings_pct": target_savings_pct,
        "summary": {
            "prompt_count": len(rows),
            "original_tokens": totals["original_tokens"],
            "wire_tokens": totals["wire_tokens"],
            "squashed_tokens": totals["squashed_tokens"],
            "wire_saved_tokens": totals["wire_saved_tokens"],
            "wire_saved_pct": wire_saved_pct,
            "saved_tokens": totals["saved_tokens"],
            "saved_pct": saved_pct,
            "wire_wins": totals["wire_wins"],
            "wire_losses": totals["wire_losses"],
            "wire_ties": totals["wire_ties"],
            "wins": totals["wins"],
            "losses": totals["losses"],
            "ties": totals["ties"],
            "passthroughs": totals["passthroughs"],
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "rows": rows,
    }


def load_prompts(path: Path | str) -> list[str]:
    return [str(record["text"]) for record in load_prompt_records(path)]


def compare_benchmarks(base: Path | str, target: Path | str) -> dict[str, Any]:
    """Compare two benchmark JSON reports."""

    base_report = _load_benchmark_report(base)
    target_report = _load_benchmark_report(target)
    base_summary = base_report.get("summary", {})
    target_summary = target_report.get("summary", {})
    saved_delta = float(target_summary.get("saved_pct", 0.0)) - float(base_summary.get("saved_pct", 0.0))
    wire_delta = float(target_summary.get("wire_saved_pct", 0.0)) - float(base_summary.get("wire_saved_pct", 0.0))
    token_delta = int(target_summary.get("saved_tokens", 0)) - int(base_summary.get("saved_tokens", 0))
    status = "improved" if saved_delta > 0 else "regressed" if saved_delta < 0 else "same"
    return {
        "schema_version": "tokensquash.bench.compare.v1",
        "status": status,
        "base": _benchmark_identity(base, base_report),
        "target": _benchmark_identity(target, target_report),
        "delta": {
            "saved_pct": round(saved_delta, 4),
            "wire_saved_pct": round(wire_delta, 4),
            "saved_tokens": token_delta,
            "passthroughs": int(target_summary.get("passthroughs", 0)) - int(base_summary.get("passthroughs", 0)),
        },
    }


def format_benchmark_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Benchmark",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Adaptive: `{report.get('adaptive')}`",
        f"- Source: `{report.get('source') or 'inline'}`",
        f"- Target savings: `{report.get('target_savings_pct')}%`",
        f"- Prompts: `{summary.get('prompt_count', 0)}`",
        f"- Original tokens: `{summary.get('original_tokens', 0)}`",
        f"- Raw wire tokens: `{summary.get('wire_tokens', 0)}`",
        f"- Squashed tokens: `{summary.get('squashed_tokens', 0)}`",
        f"- Raw wire saved: `{summary.get('wire_saved_tokens', 0)} ({summary.get('wire_saved_pct', 0.0)}%)`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Raw wire wins/losses/ties: `{summary.get('wire_wins', 0)}/{summary.get('wire_losses', 0)}/{summary.get('wire_ties', 0)}`",
        f"- Adaptive wins/losses/ties: `{summary.get('wins', 0)}/{summary.get('losses', 0)}/{summary.get('ties', 0)}`",
        f"- Pass-through rows: `{summary.get('passthroughs', 0)}`",
        "",
        "## Rows",
        "",
        "| # | Mode | Original | Wire | Squashed | Saved |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for row in report.get("rows", []):
        lines.append(
            f"| {row.get('index')} | {row.get('mode')} | {row.get('original_tokens')} | "
            f"{row.get('wire_tokens')} | {row.get('squashed_tokens')} | "
            f"{row.get('saved_tokens')} ({row.get('saved_pct')}%) |"
        )
    return "\n".join(lines).rstrip() + "\n"


def format_benchmark_compare_markdown(report: dict[str, Any]) -> str:
    delta = report.get("delta", {})
    base = report.get("base", {})
    target = report.get("target", {})
    return "\n".join(
        [
            "# TokenSquash Benchmark Compare",
            "",
            f"- Status: `{report.get('status')}`",
            f"- Base: `{base.get('path')}` saved=`{base.get('saved_pct')}%` raw=`{base.get('wire_saved_pct')}%`",
            f"- Target: `{target.get('path')}` saved=`{target.get('saved_pct')}%` raw=`{target.get('wire_saved_pct')}%`",
            f"- Saved percent delta: `{delta.get('saved_pct')}%`",
            f"- Raw wire percent delta: `{delta.get('wire_saved_pct')}%`",
            f"- Saved token delta: `{delta.get('saved_tokens')}`",
            f"- Pass-through row delta: `{delta.get('passthroughs')}`",
            "",
        ]
    )


def _count_tiktoken(text: str, encoding_name: str) -> int:
    try:
        import tiktoken  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError("tiktoken counter requested but tiktoken is not installed") from exc
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(text))


def _pct(part: int | float, whole: int | float) -> float:
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100.0, 4)


def _load_benchmark_report(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "tokensquash.bench.v1":
        raise ValueError(f"Not a TokenSquash benchmark report: {source}")
    return payload


def _benchmark_identity(path: Path | str, report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    return {
        "path": str(path),
        "counter": report.get("counter"),
        "adaptive": report.get("adaptive"),
        "source": report.get("source"),
        "prompt_count": summary.get("prompt_count"),
        "saved_pct": summary.get("saved_pct"),
        "wire_saved_pct": summary.get("wire_saved_pct"),
        "saved_tokens": summary.get("saved_tokens"),
        "passthroughs": summary.get("passthroughs"),
    }
