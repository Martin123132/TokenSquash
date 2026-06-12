from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from email.parser import Parser
from pathlib import Path
from typing import Any, Callable
from zipfile import BadZipFile, ZipFile

from .about import PROJECT_NAME, package_requires_python, package_version
from .baselines import format_benchmark_baseline_verify_markdown, verify_benchmark_baselines
from .readiness import (
    format_product_readiness_verify_markdown,
    run_product_readiness,
    verify_product_readiness_pack,
)
from .release_info import build_release_info, format_release_info_markdown


RELEASE_CANDIDATE_SCHEMA_VERSION = "tokensquash.release_candidate.v1"
RELEASE_CANDIDATE_ARTIFACTS_SCHEMA_VERSION = "tokensquash.release_candidate.artifacts.v1"
RELEASE_CANDIDATE_ATTESTATION_SCHEMA_VERSION = "tokensquash.release_candidate.attestation.v1"
RELEASE_CANDIDATE_VERIFY_SCHEMA_VERSION = "tokensquash.release_candidate.verify.v1"
DEFAULT_RELEASE_CANDIDATE_OUT_DIR = Path("private-turns/release-candidate")
PACKAGED_DEMO_DATA_PATH = "tokensquash/data/sample-turns.jsonl"
REQUIRED_PACKAGE_LICENSE_FILES = ("LICENSE", "COMMERCIAL-LICENSE.md")
ARTIFACT_MANIFEST_FILENAMES = {
    "artifact-manifest.json",
    "artifact-manifest.md",
    "release-attestation.json",
    "release-attestation.md",
}


