from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .turns import evaluate_turn_corpus


DEFAULT_DEMO_CORPUS = Path(__file__).resolve().parent / "data" / "sample-turns.jsonl"


def run_demo(
    corpus: Path | str = DEFAULT_DEMO_CORPUS,
    *,
    counter: str = "heuristic",
    target_savings_pct: float = 0.0,
    out_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run the deterministic public TokenSquash demo workflow."""

    started = time.time()
    source = Path(corpus)
    evaluation_out_dir = Path(out_dir) / "turn-evaluation" if out_dir is not None else None
    evaluation = evaluate_turn_corpus(
        source,
        counter=counter,
        target_savings_pct=target_savings_pct,
        out_dir=evaluation_out_dir,
    )
    evaluation_summary = evaluation.get("summary", {})
    outputs: dict[str, str] = {}
    if evaluation_out_dir is not None:
        outputs["turn_evaluation_dir"] = str(evaluation_out_dir)
        outputs.update(
            {
                f"turn_{key}": value
                for key, value in (evaluation.get("outputs") or {}).items()
            }
        )
    return {
        "schema_version": "tokensquash.demo.v1",
        "status": evaluation.get("status", "fail"),
        "corpus": str(source),
        "counter": counter,
        "target_savings_pct": target_savings_pct,
        "summary": {
            "turn_count": int(evaluation_summary.get("turn_count", 0)),
            "privacy_finding_count": int(evaluation_summary.get("privacy_finding_count", 0)),
            "saved_pct": float(evaluation_summary.get("saved_pct", 0.0)),
            "prompt_saved_pct": float(evaluation_summary.get("prompt_saved_pct", 0.0)),
            "reply_saved_pct": float(evaluation_summary.get("reply_saved_pct", 0.0)),
            "selected_path_prefix_count": int(evaluation_summary.get("selected_path_prefix_count", 0)),
            "selected_field_value_count": int(evaluation_summary.get("selected_field_value_count", 0)),
            "alias_saved_tokens_delta": int(evaluation_summary.get("alias_saved_tokens_delta", 0)),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "commands": _demo_commands(source, counter=counter, target_savings_pct=target_savings_pct),
        "outputs": outputs,
        "evaluation": evaluation,
    }


def format_demo_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs") or {}
    commands = report.get("commands") or {}
    lines = [
        "# TokenSquash Demo",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Corpus: `{report.get('corpus')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Target saved percent: `{report.get('target_savings_pct', 0.0)}%`",
        f"- Turns: `{summary.get('turn_count', 0)}`",
        f"- Privacy findings: `{summary.get('privacy_finding_count', 0)}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Prompt saved percent: `{summary.get('prompt_saved_pct', 0.0)}%`",
        f"- Reply saved percent: `{summary.get('reply_saved_pct', 0.0)}%`",
        f"- Selected path aliases: `{summary.get('selected_path_prefix_count', 0)}`",
        f"- Selected field aliases: `{summary.get('selected_field_value_count', 0)}`",
        f"- Alias saved token delta: `{summary.get('alias_saved_tokens_delta', 0)}`",
        "",
        "## Try Next",
        "",
    ]
    for key in ("evaluate", "report", "suggestions"):
        command = commands.get(key)
        if command:
            lines.append(f"- `{command}`")
    if outputs:
        lines.extend(["", "## Outputs", ""])
        for key, path in sorted(outputs.items()):
            lines.append(f"- `{key}`: `{path}`")
    return "\n".join(lines).rstrip() + "\n"


def _demo_commands(source: Path, *, counter: str, target_savings_pct: float) -> dict[str, str]:
    corpus = _quote_command_arg(str(source))
    return {
        "evaluate": (
            f"python -m tokensquash turns evaluate {corpus} "
            f"--counter {counter} --target {target_savings_pct}"
        ),
        "report": f"python -m tokensquash turns report {corpus} --counter {counter}",
        "suggestions": f"python -m tokensquash turns suggestions <saved-report.json>",
    }


def _quote_command_arg(value: str) -> str:
    if any(char.isspace() for char in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def write_demo_outputs(out_dir: Path | str, report: dict[str, Any]) -> None:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    demo_path = target / "demo.json"
    markdown_path = target / "demo.md"
    report.setdefault("outputs", {})
    report["outputs"]["demo"] = str(demo_path)
    report["outputs"]["markdown"] = str(markdown_path)
    markdown_path.write_text(format_demo_markdown(report), encoding="utf-8")
    demo_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
