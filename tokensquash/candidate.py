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
