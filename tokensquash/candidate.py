from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable
from zipfile import BadZipFile, ZipFile

from .baselines import format_benchmark_baseline_verify_markdown, verify_benchmark_baselines
from .readiness import (
    format_product_readiness_verify_markdown,
    run_product_readiness,
    verify_product_readiness_pack,
)


RELEASE_CANDIDATE_SCHEMA_VERSION = "tokensquash.release_candidate.v1"
RELEASE_CANDIDATE_VERIFY_SCHEMA_VERSION = "tokensquash.release_candidate.verify.v1"
DEFAULT_RELEASE_CANDIDATE_OUT_DIR = Path("private-turns/release-candidate")
PACKAGED_DEMO_DATA_PATH = "tokensquash/data/sample-turns.jsonl"


def run_release_candidate(
    *,
    out_dir: Path | str = DEFAULT_RELEASE_CANDIDATE_OUT_DIR,
    counter: str = "chars",
    skip_tests: bool = False,
    require_exact_tokenizer: bool = True,
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
    steps: list[dict[str, Any]] = []

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
        "check_ollama": check_ollama,
        "summary": {
            "step_count": len(steps),
            "failed_required_count": len(failed_required),
            "warning_count": len(warnings),
            "skip_count": len(skipped),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "commands": _release_candidate_commands(
            output_dir,
            readiness_dir,
            wheel_dir,
            counter,
            skip_tests=skip_tests,
            require_exact_tokenizer=require_exact_tokenizer,
            check_ollama=check_ollama,
            ollama_endpoint=ollama_endpoint,
            ollama_timeout=ollama_timeout,
        ),
        "steps": steps,
        "outputs": {
            "output_dir": str(output_dir),
            "report": str(output_dir / "release-candidate.json"),
            "markdown": str(output_dir / "release-candidate.md"),
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
    _write_json(target_path / "release-candidate.json", report)
    (target_path / "release-candidate.md").write_text(format_release_candidate_markdown(report), encoding="utf-8")


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
        "readiness",
        "readiness_verify",
        "baseline_verify",
        "exact_baseline_verify",
        "wheel_dir",
        "wheel_log",
    ):
        if outputs.get(name):
            lines.append(f"- `{name}`: `{outputs.get(name)}`")
    lines.extend(["", "## Commands", ""])
    for command in report.get("commands", []):
        lines.append(f"- `{command}`")
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
        _append_candidate_wheel_check(checks, wheel_path, required=True)

    _append_candidate_steps_check(checks, candidate_path, candidate)

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
            "readiness_verify_status": stored_readiness_verify.get("status") if stored_readiness_verify else None,
            "nested_readiness_verify_status": readiness_verify_report.get("status") if readiness_verify_report else None,
            "baseline_verify_status": baseline_verify.get("status") if baseline_verify else None,
            "exact_baseline_verify_status": exact_baseline_verify.get("status") if exact_baseline_verify else None,
            "wheel": str(wheel_path) if wheel_path else None,
        },
        "checks": checks,
        "artifacts": {
            "release_candidate": _candidate_artifact_reference(candidate),
            "readiness_verification": _candidate_artifact_reference(readiness_verify_report),
            "stored_readiness_verify": _candidate_artifact_reference(stored_readiness_verify),
            "baseline_verify": _candidate_artifact_reference(baseline_verify),
            "exact_baseline_verify": _candidate_artifact_reference(exact_baseline_verify),
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
        f"- Nested readiness verify: `{summary.get('nested_readiness_verify_status')}`",
        f"- Baseline verify: `{summary.get('baseline_verify_status')}`",
        f"- Exact baseline verify: `{summary.get('exact_baseline_verify_status')}`",
        f"- Wheel: `{summary.get('wheel')}`",
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
    log_text = (
        f"$ {' '.join(command)}\n"
        f"exit_code={completed.returncode}\n"
        f"wheel={wheel_path or ''}\n"
        f"contains_{PACKAGED_DEMO_DATA_PATH}={packaged_demo_data}\n\n"
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
    else:
        status = "pass"
        message = "Wheel built and packaged demo data is present."
    return status, message, {
        "wheel_dir": str(wheel_dir),
        "log": str(log_path),
        "returncode": completed.returncode,
        "wheel": str(wheel_path) if wheel_path else None,
        "packaged_demo_data": packaged_demo_data,
    }


def _wheel_contains(path: Path | None, member: str) -> bool:
    if path is None:
        return False
    try:
        with ZipFile(path) as archive:
            return member in set(archive.namelist())
    except (BadZipFile, OSError):
        return False


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


def _append_candidate_wheel_check(checks: list[dict[str, Any]], path: Path | None, *, required: bool) -> None:
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
    checks.append(
        _candidate_check(
            "wheel",
            "pass" if packaged_demo_data else "fail",
            required=required,
            path=path,
            message=(
                "Wheel exists and packaged demo data is present."
                if packaged_demo_data
                else f"Wheel is missing packaged demo data: {PACKAGED_DEMO_DATA_PATH}."
            ),
            data={"packaged_demo_data": packaged_demo_data, "member": PACKAGED_DEMO_DATA_PATH},
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
        "readiness",
        "verify_readiness",
        "benchmark_baselines",
        "exact_tokenizer_baselines",
        "wheel_build",
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


def _resolve_candidate_artifact(base_dir: Path, value: Any, fallback: Path) -> Path:
    if isinstance(value, str) and value:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else base_dir / candidate
    return base_dir / fallback


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


def _release_candidate_commands(
    output_dir: Path,
    readiness_dir: Path,
    wheel_dir: Path,
    counter: str,
    *,
    skip_tests: bool,
    require_exact_tokenizer: bool,
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
    if check_ollama:
        ollama_options = f" --check-ollama --ollama-endpoint {ollama_endpoint} --ollama-timeout {ollama_timeout}"
        release_candidate += ollama_options
        readiness += ollama_options
    commands = [
        release_candidate,
        readiness,
        f"python -m tokensquash verify-readiness {readiness_dir} --require-readiness-pass",
        "python -m tokensquash baselines verify",
    ]
    if require_exact_tokenizer:
        commands.append("python -m tokensquash baselines verify --include-exact-tokenizer")
    commands.append(f"python -m pip wheel . --no-deps -w {wheel_dir}")
    return commands


def _command(*parts: str) -> str:
    return " ".join([sys.executable, "-m", "tokensquash", *parts])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
