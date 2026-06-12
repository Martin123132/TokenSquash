from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path
from typing import Any

from .demo import DEFAULT_DEMO_CORPUS
from .workspace import GITIGNORE_PATTERNS, WORKSPACE_INIT_SCHEMA_VERSION


MANIFEST_SCHEMA_VERSION = "tokensquash.product.manifest.v1"
PROJECT_NAME = "tokensquash"
PROJECT_DESCRIPTION = "Compact AI-agent intent codec and token-savings benchmark tools."

COMMAND_GROUPS = {
    "core": [
        "encode",
        "decode",
        "bench",
        "compare",
        "init",
        "demo",
        "doctor",
        "readiness",
        "verify-readiness",
        "about",
    ],
    "quality_budget": ["budget init", "budget validate"],
    "corpus": ["corpus stats", "corpus validate", "corpus redact"],
    "reply": ["reply encode", "reply decode", "reply bench", "reply mine", "reply aliases"],
    "turns": [
        "turns add",
        "turns capture",
        "turns import",
        "turns validate",
        "turns stats",
        "turns redact",
        "turns split",
        "turns bench",
        "turns measure",
        "turns diagnose",
        "turns mine",
        "turns aliases",
        "turns alias-impact",
        "turns evaluate",
        "turns report",
        "turns compare-reports",
        "turns compare-certifications",
        "turns certification-history",
        "turns gate",
        "turns certify",
        "turns release-check",
        "turns verify-release",
        "turns suggestions",
    ],
    "sidecar_experimental": [
        "sidecar translate",
        "sidecar decode",
        "sidecar roundtrip",
        "sidecar evaluate",
        "sidecar experiment",
        "sidecar sweep",
        "sidecar review",
        "sidecar suggestions",
        "sidecar gate",
        "sidecar certify",
        "sidecar compare-evaluations",
    ],
}

