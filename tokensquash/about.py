from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path
from typing import Any

from .demo import DEFAULT_DEMO_CORPUS
from .workspace import GITIGNORE_PATTERNS, WORKSPACE_INIT_SCHEMA_VERSION


MANIFEST_SCHEMA_VERSION = "tokensquash.product.manifest.v1"
PROJECT_NAME = "tokensquash"
PROJECT_DESCRIPTION = (
    "Local-first codec and evidence harness for measuring whether AI-agent task/reply traffic "
    "can be made shorter without losing meaning."
)
PUBLIC_LICENSE_NAME = "PolyForm Noncommercial License 1.0.0"
PUBLIC_LICENSE_PATH = "LICENSE"
COMMERCIAL_LICENSE_PATH = "COMMERCIAL-LICENSE.md"
LICENSOR = "TWO HANDS NETWORK LTD"
COMMERCIAL_CONTACT = "Glyn Evans <glyn@twohandsnetwork.co.uk>"

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
        "release-info",
        "release-candidate",
        "verify-release-candidate",
        "release-assets",
        "verify-release-assets",
        "about",
    ],
    "benchmark_baselines": ["baselines verify"],
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
        "turns scorecard",
        "turns scorecard-pack",
        "turns compare-reports",
        "turns compare-scorecards",
        "turns scorecard-history",
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
    ("core", "tokensquash.baselines.verify.v1", "Committed benchmark baseline verification report."),
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
    ("product", "tokensquash.release_info.v1", "Release package, Git, and runtime metadata report."),
    ("product", "tokensquash.release_candidate.v1", "Pre-release product gate and packaging evidence report."),
    ("product", "tokensquash.release_candidate.artifacts.v1", "Release-candidate artifact hash manifest."),
    ("product", "tokensquash.release_candidate.attestation.v1", "Release-candidate provenance and verification attestation."),
    ("product", "tokensquash.release_candidate.verify.v1", "Release-candidate evidence verification report."),
    ("product", "tokensquash.release_assets.v1", "Verified public release asset staging and upload report."),
    ("product", "tokensquash.release_assets.verify.v1", "Public release asset hash and schema verification report."),
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
    ("turns", "tokensquash.turns.scorecard.v1", "Real turn corpus scorecard and growth dashboard."),
    ("turns", "tokensquash.turns.scorecard.pack.v1", "Turn scorecard evidence pack report."),
    ("turns", "tokensquash.turns.report.compare.v1", "Turn report comparison report."),
    ("turns", "tokensquash.turns.scorecard.compare.v1", "Turn scorecard comparison report."),
    ("turns", "tokensquash.turns.scorecard.history.v1", "Turn scorecard history trend report."),
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
    "python -m tokensquash release-info --json",
    "python -m tokensquash release-candidate --out-dir private-turns\\release-candidate",
    "python -m tokensquash verify-release-candidate private-turns\\release-candidate --require-release-candidate-pass",
    "python -m tokensquash release-assets private-turns\\release-candidate --tag v0.1.1 --update-verification-doc docs\\release-verification.md",
    "python -m tokensquash verify-release-assets private-turns\\release-assets\\release-assets.json",
    "python -m tokensquash baselines verify",
    "python -m unittest discover -s tests",
    "python -m tokensquash init --dry-run",
    "python -m tokensquash budget init --out private-turns\\quality-budget.json --dry-run --json",
    "python -m tokensquash budget validate examples\\quality-budget.json",
    "python -m tokensquash doctor --strict",
    "python -m tokensquash demo --counter chars --out-dir private-turns\\demo-output",
    "python -m tokensquash turns scorecard examples\\sample-turns.jsonl --counter chars",
    "python -m tokensquash turns scorecard-pack examples\\sample-turns.jsonl --counter chars --out-dir private-turns\\scorecard-pack",
    "python -m tokensquash turns compare-scorecards private-turns\\scorecard-before.json private-turns\\scorecard-after.json",
    "python -m tokensquash turns scorecard-history private-turns\\scorecard-before.json private-turns\\scorecard-after.json",
    "python -m tokensquash turns certify examples\\sample-turns.jsonl --counter chars --out-dir private-turns\\certification",
    "python -m tokensquash turns release-check examples\\sample-turns.jsonl --counter chars --budget examples\\quality-budget.json --history private-turns\\certification --out-dir private-turns\\release-check",
    "python -m tokensquash turns verify-release private-turns\\release-check --require-release-pass",
]

PRIVATE_STORAGE_PATTERNS = list(GITIGNORE_PATTERNS)

