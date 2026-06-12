from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .about import READINESS_COMMANDS
from .demo import DEFAULT_DEMO_CORPUS, run_demo, write_demo_outputs
from .doctor import format_doctor_markdown, run_doctor
from .release import (
    format_quality_budget_init_markdown,
    format_quality_budget_validation_markdown,
    format_turn_release_verify_markdown,
    initialize_quality_budget,
    run_turn_release_check,
    validate_quality_budget,
    verify_turn_release_pack,
)
from .turns import certify_turn_corpus, write_turn_certification_outputs
from .workspace import format_workspace_init_markdown, initialize_workspace


READINESS_SCHEMA_VERSION = "tokensquash.readiness.v1"
READINESS_VERIFY_SCHEMA_VERSION = "tokensquash.readiness.verify.v1"
DEFAULT_READINESS_OUT_DIR = Path("private-turns/readiness")


def run_product_readiness(
    *,
    out_dir: Path | str = DEFAULT_READINESS_OUT_DIR,
    counter: str = "chars",
    skip_tests: bool = False,
    check_ollama: bool = False,
    ollama_endpoint: str = "http://localhost:11434",
    ollama_timeout: float = 2.0,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Run the local TokenSquash product-readiness workflow and write evidence."""

    started = time.time()
    root = Path(cwd) if cwd is not None else Path.cwd()
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    example_corpus = _example_corpus(root)
    quality_budget_path = root / "examples" / "quality-budget.json"
    certification_dir = output_dir / "certification"
    release_check_dir = output_dir / "release-check"
    doctor_strict_dir = output_dir / "doctor-strict"
    steps: list[dict[str, Any]] = []

    _run_readiness_step(
        steps,
        "unit_tests",
        command=f"{sys.executable} -m unittest discover -s tests",
        required=True,
        action=lambda: _run_unit_tests(root, output_dir, skip_tests=skip_tests),
    )
    _run_readiness_step(
        steps,
        "workspace_init_dry_run",
        command=f"{sys.executable} -m tokensquash init --dry-run",
        required=True,
        action=lambda: _run_workspace_init(root, output_dir),
    )
    _run_readiness_step(
        steps,
        "quality_budget_init_dry_run",
        command=f"{sys.executable} -m tokensquash budget init --dry-run --json",
        required=True,
        action=lambda: _run_quality_budget_init(output_dir),
    )
    _run_readiness_step(
        steps,
        "quality_budget_validate",
        command=f"{sys.executable} -m tokensquash budget validate {quality_budget_path}",
        required=True,
        action=lambda: _run_quality_budget_validate(quality_budget_path, output_dir),
    )
    _run_readiness_step(
        steps,
        "strict_doctor",
        command=f"{sys.executable} -m tokensquash doctor --strict",
        required=True,
        action=lambda: _run_strict_doctor(
            root,
            output_dir,
            doctor_strict_dir,
            check_ollama=check_ollama,
            ollama_endpoint=ollama_endpoint,
            ollama_timeout=ollama_timeout,
        ),
    )
    _run_readiness_step(
        steps,
        "demo",
        command=f"{sys.executable} -m tokensquash demo --counter {counter}",
        required=True,
        action=lambda: _run_demo(example_corpus, output_dir, counter=counter),
    )
    _run_readiness_step(
        steps,
        "turn_certification",
        command=f"{sys.executable} -m tokensquash turns certify {example_corpus} --counter {counter}",
        required=True,
        action=lambda: _run_turn_certification(example_corpus, certification_dir, counter=counter),
    )
    _run_readiness_step(
        steps,
        "release_check",
        command=(
            f"{sys.executable} -m tokensquash turns release-check {example_corpus} --counter {counter} "
            f"--budget {quality_budget_path} --history {certification_dir}"
        ),
        required=True,
        action=lambda: _run_release_check(
            root,
            example_corpus,
            quality_budget_path,
            certification_dir,
            release_check_dir,
            counter=counter,
            check_ollama=check_ollama,
            ollama_endpoint=ollama_endpoint,
            ollama_timeout=ollama_timeout,
        ),
    )
    _run_readiness_step(
        steps,
        "verify_release",
        command=f"{sys.executable} -m tokensquash turns verify-release {release_check_dir} --require-release-pass",
        required=True,
        action=lambda: _run_verify_release(release_check_dir, output_dir),
    )

    failed_required = [step for step in steps if step.get("required") and step.get("status") == "fail"]
    warnings = [step for step in steps if step.get("status") == "warn"]
    skipped = [step for step in steps if step.get("status") == "skip"]
    status = "fail" if failed_required else "warn" if warnings else "pass"
    report = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "status": status,
        "root": str(root),
        "counter": counter,
        "check_ollama": check_ollama,
        "skip_tests": skip_tests,
        "summary": {
            "step_count": len(steps),
            "failed_required_count": len(failed_required),
            "warning_count": len(warnings),
            "skip_count": len(skipped),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "commands": list(READINESS_COMMANDS),
        "steps": steps,
        "outputs": {
            "output_dir": str(output_dir),
            "readiness": str(output_dir / "readiness.json"),
            "markdown": str(output_dir / "readiness.md"),
            "unit_tests": str(output_dir / "unit-tests.txt"),
            "workspace_init": str(output_dir / "workspace-init.json"),
            "quality_budget_init": str(output_dir / "quality-budget-init.json"),
            "quality_budget_validation": str(output_dir / "quality-budget-validation.json"),
            "doctor": str(output_dir / "doctor.json"),
            "doctor_markdown": str(output_dir / "doctor.md"),
            "doctor_strict_dir": str(doctor_strict_dir),
            "demo_dir": str(output_dir / "demo-output"),
            "certification_dir": str(certification_dir),
            "release_check_dir": str(release_check_dir),
            "release_verify": str(output_dir / "release-verify.json"),
            "release_verify_markdown": str(output_dir / "release-verify.md"),
        },
    }
    write_product_readiness_outputs(output_dir, report)
    return report


def write_product_readiness_outputs(target: Path | str, report: dict[str, Any]) -> None:
    target_path = Path(target)
    target_path.mkdir(parents=True, exist_ok=True)
    report.setdefault("outputs", {})
    report["outputs"]["output_dir"] = str(target_path)
    report["outputs"]["readiness"] = str(target_path / "readiness.json")
    report["outputs"]["markdown"] = str(target_path / "readiness.md")
    (target_path / "readiness.md").write_text(format_product_readiness_markdown(report), encoding="utf-8")
    _write_json(target_path / "readiness.json", report)


def verify_product_readiness_pack(path: Path | str, *, require_readiness_pass: bool = False) -> dict[str, Any]:
    """Verify a saved product-readiness evidence pack."""

    source = Path(path)
    readiness_path = source / "readiness.json" if source.is_dir() else source
    readiness_dir = readiness_path.parent
    checks: list[dict[str, Any]] = []
    readiness, readiness_check = _verify_readiness_json_artifact(
        "readiness",
        readiness_path,
        READINESS_SCHEMA_VERSION,
        required=True,
        allowed_statuses={"pass", "warn", "fail"},
    )
    checks.append(readiness_check)
    if require_readiness_pass:
        _append_readiness_approval_check(checks, readiness_path, readiness)

    outputs = readiness.get("outputs", {}) if readiness else {}
    _append_readiness_file_check(
        checks,
        "readiness_markdown",
        _resolve_readiness_artifact(readiness_dir, outputs.get("markdown"), Path("readiness.md")),
        required=True,
    )
    _append_readiness_file_check(
        checks,
        "unit_tests_log",
        _resolve_readiness_artifact(readiness_dir, outputs.get("unit_tests"), Path("unit-tests.txt")),
        required=True,
    )

    workspace_init, workspace_init_check = _verify_readiness_json_artifact(
        "workspace_init",
        _resolve_readiness_artifact(readiness_dir, outputs.get("workspace_init"), Path("workspace-init.json")),
        "tokensquash.workspace.init.v1",
        required=True,
        allowed_statuses={"dry-run", "changed", "ready", "fail"},
    )
    checks.append(workspace_init_check)
    quality_budget_init, quality_budget_init_check = _verify_readiness_json_artifact(
        "quality_budget_init",
        _resolve_readiness_artifact(
            readiness_dir,
            outputs.get("quality_budget_init"),
            Path("quality-budget-init.json"),
        ),
        "tokensquash.quality_budget.init.v1",
        required=True,
        allowed_statuses={"planned", "written", "exists", "fail"},
    )
    checks.append(quality_budget_init_check)
    quality_budget_validation, quality_budget_validation_check = _verify_readiness_json_artifact(
        "quality_budget_validation",
        _resolve_readiness_artifact(
            readiness_dir,
            outputs.get("quality_budget_validation"),
            Path("quality-budget-validation.json"),
        ),
        "tokensquash.quality_budget.validate.v1",
        required=True,
        allowed_statuses={"pass", "warn", "fail"},
    )
    checks.append(quality_budget_validation_check)

    doctor, doctor_check = _verify_readiness_json_artifact(
        "doctor",
        _resolve_readiness_artifact(readiness_dir, outputs.get("doctor"), Path("doctor.json")),
        "tokensquash.doctor.v1",
        required=True,
        allowed_statuses={"pass", "warn", "fail"},
    )
    checks.append(doctor_check)
    _append_readiness_file_check(
        checks,
        "doctor_markdown",
        _resolve_readiness_artifact(readiness_dir, outputs.get("doctor_markdown"), Path("doctor.md")),
        required=True,
    )
    doctor_strict_dir = _resolve_readiness_artifact(
        readiness_dir,
        outputs.get("doctor_strict_dir"),
        Path("doctor-strict"),
    )
    if _append_readiness_directory_check(checks, "doctor_strict_dir", doctor_strict_dir, required=True):
        doctor_strict, doctor_strict_check = _verify_readiness_json_artifact(
            "doctor_strict_certification",
            doctor_strict_dir / "certification.json",
            "tokensquash.turns.certify.v1",
            required=True,
            allowed_statuses={"pass", "fail"},
        )
        checks.append(doctor_strict_check)
    else:
        doctor_strict = None

    demo_dir = _resolve_readiness_artifact(readiness_dir, outputs.get("demo_dir"), Path("demo-output"))
    if _append_readiness_directory_check(checks, "demo_dir", demo_dir, required=True):
        demo, demo_check = _verify_readiness_json_artifact(
            "demo",
            demo_dir / "demo.json",
            "tokensquash.demo.v1",
            required=True,
            allowed_statuses={"pass", "warn", "fail"},
        )
        checks.append(demo_check)
        _append_readiness_file_check(checks, "demo_markdown", demo_dir / "demo.md", required=True)
    else:
        demo = None

    certification_dir = _resolve_readiness_artifact(
        readiness_dir,
        outputs.get("certification_dir"),
        Path("certification"),
    )
    if _append_readiness_directory_check(checks, "certification_dir", certification_dir, required=True):
        certification, certification_check = _verify_readiness_json_artifact(
            "certification",
            certification_dir / "certification.json",
            "tokensquash.turns.certify.v1",
            required=True,
            allowed_statuses={"pass", "fail"},
        )
        checks.append(certification_check)
        _append_readiness_file_check(checks, "certification_markdown", certification_dir / "certification.md", required=True)
    else:
        certification = None

    release_check_dir = _resolve_readiness_artifact(
        readiness_dir,
        outputs.get("release_check_dir"),
        Path("release-check"),
    )
    release_verify_report = _verify_nested_release_pack(
        checks,
        release_check_dir,
        require_release_pass=require_readiness_pass,
    )
    release_verify, release_verify_check = _verify_readiness_json_artifact(
        "release_verify",
        _resolve_readiness_artifact(readiness_dir, outputs.get("release_verify"), Path("release-verify.json")),
        "tokensquash.turns.release_verify.v1",
        required=True,
        allowed_statuses={"pass", "warn", "fail"},
    )
    checks.append(release_verify_check)
    _append_readiness_file_check(
        checks,
        "release_verify_markdown",
        _resolve_readiness_artifact(readiness_dir, outputs.get("release_verify_markdown"), Path("release-verify.md")),
        required=False,
    )
    _append_readiness_steps_check(checks, readiness_path, readiness)

    failed_checks = [check for check in checks if check.get("status") == "fail"]
    warning_checks = [check for check in checks if check.get("status") == "warn"]
    status = "fail" if failed_checks else "warn" if warning_checks else "pass"
    return {
        "schema_version": READINESS_VERIFY_SCHEMA_VERSION,
        "status": status,
        "source": str(source),
        "readiness_path": str(readiness_path),
        "require_readiness_pass": require_readiness_pass,
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed_checks),
            "warning_count": len(warning_checks),
            "readiness_pass_required": require_readiness_pass,
            "readiness_status": readiness.get("status") if readiness else None,
            "readiness_step_count": len(readiness.get("steps", [])) if readiness else 0,
            "doctor_status": doctor.get("status") if doctor else None,
            "doctor_strict_certification_status": doctor_strict.get("status") if doctor_strict else None,
            "demo_status": demo.get("status") if demo else None,
            "certification_status": certification.get("status") if certification else None,
            "release_check_verify_status": release_verify_report.get("status") if release_verify_report else None,
            "release_verify_status": release_verify.get("status") if release_verify else None,
            "workspace_init_status": workspace_init.get("status") if workspace_init else None,
            "quality_budget_init_status": quality_budget_init.get("status") if quality_budget_init else None,
            "quality_budget_validation_status": quality_budget_validation.get("status")
            if quality_budget_validation
            else None,
        },
        "checks": checks,
        "artifacts": {
            "readiness": _readiness_artifact_reference(readiness),
            "workspace_init": _readiness_artifact_reference(workspace_init),
            "quality_budget_init": _readiness_artifact_reference(quality_budget_init),
            "quality_budget_validation": _readiness_artifact_reference(quality_budget_validation),
            "doctor": _readiness_artifact_reference(doctor),
            "doctor_strict_certification": _readiness_artifact_reference(doctor_strict),
            "demo": _readiness_artifact_reference(demo),
            "certification": _readiness_artifact_reference(certification),
            "release_check_verification": _readiness_artifact_reference(release_verify_report),
            "release_verify": _readiness_artifact_reference(release_verify),
        },
    }


def format_product_readiness_verify_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Product Readiness Verify",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source')}`",
        f"- Readiness: `{report.get('readiness_path')}`",
        f"- Require readiness pass: `{report.get('require_readiness_pass')}`",
        f"- Checks: `{summary.get('check_count', 0)}`",
        f"- Failed checks: `{summary.get('failed_check_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Readiness status: `{summary.get('readiness_status')}`",
        f"- Doctor status: `{summary.get('doctor_status')}`",
        f"- Demo status: `{summary.get('demo_status')}`",
        f"- Certification status: `{summary.get('certification_status')}`",
        f"- Release check verification: `{summary.get('release_check_verify_status')}`",
        f"- Release verify status: `{summary.get('release_verify_status')}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Required | Path | Detail |",
        "|---|---|---:|---|---|",
    ]
    for check in report.get("checks", []):
        lines.append(
            "| "
            f"{_markdown_cell(str(check.get('name', '')))} | "
            f"`{check.get('status')}` | "
            f"{check.get('required')} | "
            f"`{_markdown_cell(str(check.get('path', '')))}` | "
            f"{_markdown_cell(str(check.get('message', '')))} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def format_product_readiness_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs") or {}
    lines = [
        "# TokenSquash Product Readiness",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Root: `{report.get('root')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Steps: `{summary.get('step_count', 0)}`",
        f"- Failed required steps: `{summary.get('failed_required_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Skipped: `{summary.get('skip_count', 0)}`",
        f"- Elapsed seconds: `{summary.get('elapsed_seconds', 0.0)}`",
        "",
        "## Outputs",
        "",
    ]
    for key, path in sorted(outputs.items()):
        lines.append(f"- `{key}`: `{path}`")
    lines.extend(
        [
            "",
            "## Steps",
            "",
            "| Step | Status | Required | Seconds | Detail |",
            "|---|---|---:|---:|---|",
        ]
    )
    for step in report.get("steps", []):
        lines.append(
            "| "
            f"{_markdown_cell(str(step.get('name', '')))} | "
            f"`{step.get('status')}` | "
            f"{step.get('required')} | "
            f"{step.get('elapsed_seconds', 0.0)} | "
            f"{_markdown_cell(str(step.get('message', '')))} |"
        )
    lines.extend(["", "## Checklist Commands", ""])
    for command in report.get("commands", []):
        lines.append(f"- `{command}`")
    return "\n".join(lines).rstrip() + "\n"


def _run_readiness_step(
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


def _run_unit_tests(root: Path, output_dir: Path, *, skip_tests: bool) -> tuple[str, str, dict[str, Any]]:
    log_path = output_dir / "unit-tests.txt"
    if skip_tests:
        log_path.write_text("Skipped by --skip-tests.\n", encoding="utf-8")
        return "skip", "Unit tests skipped by request.", {"log": str(log_path)}
    tests_dir = root / "tests"
    if not tests_dir.exists():
        log_path.write_text("No tests directory found.\n", encoding="utf-8")
        return "fail", f"No tests directory found at {tests_dir}.", {"log": str(log_path)}
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    log_text = (
        f"$ {' '.join(command)}\n"
        f"exit_code={completed.returncode}\n\n"
        "## stdout\n"
        f"{completed.stdout}\n"
        "## stderr\n"
        f"{completed.stderr}\n"
    )
    log_path.write_text(log_text, encoding="utf-8")
    if completed.returncode == 0:
        return "pass", "Unit tests passed.", {"log": str(log_path), "returncode": completed.returncode}
    return "fail", "Unit tests failed.", {"log": str(log_path), "returncode": completed.returncode}


def _run_workspace_init(root: Path, output_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = initialize_workspace(root, dry_run=True)
    json_path = output_dir / "workspace-init.json"
    markdown_path = output_dir / "workspace-init.md"
    _write_json(json_path, report)
    markdown_path.write_text(format_workspace_init_markdown(report), encoding="utf-8")
    status = "pass" if report.get("status") == "dry-run" else "fail"
    return status, "Workspace init dry-run completed.", {"report": str(json_path), "markdown": str(markdown_path)}


def _run_quality_budget_init(output_dir: Path) -> tuple[str, str, dict[str, Any]]:
    target = output_dir / "planned-quality-budget.json"
    report = initialize_quality_budget(target, dry_run=True)
    json_path = output_dir / "quality-budget-init.json"
    markdown_path = output_dir / "quality-budget-init.md"
    _write_json(json_path, report)
    markdown_path.write_text(format_quality_budget_init_markdown(report), encoding="utf-8")
    status = "pass" if report.get("status") == "planned" else "fail"
    return status, "Quality budget init dry-run completed.", {"report": str(json_path), "markdown": str(markdown_path)}


def _run_quality_budget_validate(path: Path, output_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = validate_quality_budget(path)
    json_path = output_dir / "quality-budget-validation.json"
    markdown_path = output_dir / "quality-budget-validation.md"
    _write_json(json_path, report)
    markdown_path.write_text(format_quality_budget_validation_markdown(report), encoding="utf-8")
    status = "pass" if report.get("status") == "pass" else "warn" if report.get("status") == "warn" else "fail"
    return status, f"Quality budget validation returned {report.get('status')}.", {
        "report": str(json_path),
        "markdown": str(markdown_path),
        "source": str(path),
    }


def _run_strict_doctor(
    root: Path,
    output_dir: Path,
    strict_dir: Path,
    *,
    check_ollama: bool,
    ollama_endpoint: str,
    ollama_timeout: float,
) -> tuple[str, str, dict[str, Any]]:
    report = run_doctor(
        check_ollama=check_ollama,
        ollama_endpoint=ollama_endpoint,
        ollama_timeout=ollama_timeout,
        strict=True,
        strict_output_dir=strict_dir,
        cwd=root,
    )
    json_path = output_dir / "doctor.json"
    markdown_path = output_dir / "doctor.md"
    _write_json(json_path, report)
    markdown_path.write_text(format_doctor_markdown(report), encoding="utf-8")
    status = "pass" if report.get("status") == "pass" else "warn" if report.get("status") == "warn" else "fail"
    return status, f"Strict doctor returned {report.get('status')}.", {
        "report": str(json_path),
        "markdown": str(markdown_path),
        "strict_output_dir": str(strict_dir),
        "failed_required_count": (report.get("summary") or {}).get("failed_required_count", 0),
        "warning_count": (report.get("summary") or {}).get("warning_count", 0),
    }


def _run_demo(corpus: Path, output_dir: Path, *, counter: str) -> tuple[str, str, dict[str, Any]]:
    demo_dir = output_dir / "demo-output"
    report = run_demo(corpus, counter=counter, out_dir=demo_dir)
    write_demo_outputs(demo_dir, report)
    status = "pass" if report.get("status") == "pass" else "warn" if report.get("status") == "warn" else "fail"
    return status, f"Demo returned {report.get('status')}.", {
        "output_dir": str(demo_dir),
        "report": str(demo_dir / "demo.json"),
        "saved_pct": (report.get("summary") or {}).get("saved_pct", 0.0),
    }


def _run_turn_certification(corpus: Path, output_dir: Path, *, counter: str) -> tuple[str, str, dict[str, Any]]:
    report = certify_turn_corpus(corpus, counter=counter)
    write_turn_certification_outputs(output_dir, report)
    status = "pass" if report.get("status") == "pass" else "fail"
    return status, f"Turn certification returned {report.get('status')}.", {
        "output_dir": str(output_dir),
        "report": str(output_dir / "certification.json"),
        "saved_pct": (report.get("summary") or {}).get("saved_pct", 0.0),
    }


def _run_release_check(
    root: Path,
    corpus: Path,
    budget_path: Path,
    certification_dir: Path,
    output_dir: Path,
    *,
    counter: str,
    check_ollama: bool,
    ollama_endpoint: str,
    ollama_timeout: float,
) -> tuple[str, str, dict[str, Any]]:
    report = run_turn_release_check(
        corpus,
        out_dir=output_dir,
        history_paths=[certification_dir],
        quality_budget_path=budget_path,
        counter=counter,
        check_ollama=check_ollama,
        ollama_endpoint=ollama_endpoint,
        ollama_timeout=ollama_timeout,
        cwd=root,
    )
    status = "pass" if report.get("status") == "pass" else "warn" if report.get("status") == "warn" else "fail"
    return status, f"Release check returned {report.get('status')}.", {
        "output_dir": str(output_dir),
        "report": str(output_dir / "release-check.json"),
        "saved_pct": (report.get("summary") or {}).get("saved_pct", 0.0),
        "failed_required_count": (report.get("summary") or {}).get("failed_required_count", 0),
        "warning_count": (report.get("summary") or {}).get("warning_count", 0),
    }


def _run_verify_release(release_check_dir: Path, output_dir: Path) -> tuple[str, str, dict[str, Any]]:
    report = verify_turn_release_pack(release_check_dir, require_release_pass=True)
    json_path = output_dir / "release-verify.json"
    markdown_path = output_dir / "release-verify.md"
    _write_json(json_path, report)
    markdown_path.write_text(format_turn_release_verify_markdown(report), encoding="utf-8")
    status = "pass" if report.get("status") == "pass" else "warn" if report.get("status") == "warn" else "fail"
    return status, f"Release verification returned {report.get('status')}.", {
        "report": str(json_path),
        "markdown": str(markdown_path),
        "check_count": (report.get("summary") or {}).get("check_count", 0),
        "release_status": (report.get("summary") or {}).get("release_status"),
    }


def _example_corpus(root: Path) -> Path:
    source_checkout_corpus = root / "examples" / "sample-turns.jsonl"
    return source_checkout_corpus if source_checkout_corpus.exists() else DEFAULT_DEMO_CORPUS


def _verify_nested_release_pack(
    checks: list[dict[str, Any]],
    release_check_dir: Path,
    *,
    require_release_pass: bool,
) -> dict[str, Any] | None:
    if not _append_readiness_directory_check(checks, "release_check_dir", release_check_dir, required=True):
        return None
    try:
        report = verify_turn_release_pack(release_check_dir, require_release_pass=require_release_pass)
    except Exception as exc:
        checks.append(
            _readiness_check(
                "release_check_pack",
                "fail",
                required=True,
                path=release_check_dir,
                message=f"Release-check pack verification failed: {exc}",
            )
        )
        return None
    status = "pass" if report.get("status") == "pass" else "warn" if report.get("status") == "warn" else "fail"
    checks.append(
        _readiness_check(
            "release_check_pack",
            status,
            required=True,
            path=release_check_dir,
            message=f"Nested release-check verifier returned {report.get('status')}.",
            data={
                "check_count": (report.get("summary") or {}).get("check_count", 0),
                "failed_check_count": (report.get("summary") or {}).get("failed_check_count", 0),
                "release_status": (report.get("summary") or {}).get("release_status"),
            },
        )
    )
    return report


def _verify_readiness_json_artifact(
    name: str,
    path: Path,
    schema_version: str,
    *,
    required: bool,
    allowed_statuses: set[str] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not path.exists():
        return None, _readiness_check(
            name,
            "fail" if required else "warn",
            required=required,
            path=path,
            message=f"Missing JSON artifact: {path}.",
        )
    if not path.is_file():
        return None, _readiness_check(
            name,
            "fail",
            required=required,
            path=path,
            message=f"Expected a JSON file but found a non-file path: {path}.",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return None, _readiness_check(
            name,
            "fail",
            required=required,
            path=path,
            message=f"Could not parse JSON artifact: {exc}",
        )
    if not isinstance(payload, dict):
        return None, _readiness_check(
            name,
            "fail",
            required=required,
            path=path,
            message="JSON artifact must be an object.",
        )
    actual_schema = payload.get("schema_version")
    if actual_schema != schema_version:
        return payload, _readiness_check(
            name,
            "fail",
            required=required,
            path=path,
            message=f"Expected schema {schema_version}, found {actual_schema}.",
            data={"actual_schema": actual_schema, "expected_schema": schema_version},
        )
    actual_status = payload.get("status")
    if allowed_statuses is not None and actual_status not in allowed_statuses:
        return payload, _readiness_check(
            name,
            "fail",
            required=required,
            path=path,
            message=f"Status {actual_status} is not allowed for {name}.",
            data={"actual_status": actual_status, "allowed_statuses": sorted(allowed_statuses)},
        )
    return payload, _readiness_check(
        name,
        "pass",
        required=required,
        path=path,
        message=f"Verified {schema_version} JSON artifact.",
        data={"schema_version": schema_version, "status": actual_status},
    )


def _append_readiness_file_check(
    checks: list[dict[str, Any]],
    name: str,
    path: Path,
    *,
    required: bool,
) -> bool:
    if not path.exists():
        checks.append(
            _readiness_check(
                name,
                "fail" if required else "warn",
                required=required,
                path=path,
                message=f"Missing file artifact: {path}.",
            )
        )
        return False
    if not path.is_file():
        checks.append(
            _readiness_check(
                name,
                "fail",
                required=required,
                path=path,
                message=f"Expected a file artifact but found a non-file path: {path}.",
            )
        )
        return False
    if path.stat().st_size == 0:
        checks.append(
            _readiness_check(
                name,
                "fail" if required else "warn",
                required=required,
                path=path,
                message=f"File artifact is empty: {path}.",
            )
        )
        return False
    checks.append(
        _readiness_check(
            name,
            "pass",
            required=required,
            path=path,
            message="File artifact exists and is non-empty.",
            data={"bytes": path.stat().st_size},
        )
    )
    return True


def _append_readiness_directory_check(
    checks: list[dict[str, Any]],
    name: str,
    path: Path,
    *,
    required: bool,
) -> bool:
    if not path.exists():
        checks.append(
            _readiness_check(
                name,
                "fail" if required else "warn",
                required=required,
                path=path,
                message=f"Missing directory artifact: {path}.",
            )
        )
        return False
    if not path.is_dir():
        checks.append(
            _readiness_check(
                name,
                "fail",
                required=required,
                path=path,
                message=f"Expected a directory artifact but found a non-directory path: {path}.",
            )
        )
        return False
    checks.append(
        _readiness_check(
            name,
            "pass",
            required=required,
            path=path,
            message="Directory artifact exists.",
        )
    )
    return True


def _append_readiness_approval_check(
    checks: list[dict[str, Any]],
    readiness_path: Path,
    readiness: dict[str, Any] | None,
) -> None:
    if readiness is None:
        checks.append(
            _readiness_check(
                "readiness_approval",
                "fail",
                required=True,
                path=readiness_path,
                message="Cannot require readiness pass because readiness.json is unreadable.",
            )
        )
        return
    status = readiness.get("status")
    checks.append(
        _readiness_check(
            "readiness_approval",
            "pass" if status == "pass" else "fail",
            required=True,
            path=readiness_path,
            message="Readiness status is pass." if status == "pass" else f"Readiness status is {status}, not pass.",
            data={"readiness_status": status},
        )
    )


def _append_readiness_steps_check(
    checks: list[dict[str, Any]],
    readiness_path: Path,
    readiness: dict[str, Any] | None,
) -> None:
    if readiness is None:
        checks.append(
            _readiness_check(
                "readiness_steps",
                "fail",
                required=True,
                path=readiness_path,
                message="Cannot verify readiness steps because readiness.json is unreadable.",
            )
        )
        return
    steps = readiness.get("steps")
    summary = readiness.get("summary") or {}
    if not isinstance(steps, list):
        checks.append(
            _readiness_check(
                "readiness_steps",
                "fail",
                required=True,
                path=readiness_path,
                message="readiness.steps must be a list.",
            )
        )
        return
    required_step_names = {
        "unit_tests",
        "workspace_init_dry_run",
        "quality_budget_init_dry_run",
        "quality_budget_validate",
        "strict_doctor",
        "demo",
        "turn_certification",
        "release_check",
        "verify_release",
    }
    step_names = {str(step.get("name")) for step in steps if isinstance(step, dict)}
    missing_steps = sorted(required_step_names - step_names)
    invalid_steps = [
        str(step.get("name", index))
        for index, step in enumerate(steps)
        if not isinstance(step, dict)
        or step.get("status") not in {"pass", "warn", "fail", "skip"}
        or "command" not in step
        or "message" not in step
    ]
    expected_count = summary.get("step_count")
    count_matches = expected_count == len(steps)
    passed = not missing_steps and not invalid_steps and count_matches
    checks.append(
        _readiness_check(
            "readiness_steps",
            "pass" if passed else "fail",
            required=True,
            path=readiness_path,
            message=(
                f"Readiness report lists {len(steps)} well-formed steps."
                if passed
                else "Readiness step list is incomplete or inconsistent."
            ),
            data={
                "step_count": len(steps),
                "summary_step_count": expected_count,
                "missing_steps": missing_steps,
                "invalid_steps": invalid_steps,
            },
        )
    )


def _resolve_readiness_artifact(base_dir: Path, value: Any, fallback: Path) -> Path:
    if value:
        candidate = Path(str(value))
        if candidate.is_absolute() or candidate.exists():
            return candidate
        base_name = base_dir.name
        parts = list(candidate.parts)
        if base_name in parts:
            index = len(parts) - 1 - parts[::-1].index(base_name)
            tail = parts[index + 1 :]
            if tail:
                return base_dir.joinpath(*tail)
        direct_child = base_dir / candidate.name
        if direct_child.exists():
            return direct_child
    return base_dir / fallback


def _readiness_artifact_reference(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return {
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "summary": payload.get("summary"),
    }


def _readiness_check(
    name: str,
    status: str,
    *,
    required: bool,
    path: Path,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "required": required,
        "path": str(path),
        "message": message,
        "data": data or {},
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