SUPPORTED_SCHEMAS = [
    ("core", "tokensquash.intent.v1", "Encoded prompt intent JSON."),
    ("core", "tokensquash.reply.v1", "Encoded agent reply JSON."),
    ("core", "tokensquash.bench.v1", "Prompt benchmark report."),
    ("core", "tokensquash.reply.bench.v1", "Reply benchmark report."),
    ("core", "tokensquash.bench.compare.v1", "Benchmark comparison report."),
    ("core", "tokensquash.aliases.v1", "Session alias table and learner report."),
    ("core", "tokensquash.patterns.mine.v1", "Repeated reply-pattern mining report."),
    ("corpus", "tokensquash.corpus.validate.v1", "Prompt corpus validation report."),
    ("corpus", "tokensquash.corpus.stats.v1", "Prompt corpus statistics report."),
    ("corpus", "tokensquash.corpus.privacy.v1", "Privacy finding scan report."),
    ("corpus", "tokensquash.corpus.redact.v1", "Prompt corpus redaction report."),
    ("product", "tokensquash.demo.v1", "Public deterministic demo report."),
    ("product", "tokensquash.doctor.v1", "Install and readiness doctor report."),
    ("product", "tokensquash.readiness.v1", "One-command product-readiness evidence report."),
    ("product", "tokensquash.readiness.verify.v1", "Product-readiness evidence verification report."),
    ("product", MANIFEST_SCHEMA_VERSION, "Product manifest report."),
    ("product", "tokensquash.quality_budget.v1", "Project quality budget for release checks."),
    ("product", "tokensquash.quality_budget.init.v1", "Quality budget initializer report."),
    ("product", "tokensquash.quality_budget.validate.v1", "Quality budget validation report."),
    ("product", WORKSPACE_INIT_SCHEMA_VERSION, "Local private workspace initialization report."),
    ("turns", "tokensquash.turns.validate.v1", "Turn corpus validation report."),
    ("turns", "tokensquash.turns.stats.v1", "Turn corpus statistics report."),
    ("turns", "tokensquash.turns.redact.v1", "Turn corpus redaction report."),
    ("turns", "tokensquash.turns.add.v1", "Append-one-turn report."),
    ("turns", "tokensquash.turns.capture.v1", "Capture raw/redacted/evaluate workflow report."),
    ("turns", "tokensquash.turns.import.v1", "Bulk import raw/redacted/evaluate workflow report."),
    ("turns", "tokensquash.turns.split.v1", "Turn prompt/reply split report."),
    ("turns", "tokensquash.turns.bench.v1", "Paired turn benchmark report."),
    ("turns", "tokensquash.turns.measure.v1", "Turn measurement report."),
    ("turns", "tokensquash.turns.diagnose.v1", "Turn diagnostic report."),
    ("turns", "tokensquash.turns.mine.v1", "Turn pattern mining report."),
    ("turns", "tokensquash.turns.alias_impact.v1", "Turn alias impact report."),
    ("turns", "tokensquash.turns.evaluate.v1", "Full turn evaluation pack report."),
    ("turns", "tokensquash.turns.report.v1", "Compact turn feedback report."),
    ("turns", "tokensquash.turns.report.compare.v1", "Turn report comparison report."),
    ("turns", "tokensquash.turns.certify.compare.v1", "Turn certification comparison report."),
    ("turns", "tokensquash.turns.certify.history.v1", "Turn certification history trend report."),
    ("turns", "tokensquash.turns.gate.v1", "Turn report quality gate."),
    ("turns", "tokensquash.turns.certify.v1", "Turn certification evidence pack."),
    ("turns", "tokensquash.turns.release_check.v1", "Turn release-readiness check report."),
    ("turns", "tokensquash.turns.release_verify.v1", "Turn release evidence verification report."),
    ("turns", "tokensquash.turns.suggestions.v1", "Turn improvement suggestions report."),
    ("sidecar_experimental", "tokensquash.sidecar.request.v1", "Ollama request preview."),
    ("sidecar_experimental", "tokensquash.sidecar.semantic.v1", "Local-AI semantic translation report."),
    ("sidecar_experimental", "tokensquash.sidecar.decode.v1", "Semantic JSON decode report."),
    ("sidecar_experimental", "tokensquash.sidecar.roundtrip.v1", "Semantic round-trip report."),
    ("sidecar_experimental", "tokensquash.sidecar.evaluate.v1", "Sidecar corpus evaluation report."),
    ("sidecar_experimental", "tokensquash.sidecar.evaluate.compare.v1", "Sidecar evaluation comparison."),
    ("sidecar_experimental", "tokensquash.sidecar.review.v1", "Sidecar meaning-risk review report."),
    ("sidecar_experimental", "tokensquash.sidecar.suggestions.v1", "Sidecar tuning suggestions report."),
    ("sidecar_experimental", "tokensquash.sidecar.gate.v1", "Sidecar quality gate."),
    ("sidecar_experimental", "tokensquash.sidecar.certify.v1", "Sidecar certification pack."),
    ("sidecar_experimental", "tokensquash.sidecar.experiment.v1", "Named sidecar experiment pack."),
    ("sidecar_experimental", "tokensquash.sidecar.sweep.v1", "Sidecar experiment sweep report."),
    ("sidecar_experimental", "tokensquash.sidecar.sweep.compare.v1", "Sidecar sweep comparison report."),
]

READINESS_COMMANDS = [
    "python -m tokensquash readiness --out-dir private-turns\\readiness",
    "python -m tokensquash verify-readiness private-turns\\readiness --require-readiness-pass",
    "python -m unittest discover -s tests",
    "python -m tokensquash init --dry-run",
    "python -m tokensquash budget init --out private-turns\\quality-budget.json --dry-run --json",
    "python -m tokensquash budget validate examples\\quality-budget.json",
    "python -m tokensquash doctor --strict",
    "python -m tokensquash demo --counter chars --out-dir private-turns\\demo-output",
    "python -m tokensquash turns certify examples\\sample-turns.jsonl --counter chars --out-dir private-turns\\certification",
    "python -m tokensquash turns release-check examples\\sample-turns.jsonl --counter chars --budget examples\\quality-budget.json --history private-turns\\certification --out-dir private-turns\\release-check",
    "python -m tokensquash turns verify-release private-turns\\release-check --require-release-pass",
]

PRIVATE_STORAGE_PATTERNS = list(GITIGNORE_PATTERNS)