def run_release_candidate(
    *,
    out_dir: Path | str = DEFAULT_RELEASE_CANDIDATE_OUT_DIR,
    counter: str = "chars",
    skip_tests: bool = False,
    require_exact_tokenizer: bool = True,
    require_clean_git: bool = False,
    check_ollama: bool = False,
    ollama_endpoint: str = "http://localhost:11434",
    ollama_timeout: float = 2.0,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Run the release-candidate gate and write a reusable local evidence pack."""

    started = time.time()
    root = Path(cwd) if cwd is not None else Path.cwd()
    output_dir = Path(out_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    readiness_dir = output_dir / "readiness"
    wheel_dir = output_dir / "wheel"
    sdist_dir = output_dir / "sdist"
    steps: list[dict[str, Any]] = []

    _run_candidate_step(
        steps,
        "release_info",
        command=_command("release-info", "--root", str(root), *(("--require-clean",) if require_clean_git else ())),
        required=True,
        action=lambda: _run_release_info(root, output_dir, require_clean=require_clean_git),
    )
    _run_candidate_step(
        steps,
        "readiness",
        command=_command(
            "readiness",
            "--out-dir",
            str(readiness_dir),
            "--counter",
            counter,
            *(("--skip-tests",) if skip_tests else ()),
            *(
                ("--check-ollama", "--ollama-endpoint", ollama_endpoint, "--ollama-timeout", str(ollama_timeout))
                if check_ollama
                else ()
            ),
        ),
        required=True,
        action=lambda: _run_readiness(
            root,
            readiness_dir,
            counter=counter,
            skip_tests=skip_tests,
            check_ollama=check_ollama,
            ollama_endpoint=ollama_endpoint,
            ollama_timeout=ollama_timeout,
        ),
    )
    _run_candidate_step(
        steps,
        "verify_readiness",
        command=_command("verify-readiness", str(readiness_dir), "--require-readiness-pass"),
        required=True,
        action=lambda: _run_readiness_verify(readiness_dir, output_dir),
    )
    _run_candidate_step(
        steps,
        "benchmark_baselines",
        command=_command("baselines", "verify"),
        required=True,
        action=lambda: _run_baselines(
            output_dir,
            root,
            include_exact_tokenizer=False,
            stem="baseline-verify",
            allow_partial=True,
        ),
    )
    _run_candidate_step(
        steps,
        "exact_tokenizer_baselines",
        command=_command("baselines", "verify", "--include-exact-tokenizer"),
        required=require_exact_tokenizer,
        action=lambda: _run_exact_baselines(output_dir, root, require_exact_tokenizer=require_exact_tokenizer),
    )
    _run_candidate_step(
        steps,
        "wheel_build",
        command=f"{sys.executable} -m pip wheel . --no-deps -w {wheel_dir}",
        required=True,
        action=lambda: _run_wheel_build(root, output_dir, wheel_dir),
    )
    _run_candidate_step(
        steps,
        "wheel_smoke",
        command=(
            f"{sys.executable} -m venv <temp> && <venv-python> -m pip install --no-deps <wheel> "
            "&& <venv-python> -m tokensquash about --json "
            "&& <venv-python> -m tokensquash demo --counter chars --json"
        ),
        required=True,
        action=lambda: _run_wheel_smoke(root, output_dir, wheel_dir),
    )
    _run_candidate_step(
        steps,
        "sdist_build",
        command=f"{sys.executable} -c \"import setuptools.build_meta as b; print(b.build_sdist(<sdist-dir>))\"",
        required=True,
        action=lambda: _run_sdist_build(root, output_dir, sdist_dir),
    )

    failed_required = [step for step in steps if step.get("required") and step.get("status") == "fail"]
    warnings = [step for step in steps if step.get("status") == "warn"]
    skipped = [step for step in steps if step.get("status") == "skip"]
    status = "fail" if failed_required else "warn" if warnings else "pass"
    report = {
        "schema_version": RELEASE_CANDIDATE_SCHEMA_VERSION,
        "status": status,
        "root": str(root),
        "out_dir": str(output_dir),
        "counter": counter,
        "skip_tests": skip_tests,
        "require_exact_tokenizer": require_exact_tokenizer,
        "require_clean_git": require_clean_git,
        "check_ollama": check_ollama,
        "summary": {
            "step_count": len(steps),
            "failed_required_count": len(failed_required),
            "warning_count": len(warnings),
            "skip_count": len(skipped),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "commands": _release_candidate_commands(
            root,
            output_dir,
            readiness_dir,
            wheel_dir,
            sdist_dir,
            counter,
            skip_tests=skip_tests,
            require_exact_tokenizer=require_exact_tokenizer,
            require_clean_git=require_clean_git,
            check_ollama=check_ollama,
            ollama_endpoint=ollama_endpoint,
            ollama_timeout=ollama_timeout,
        ),
        "steps": steps,
        "outputs": {
            "output_dir": str(output_dir),
            "report": str(output_dir / "release-candidate.json"),
            "markdown": str(output_dir / "release-candidate.md"),
            "artifact_manifest": str(output_dir / "artifact-manifest.json"),
            "artifact_manifest_markdown": str(output_dir / "artifact-manifest.md"),
            "release_info": str(output_dir / "release-info.json"),
            "release_info_markdown": str(output_dir / "release-info.md"),
            "readiness_dir": str(readiness_dir),
            "readiness": str(readiness_dir / "readiness.json"),
            "readiness_verify": str(output_dir / "readiness-verify.json"),
            "readiness_verify_markdown": str(output_dir / "readiness-verify.md"),
            "baseline_verify": str(output_dir / "baseline-verify.json"),
            "baseline_verify_markdown": str(output_dir / "baseline-verify.md"),
            "exact_baseline_verify": str(output_dir / "exact-baseline-verify.json"),
            "exact_baseline_verify_markdown": str(output_dir / "exact-baseline-verify.md"),
            "wheel_dir": str(wheel_dir),
            "wheel_log": str(output_dir / "wheel-build.txt"),
            "wheel_smoke_log": str(output_dir / "wheel-smoke.txt"),
            "sdist_dir": str(sdist_dir),
            "sdist_log": str(output_dir / "sdist-build.txt"),
        },
    }
    write_release_candidate_outputs(output_dir, report)
    return report


def write_release_candidate_outputs(target: Path | str, report: dict[str, Any]) -> None:
    target_path = Path(target)
    target_path.mkdir(parents=True, exist_ok=True)
    report.setdefault("outputs", {})
    report["outputs"]["output_dir"] = str(target_path)
    report["outputs"]["report"] = str(target_path / "release-candidate.json")
    report["outputs"]["markdown"] = str(target_path / "release-candidate.md")
    report["outputs"]["artifact_manifest"] = str(target_path / "artifact-manifest.json")
    report["outputs"]["artifact_manifest_markdown"] = str(target_path / "artifact-manifest.md")
    _write_json(target_path / "release-candidate.json", report)
    (target_path / "release-candidate.md").write_text(format_release_candidate_markdown(report), encoding="utf-8")
    artifact_manifest = build_release_candidate_artifact_manifest(target_path, report)
    _write_json(target_path / "artifact-manifest.json", artifact_manifest)
    (target_path / "artifact-manifest.md").write_text(
        format_release_candidate_artifact_manifest_markdown(artifact_manifest),
        encoding="utf-8",
    )


def format_release_candidate_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs", {})
    lines = [
        "# TokenSquash Release Candidate",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Root: `{report.get('root')}`",
        f"- Output dir: `{report.get('out_dir')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Require exact tokenizer: `{report.get('require_exact_tokenizer')}`",
        f"- Require clean Git: `{report.get('require_clean_git')}`",
        f"- Steps: `{summary.get('step_count', 0)}`",
        f"- Failed required: `{summary.get('failed_required_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Skipped: `{summary.get('skip_count', 0)}`",
        "",
        "## Steps",
        "",
        "| Step | Status | Required | Seconds | Detail |",
        "|---|---|---:|---:|---|",
    ]
    for step in report.get("steps", []):
        lines.append(
            "| "
            f"{_markdown_cell(str(step.get('name', '')))} | "
            f"`{step.get('status')}` | "
            f"{step.get('required')} | "
            f"{step.get('elapsed_seconds', 0.0)} | "
            f"{_markdown_cell(str(step.get('message', '')))} |"
        )
    lines.extend(["", "## Outputs", ""])
    for name in (
        "report",
        "markdown",
        "artifact_manifest",
        "artifact_manifest_markdown",
        "release_info",
        "readiness",
        "readiness_verify",
        "baseline_verify",
        "exact_baseline_verify",
        "wheel_dir",
        "wheel_log",
        "wheel_smoke_log",
        "sdist_dir",
        "sdist_log",
    ):
        if outputs.get(name):
            lines.append(f"- `{name}`: `{outputs.get(name)}`")
    lines.extend(["", "## Commands", ""])
    for command in report.get("commands", []):
        lines.append(f"- `{command}`")
    return "\n".join(lines).rstrip() + "\n"


def build_release_candidate_artifact_manifest(candidate_dir: Path | str, report: dict[str, Any]) -> dict[str, Any]:
    """Build a SHA-256 manifest for the files in a release-candidate pack."""

    root = Path(candidate_dir)
    files = _candidate_artifact_manifest_expected_files(root, report)
    artifacts = [_candidate_artifact_manifest_entry(root, path) for path in files]
    total_bytes = sum(int(item["bytes"]) for item in artifacts)
    return {
        "schema_version": RELEASE_CANDIDATE_ARTIFACTS_SCHEMA_VERSION,
        "status": "pass" if artifacts else "fail",
        "out_dir": str(root),
        "algorithm": "sha256",
        "summary": {
            "artifact_count": len(artifacts),
            "total_bytes": total_bytes,
        },
        "release_candidate": {
            "schema_version": report.get("schema_version"),
            "status": report.get("status"),
        },
        "artifacts": artifacts,
    }


def format_release_candidate_artifact_manifest_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Release Candidate Artifact Manifest",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Output dir: `{report.get('out_dir')}`",
        f"- Algorithm: `{report.get('algorithm')}`",
        f"- Artifacts: `{summary.get('artifact_count', 0)}`",
        f"- Total bytes: `{summary.get('total_bytes', 0)}`",
        "",
        "## Artifacts",
        "",
        "| Artifact | Bytes | SHA-256 |",
        "|---|---:|---|",
    ]
    for artifact in report.get("artifacts", []):
        lines.append(
            "| "
            f"`{_markdown_cell(str(artifact.get('relative_path', '')))}` | "
            f"{artifact.get('bytes', 0)} | "
            f"`{artifact.get('sha256')}` |"
        )
    return "\n".join(lines).rstrip() + "\n"


def format_release_candidate_attestation_markdown(report: dict[str, Any]) -> str:
    verification = report.get("verification", {})
    provenance = report.get("provenance", {})
    git = provenance.get("git", {})
    project = provenance.get("project", {})
    materials = report.get("materials", {})
    wheel = materials.get("wheel") or {}
    sdist = materials.get("sdist") or {}
    artifact_manifest = materials.get("artifact_manifest") or {}
    lines = [
        "# TokenSquash Release Attestation",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Evidence hash: `{report.get('evidence_hash')}`",
        f"- Project: `{project.get('name')}`",
        f"- Version: `{project.get('version')}`",
        f"- Git commit: `{git.get('commit')}`",
        f"- Git dirty: `{git.get('dirty')}`",
        f"- Verification status: `{verification.get('status')}`",
        f"- Checks: `{verification.get('check_count', 0)}`",
        f"- Failed checks: `{verification.get('failed_check_count', 0)}`",
        f"- Wheel SHA-256: `{wheel.get('sha256')}`",
        f"- Sdist SHA-256: `{sdist.get('sha256')}`",
        f"- Artifact manifest SHA-256: `{artifact_manifest.get('sha256')}`",
        f"- Signature: `{(report.get('signature') or {}).get('type')}`",
    ]
    return "\n".join(lines).rstrip() + "\n"


def verify_release_candidate_pack(
    path: Path | str,
    *,
    require_release_candidate_pass: bool = False,
) -> dict[str, Any]:
    """Verify a saved release-candidate evidence pack."""

    source = Path(path)
    candidate_path = source / "release-candidate.json" if source.is_dir() else source
    candidate_dir = candidate_path.parent
    checks: list[dict[str, Any]] = []
    candidate, candidate_check = _verify_candidate_json_artifact(
        "release_candidate",
        candidate_path,
        RELEASE_CANDIDATE_SCHEMA_VERSION,
        required=True,
        allowed_statuses={"pass", "warn", "fail"},
    )
    checks.append(candidate_check)
    if require_release_candidate_pass:
        _append_candidate_approval_check(checks, candidate_path, candidate)

    outputs = candidate.get("outputs", {}) if candidate else {}
    _append_candidate_file_check(
        checks,
        "release_candidate_markdown",
        _resolve_candidate_artifact(candidate_dir, outputs.get("markdown"), Path("release-candidate.md")),
        required=True,
    )
    artifact_manifest, artifact_manifest_check = _verify_candidate_json_artifact(
        "artifact_manifest",
        _resolve_candidate_artifact(candidate_dir, outputs.get("artifact_manifest"), Path("artifact-manifest.json")),
        RELEASE_CANDIDATE_ARTIFACTS_SCHEMA_VERSION,
        required=True,
        allowed_statuses={"pass", "warn", "fail"},
    )
    checks.append(artifact_manifest_check)
    _append_status_expectation_check(
        checks,
        "artifact_manifest_status",
        artifact_manifest,
        required=True,
        allowed_statuses={"pass"},
    )
    _append_candidate_file_check(
        checks,
        "artifact_manifest_markdown",
        _resolve_candidate_artifact(
            candidate_dir,
            outputs.get("artifact_manifest_markdown"),
            Path("artifact-manifest.md"),
        ),
        required=True,
    )
    _append_candidate_artifact_manifest_integrity_check(
        checks,
        candidate_dir,
        candidate,
        artifact_manifest,
        required=True,
    )
    release_info, release_info_check = _verify_candidate_json_artifact(
        "release_info",
        _resolve_candidate_artifact(candidate_dir, outputs.get("release_info"), Path("release-info.json")),
        "tokensquash.release_info.v1",
        required=True,
        allowed_statuses={"pass", "warn", "fail"},
    )
    checks.append(release_info_check)
    _append_status_expectation_check(
        checks,
        "release_info_status",
        release_info,
        required=True,
        allowed_statuses={"pass", "warn"},
    )
    _append_candidate_clean_git_check(checks, candidate, release_info)
    _append_candidate_file_check(
        checks,
        "release_info_markdown",
        _resolve_candidate_artifact(
            candidate_dir,
            outputs.get("release_info_markdown"),
            Path("release-info.md"),
        ),
        required=True,
    )

    readiness_dir = _resolve_candidate_artifact(candidate_dir, outputs.get("readiness_dir"), Path("readiness"))
    if _append_candidate_directory_check(checks, "readiness_dir", readiness_dir, required=True):
        readiness_verify_report = verify_product_readiness_pack(
            readiness_dir,
            require_readiness_pass=require_release_candidate_pass,
        )
        checks.append(
            _candidate_check(
                "readiness_pack",
                "pass" if readiness_verify_report.get("status") == "pass" else "fail",
                required=True,
                path=readiness_dir,
                message=f"Nested readiness verifier returned {readiness_verify_report.get('status')}.",
                data={
                    "check_count": (readiness_verify_report.get("summary") or {}).get("check_count", 0),
                    "failed_check_count": (readiness_verify_report.get("summary") or {}).get("failed_check_count", 0),
                    "readiness_status": (readiness_verify_report.get("summary") or {}).get("readiness_status"),
                },
            )
        )
    else:
        readiness_verify_report = None

    stored_readiness_verify, stored_readiness_verify_check = _verify_candidate_json_artifact(
        "readiness_verify",
        _resolve_candidate_artifact(candidate_dir, outputs.get("readiness_verify"), Path("readiness-verify.json")),
        "tokensquash.readiness.verify.v1",
        required=True,
        allowed_statuses={"pass", "warn", "fail"},
    )
    checks.append(stored_readiness_verify_check)
    _append_status_expectation_check(
        checks,
        "readiness_verify_status",
        stored_readiness_verify,
        required=True,
        allowed_statuses={"pass"},
    )
    _append_candidate_file_check(
        checks,
        "readiness_verify_markdown",
        _resolve_candidate_artifact(
            candidate_dir,
            outputs.get("readiness_verify_markdown"),
            Path("readiness-verify.md"),
        ),
        required=True,
    )

    baseline_verify, baseline_verify_check = _verify_candidate_json_artifact(
        "baseline_verify",
        _resolve_candidate_artifact(candidate_dir, outputs.get("baseline_verify"), Path("baseline-verify.json")),
        "tokensquash.baselines.verify.v1",
        required=True,
        allowed_statuses={"pass", "partial", "fail"},
    )
    checks.append(baseline_verify_check)
    _append_baseline_expectation_check(
        checks,
        "baseline_verify_status",
        baseline_verify,
        required=True,
        allow_partial=True,
    )
    _append_candidate_file_check(
        checks,
        "baseline_verify_markdown",
        _resolve_candidate_artifact(
            candidate_dir,
            outputs.get("baseline_verify_markdown"),
            Path("baseline-verify.md"),
        ),
        required=True,
    )

    require_exact = bool(candidate.get("require_exact_tokenizer")) if candidate else True
    exact_baseline_verify, exact_baseline_verify_check = _verify_candidate_json_artifact(
        "exact_baseline_verify",
        _resolve_candidate_artifact(
            candidate_dir,
            outputs.get("exact_baseline_verify"),
            Path("exact-baseline-verify.json"),
        ),
        "tokensquash.baselines.verify.v1",
        required=require_exact,
        allowed_statuses={"pass", "partial", "fail"},
    )
    checks.append(exact_baseline_verify_check)
    _append_baseline_expectation_check(
        checks,
        "exact_baseline_verify_status",
        exact_baseline_verify,
        required=require_exact,
        allow_partial=False,
    )
    _append_candidate_file_check(
        checks,
        "exact_baseline_verify_markdown",
        _resolve_candidate_artifact(
            candidate_dir,
            outputs.get("exact_baseline_verify_markdown"),
            Path("exact-baseline-verify.md"),
        ),
        required=require_exact,
    )

    wheel_dir = _resolve_candidate_artifact(candidate_dir, outputs.get("wheel_dir"), Path("wheel"))
    wheel_log = _resolve_candidate_artifact(candidate_dir, outputs.get("wheel_log"), Path("wheel-build.txt"))
    _append_candidate_file_check(checks, "wheel_log", wheel_log, required=True)
    wheel_path = _candidate_wheel_path(wheel_dir, candidate)
    if _append_candidate_directory_check(checks, "wheel_dir", wheel_dir, required=True):
        _append_candidate_wheel_check(checks, wheel_path, release_info=release_info, required=True)
    _append_candidate_file_check(
        checks,
        "wheel_smoke_log",
        _resolve_candidate_artifact(candidate_dir, outputs.get("wheel_smoke_log"), Path("wheel-smoke.txt")),
        required=True,
    )
    _append_candidate_wheel_smoke_check(checks, candidate, required=True)

    sdist_dir = _resolve_candidate_artifact(candidate_dir, outputs.get("sdist_dir"), Path("sdist"))
    sdist_log = _resolve_candidate_artifact(candidate_dir, outputs.get("sdist_log"), Path("sdist-build.txt"))
    _append_candidate_file_check(checks, "sdist_log", sdist_log, required=True)
    sdist_path = _candidate_sdist_path(sdist_dir, candidate)
    if _append_candidate_directory_check(checks, "sdist_dir", sdist_dir, required=True):
        _append_candidate_sdist_check(checks, sdist_path, release_info=release_info, required=True)

    _append_candidate_steps_check(checks, candidate_path, candidate)

    attestation_check = _candidate_check(
        "release_attestation",
        "pass",
        required=True,
        path=candidate_dir / "release-attestation.json",
        message="Release attestation was written.",
    )
    attestation_status = _candidate_status_from_checks([*checks, attestation_check])
    attestation = _build_release_candidate_attestation(
        candidate_dir=candidate_dir,
        source=source,
        candidate_path=candidate_path,
        require_release_candidate_pass=require_release_candidate_pass,
        verification_status=attestation_status,
        checks=[*checks, attestation_check],
        candidate=candidate,
        release_info=release_info,
        artifact_manifest=artifact_manifest,
        wheel_path=wheel_path,
        stored_readiness_verify=stored_readiness_verify,
        readiness_verify_report=readiness_verify_report,
        baseline_verify=baseline_verify,
        exact_baseline_verify=exact_baseline_verify,
        sdist_path=sdist_path,
    )
    try:
        _write_release_candidate_attestation_outputs(candidate_dir, attestation)
    except OSError as exc:
        attestation_check = _candidate_check(
            "release_attestation",
            "fail",
            required=True,
            path=candidate_dir / "release-attestation.json",
            message=f"Release attestation could not be written: {exc}",
        )
        attestation = None
    checks.append(attestation_check)

    failed = [check for check in checks if check.get("status") == "fail" and check.get("required")]
    warnings = [check for check in checks if check.get("status") == "warn"]
    status = "fail" if failed else "warn" if warnings else "pass"
    return {
        "schema_version": RELEASE_CANDIDATE_VERIFY_SCHEMA_VERSION,
        "status": status,
        "source": str(source),
        "release_candidate_path": str(candidate_path),
        "require_release_candidate_pass": require_release_candidate_pass,
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "warning_count": len(warnings),
            "release_candidate_pass_required": require_release_candidate_pass,
            "release_candidate_status": candidate.get("status") if candidate else None,
            "release_candidate_step_count": len(candidate.get("steps", [])) if candidate else 0,
            "release_candidate_require_clean_git": candidate.get("require_clean_git") if candidate else None,
            "artifact_manifest_status": artifact_manifest.get("status") if artifact_manifest else None,
            "artifact_manifest_artifact_count": (
                (artifact_manifest.get("summary") or {}).get("artifact_count") if artifact_manifest else None
            ),
            "artifact_manifest_total_bytes": (
                (artifact_manifest.get("summary") or {}).get("total_bytes") if artifact_manifest else None
            ),
            "release_attestation_status": attestation.get("status") if attestation else None,
            "release_attestation_evidence_hash": attestation.get("evidence_hash") if attestation else None,
            "release_info_status": release_info.get("status") if release_info else None,
            "release_info_dirty": ((release_info.get("summary") or {}).get("dirty") if release_info else None),
            "release_info_commit": ((release_info.get("git") or {}).get("commit") if release_info else None),
            "readiness_verify_status": stored_readiness_verify.get("status") if stored_readiness_verify else None,
            "nested_readiness_verify_status": readiness_verify_report.get("status") if readiness_verify_report else None,
            "baseline_verify_status": baseline_verify.get("status") if baseline_verify else None,
            "exact_baseline_verify_status": exact_baseline_verify.get("status") if exact_baseline_verify else None,
            "wheel": str(wheel_path) if wheel_path else None,
            "wheel_smoke_status": _candidate_step_status(candidate, "wheel_smoke"),
            "sdist": str(sdist_path) if sdist_path else None,
            "sdist_status": _candidate_step_status(candidate, "sdist_build"),
        },
        "checks": checks,
        "artifacts": {
            "release_candidate": _candidate_artifact_reference(candidate),
            "artifact_manifest": _candidate_artifact_reference(artifact_manifest),
            "release_attestation": _candidate_artifact_reference(attestation),
            "release_info": _candidate_artifact_reference(release_info),
            "readiness_verification": _candidate_artifact_reference(readiness_verify_report),
            "stored_readiness_verify": _candidate_artifact_reference(stored_readiness_verify),
            "baseline_verify": _candidate_artifact_reference(baseline_verify),
            "exact_baseline_verify": _candidate_artifact_reference(exact_baseline_verify),
        },
        "outputs": {
            "release_attestation": str(candidate_dir / "release-attestation.json"),
            "release_attestation_markdown": str(candidate_dir / "release-attestation.md"),
        },
    }


def format_release_candidate_verify_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Release Candidate Verify",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source')}`",
        f"- Release candidate: `{report.get('release_candidate_path')}`",
        f"- Require release-candidate pass: `{report.get('require_release_candidate_pass')}`",
        f"- Checks: `{summary.get('check_count', 0)}`",
        f"- Failed checks: `{summary.get('failed_check_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Release-candidate status: `{summary.get('release_candidate_status')}`",
        f"- Require clean Git: `{summary.get('release_candidate_require_clean_git')}`",
        f"- Artifact manifest: `{summary.get('artifact_manifest_status')}`",
        f"- Artifact count: `{summary.get('artifact_manifest_artifact_count')}`",
        f"- Release attestation: `{summary.get('release_attestation_status')}`",
        f"- Evidence hash: `{summary.get('release_attestation_evidence_hash')}`",
        f"- Release info: `{summary.get('release_info_status')}`",
        f"- Git commit: `{summary.get('release_info_commit')}`",
        f"- Git dirty: `{summary.get('release_info_dirty')}`",
        f"- Nested readiness verify: `{summary.get('nested_readiness_verify_status')}`",
        f"- Baseline verify: `{summary.get('baseline_verify_status')}`",
        f"- Exact baseline verify: `{summary.get('exact_baseline_verify_status')}`",
        f"- Wheel: `{summary.get('wheel')}`",
        f"- Wheel smoke: `{summary.get('wheel_smoke_status')}`",
        f"- Sdist: `{summary.get('sdist')}`",
        f"- Sdist status: `{summary.get('sdist_status')}`",
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


def _run_candidate_step(
    steps: list[dict[str, Any]],
    name: str,
    *,
    command: str,
    required: bool,
    action: Callable[[], tuple[str, str, dict[str, Any]]],
) -> None:
    started = time.time()
    try:
        status, message, data = action()
    except Exception as exc:  # pragma: no cover - exercised by real command failures.
        status = "fail"
        message = f"{name} failed: {exc}"
        data = {"error": str(exc)}
    steps.append(
        {
            "name": name,
            "status": status,
            "required": required,
            "command": command,
            "message": message,
            "elapsed_seconds": round(time.time() - started, 4),
            "data": data,
        }
    )


def _run_release_info(root: Path, output_dir: Path, *, require_clean: bool = False) -> tuple[str, str, dict[str, Any]]:
    report = build_release_info(root=root, require_clean=require_clean)
    json_path = output_dir / "release-info.json"
    markdown_path = output_dir / "release-info.md"
    _write_json(json_path, report)
    markdown_path.write_text(format_release_info_markdown(report), encoding="utf-8")
    status = "pass" if report.get("status") in {"pass", "warn"} else "fail"
    return status, f"Release info returned {report.get('status')}.", {
        "report": str(json_path),
        "markdown": str(markdown_path),
        "git_commit": (report.get("git") or {}).get("commit"),
        "git_dirty": (report.get("summary") or {}).get("dirty"),
        "version": (report.get("project") or {}).get("version"),
    }


def _run_readiness(
    root: Path,
    readiness_dir: Path,
    *,
    counter: str,
    skip_tests: bool,
    check_ollama: bool,
    ollama_endpoint: str,
    ollama_timeout: float,
) -> tuple[str, str, dict[str, Any]]:
    report = run_product_readiness(
        out_dir=readiness_dir,
        counter=counter,
        skip_tests=skip_tests,
        check_ollama=check_ollama,
        ollama_endpoint=ollama_endpoint,
        ollama_timeout=ollama_timeout,
        cwd=root,
    )
    status = "pass" if report.get("status") == "pass" else "warn" if report.get("status") == "warn" else "fail"
    return status, f"Product readiness returned {report.get('status')}.", {
        "output_dir": str(readiness_dir),
        "report": str(readiness_dir / "readiness.json"),
        "markdown": str(readiness_dir / "readiness.md"),
        "readiness_status": report.get("status"),
        "failed_required_count": (report.get("summary") or {}).get("failed_required_count", 0),
    }


def _run_readiness_verify(readiness_dir: Path, output_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = verify_product_readiness_pack(readiness_dir, require_readiness_pass=True)
    json_path = output_dir / "readiness-verify.json"
    markdown_path = output_dir / "readiness-verify.md"
    _write_json(json_path, report)
    markdown_path.write_text(format_product_readiness_verify_markdown(report), encoding="utf-8")
    status = "pass" if report.get("status") == "pass" else "warn" if report.get("status") == "warn" else "fail"
    return status, f"Readiness pack verification returned {report.get('status')}.", {
        "report": str(json_path),
        "markdown": str(markdown_path),
        "failed_check_count": (report.get("summary") or {}).get("failed_check_count", 0),
    }


def _run_exact_baselines(
    output_dir: Path,
    root: Path,
    *,
    require_exact_tokenizer: bool,
) -> tuple[str, str, dict[str, Any]]:
    if not require_exact_tokenizer:
        return "skip", "Exact-tokenizer baseline verification skipped by request.", {}
    return _run_baselines(
        output_dir,
        root,
        include_exact_tokenizer=True,
        stem="exact-baseline-verify",
        allow_partial=False,
    )


def _run_baselines(
    output_dir: Path,
    root: Path,
    *,
    include_exact_tokenizer: bool,
    stem: str,
    allow_partial: bool,
) -> tuple[str, str, dict[str, Any]]:
    report = verify_benchmark_baselines(root=root, include_exact_tokenizer=include_exact_tokenizer)
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    _write_json(json_path, report)
    markdown_path.write_text(format_benchmark_baseline_verify_markdown(report), encoding="utf-8")
    report_status = report.get("status")
    failed_count = int((report.get("summary") or {}).get("failed_count", 0))
    if report_status == "pass" or (allow_partial and report_status == "partial" and failed_count == 0):
        status = "pass"
    else:
        status = "fail"
    return status, f"Benchmark baseline verification returned {report_status}.", {
        "report": str(json_path),
        "markdown": str(markdown_path),
        "include_exact_tokenizer": include_exact_tokenizer,
        "failed_count": failed_count,
        "skipped_count": (report.get("summary") or {}).get("skipped_count", 0),
        "verified_count": (report.get("summary") or {}).get("verified_count", 0),
    }


def _run_wheel_build(root: Path, output_dir: Path, wheel_dir: Path) -> tuple[str, str, dict[str, Any]]:
    wheel_dir.mkdir(parents=True, exist_ok=True)
    for old_wheel in wheel_dir.glob("tokensquash-*.whl"):
        old_wheel.unlink()
    log_path = output_dir / "wheel-build.txt"
    command = [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(wheel_dir)]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    wheels = sorted(wheel_dir.glob("tokensquash-*.whl"))
    wheel_path = wheels[-1] if wheels else None
    packaged_demo_data = _wheel_contains(wheel_path, PACKAGED_DEMO_DATA_PATH) if wheel_path else False
    license_files = _package_license_files(wheel_path, _wheel_contains)
    wheel_metadata = _wheel_metadata(wheel_path)
    wheel_metadata_mismatches = _package_metadata_mismatches(
        wheel_metadata,
        expected_name=PROJECT_NAME,
        expected_version=package_version(root),
        expected_requires_python=package_requires_python(root),
    )
    log_text = (
        f"$ {' '.join(command)}\n"
        f"exit_code={completed.returncode}\n"
        f"wheel={wheel_path or ''}\n"
        f"contains_{PACKAGED_DEMO_DATA_PATH}={packaged_demo_data}\n\n"
        "## license files\n"
        f"{json.dumps(license_files, indent=2, sort_keys=True)}\n\n"
        "## metadata\n"
        f"{json.dumps(wheel_metadata, indent=2, sort_keys=True)}\n"
        f"metadata_mismatches={json.dumps(wheel_metadata_mismatches, sort_keys=True)}\n\n"
        "## stdout\n"
        f"{completed.stdout}\n"
        "## stderr\n"
        f"{completed.stderr}\n"
    )
    log_path.write_text(log_text, encoding="utf-8")
    if completed.returncode != 0:
        status = "fail"
        message = "Wheel build failed."
    elif not wheel_path:
        status = "fail"
        message = "Wheel build completed but no TokenSquash wheel was produced."
    elif not packaged_demo_data:
        status = "fail"
        message = f"Wheel is missing packaged demo data: {PACKAGED_DEMO_DATA_PATH}."
    elif not all(license_files.values()):
        status = "fail"
        message = f"Wheel is missing required license files: {', '.join(_missing_package_license_files(license_files))}."
    elif wheel_metadata_mismatches:
        status = "fail"
        message = "Wheel metadata does not match the release package metadata."
    else:
        status = "pass"
        message = "Wheel built, metadata matches, packaged demo data is present, and license files are present."
    return status, message, {
        "wheel_dir": str(wheel_dir),
        "log": str(log_path),
        "returncode": completed.returncode,
        "wheel": str(wheel_path) if wheel_path else None,
        "packaged_demo_data": packaged_demo_data,
        "license_files": license_files,
        "wheel_metadata": wheel_metadata,
        "wheel_metadata_mismatches": wheel_metadata_mismatches,
    }


def _run_wheel_smoke(root: Path, output_dir: Path, wheel_dir: Path) -> tuple[str, str, dict[str, Any]]:
    log_path = output_dir / "wheel-smoke.txt"
    wheel_path = _candidate_wheel_path(wheel_dir, None)
    if wheel_path is None:
        log_path.write_text("No TokenSquash wheel found for smoke test.\n", encoding="utf-8")
        return "fail", "Wheel smoke test could not find a built wheel.", {"log": str(log_path)}

    logs: list[str] = [f"wheel={wheel_path}"]
    about_payload: dict[str, Any] | None = None
    demo_payload: dict[str, Any] | None = None
    create_env = install = about = demo = None
    with tempfile.TemporaryDirectory(prefix="tokensquash-wheel-smoke-") as tmp:
        temp_dir = Path(tmp)
        env_dir = temp_dir / "venv"
        demo_dir = temp_dir / "demo"
        create_env = _run_logged_command(
            [sys.executable, "-m", "venv", str(env_dir)],
            cwd=root,
            logs=logs,
            label="create_venv",
        )
        env_python = _venv_python(env_dir)
        if create_env.returncode == 0:
            install = _run_logged_command(
                [str(env_python), "-m", "pip", "install", "--no-deps", str(wheel_path)],
                cwd=root,
                logs=logs,
                label="install_wheel",
            )
        if install is not None and install.returncode == 0:
            about = _run_logged_command(
                [str(env_python), "-m", "tokensquash", "about", "--json"],
                cwd=root,
                logs=logs,
                label="about_json",
            )
            about_payload = _json_stdout_payload(about)
        if about_payload is not None and about_payload.get("status") == "pass":
            demo = _run_logged_command(
                [
                    str(env_python),
                    "-m",
                    "tokensquash",
                    "demo",
                    "--counter",
                    "chars",
                    "--out-dir",
                    str(demo_dir),
                    "--json",
                ],
                cwd=root,
                logs=logs,
                label="demo_json",
            )
            demo_payload = _json_stdout_payload(demo)

    log_path.write_text("\n".join(logs).rstrip() + "\n", encoding="utf-8")
    demo_summary = demo_payload.get("summary", {}) if demo_payload else {}
    passed = (
        create_env is not None
        and create_env.returncode == 0
        and install is not None
        and install.returncode == 0
        and about is not None
        and about.returncode == 0
        and about_payload is not None
        and about_payload.get("schema_version") == "tokensquash.product.manifest.v1"
        and about_payload.get("status") == "pass"
        and demo is not None
        and demo.returncode == 0
        and demo_payload is not None
        and demo_payload.get("schema_version") == "tokensquash.demo.v1"
        and demo_payload.get("status") == "pass"
        and int(demo_summary.get("turn_count", 0)) > 0
    )
    return (
        "pass" if passed else "fail",
        "Wheel installed in an isolated environment and ran about/demo." if passed else "Wheel smoke test failed.",
        {
            "wheel": str(wheel_path),
            "log": str(log_path),
            "create_env_returncode": create_env.returncode if create_env is not None else None,
            "install_returncode": install.returncode if install is not None else None,
            "about_returncode": about.returncode if about is not None else None,
            "demo_returncode": demo.returncode if demo is not None else None,
            "about_status": about_payload.get("status") if about_payload else None,
            "demo_status": demo_payload.get("status") if demo_payload else None,
            "demo_turn_count": demo_summary.get("turn_count", 0),
            "demo_saved_pct": demo_summary.get("saved_pct", 0.0),
        },
    )


def _run_sdist_build(root: Path, output_dir: Path, sdist_dir: Path) -> tuple[str, str, dict[str, Any]]:
    sdist_dir.mkdir(parents=True, exist_ok=True)
    for old_sdist in sdist_dir.glob("tokensquash-*.tar.gz"):
        old_sdist.unlink()
    log_path = output_dir / "sdist-build.txt"
    script = "import setuptools.build_meta as b, sys; print(b.build_sdist(sys.argv[1]))"
    sdist_arg = _sdist_build_arg(root, sdist_dir)
    command = [sys.executable, "-c", script, sdist_arg]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    sdists = sorted(sdist_dir.glob("tokensquash-*.tar.gz"))
    sdist_path = sdists[-1] if sdists else None
    packaged_demo_data = _sdist_contains(sdist_path, PACKAGED_DEMO_DATA_PATH) if sdist_path else False
    license_files = _package_license_files(sdist_path, _sdist_contains)
    sdist_metadata = _sdist_metadata(sdist_path)
    sdist_metadata_mismatches = _package_metadata_mismatches(
        sdist_metadata,
        expected_name=PROJECT_NAME,
        expected_version=package_version(root),
        expected_requires_python=package_requires_python(root),
    )
    log_text = (
        f"$ {' '.join(command)}\n"
        f"exit_code={completed.returncode}\n"
        f"sdist={sdist_path or ''}\n"
        f"contains_{PACKAGED_DEMO_DATA_PATH}={packaged_demo_data}\n\n"
        "## license files\n"
        f"{json.dumps(license_files, indent=2, sort_keys=True)}\n\n"
        "## metadata\n"
        f"{json.dumps(sdist_metadata, indent=2, sort_keys=True)}\n"
        f"metadata_mismatches={json.dumps(sdist_metadata_mismatches, sort_keys=True)}\n\n"
        "## stdout\n"
        f"{completed.stdout}\n"
        "## stderr\n"
        f"{completed.stderr}\n"
    )
    log_path.write_text(log_text, encoding="utf-8")
    if completed.returncode != 0:
        status = "fail"
        message = "Source distribution build failed."
    elif not sdist_path:
        status = "fail"
        message = "Source distribution build completed but no TokenSquash sdist was produced."
    elif not packaged_demo_data:
        status = "fail"
        message = f"Source distribution is missing packaged demo data: {PACKAGED_DEMO_DATA_PATH}."
    elif not all(license_files.values()):
        status = "fail"
        message = (
            "Source distribution is missing required license files: "
            f"{', '.join(_missing_package_license_files(license_files))}."
        )
    elif sdist_metadata_mismatches:
        status = "fail"
        message = "Source distribution metadata does not match the release package metadata."
    else:
        status = "pass"
        message = (
            "Source distribution built, metadata matches, packaged demo data is present, "
            "and license files are present."
        )
    data = {
        "sdist_dir": str(sdist_dir),
        "log": str(log_path),
        "returncode": completed.returncode,
        "sdist": str(sdist_path) if sdist_path else None,
        "packaged_demo_data": packaged_demo_data,
        "license_files": license_files,
        "sdist_metadata": sdist_metadata,
        "sdist_metadata_mismatches": sdist_metadata_mismatches,
    }
    if completed.returncode != 0:
        data["stdout"] = _text_excerpt(completed.stdout)
        data["stderr"] = _text_excerpt(completed.stderr)
    return status, message, data


def _run_logged_command(
    command: list[str],
    *,
    cwd: Path,
    logs: list[str],
    label: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    logs.extend(
        [
            "",
            f"## {label}",
            f"$ {' '.join(command)}",
            f"exit_code={completed.returncode}",
            "### stdout",
            completed.stdout.rstrip(),
            "### stderr",
            completed.stderr.rstrip(),
        ]
    )
    return completed


def _json_stdout_payload(completed: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _venv_python(env_dir: Path) -> Path:
    if sys.platform == "win32":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def _wheel_contains(path: Path | None, member: str) -> bool:
    if path is None:
        return False
    target = member.replace("\\", "/")
    try:
        with ZipFile(path) as archive:
            return any(
                item.replace("\\", "/") == target
                or item.replace("\\", "/").endswith(f"/{target}")
                for item in archive.namelist()
            )
    except (BadZipFile, OSError):
        return False


def _package_license_files(
    path: Path | None,
    contains: Callable[[Path | None, str], bool],
) -> dict[str, bool]:
    return {filename: contains(path, filename) for filename in REQUIRED_PACKAGE_LICENSE_FILES}


def _missing_package_license_files(license_files: dict[str, bool]) -> list[str]:
    return [filename for filename in REQUIRED_PACKAGE_LICENSE_FILES if not license_files.get(filename)]


def _wheel_metadata(path: Path | None) -> dict[str, Any]:
    base = {
        "present": False,
        "metadata_path": None,
        "name": None,
        "version": None,
        "requires_python": None,
    }
    if path is None:
        return {**base, "message": "No wheel path was resolved."}
    try:
        with ZipFile(path) as archive:
            metadata_members = [
                member
                for member in archive.namelist()
                if member.endswith(".dist-info/METADATA")
            ]
            if not metadata_members:
                return {**base, "message": "Wheel METADATA file was not found."}
            metadata_path = sorted(metadata_members)[0]
            text = archive.read(metadata_path).decode("utf-8", errors="replace")
    except (BadZipFile, OSError, KeyError) as exc:
        return {**base, "message": f"Wheel metadata could not be read: {exc}"}

    parsed = Parser().parsestr(text)
    return {
        **base,
        "present": True,
        "metadata_path": metadata_path,
        "name": parsed.get("Name"),
        "version": parsed.get("Version"),
        "requires_python": parsed.get("Requires-Python"),
        "message": "Wheel metadata captured.",
    }


def _package_metadata_mismatches(
    metadata: dict[str, Any],
    *,
    expected_name: str | None,
    expected_version: str | None,
    expected_requires_python: str | None,
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    if not metadata.get("present"):
        return [{"field": "METADATA", "expected": "present", "actual": metadata.get("message")}]

    actual_name = metadata.get("name")
    if expected_name and str(actual_name).lower() != expected_name.lower():
        mismatches.append({"field": "Name", "expected": expected_name, "actual": actual_name})

    actual_version = metadata.get("version")
    if expected_version and actual_version != expected_version:
        mismatches.append({"field": "Version", "expected": expected_version, "actual": actual_version})

    actual_requires = metadata.get("requires_python")
    if expected_requires_python and actual_requires != expected_requires_python:
        mismatches.append(
            {
                "field": "Requires-Python",
                "expected": expected_requires_python,
                "actual": actual_requires,
            }
        )
    return mismatches


def _sdist_contains(path: Path | None, member: str) -> bool:
    if path is None:
        return False
    target = member.replace("\\", "/")
    try:
        with tarfile.open(path, "r:gz") as archive:
            return any(
                item.isfile() and item.name.replace("\\", "/").endswith(f"/{target}")
                for item in archive.getmembers()
            )
    except (tarfile.TarError, OSError):
        return False


def _sdist_metadata(path: Path | None) -> dict[str, Any]:
    base = {
        "present": False,
        "metadata_path": None,
        "name": None,
        "version": None,
        "requires_python": None,
    }
    if path is None:
        return {**base, "message": "No source distribution path was resolved."}
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.isfile() and member.name.replace("\\", "/").endswith("/PKG-INFO")
            ]
            if not members:
                return {**base, "message": "Source distribution PKG-INFO file was not found."}
            metadata_member = sorted(members, key=lambda item: item.name)[0]
            handle = archive.extractfile(metadata_member)
            if handle is None:
                return {**base, "message": "Source distribution PKG-INFO could not be opened."}
            text = handle.read().decode("utf-8", errors="replace")
    except (tarfile.TarError, OSError, KeyError) as exc:
        return {**base, "message": f"Source distribution metadata could not be read: {exc}"}

    parsed = Parser().parsestr(text)
    return {
        **base,
        "present": True,
        "metadata_path": metadata_member.name,
        "name": parsed.get("Name"),
        "version": parsed.get("Version"),
        "requires_python": parsed.get("Requires-Python"),
        "message": "Source distribution metadata captured.",
    }


def _sdist_build_arg(root: Path, sdist_dir: Path) -> str:
    try:
        return os.path.relpath(sdist_dir.resolve(), root.resolve())
    except ValueError:
        return str(sdist_dir)


def _text_excerpt(value: str, *, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]\n"


def _candidate_artifact_manifest_expected_files(candidate_dir: Path, candidate: dict[str, Any]) -> list[Path]:
    outputs = candidate.get("outputs", {}) if isinstance(candidate, dict) else {}
    files: dict[str, Path] = {}

    def add_path(path: Path) -> None:
        if not path.exists():
            return
        if path.is_dir():
            for child in path.rglob("*"):
                add_path(child)
            return
        if not path.is_file() or path.name in ARTIFACT_MANIFEST_FILENAMES:
            return
        if not _candidate_path_is_within(path, candidate_dir):
            return
        relative = _candidate_relative_path(candidate_dir, path)
        files[relative] = path

    for key, fallback in (
        ("report", Path("release-candidate.json")),
        ("markdown", Path("release-candidate.md")),
        ("release_info", Path("release-info.json")),
        ("release_info_markdown", Path("release-info.md")),
        ("readiness_verify", Path("readiness-verify.json")),
        ("readiness_verify_markdown", Path("readiness-verify.md")),
        ("baseline_verify", Path("baseline-verify.json")),
        ("baseline_verify_markdown", Path("baseline-verify.md")),
        ("exact_baseline_verify", Path("exact-baseline-verify.json")),
        ("exact_baseline_verify_markdown", Path("exact-baseline-verify.md")),
        ("wheel_log", Path("wheel-build.txt")),
        ("wheel_smoke_log", Path("wheel-smoke.txt")),
        ("sdist_log", Path("sdist-build.txt")),
    ):
        add_path(_resolve_candidate_artifact(candidate_dir, outputs.get(key), fallback))

    readiness_dir = _resolve_candidate_artifact(candidate_dir, outputs.get("readiness_dir"), Path("readiness"))
    add_path(readiness_dir)

    wheel_dir = _resolve_candidate_artifact(candidate_dir, outputs.get("wheel_dir"), Path("wheel"))
    add_path(wheel_dir)
    wheel_path = _candidate_wheel_path(wheel_dir, candidate)
    if wheel_path is not None:
        add_path(wheel_path)

    sdist_dir = _resolve_candidate_artifact(candidate_dir, outputs.get("sdist_dir"), Path("sdist"))
    add_path(sdist_dir)
    sdist_path = _candidate_sdist_path(sdist_dir, candidate)
    if sdist_path is not None:
        add_path(sdist_path)

    return [files[key] for key in sorted(files)]


def _candidate_artifact_manifest_entry(candidate_dir: Path, path: Path) -> dict[str, Any]:
    return {
        "relative_path": _candidate_relative_path(candidate_dir, path),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _build_release_candidate_attestation(
    *,
    candidate_dir: Path,
    source: Path,
    candidate_path: Path,
    require_release_candidate_pass: bool,
    verification_status: str,
    checks: list[dict[str, Any]],
    candidate: dict[str, Any] | None,
    release_info: dict[str, Any] | None,
    artifact_manifest: dict[str, Any] | None,
    wheel_path: Path | None,
    stored_readiness_verify: dict[str, Any] | None,
    readiness_verify_report: dict[str, Any] | None,
    baseline_verify: dict[str, Any] | None,
    exact_baseline_verify: dict[str, Any] | None,
    sdist_path: Path | None,
) -> dict[str, Any]:
    release_summary = (release_info.get("summary") if release_info else {}) or {}
    git = (release_info.get("git") if release_info else {}) or {}
    project = (release_info.get("project") if release_info else {}) or {}
    verification = {
        "schema_version": RELEASE_CANDIDATE_VERIFY_SCHEMA_VERSION,
        "status": verification_status,
        "source": str(source),
        "require_release_candidate_pass": require_release_candidate_pass,
        "check_count": len(checks),
        "failed_check_count": sum(1 for check in checks if check.get("status") == "fail" and check.get("required")),
        "warning_count": sum(1 for check in checks if check.get("status") == "warn"),
    }
    materials = {
        "release_candidate": _candidate_file_reference(candidate_dir, candidate_path),
        "artifact_manifest": _candidate_file_reference(candidate_dir, candidate_dir / "artifact-manifest.json"),
        "wheel": _candidate_file_reference(candidate_dir, wheel_path),
        "sdist": _candidate_file_reference(candidate_dir, sdist_path),
    }
    evidence = {
        "release_candidate_status": candidate.get("status") if candidate else None,
        "release_candidate_require_clean_git": candidate.get("require_clean_git") if candidate else None,
        "release_info_status": release_info.get("status") if release_info else None,
        "artifact_manifest_status": artifact_manifest.get("status") if artifact_manifest else None,
        "readiness_verify_status": stored_readiness_verify.get("status") if stored_readiness_verify else None,
        "nested_readiness_verify_status": readiness_verify_report.get("status") if readiness_verify_report else None,
        "baseline_verify_status": baseline_verify.get("status") if baseline_verify else None,
        "exact_baseline_verify_status": exact_baseline_verify.get("status") if exact_baseline_verify else None,
        "wheel_smoke_status": _candidate_step_status(candidate, "wheel_smoke"),
        "sdist_status": _candidate_step_status(candidate, "sdist_build"),
    }
    evidence_material = {
        "git_commit": git.get("commit"),
        "git_dirty": release_summary.get("dirty"),
        "version": project.get("version"),
        "require_clean_git": candidate.get("require_clean_git") if candidate else None,
        "verification_status": verification_status,
        "release_candidate_sha256": (materials.get("release_candidate") or {}).get("sha256"),
        "artifact_manifest_sha256": (materials.get("artifact_manifest") or {}).get("sha256"),
        "wheel_sha256": (materials.get("wheel") or {}).get("sha256"),
        "sdist_sha256": (materials.get("sdist") or {}).get("sha256"),
    }
    return {
        "schema_version": RELEASE_CANDIDATE_ATTESTATION_SCHEMA_VERSION,
        "status": verification_status,
        "evidence_hash": _stable_sha256(evidence_material),
        "out_dir": str(candidate_dir),
        "provenance": {
            "project": {
                "name": project.get("name"),
                "version": project.get("version"),
                "requires_python": project.get("requires_python"),
            },
            "git": {
                "commit": git.get("commit"),
                "short_commit": git.get("short_commit"),
                "branch": git.get("branch"),
                "dirty": release_summary.get("dirty"),
            },
        },
        "verification": verification,
        "evidence": evidence,
        "materials": materials,
        "signature": {
            "type": "unsigned-local-attestation",
            "signed": False,
            "rationale": "This local attestation records hashes and verification status but is not cryptographically signed.",
        },
    }


def _write_release_candidate_attestation_outputs(candidate_dir: Path, report: dict[str, Any]) -> None:
    _write_json(candidate_dir / "release-attestation.json", report)
    (candidate_dir / "release-attestation.md").write_text(
        format_release_candidate_attestation_markdown(report),
        encoding="utf-8",
    )


def _candidate_file_reference(candidate_dir: Path, path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    resolved = path.resolve()
    if _candidate_path_is_within(resolved, candidate_dir):
        display_path = _candidate_relative_path(candidate_dir, resolved)
    else:
        display_path = str(resolved)
    return {
        "path": display_path,
        "bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
    }


def _stable_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _append_candidate_artifact_manifest_integrity_check(
    checks: list[dict[str, Any]],
    candidate_dir: Path,
    candidate: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    *,
    required: bool,
) -> None:
    if manifest is None:
        checks.append(
            _candidate_check(
                "artifact_manifest_integrity",
                "fail" if required else "skip",
                required=required,
                message="Cannot verify artifact hashes because the artifact manifest is unreadable.",
            )
        )
        return
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        checks.append(
            _candidate_check(
                "artifact_manifest_integrity",
                "fail",
                required=required,
                message="Artifact manifest field `artifacts` must be a list.",
            )
        )
        return

    expected_paths = _candidate_artifact_manifest_expected_files(candidate_dir, candidate or {})
    expected = {_candidate_relative_path(candidate_dir, path) for path in expected_paths}
    recorded: set[str] = set()
    failures: list[dict[str, Any]] = []
    verified_count = 0
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            failures.append({"index": index, "reason": "artifact entry is not an object"})
            continue
        relative = artifact.get("relative_path")
        if not isinstance(relative, str) or not relative:
            failures.append({"index": index, "reason": "artifact entry is missing relative_path"})
            continue
        rel_path = Path(relative)
        if rel_path.is_absolute() or ".." in rel_path.parts or rel_path.name in ARTIFACT_MANIFEST_FILENAMES:
            failures.append({"relative_path": relative, "reason": "artifact path is not allowed"})
            continue
        if relative in recorded:
            failures.append({"relative_path": relative, "reason": "duplicate artifact entry"})
            continue
        recorded.add(relative)

        path = candidate_dir / rel_path
        if not _candidate_path_is_within(path, candidate_dir):
            failures.append({"relative_path": relative, "reason": "artifact path escapes the candidate directory"})
            continue
        if not path.exists() or not path.is_file():
            failures.append({"relative_path": relative, "reason": "artifact file is missing"})
            continue

        actual_bytes = path.stat().st_size
        expected_bytes = artifact.get("bytes")
        if expected_bytes != actual_bytes:
            failures.append(
                {
                    "relative_path": relative,
                    "reason": "byte size mismatch",
                    "expected_bytes": expected_bytes,
                    "actual_bytes": actual_bytes,
                }
            )
            continue

        expected_sha = artifact.get("sha256")
        actual_sha = _sha256_file(path)
        if expected_sha != actual_sha:
            failures.append(
                {
                    "relative_path": relative,
                    "reason": "sha256 mismatch",
                    "expected_sha256": expected_sha,
                    "actual_sha256": actual_sha,
                }
            )
            continue
        verified_count += 1

    missing_entries = sorted(expected - recorded)
    passed = not failures and not missing_entries and verified_count > 0
    checks.append(
        _candidate_check(
            "artifact_manifest_integrity",
            "pass" if passed else "fail",
            required=required,
            message=(
                f"Verified {verified_count} artifact hash(es)."
                if passed
                else "Artifact manifest is missing entries or contains mismatched hashes."
            ),
            data={
                "verified_count": verified_count,
                "expected_count": len(expected),
                "recorded_count": len(recorded),
                "missing_entries": missing_entries[:20],
                "mismatch_count": len(failures),
                "mismatches": failures[:20],
            },
        )
    )


def _verify_candidate_json_artifact(
    name: str,
    path: Path,
    schema_version: str,
    *,
    required: bool,
    allowed_statuses: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not path.exists():
        return None, _candidate_check(
            name,
            "fail" if required else "skip",
            required=required,
            path=path,
            message=f"Missing JSON artifact: {path}.",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return None, _candidate_check(
            name,
            "fail" if required else "skip",
            required=required,
            path=path,
            message=f"Could not read JSON artifact: {exc}",
        )
    if payload.get("schema_version") != schema_version:
        return payload, _candidate_check(
            name,
            "fail",
            required=required,
            path=path,
            message=f"Expected schema {schema_version}, found {payload.get('schema_version')}.",
            data={"schema_version": payload.get("schema_version"), "expected_schema_version": schema_version},
        )
    if payload.get("status") not in allowed_statuses:
        return payload, _candidate_check(
            name,
            "fail",
            required=required,
            path=path,
            message=f"Unexpected status {payload.get('status')}.",
            data={"status": payload.get("status"), "allowed_statuses": sorted(allowed_statuses)},
        )
    return payload, _candidate_check(
        name,
        "pass",
        required=required,
        path=path,
        message=f"Verified {schema_version} JSON artifact.",
        data={"schema_version": payload.get("schema_version"), "status": payload.get("status")},
    )


def _append_candidate_file_check(checks: list[dict[str, Any]], name: str, path: Path, *, required: bool) -> bool:
    if not path.exists():
        checks.append(
            _candidate_check(
                name,
                "fail" if required else "skip",
                required=required,
                path=path,
                message=f"Missing file artifact: {path}.",
            )
        )
        return False
    if not path.is_file():
        checks.append(
            _candidate_check(
                name,
                "fail",
                required=required,
                path=path,
                message=f"Expected a file artifact, found a non-file path: {path}.",
            )
        )
        return False
    size = path.stat().st_size
    if size <= 0:
        checks.append(
            _candidate_check(
                name,
                "fail",
                required=required,
                path=path,
                message=f"File artifact is empty: {path}.",
                data={"bytes": size},
            )
        )
        return False
    checks.append(
        _candidate_check(
            name,
            "pass",
            required=required,
            path=path,
            message="File artifact exists and is non-empty.",
            data={"bytes": size},
        )
    )
    return True


def _append_candidate_directory_check(checks: list[dict[str, Any]], name: str, path: Path, *, required: bool) -> bool:
    if not path.exists():
        checks.append(
            _candidate_check(
                name,
                "fail" if required else "skip",
                required=required,
                path=path,
                message=f"Missing directory artifact: {path}.",
            )
        )
        return False
    if not path.is_dir():
        checks.append(
            _candidate_check(
                name,
                "fail",
                required=required,
                path=path,
                message=f"Expected a directory artifact, found a non-directory path: {path}.",
            )
        )
        return False
    checks.append(_candidate_check(name, "pass", required=required, path=path, message="Directory artifact exists."))
    return True


def _append_candidate_approval_check(
    checks: list[dict[str, Any]],
    candidate_path: Path,
    candidate: dict[str, Any] | None,
) -> None:
    if candidate is None:
        checks.append(
            _candidate_check(
                "release_candidate_approval",
                "fail",
                required=True,
                path=candidate_path,
                message="Cannot require release-candidate pass because release-candidate.json is unreadable.",
            )
        )
        return
    status = candidate.get("status")
    checks.append(
        _candidate_check(
            "release_candidate_approval",
            "pass" if status == "pass" else "fail",
            required=True,
            path=candidate_path,
            message="Release-candidate status is pass." if status == "pass" else f"Release-candidate status is {status}.",
            data={"release_candidate_status": status},
        )
    )


def _append_status_expectation_check(
    checks: list[dict[str, Any]],
    name: str,
    payload: dict[str, Any] | None,
    *,
    required: bool,
    allowed_statuses: set[str],
) -> None:
    if payload is None:
        checks.append(
            _candidate_check(
                name,
                "fail" if required else "skip",
                required=required,
                message="Cannot verify report status because the report is unreadable.",
            )
        )
        return
    status = payload.get("status")
    passed = status in allowed_statuses
    checks.append(
        _candidate_check(
            name,
            "pass" if passed else "fail",
            required=required,
            message=(
                f"Report status {status} is acceptable."
                if passed
                else f"Report status {status} is not acceptable."
            ),
            data={"status": status, "allowed_statuses": sorted(allowed_statuses)},
        )
    )


def _append_candidate_clean_git_check(
    checks: list[dict[str, Any]],
    candidate: dict[str, Any] | None,
    release_info: dict[str, Any] | None,
) -> None:
    require_clean_git = bool(candidate.get("require_clean_git")) if candidate else False
    if not require_clean_git:
        checks.append(
            _candidate_check(
                "release_clean_git",
                "skip",
                required=False,
                message="Clean Git state was not required for this release-candidate pack.",
            )
        )
        return
    if release_info is None:
        checks.append(
            _candidate_check(
                "release_clean_git",
                "fail",
                required=True,
                message="Cannot verify clean Git state because release-info is unreadable.",
            )
        )
        return
    summary = release_info.get("summary") or {}
    git = release_info.get("git") or {}
    passed = (
        release_info.get("require_clean") is True
        and release_info.get("status") == "pass"
        and bool(summary.get("git_ready")) is True
        and bool(summary.get("dirty")) is False
    )
    checks.append(
        _candidate_check(
            "release_clean_git",
            "pass" if passed else "fail",
            required=True,
            message=(
                "Release-candidate pack required and captured a clean Git state."
                if passed
                else "Release-candidate pack required clean Git, but release-info did not prove it."
            ),
            data={
                "require_clean": release_info.get("require_clean"),
                "release_info_status": release_info.get("status"),
                "git_ready": summary.get("git_ready"),
                "dirty": summary.get("dirty"),
                "commit": git.get("commit"),
            },
        )
    )


def _append_baseline_expectation_check(
    checks: list[dict[str, Any]],
    name: str,
    payload: dict[str, Any] | None,
    *,
    required: bool,
    allow_partial: bool,
) -> None:
    if payload is None:
        checks.append(
            _candidate_check(
                name,
                "fail" if required else "skip",
                required=required,
                message="Cannot verify baseline status because the report is unreadable.",
            )
        )
        return
    summary = payload.get("summary") or {}
    failed_count = int(summary.get("failed_count", 0))
    status = payload.get("status")
    passed = status == "pass" or (allow_partial and status == "partial" and failed_count == 0)
    checks.append(
        _candidate_check(
            name,
            "pass" if passed else "fail",
            required=required,
            message=(
                f"Baseline report status {status} is acceptable."
                if passed
                else f"Baseline report status {status} is not acceptable."
            ),
            data={
                "status": status,
                "failed_count": failed_count,
                "skipped_count": summary.get("skipped_count", 0),
                "allow_partial": allow_partial,
            },
        )
    )


def _append_candidate_wheel_check(
    checks: list[dict[str, Any]],
    path: Path | None,
    *,
    release_info: dict[str, Any] | None,
    required: bool,
) -> None:
    if path is None:
        checks.append(
            _candidate_check(
                "wheel",
                "fail" if required else "skip",
                required=required,
                path=None,
                message="No TokenSquash wheel path could be resolved.",
            )
        )
        return
    if not path.exists() or not path.is_file():
        checks.append(
            _candidate_check(
                "wheel",
                "fail" if required else "skip",
                required=required,
                path=path,
                message=f"Missing wheel artifact: {path}.",
            )
        )
        return
    packaged_demo_data = _wheel_contains(path, PACKAGED_DEMO_DATA_PATH)
    license_files = _package_license_files(path, _wheel_contains)
    project = release_info.get("project") if release_info else {}
    metadata = _wheel_metadata(path)
    metadata_mismatches = _package_metadata_mismatches(
        metadata,
        expected_name=(project or {}).get("name") or PROJECT_NAME,
        expected_version=(project or {}).get("version"),
        expected_requires_python=(project or {}).get("requires_python"),
    )
    passed = packaged_demo_data and all(license_files.values()) and not metadata_mismatches
    checks.append(
        _candidate_check(
            "wheel",
            "pass" if passed else "fail",
            required=required,
            path=path,
            message=(
                "Wheel exists, package metadata matches, packaged demo data is present, and license files are present."
                if passed
                else "Wheel is missing packaged data, license files, or metadata does not match release-info."
            ),
            data={
                "packaged_demo_data": packaged_demo_data,
                "member": PACKAGED_DEMO_DATA_PATH,
                "license_files": license_files,
                "missing_license_files": _missing_package_license_files(license_files),
                "metadata": metadata,
                "metadata_mismatches": metadata_mismatches,
            },
        )
    )


def _append_candidate_wheel_smoke_check(
    checks: list[dict[str, Any]],
    candidate: dict[str, Any] | None,
    *,
    required: bool,
) -> None:
    if candidate is None:
        checks.append(
            _candidate_check(
                "wheel_smoke",
                "fail" if required else "skip",
                required=required,
                message="Cannot verify wheel smoke step because release-candidate.json is unreadable.",
            )
        )
        return
    step = _candidate_step(candidate, "wheel_smoke")
    if step is None:
        checks.append(
            _candidate_check(
                "wheel_smoke",
                "fail" if required else "skip",
                required=required,
                message="Release-candidate report does not include the wheel_smoke step.",
            )
        )
        return
    data = step.get("data") if isinstance(step.get("data"), dict) else {}
    passed = (
        step.get("status") == "pass"
        and data.get("install_returncode") == 0
        and data.get("about_status") == "pass"
        and data.get("demo_status") == "pass"
        and _candidate_int(data.get("demo_turn_count"), default=0) > 0
    )
    checks.append(
        _candidate_check(
            "wheel_smoke",
            "pass" if passed else "fail",
            required=required,
            message=(
                "Wheel smoke step installed the built wheel and ran about/demo."
                if passed
                else "Wheel smoke step did not prove the built wheel installs and runs."
            ),
            data={
                "step_status": step.get("status"),
                "install_returncode": data.get("install_returncode"),
                "about_status": data.get("about_status"),
                "demo_status": data.get("demo_status"),
                "demo_turn_count": data.get("demo_turn_count", 0),
            },
        )
    )


def _append_candidate_sdist_check(
    checks: list[dict[str, Any]],
    path: Path | None,
    *,
    release_info: dict[str, Any] | None,
    required: bool,
) -> None:
    if path is None:
        checks.append(
            _candidate_check(
                "sdist",
                "fail" if required else "skip",
                required=required,
                path=None,
                message="No TokenSquash source distribution path could be resolved.",
            )
        )
        return
    if not path.exists() or not path.is_file():
        checks.append(
            _candidate_check(
                "sdist",
                "fail" if required else "skip",
                required=required,
                path=path,
                message=f"Missing source distribution artifact: {path}.",
            )
        )
        return
    packaged_demo_data = _sdist_contains(path, PACKAGED_DEMO_DATA_PATH)
    license_files = _package_license_files(path, _sdist_contains)
    project = release_info.get("project") if release_info else {}
    metadata = _sdist_metadata(path)
    metadata_mismatches = _package_metadata_mismatches(
        metadata,
        expected_name=(project or {}).get("name") or PROJECT_NAME,
        expected_version=(project or {}).get("version"),
        expected_requires_python=(project or {}).get("requires_python"),
    )
    passed = packaged_demo_data and all(license_files.values()) and not metadata_mismatches
    checks.append(
        _candidate_check(
            "sdist",
            "pass" if passed else "fail",
            required=required,
            path=path,
            message=(
                "Source distribution exists, metadata matches, packaged demo data is present, and license files are present."
                if passed
                else "Source distribution is missing packaged data, license files, or metadata does not match release-info."
            ),
            data={
                "packaged_demo_data": packaged_demo_data,
                "member": PACKAGED_DEMO_DATA_PATH,
                "license_files": license_files,
                "missing_license_files": _missing_package_license_files(license_files),
                "metadata": metadata,
                "metadata_mismatches": metadata_mismatches,
            },
        )
    )


def _append_candidate_steps_check(
    checks: list[dict[str, Any]],
    candidate_path: Path,
    candidate: dict[str, Any] | None,
) -> None:
    if candidate is None:
        checks.append(
            _candidate_check(
                "release_candidate_steps",
                "fail",
                required=True,
                path=candidate_path,
                message="Cannot verify release-candidate steps because release-candidate.json is unreadable.",
            )
        )
        return
    steps = candidate.get("steps")
    summary = candidate.get("summary") or {}
    if not isinstance(steps, list):
        checks.append(
            _candidate_check(
                "release_candidate_steps",
                "fail",
                required=True,
                path=candidate_path,
                message="release_candidate.steps must be a list.",
            )
        )
        return
    required_steps = {
        "release_info",
        "readiness",
        "verify_readiness",
        "benchmark_baselines",
        "exact_tokenizer_baselines",
        "wheel_build",
        "wheel_smoke",
        "sdist_build",
    }
    names = {step.get("name") for step in steps if isinstance(step, dict)}
    missing_steps = sorted(required_steps - names)
    invalid_steps = [
        step.get("name", f"step[{index}]")
        for index, step in enumerate(steps)
        if not isinstance(step, dict)
        or step.get("status") not in {"pass", "warn", "fail", "skip"}
        or not step.get("name")
        or "required" not in step
    ]
    summary_count = int(summary.get("step_count", -1))
    passed = not missing_steps and not invalid_steps and summary_count == len(steps)
    checks.append(
        _candidate_check(
            "release_candidate_steps",
            "pass" if passed else "fail",
            required=True,
            path=candidate_path,
            message=(
                f"Release-candidate report lists {len(steps)} well-formed steps."
                if passed
                else "Release-candidate steps are missing, malformed, or inconsistent with summary."
            ),
            data={
                "step_count": len(steps),
                "summary_step_count": summary_count,
                "missing_steps": missing_steps,
                "invalid_steps": invalid_steps,
            },
        )
    )


def _candidate_wheel_path(wheel_dir: Path, candidate: dict[str, Any] | None) -> Path | None:
    if candidate:
        wheel_step = next(
            (
                step
                for step in candidate.get("steps", [])
                if isinstance(step, dict) and step.get("name") == "wheel_build"
            ),
            None,
        )
        if wheel_step:
            wheel = (wheel_step.get("data") or {}).get("wheel")
            if wheel:
                return Path(str(wheel))
    wheels = sorted(wheel_dir.glob("tokensquash-*.whl")) if wheel_dir.exists() and wheel_dir.is_dir() else []
    return wheels[-1] if wheels else None


def _candidate_sdist_path(sdist_dir: Path, candidate: dict[str, Any] | None) -> Path | None:
    if candidate:
        sdist_step = next(
            (
                step
                for step in candidate.get("steps", [])
                if isinstance(step, dict) and step.get("name") == "sdist_build"
            ),
            None,
        )
        if sdist_step:
            sdist = (sdist_step.get("data") or {}).get("sdist")
            if sdist:
                return Path(str(sdist))
    sdists = sorted(sdist_dir.glob("tokensquash-*.tar.gz")) if sdist_dir.exists() and sdist_dir.is_dir() else []
    return sdists[-1] if sdists else None


def _candidate_step(candidate: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next(
        (
            step
            for step in candidate.get("steps", [])
            if isinstance(step, dict) and step.get("name") == name
        ),
        None,
    )


def _candidate_step_status(candidate: dict[str, Any] | None, name: str) -> Any:
    if candidate is None:
        return None
    step = _candidate_step(candidate, name)
    return step.get("status") if step else None


def _candidate_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_candidate_artifact(base_dir: Path, value: Any, fallback: Path) -> Path:
    if isinstance(value, str) and value:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else base_dir / candidate
    return base_dir / fallback


def _candidate_relative_path(base_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(base_dir.resolve()).as_posix()


def _candidate_path_is_within(path: Path, base_dir: Path) -> bool:
    try:
        path.resolve().relative_to(base_dir.resolve())
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_artifact_reference(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "summary": payload.get("summary"),
    }


def _candidate_check(
    name: str,
    status: str,
    *,
    required: bool,
    path: Path | None = None,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    check = {
        "name": name,
        "status": status,
        "required": required,
        "message": message,
        "data": data or {},
    }
    if path is not None:
        check["path"] = str(path)
    return check


def _candidate_status_from_checks(checks: list[dict[str, Any]]) -> str:
    failed = [check for check in checks if check.get("status") == "fail" and check.get("required")]
    warnings = [check for check in checks if check.get("status") == "warn"]
    return "fail" if failed else "warn" if warnings else "pass"


def _release_candidate_commands(
    root: Path,
    output_dir: Path,
    readiness_dir: Path,
    wheel_dir: Path,
    sdist_dir: Path,
    counter: str,
    *,
    skip_tests: bool,
    require_exact_tokenizer: bool,
    require_clean_git: bool,
    check_ollama: bool,
    ollama_endpoint: str,
    ollama_timeout: float,
) -> list[str]:
    release_candidate = f"python -m tokensquash release-candidate --out-dir {output_dir} --counter {counter}"
    readiness = f"python -m tokensquash readiness --out-dir {readiness_dir} --counter {counter}"
    if skip_tests:
        release_candidate += " --skip-tests"
        readiness += " --skip-tests"
    if not require_exact_tokenizer:
        release_candidate += " --skip-exact-tokenizer"
    if require_clean_git:
        release_candidate += " --require-clean"
    if check_ollama:
        ollama_options = f" --check-ollama --ollama-endpoint {ollama_endpoint} --ollama-timeout {ollama_timeout}"
        release_candidate += ollama_options
        readiness += ollama_options
    commands = [
        release_candidate,
        f"python -m tokensquash release-info --root {root}"
        + (" --require-clean" if require_clean_git else ""),
        readiness,
        f"python -m tokensquash verify-readiness {readiness_dir} --require-readiness-pass",
        "python -m tokensquash baselines verify",
    ]
    if require_exact_tokenizer:
        commands.append("python -m tokensquash baselines verify --include-exact-tokenizer")
    commands.append(f"python -m pip wheel . --no-deps -w {wheel_dir}")
    commands.append(
        "python -m venv <temp> && <venv-python> -m pip install --no-deps <wheel> "
        "&& <venv-python> -m tokensquash about --json "
        "&& <venv-python> -m tokensquash demo --counter chars --json"
    )
    commands.append("python -c \"import setuptools.build_meta as b; print(b.build_sdist(<sdist-dir>))\"")
    return commands


def _command(*parts: str) -> str:
    return " ".join([sys.executable, "-m", "tokensquash", *parts])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
