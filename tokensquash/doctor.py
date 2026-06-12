from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .demo import DEFAULT_DEMO_CORPUS, run_demo


def run_doctor(
    *,
    check_ollama: bool = False,
    ollama_endpoint: str = "http://localhost:11434",
    ollama_timeout: float = 2.0,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Run local health checks for a TokenSquash install/workspace."""

    started = time.time()
    root = Path(cwd) if cwd is not None else Path.cwd()
    checks = [
        _check_python_version(),
        _check_demo_corpus(),
        _check_demo_workflow(),
        _check_private_storage_ignore(root),
        _check_tiktoken_available(),
        _check_ollama(ollama_endpoint, timeout=ollama_timeout) if check_ollama else _skip_ollama_check(ollama_endpoint),
    ]
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
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "environment": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "cwd": str(root),
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