def build_product_manifest(*, cwd: Path | str | None = None) -> dict[str, Any]:
    """Return the public product manifest for the installed TokenSquash package."""

    root = Path(cwd) if cwd is not None else Path.cwd()
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "pass",
        "project": {
            "name": PROJECT_NAME,
            "version": package_version(root),
            "description": PROJECT_DESCRIPTION,
            "requires_python": package_requires_python(root),
            "console_script": "tokensquash = tokensquash.cli:main",
        },
        "protocols": [
            {
                "name": "TokenSquash prompt intent",
                "wire_version": "ts1",
                "schema_version": "tokensquash.intent.v1",
                "stability": "deterministic_core",
            },
            {
                "name": "TokenSquash agent reply",
                "wire_version": "tr1",
                "schema_version": "tokensquash.reply.v1",
                "stability": "deterministic_core",
            },
            {
                "name": "Local-AI semantic sidecar",
                "wire_version": "semantic-json",
                "schema_version": "tokensquash.sidecar.semantic.v1",
                "stability": "experimental",
            },
        ],
        "commands": [
            {"group": group, "command": command}
            for group, commands in COMMAND_GROUPS.items()
            for command in commands
        ],
        "schemas": [
            {"category": category, "schema_version": schema, "purpose": purpose}
            for category, schema, purpose in SUPPORTED_SCHEMAS
        ],
        "readiness": {
            "strict_doctor": "python -m tokensquash doctor --strict",
            "commands": READINESS_COMMANDS,
            "private_storage_patterns": PRIVATE_STORAGE_PATTERNS,
        },
        "data": {
            "packaged_demo_corpus": str(DEFAULT_DEMO_CORPUS),
            "packaged_demo_corpus_exists": DEFAULT_DEMO_CORPUS.exists(),
        },
        "counts": {
            "command_count": sum(len(commands) for commands in COMMAND_GROUPS.values()),
            "schema_count": len(SUPPORTED_SCHEMAS),
            "readiness_command_count": len(READINESS_COMMANDS),
        },
    }


def format_product_manifest_markdown(report: dict[str, Any]) -> str:
    project = report.get("project", {})
    counts = report.get("counts", {})
    lines = [
        "# TokenSquash Product Manifest",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Name: `{project.get('name')}`",
        f"- Version: `{project.get('version')}`",
        f"- Requires Python: `{project.get('requires_python')}`",
        f"- Commands: `{counts.get('command_count', 0)}`",
        f"- Schemas: `{counts.get('schema_count', 0)}`",
        f"- Readiness commands: `{counts.get('readiness_command_count', 0)}`",
        "",
        "## Protocols",
        "",
        "| Protocol | Wire | Schema | Stability |",
        "|---|---|---|---|",
    ]
    for protocol in report.get("protocols", []):
        lines.append(
            "| "
            f"{_markdown_cell(str(protocol.get('name', '')))} | "
            f"`{_markdown_cell(str(protocol.get('wire_version', '')))}` | "
            f"`{_markdown_cell(str(protocol.get('schema_version', '')))}` | "
            f"`{_markdown_cell(str(protocol.get('stability', '')))}` |"
        )
    lines.extend(["", "## Command Groups", ""])
    for group in COMMAND_GROUPS:
        commands = [item.get("command") for item in report.get("commands", []) if item.get("group") == group]
        lines.append(f"- `{group}`: `{len(commands)}` commands")
    lines.extend(["", "## Readiness", ""])
    for command in (report.get("readiness") or {}).get("commands", []):
        lines.append(f"- `{command}`")
    lines.extend(["", "## Schemas", ""])
    for item in report.get("schemas", []):
        lines.append(
            "- "
            f"`{item.get('schema_version')}` "
            f"({item.get('category')}): {item.get('purpose')}"
        )
    return "\n".join(lines).rstrip() + "\n"


def package_version(cwd: Path | str | None = None) -> str:
    try:
        return metadata.version(PROJECT_NAME)
    except metadata.PackageNotFoundError:
        return _pyproject_value(Path(cwd) if cwd is not None else Path.cwd(), "version") or "0.0.0"


def package_requires_python(cwd: Path | str | None = None) -> str:
    try:
        value = metadata.metadata(PROJECT_NAME).get("Requires-Python")
        if value:
            return value
    except metadata.PackageNotFoundError:
        pass
    return _pyproject_value(Path(cwd) if cwd is not None else Path.cwd(), "requires-python") or ">=3.10"


def _pyproject_value(cwd: Path, key: str) -> str | None:
    pyproject = _find_upwards(cwd, "pyproject.toml")
    if pyproject is None:
        return None
    match = re.search(rf"^{re.escape(key)}\s*=\s*\"([^\"]+)\"", pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def _find_upwards(start: Path, filename: str) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        path = candidate / filename
        if path.exists():
            return path
    return None


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
