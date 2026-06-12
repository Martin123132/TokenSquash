from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .about import (
    COMMERCIAL_CONTACT,
    COMMERCIAL_LICENSE_PATH,
    GOVERNANCE_DOCUMENTS,
    LICENSOR,
    MANIFEST_SCHEMA_VERSION,
    PUBLIC_LICENSE_NAME,
    PUBLIC_LICENSE_PATH,
    build_product_manifest,
)
from .demo import DEFAULT_DEMO_CORPUS, run_demo
from .turns import certify_turn_corpus, write_turn_certification_outputs
from .workspace import WORKSPACE_INIT_SCHEMA_VERSION, initialize_workspace


STRICT_CERTIFICATION_FILES = (
    "certification.json",
    "certification.md",
    "report.json",
    "report.md",
    "gate.json",
    "gate.md",
    "suggestions.json",
    "suggestions.md",
    "evaluation/evaluation.json",
    "evaluation/measure.json",
    "evaluation/diagnose.json",
)


def run_doctor(
    *,
    check_ollama: bool = False,
    ollama_endpoint: str = "http://localhost:11434",
    ollama_timeout: float = 2.0,
    strict: bool = False,
    strict_output_dir: Path | str | None = None,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Run local health checks for a TokenSquash install/workspace."""

    started = time.time()
    root = Path(cwd) if cwd is not None else Path.cwd()
    strict_dir = Path(strict_output_dir) if strict_output_dir is not None else root / "private-turns" / "doctor-strict"
    checks = [
        _check_python_version(),
        _check_demo_corpus(),
        _check_demo_workflow(),
        _check_private_storage_ignore(root),
        _check_tiktoken_available(),
        _check_ollama(ollama_endpoint, timeout=ollama_timeout) if check_ollama else _skip_ollama_check(ollama_endpoint),
    ]
    if strict:
        checks.extend(
            [
                _check_sample_corpus_copy(root),
                _check_console_script_metadata(root),
                _check_workspace_init_dry_run(root),
                _check_governance_documents(root),
                _check_product_manifest(root),
                _check_turn_certification_workflow(strict_dir),
            ]
        )
    required_checks = [check for check in checks if check.get("required")]
    failed_required = [check for check in required_checks if check.get("status") == "fail"]
    warnings = [check for check in checks if check.get("status") == "warn"]
    status = "fail" if failed_required else "warn" if warnings else "pass"
    return {
        "schema_version": "tokensquash.doctor.v1",
        "status": status,
        "summary": {
            "check_count": len(checks),
            "required_check_count": len(required_checks),
            "failed_required_count": len(failed_required),
            "warning_count": len(warnings),
            "skip_count": sum(1 for check in checks if check.get("status") == "skip"),
            "strict": strict,
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "environment": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "cwd": str(root),
            "strict_output_dir": str(strict_dir) if strict else None,
        },
        "checks": checks,
    }


def format_doctor_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    environment = report.get("environment", {})
    lines = [
        "# TokenSquash Doctor",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Python: `{environment.get('python')}`",
        f"- Executable: `{environment.get('executable')}`",
        f"- CWD: `{environment.get('cwd')}`",
        f"- Checks: `{summary.get('check_count', 0)}`",
        f"- Failed required checks: `{summary.get('failed_required_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Skipped: `{summary.get('skip_count', 0)}`",
        f"- Strict: `{summary.get('strict', False)}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Required | Detail |",
        "|---|---|---:|---|",
    ]
    for check in report.get("checks", []):
        lines.append(
            "| "
            f"{_markdown_cell(str(check.get('name', '')))} | "
            f"`{check.get('status')}` | "
            f"{check.get('required')} | "
            f"{_markdown_cell(str(check.get('message', '')))} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _check_python_version() -> dict[str, Any]:
    version = sys.version_info
    passed = version >= (3, 10)
    return _doctor_check(
        "python_version",
        "pass" if passed else "fail",
        required=True,
        message=f"Python {version.major}.{version.minor}.{version.micro}; TokenSquash requires >=3.10.",
    )


def _check_demo_corpus() -> dict[str, Any]:
    exists = DEFAULT_DEMO_CORPUS.exists()
    return _doctor_check(
        "packaged_demo_corpus",
        "pass" if exists else "fail",
        required=True,
        message=f"Packaged sample corpus {'found' if exists else 'missing'} at {DEFAULT_DEMO_CORPUS}.",
        data={"path": str(DEFAULT_DEMO_CORPUS)},
    )


def _check_demo_workflow() -> dict[str, Any]:
    try:
        report = run_demo(counter="chars")
    except Exception as exc:  # pragma: no cover - exercised through failure path in CLI use.
        return _doctor_check(
            "deterministic_demo",
            "fail",
            required=True,
            message=f"Demo workflow failed: {exc}",
        )
    summary = report.get("summary", {})
    passed = report.get("status") in {"pass", "warn"} and int(summary.get("turn_count", 0)) > 0
    return _doctor_check(
        "deterministic_demo",
        "pass" if passed else "fail",
        required=True,
        message=(
            f"Demo status {report.get('status')} with {summary.get('turn_count', 0)} turns "
            f"and {summary.get('saved_pct', 0.0)}% saved."
        ),
        data={
            "status": report.get("status"),
            "turn_count": summary.get("turn_count", 0),
            "saved_pct": summary.get("saved_pct", 0.0),
            "privacy_finding_count": summary.get("privacy_finding_count", 0),
        },
    )


def _check_private_storage_ignore(cwd: Path) -> dict[str, Any]:
    gitignore = _find_upwards(cwd, ".gitignore")
    if gitignore is None:
        return _doctor_check(
            "private_storage_gitignore",
            "skip",
            required=False,
            message="No .gitignore found from current directory; workspace private-storage check skipped.",
        )
    lines = {
        line.strip().replace("\\", "/")
        for line in gitignore.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required_patterns = {"private-turns/", "turns/", "private-prompts/", "private-aliases/"}
    missing = sorted(required_patterns - lines)
    return _doctor_check(
        "private_storage_gitignore",
        "pass" if not missing else "warn",
        required=False,
        message=(
            f"Private storage patterns present in {gitignore}."
            if not missing
            else f"Missing private storage patterns in {gitignore}: {', '.join(missing)}."
        ),
        data={"gitignore": str(gitignore), "missing": missing},
    )


def _check_tiktoken_available() -> dict[str, Any]:
    try:
        import tiktoken  # type: ignore[import-not-found]
    except Exception:
        return _doctor_check(
            "optional_tiktoken",
            "skip",
            required=False,
            message="Optional tiktoken extra is not installed; exact-tokenizer counters are unavailable.",
        )
    location = getattr(tiktoken, "__file__", None)
    detail = f" at {Path(location).parent}" if location else ""
    return _doctor_check(
        "optional_tiktoken",
        "pass",
        required=False,
        message=f"tiktoken is installed{detail}.",
    )


def _skip_ollama_check(endpoint: str) -> dict[str, Any]:
    return _doctor_check(
        "optional_ollama",
        "skip",
        required=False,
        message=f"Ollama reachability not checked. Use --check-ollama to query {endpoint}.",
        data={"endpoint": endpoint},
    )


def _check_ollama(endpoint: str, *, timeout: float) -> dict[str, Any]:
    url = endpoint.rstrip("/") + "/api/tags"
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return _doctor_check(
            "optional_ollama",
            "warn",
            required=False,
            message=f"Ollama check could not reach {url}: {exc}",
            data={"endpoint": endpoint, "url": url},
        )
    models = payload.get("models", []) if isinstance(payload, dict) else []
    return _doctor_check(
        "optional_ollama",
        "pass",
        required=False,
        message=f"Ollama responded at {url} with {len(models)} model(s).",
        data={"endpoint": endpoint, "url": url, "model_count": len(models)},
    )


def _check_sample_corpus_copy(cwd: Path) -> dict[str, Any]:
    example = cwd / "examples" / "sample-turns.jsonl"
    if not example.exists():
        return _doctor_check(
            "sample_corpus_copy",
            "skip",
            required=False,
            message="Repository example sample corpus not present; packaged corpus check already covered install data.",
            data={"example": str(example), "packaged": str(DEFAULT_DEMO_CORPUS)},
        )
    packaged_text = DEFAULT_DEMO_CORPUS.read_text(encoding="utf-8")
    example_text = example.read_text(encoding="utf-8")
    matches = packaged_text == example_text
    return _doctor_check(
        "sample_corpus_copy",
        "pass" if matches else "fail",
        required=True,
        message=(
            f"Packaged sample corpus matches {example}."
            if matches
            else f"Packaged sample corpus differs from {example}."
        ),
        data={"example": str(example), "packaged": str(DEFAULT_DEMO_CORPUS)},
    )


def _check_console_script_metadata(cwd: Path) -> dict[str, Any]:
    pyproject = cwd / "pyproject.toml"
    if not pyproject.exists():
        return _doctor_check(
            "console_script_metadata",
            "skip",
            required=False,
            message="pyproject.toml not present; console script metadata check skipped outside a source checkout.",
        )
    text = pyproject.read_text(encoding="utf-8")
    has_script = 'tokensquash = "tokensquash.cli:main"' in text
    has_package_data = 'tokensquash = ["data/*.jsonl"]' in text
    passed = has_script and has_package_data
    missing = []
    if not has_script:
        missing.append("project.scripts tokensquash entry")
    if not has_package_data:
        missing.append("package-data data/*.jsonl entry")
    return _doctor_check(
        "console_script_metadata",
        "pass" if passed else "fail",
        required=True,
        message=(
            f"pyproject.toml exposes the CLI script and packaged demo data."
            if passed
            else f"pyproject.toml is missing: {', '.join(missing)}."
        ),
        data={"pyproject": str(pyproject), "missing": missing},
    )


def _check_workspace_init_dry_run(cwd: Path) -> dict[str, Any]:
    try:
        report = initialize_workspace(cwd, dry_run=True)
    except Exception as exc:  # pragma: no cover - exercised through failure path in CLI use.
        return _doctor_check(
            "workspace_init_dry_run",
            "fail",
            required=True,
            message=f"Workspace init dry-run failed: {exc}",
        )
    passed = (
        report.get("schema_version") == WORKSPACE_INIT_SCHEMA_VERSION
        and report.get("status") == "dry-run"
        and int((report.get("summary") or {}).get("directory_count", 0)) >= 3
        and bool((report.get("gitignore") or {}).get("required_patterns"))
    )
    return _doctor_check(
        "workspace_init_dry_run",
        "pass" if passed else "fail",
        required=True,
        message=(
            "Workspace init dry-run produced the expected private directory and gitignore plan."
            if passed
            else "Workspace init dry-run did not produce the expected setup plan."
        ),
        data={
            "status": report.get("status"),
            "directory_count": (report.get("summary") or {}).get("directory_count", 0),
            "added_gitignore_pattern_count": (report.get("summary") or {}).get("added_gitignore_pattern_count", 0),
        },
    )


def _check_product_manifest(cwd: Path) -> dict[str, Any]:
    try:
        manifest = build_product_manifest(cwd=cwd)
    except Exception as exc:  # pragma: no cover - exercised through failure path in CLI use.
        return _doctor_check(
            "product_manifest",
            "fail",
            required=True,
            message=f"Product manifest failed to build: {exc}",
        )
    command_count = int((manifest.get("counts") or {}).get("command_count", 0))
    schema_count = int((manifest.get("counts") or {}).get("schema_count", 0))
    governance_document_count = int((manifest.get("counts") or {}).get("governance_document_count", 0))
    schemas = {item.get("schema_version") for item in manifest.get("schemas", [])}
    commands = {item.get("command") for item in manifest.get("commands", [])}
    governance = manifest.get("governance") or {}
    governance_docs = governance.get("documents") or []
    license_info = governance.get("license") or {}
    source_checkout = (cwd / "pyproject.toml").exists()
    missing_governance_docs = sorted(
        str(item.get("path"))
        for item in governance_docs
        if isinstance(item, dict) and not item.get("present")
    )
    required_schemas = {
        MANIFEST_SCHEMA_VERSION,
        WORKSPACE_INIT_SCHEMA_VERSION,
        "tokensquash.doctor.v1",
        "tokensquash.readiness.v1",
        "tokensquash.readiness.verify.v1",
        "tokensquash.release_info.v1",
        "tokensquash.release_candidate.v1",
        "tokensquash.release_candidate.artifacts.v1",
        "tokensquash.release_candidate.attestation.v1",
        "tokensquash.release_candidate.verify.v1",
        "tokensquash.release_assets.v1",
        "tokensquash.baselines.verify.v1",
        "tokensquash.quality_budget.v1",
        "tokensquash.quality_budget.init.v1",
        "tokensquash.quality_budget.validate.v1",
        "tokensquash.turns.certify.v1",
        "tokensquash.turns.release_check.v1",
        "tokensquash.turns.release_verify.v1",
        "tokensquash.sidecar.certify.v1",
    }
    required_commands = {
        "about",
        "budget init",
        "budget validate",
        "init",
        "doctor",
        "readiness",
        "verify-readiness",
        "release-info",
        "release-candidate",
        "verify-release-candidate",
        "release-assets",
        "baselines verify",
        "turns certify",
        "turns release-check",
        "turns verify-release",
        "sidecar certify",
    }
    missing_schemas = sorted(required_schemas - schemas)
    missing_commands = sorted(required_commands - commands)
    passed = (
        manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION
        and manifest.get("status") == "pass"
        and command_count >= 40
        and schema_count >= 40
        and governance_document_count >= len(GOVERNANCE_DOCUMENTS)
        and (not source_checkout or not missing_governance_docs)
        and (not source_checkout or bool(license_info.get("present")))
        and (not source_checkout or bool(license_info.get("commercial_license_present")))
        and not missing_schemas
        and not missing_commands
        and bool((manifest.get("data") or {}).get("packaged_demo_corpus_exists"))
    )
    return _doctor_check(
        "product_manifest",
        "pass" if passed else "fail",
        required=True,
        message=(
            f"Product manifest lists {command_count} commands and {schema_count} schemas."
            if passed
            else "Product manifest is incomplete; inspect missing commands, schemas, or packaged data."
        ),
        data={
            "command_count": command_count,
            "schema_count": schema_count,
            "governance_document_count": governance_document_count,
            "missing_commands": missing_commands,
            "missing_schemas": missing_schemas,
            "missing_governance_docs": missing_governance_docs,
            "source_checkout": source_checkout,
            "license": {
                "name": license_info.get("name"),
                "path": license_info.get("path"),
                "present": license_info.get("present"),
                "commercial_license_path": license_info.get("commercial_license_path"),
                "commercial_license_present": license_info.get("commercial_license_present"),
                "licensor": license_info.get("licensor"),
                "commercial_contact": license_info.get("commercial_contact"),
                "required_before_external_release": license_info.get("required_before_external_release"),
            },
            "packaged_demo_corpus_exists": (manifest.get("data") or {}).get("packaged_demo_corpus_exists"),
        },
    )


def _check_governance_documents(cwd: Path) -> dict[str, Any]:
    if not (cwd / "pyproject.toml").exists():
        return _doctor_check(
            "governance_documents",
            "skip",
            required=False,
            message="Source governance document check skipped outside a source checkout.",
            data={"source_checkout": False},
        )

    missing: list[str] = []
    empty: list[str] = []
    missing_references: list[dict[str, str]] = []
    required_references = {
        "README.md": [
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CHANGELOG.md",
            "ROADMAP.md",
            "docs/release-checklist.md",
            "docs/release-notes-v0.1.0.md",
            "docs/release-verification.md",
            "docs/v0.1.1-plan.md",
            ".github/ISSUE_TEMPLATE",
            PUBLIC_LICENSE_PATH,
            COMMERCIAL_LICENSE_PATH,
            PUBLIC_LICENSE_NAME,
        ],
        "CHANGELOG.md": [
            "ROADMAP.md",
            "docs/v0.1.1-plan.md",
            "Contributor, security, and pull-request policy docs",
            PUBLIC_LICENSE_NAME,
            LICENSOR,
            "v0.1.0 release notes",
            "GitHub issue forms",
        ],
        "ROADMAP.md": [
            "TokenSquash Roadmap",
            "deterministic codec as the source of truth",
            "Experimental Surface",
            "v0.1.x Goals",
            "Evidence Bar",
            "PolyForm Noncommercial",
        ],
        "CONTRIBUTING.md": [
            "private-turns/",
            "docs/release-checklist.md",
            PUBLIC_LICENSE_PATH,
            COMMERCIAL_LICENSE_PATH,
            PUBLIC_LICENSE_NAME,
            LICENSOR,
        ],
        "SECURITY.md": [
            "Report a vulnerability",
            "private-turns/",
        ],
        "docs/release-checklist.md": [
            "release-candidate-evidence",
            "docs/release-notes-v0.1.0.md",
            "docs/release-verification.md",
            "Release-Prep Command Block",
            PUBLIC_LICENSE_PATH,
            COMMERCIAL_LICENSE_PATH,
        ],
        "docs/release-notes-v0.1.0.md": [
            "TokenSquash v0.1.0 Release Notes",
            "Release-Prep Command Block",
            "release-candidate-evidence",
            "private-turns/",
            PUBLIC_LICENSE_NAME,
            LICENSOR,
        ],
        "docs/release-verification.md": [
            "Release Verification",
            "tokensquash-0.1.0-py3-none-any.whl",
            "release-attestation.json",
            "verify-release-candidate.json",
            "9583c296f4ada082c88b7bc8149b678ed1529a16",
            "LICENSE",
            COMMERCIAL_LICENSE_PATH,
        ],
        "docs/v0.1.1-plan.md": [
            "TokenSquash v0.1.1 Plan",
            "Release Evidence",
            "Real Corpus Workflow",
            "Sidecar Evidence",
            "Acceptance Checklist",
            "Out Of Scope",
        ],
        ".github/PULL_REQUEST_TEMPLATE.md": [
            "README.md",
            "CHANGELOG.md",
            "docs/release-notes-v0.1.0.md",
            "issue templates",
            PUBLIC_LICENSE_PATH,
            "no raw private prompts",
        ],
        ".github/ISSUE_TEMPLATE/config.yml": [
            "blank_issues_enabled: false",
            "Commercial licensing email",
            "glyn@twohandsnetwork.co.uk",
            "Private vulnerability reporting",
        ],
        ".github/ISSUE_TEMPLATE/bug_report.yml": [
            "Bug report",
            "raw private prompts",
            "Reproduction steps",
            "Public issue safety",
        ],
        ".github/ISSUE_TEMPLATE/feature_request.yml": [
            "Feature request",
            "benchmark-first",
            "token savings alone",
            "Measurement or acceptance evidence",
        ],
        ".github/ISSUE_TEMPLATE/commercial_licensing.yml": [
            "Commercial licensing enquiry",
            PUBLIC_LICENSE_NAME,
            LICENSOR,
            "glyn@twohandsnetwork.co.uk",
            "no commercial license is granted",
        ],
        ".github/ISSUE_TEMPLATE/private_data_security.yml": [
            "Private-data or security concern",
            "private vulnerability reporting",
            "raw prompts",
            "Public issue safety",
        ],
        PUBLIC_LICENSE_PATH: [
            "Required Notice: Copyright (c) 2026 TWO HANDS NETWORK LTD.",
            "TokenSquash is source-available",
            PUBLIC_LICENSE_NAME,
            "https://polyformproject.org/licenses/noncommercial/1.0.0",
        ],
        COMMERCIAL_LICENSE_PATH: [
            "TokenSquash is available for personal and non-commercial use",
            LICENSOR,
            "Glyn Evans",
            "glyn@twohandsnetwork.co.uk",
            "commercial AI",
            "No commercial license is granted",
        ],
    }

    for document in GOVERNANCE_DOCUMENTS:
        relative = str(document["path"])
        path = cwd / relative
        if not path.exists() or not path.is_file():
            missing.append(relative)
            continue
        text = path.read_text(encoding="utf-8-sig")
        if not text.strip():
            empty.append(relative)
        for needle in required_references.get(relative, []):
            if needle not in text:
                missing_references.append({"path": relative, "text": needle})

    license_path = cwd / PUBLIC_LICENSE_PATH
    commercial_license_path = cwd / COMMERCIAL_LICENSE_PATH
    passed = not missing and not empty and not missing_references
    return _doctor_check(
        "governance_documents",
        "pass" if passed else "fail",
        required=True,
        message=(
            "Governance and licensing docs are present, non-empty, and linked from the main docs."
            if passed
            else "Governance or licensing docs are missing, empty, or not linked from the main docs."
        ),
        data={
            "document_count": len(GOVERNANCE_DOCUMENTS),
            "missing": missing,
            "empty": empty,
            "missing_references": missing_references,
            "license": {
                "name": PUBLIC_LICENSE_NAME,
                "path": str(license_path),
                "present": license_path.exists(),
                "commercial_license_path": str(commercial_license_path),
                "commercial_license_present": commercial_license_path.exists(),
                "licensor": LICENSOR,
                "commercial_contact": COMMERCIAL_CONTACT,
                "required_before_external_release": True,
            },
        },
    )


def _check_turn_certification_workflow(output_dir: Path) -> dict[str, Any]:
    try:
        report = certify_turn_corpus(DEFAULT_DEMO_CORPUS, counter="chars")
        write_turn_certification_outputs(output_dir, report)
        expected_paths = [output_dir / name for name in STRICT_CERTIFICATION_FILES]
        missing = [str(path) for path in expected_paths if not path.exists() or path.stat().st_size == 0]
        gate_path = output_dir / "gate.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.exists() else {}
    except Exception as exc:  # pragma: no cover - exercised through failure path in CLI use.
        return _doctor_check(
            "turn_certification_workflow",
            "fail",
            required=True,
            message=f"Strict turn certification failed: {exc}",
            data={"output_dir": str(output_dir)},
        )
    summary = report.get("summary", {})
    passed = (
        report.get("status") == "pass"
        and gate.get("status") == "pass"
        and not missing
        and float(summary.get("saved_pct", 0.0)) >= 0.5
        and int(summary.get("privacy_finding_count", 0)) == 0
    )
    return _doctor_check(
        "turn_certification_workflow",
        "pass" if passed else "fail",
        required=True,
        message=(
            f"Turn certification passed with {summary.get('saved_pct', 0.0)}% saved; artifacts written to {output_dir}."
            if passed
            else f"Turn certification did not meet strict readiness checks; inspect {output_dir}."
        ),
        data={
            "output_dir": str(output_dir),
            "status": report.get("status"),
            "gate_status": gate.get("status"),
            "saved_pct": summary.get("saved_pct", 0.0),
            "privacy_finding_count": summary.get("privacy_finding_count", 0),
            "missing_artifacts": missing,
        },
    )


def _find_upwards(start: Path, filename: str) -> Path | None:
    current = start.resolve()
    candidates = [current, *current.parents]
    for candidate in candidates:
        path = candidate / filename
        if path.exists():
            return path
    return None


def _doctor_check(
    name: str,
    status: str,
    *,
    required: bool,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "required": required,
        "message": message,
        "data": data or {},
    }


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
