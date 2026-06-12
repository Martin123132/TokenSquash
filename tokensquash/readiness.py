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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
