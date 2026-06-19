from __future__ import annotations

from typing import Any


GUIDE_SCHEMA_VERSION = "tokensquash.guide.v1"

_GUIDE_PATHS: list[dict[str, Any]] = [
    {
        "id": "demo",
        "title": "Try TokenSquash on public sample data",
        "best_for": "A quick no-private-data smoke test.",
        "first_command": "python -m tokensquash demo",
        "next_commands": [
            "python -m tokensquash about --json",
            "python -m tokensquash doctor --strict",
        ],
        "docs": "docs/quickstart.md",
    },
    {
        "id": "first-turn",
        "title": "Capture your first real prompt/reply turn",
        "best_for": "One pasted prompt and one pasted assistant reply kept in ignored local storage.",
        "first_command": (
            "python -m tokensquash turns first-run "
            "--prompt-file private-turns/prompt.example.txt --reply-file private-turns/reply.example.txt"
        ),
        "next_commands": [
            "python -m tokensquash turns scorecard private-turns/real.redacted-turns.jsonl",
            "python -m tokensquash turns certify private-turns/real.redacted-turns.jsonl",
        ],
        "docs": "docs/real-turn-workflow.md",
    },
    {
        "id": "corpus",
        "title": "Evaluate and certify a redacted corpus",
        "best_for": "A local JSONL corpus that already contains multiple prompt/reply turns.",
        "first_command": "python -m tokensquash turns scorecard private-turns/real.redacted-turns.jsonl",
        "next_commands": [
            "python -m tokensquash turns scorecard-pack private-turns/real.redacted-turns.jsonl",
            "python -m tokensquash turns certify private-turns/real.redacted-turns.jsonl",
            "python -m tokensquash turns claim-pack private-turns/certification",
        ],
        "docs": "docs/evidence-packs.md",
    },
    {
        "id": "sidecar",
        "title": "Try the experimental local-AI sidecar",
        "best_for": "Checking whether compact semantic JSON survives a round trip.",
        "first_command": (
            "python -m tokensquash sidecar roundtrip prompt "
            '"fix the login bug, run tests, and summarize risks"'
        ),
        "next_commands": [
            "python -m tokensquash sidecar evaluate private-turns/real.redacted-turns.jsonl --out-dir private-turns/sidecar-eval",
            "python -m tokensquash sidecar review private-turns/sidecar-eval/evaluation.json",
            "python -m tokensquash sidecar certify private-turns/sidecar-eval/evaluation.json",
        ],
        "docs": "docs/sidecar-ollama.md",
    },
    {
        "id": "release",
        "title": "Verify release evidence",
        "best_for": "Checking wheel, source distribution, hashes, and public evidence packs.",
        "first_command": "python -m tokensquash release-candidate --require-clean",
        "next_commands": [
            "python -m tokensquash verify-release-candidate private-turns/release-candidate --require-release-candidate-pass",
            "python -m tokensquash release-assets private-turns/release-candidate --tag vX.Y.Z",
            "python -m tokensquash verify-release-assets private-turns/release-assets/release-assets.json",
        ],
        "docs": "docs/release-candidate.md",
    },
]


def build_command_guide(*, path: str = "all") -> dict[str, Any]:
    """Return the beginner-facing command guide."""

    selected = _select_guide_paths(path)
    return {
        "schema_version": GUIDE_SCHEMA_VERSION,
        "status": "pass",
        "path": path,
        "summary": {
            "path_count": len(selected),
            "available_paths": [item["id"] for item in _GUIDE_PATHS],
        },
        "paths": selected,
        "docs": {
            "command_map": "docs/command-map.md",
            "quickstart": "docs/quickstart.md",
            "real_turn_workflow": "docs/real-turn-workflow.md",
        },
    }


def format_command_guide_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TokenSquash Guide",
        "",
        "Pick the path that matches what you are trying to do.",
        "",
    ]
    for item in report.get("paths", []):
        lines.extend(
            [
                f"## {item.get('title')}",
                "",
                f"- Path: `{item.get('id')}`",
                f"- Best for: {item.get('best_for')}",
                f"- Start: `{item.get('first_command')}`",
            ]
        )
        next_commands = item.get("next_commands") or []
        if next_commands:
            lines.extend(["", "Next commands:"])
            for command in next_commands:
                lines.append(f"- `{command}`")
        if item.get("docs"):
            lines.append(f"- Docs: `{item.get('docs')}`")
        lines.append("")

    docs = report.get("docs") or {}
    if docs:
        lines.extend(["## More Help", ""])
        for label, path in sorted(docs.items()):
            lines.append(f"- `{label}`: `{path}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _select_guide_paths(path: str) -> list[dict[str, Any]]:
    if path == "all":
        return [dict(item) for item in _GUIDE_PATHS]
    for item in _GUIDE_PATHS:
        if item["id"] == path:
            return [dict(item)]
    available = ", ".join(["all", *[item["id"] for item in _GUIDE_PATHS]])
    raise ValueError(f"unknown guide path: {path}; choose one of {available}")