GOVERNANCE_DOCUMENTS = [
    {"path": "README.md", "purpose": "Project overview, examples, readiness commands, and contributor links."},
    {"path": PUBLIC_LICENSE_PATH, "purpose": "Public source-available non-commercial license terms and required notices."},
    {
        "path": COMMERCIAL_LICENSE_PATH,
        "purpose": "Commercial-use examples, request details, licensor, and approved contact channel.",
    },
    {"path": "CHANGELOG.md", "purpose": "User-facing change history and release notes."},
    {"path": "ROADMAP.md", "purpose": "Public product direction, stability boundaries, and evidence bar."},
    {"path": "CONTRIBUTING.md", "purpose": "Contributor setup, quality gates, privacy rules, and release expectations."},
    {"path": "SECURITY.md", "purpose": "Security support, vulnerability reporting, and private-data handling policy."},
    {"path": "docs/quickstart.md", "purpose": "First commands, demo output shape, and health-check workflow."},
    {"path": "docs/real-turn-workflow.md", "purpose": "Private turn capture, redaction, reporting, gating, and certification workflow."},
    {"path": "docs/evidence-packs.md", "purpose": "Readiness, certification, quality-budget, release, and sidecar evidence packs."},
    {"path": "docs/release-candidate.md", "purpose": "Release-candidate build, verification, asset staging, and upload workflow."},
    {"path": "docs/release-checklist.md", "purpose": "Manual release runbook and evidence checklist."},
    {"path": "docs/release-notes-v0.1.0.md", "purpose": "Published v0.1.0 scope, evidence, and release notes."},
    {"path": "docs/release-notes-v0.1.1.md", "purpose": "v0.1.1 public-polish scope, compatibility boundary, and release evidence contract."},
    {"path": "docs/release-verification.md", "purpose": "Published release asset hash and evidence verification guide."},
    {"path": "docs/post-release-flow.md", "purpose": "Post-release changelog, notes, asset, and verification update flow."},
    {"path": "docs/first-real-corpus.md", "purpose": "First local 10-turn capture, redaction, reporting, and certification guide."},
    {"path": "docs/sidecar-ollama.md", "purpose": "Experimental local Ollama sidecar workflow and review commands."},
    {"path": "docs/sidecar-meaning-rubric.md", "purpose": "Meaning-preservation review rubric for experimental sidecar evidence."},
    {"path": "docs/commercial-license.md", "purpose": "Plain-language commercial-use boundary and license request guide."},
    {"path": "docs/v0.1.1-plan.md", "purpose": "Next patch-release scope, acceptance checklist, and out-of-scope guardrails."},
    {"path": "docs/v0.2.0-plan.md", "purpose": "Real-corpus scorecard, sidecar meaning, milestone, and release-tag comparison plan."},
    {"path": ".github/PULL_REQUEST_TEMPLATE.md", "purpose": "Pull-request verification and privacy checklist."},
    {"path": ".github/ISSUE_TEMPLATE/config.yml", "purpose": "Issue-template routing and private contact links."},
    {"path": ".github/ISSUE_TEMPLATE/bug_report.yml", "purpose": "Public-safe bug report form."},
    {"path": ".github/ISSUE_TEMPLATE/feature_request.yml", "purpose": "Benchmark-first feature request form."},
    {
        "path": ".github/ISSUE_TEMPLATE/commercial_licensing.yml",
        "purpose": "Commercial licensing enquiry form and public-safety warning.",
    },
    {
        "path": ".github/ISSUE_TEMPLATE/private_data_security.yml",
        "purpose": "Private-data and security contact request form.",
    },
]


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
        "governance": {
            "documents": [
                {
                    **document,
                    "present": (root / document["path"]).exists(),
                }
                for document in GOVERNANCE_DOCUMENTS
            ],
            "license": {
                "name": PUBLIC_LICENSE_NAME,
                "path": PUBLIC_LICENSE_PATH,
                "present": (root / PUBLIC_LICENSE_PATH).exists(),
                "commercial_license_path": COMMERCIAL_LICENSE_PATH,
                "commercial_license_present": (root / COMMERCIAL_LICENSE_PATH).exists(),
                "licensor": LICENSOR,
                "commercial_contact": COMMERCIAL_CONTACT,
                "required_before_external_release": True,
            },
        },
        "data": {
            "packaged_demo_corpus": str(DEFAULT_DEMO_CORPUS),
            "packaged_demo_corpus_exists": DEFAULT_DEMO_CORPUS.exists(),
        },
        "counts": {
            "command_count": sum(len(commands) for commands in COMMAND_GROUPS.values()),
            "schema_count": len(SUPPORTED_SCHEMAS),
            "readiness_command_count": len(READINESS_COMMANDS),
            "governance_document_count": len(GOVERNANCE_DOCUMENTS),
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
    lines.extend(["", "## Governance", ""])
    for document in (report.get("governance") or {}).get("documents", []):
        lines.append(
            "- "
            f"`{document.get('path')}`: "
            f"{document.get('purpose')} "
            f"(present: `{document.get('present')}`)"
        )
    license_info = (report.get("governance") or {}).get("license") or {}
    if license_info:
        lines.append(
            "- "
            f"`{license_info.get('path')}`: present `{license_info.get('present')}`, "
            f"license `{license_info.get('name')}`, "
            f"commercial terms `{license_info.get('commercial_license_path')}` present "
            f"`{license_info.get('commercial_license_present')}`, "
            f"required before external release `{license_info.get('required_before_external_release')}`"
        )
    lines.extend(["", "## Schemas", ""])
    for item in report.get("schemas", []):
        lines.append(
            "- "
            f"`{item.get('schema_version')}` "
            f"({item.get('category')}): {item.get('purpose')}"
        )
    return "\n".join(lines).rstrip() + "\n"


def package_version(cwd: Path | str | None = None) -> str:
    source_version = _pyproject_value(Path(cwd) if cwd is not None else Path.cwd(), "version")
    if source_version:
        return source_version
    try:
        return metadata.version(PROJECT_NAME)
    except metadata.PackageNotFoundError:
        return "0.0.0"


def package_requires_python(cwd: Path | str | None = None) -> str:
    source_requires = _pyproject_value(Path(cwd) if cwd is not None else Path.cwd(), "requires-python")
    if source_requires:
        return source_requires
    try:
        value = metadata.metadata(PROJECT_NAME).get("Requires-Python")
        if value:
            return value
    except metadata.PackageNotFoundError:
        pass
    return ">=3.10"


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
