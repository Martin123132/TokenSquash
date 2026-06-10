from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any, Iterable

from .codec import encode_intent


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
) -> dict[str, Any]:
    """Benchmark original prompts against TokenSquash wire prompts."""

    started = time.time()
    rows = []
    totals = {
        "original_tokens": 0,
        "squashed_tokens": 0,
        "saved_tokens": 0,
        "wins": 0,
        "losses": 0,
        "ties": 0,
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
        if adaptive and wire_tokens >= original_tokens:
            mode = "passthrough"
            squashed_tokens = original_tokens
            payload = text
        saved_tokens = original_tokens - squashed_tokens
        if saved_tokens > 0:
            totals["wins"] += 1
        elif saved_tokens < 0:
            totals["losses"] += 1
        else:
            totals["ties"] += 1
        totals["original_tokens"] += original_tokens
        totals["squashed_tokens"] += squashed_tokens
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
                "saved_tokens": saved_tokens,
                "saved_pct": _pct(saved_tokens, original_tokens),
            }
        )

    total_original = totals["original_tokens"]
    saved_pct = _pct(totals["saved_tokens"], total_original)
    status = "pass" if saved_pct >= target_savings_pct else "miss"
    if total_original <= 0:
        status = "empty"

    return {
        "schema_version": "tokensquash.bench.v1",
        "status": status,
        "counter": counter,
        "adaptive": adaptive,
        "target_savings_pct": target_savings_pct,
        "summary": {
            "prompt_count": len(rows),
            "original_tokens": totals["original_tokens"],
            "squashed_tokens": totals["squashed_tokens"],
            "saved_tokens": totals["saved_tokens"],
            "saved_pct": saved_pct,
            "wins": totals["wins"],
            "losses": totals["losses"],
            "ties": totals["ties"],
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "rows": rows,
    }


def load_prompts(path: Path | str) -> list[str]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"prompt corpus not found: {source}")
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".jsonl":
        prompts = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL row {line_no} must be an object")
            prompt = payload.get("text", payload.get("prompt"))
            if not isinstance(prompt, str):
                raise ValueError(f"JSONL row {line_no} must include text or prompt")
            prompts.append(prompt)
        return prompts
    if "\n\n" in text:
        return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return [line.strip() for line in text.splitlines() if line.strip()]


def format_benchmark_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Benchmark",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Adaptive: `{report.get('adaptive')}`",
        f"- Target savings: `{report.get('target_savings_pct')}%`",
        f"- Prompts: `{summary.get('prompt_count', 0)}`",
        f"- Original tokens: `{summary.get('original_tokens', 0)}`",
        f"- Squashed tokens: `{summary.get('squashed_tokens', 0)}`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Wins/losses/ties: `{summary.get('wins', 0)}/{summary.get('losses', 0)}/{summary.get('ties', 0)}`",
        "",
        "## Rows",
        "",
        "| # | Mode | Original | Squashed | Saved |",
        "|---:|---|---:|---:|---:|",
    ]
    for row in report.get("rows", []):
        lines.append(
            f"| {row.get('index')} | {row.get('mode')} | {row.get('original_tokens')} | "
            f"{row.get('squashed_tokens')} | {row.get('saved_tokens')} ({row.get('saved_pct')}%) |"
        )
    return "\n".join(lines).rstrip() + "\n"


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
