from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Iterable

from .aliases import AliasTable
from .doctor import format_doctor_markdown, run_doctor
from .turns import (
    build_turn_certification_history,
    certify_turn_corpus,
    format_turn_certification_history_markdown,
    write_turn_certification_outputs,
)


RELEASE_CHECK_SCHEMA_VERSION = "tokensquash.turns.release_check.v1"
QUALITY_BUDGET_SCHEMA_VERSION = "tokensquash.quality_budget.v1"
QUALITY_BUDGET_INIT_SCHEMA_VERSION = "tokensquash.quality_budget.init.v1"
QUALITY_BUDGET_VALIDATION_SCHEMA_VERSION = "tokensquash.quality_budget.validate.v1"
DEFAULT_RELEASE_BUDGET = {
    "min_saved_pct": 0.5,
    "max_privacy_findings": 0,
    "max_pass_through_rows": 0,
    "max_raw_wire_loss_turns": 0,
    "require_history": False,
    "max_history_regressions": 0,
    "max_history_failures": 0,
    "max_doctor_warnings": 0,
}
_RELEASE_BUDGET_KEYS = tuple(DEFAULT_RELEASE_BUDGET)
_RELEASE_BUDGET_INT_KEYS = (
    "max_privacy_findings",
    "max_pass_through_rows",
    "max_raw_wire_loss_turns",
    "max_history_regressions",
    "max_history_failures",
    "max_doctor_warnings",
)


def run_turn_release_check(
    corpus: Path | str,
    *,
    out_dir: Path | str = Path("private-turns/release-check"),
    history_paths: Iterable[Path | str] | Path | str | None = None,
    quality_budget_path: Path | str | None = None,
    counter: str = "heuristic",
    target_savings_pct: float = 0.0,
    adaptive: bool = True,
    guess_reply_fields: bool = True,
    min_count: int = 2,
    limit: int = 10,
    max_path_prefixes: int = 8,
    max_field_values: int = 8,
    min_saved_tokens: int = 1,
    base_aliases: AliasTable | dict[str, Any] | None = None,
    min_saved_pct: float | None = None,
    max_privacy_findings: int | None = None,
    max_pass_through_rows: int | None = None,
    max_raw_wire_loss_turns: int | None = None,
    suggestion_limit: int = 5,
    suggestion_min_saved_tokens: int = 1,
    check_ollama: bool = False,
    ollama_endpoint: str = "http://localhost:11434",
    ollama_timeout: float = 2.0,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Run the turn certification, optional history, and strict doctor release gates."""

    started = time.time()
    output_dir = Path(out_dir)
    certification_dir = output_dir / "certification"
    doctor_strict_dir = output_dir / "doctor-strict"
    history_inputs = _path_list(history_paths)
    quality_budget = _resolve_quality_budget(
        quality_budget_path,
        min_saved_pct=min_saved_pct,
        max_privacy_findings=max_privacy_findings,
        max_pass_through_rows=max_pass_through_rows,
        max_raw_wire_loss_turns=max_raw_wire_loss_turns,
    )
    budget_values = quality_budget["release_check"]

    certification = certify_turn_corpus(
        corpus,
        counter=counter,
        target_savings_pct=target_savings_pct,
        adaptive=adaptive,
        guess_reply_fields=guess_reply_fields,
        min_count=min_count,
        limit=limit,
        max_path_prefixes=max_path_prefixes,
        max_field_values=max_field_values,
        min_saved_tokens=min_saved_tokens,
        base_aliases=base_aliases,
        min_saved_pct=float(budget_values["min_saved_pct"]),
        max_privacy_findings=int(budget_values["max_privacy_findings"]),
        max_pass_through_rows=int(budget_values["max_pass_through_rows"]),
        max_raw_wire_loss_turns=int(budget_values["max_raw_wire_loss_turns"]),
        suggestion_limit=suggestion_limit,
        suggestion_min_saved_tokens=suggestion_min_saved_tokens,
    )
    write_turn_certification_outputs(certification_dir, certification)

    history = None
    if history_inputs:
        history = build_turn_certification_history([*history_inputs, certification_dir])

    doctor = run_doctor(
        check_ollama=check_ollama,
        ollama_endpoint=ollama_endpoint,
        ollama_timeout=ollama_timeout,
        strict=True,
        strict_output_dir=doctor_strict_dir,
        cwd=cwd,
    )

    outputs = {
        "output_dir": str(output_dir),
        "release_check": str(output_dir / "release-check.json"),
        "markdown": str(output_dir / "release-check.md"),
        "certification_dir": str(certification_dir),
        "certification": str(certification_dir / "certification.json"),
        "doctor": str(output_dir / "doctor.json"),
        "doctor_markdown": str(output_dir / "doctor.md"),
        "doctor_strict_dir": str(doctor_strict_dir),
    }
    if history is not None:
        outputs.update(
            {
                "history": str(output_dir / "history.json"),
                "history_markdown": str(output_dir / "history.md"),
            }
        )

    checks = [
        _release_check(
            "turn_certification",
            "pass" if certification.get("status") == "pass" else "fail",
            required=True,
            message=(
                "Turn certification gate passed."
                if certification.get("status") == "pass"
                else "Turn certification gate failed."
            ),
            data={
                "artifact": outputs["certification"],
                "saved_pct": (certification.get("summary") or {}).get("saved_pct", 0.0),
                "failed_check_count": (certification.get("summary") or {}).get("failed_check_count", 0),
            },
        ),
        _release_check(
            "strict_doctor",
            "pass" if doctor.get("status") == "pass" else "warn" if doctor.get("status") == "warn" else "fail",
            required=True,
            message=(
                "Strict doctor passed."
                if doctor.get("status") == "pass"
                else "Strict doctor reported warnings."
                if doctor.get("status") == "warn"
                else "Strict doctor failed."
            ),
            data={
                "artifact": outputs["doctor"],
                "strict_artifact_dir": outputs["doctor_strict_dir"],
                "failed_required_count": (doctor.get("summary") or {}).get("failed_required_count", 0),
                "warning_count": (doctor.get("summary") or {}).get("warning_count", 0),
            },
        ),
        _history_release_check(history, outputs, budget_values),
        _doctor_warning_budget_check(doctor, budget_values),
    ]
    status = _release_status(checks)
    summary = _release_summary(certification, doctor, history, checks)
    summary["elapsed_seconds"] = round(time.time() - started, 4)

    report = {
        "schema_version": RELEASE_CHECK_SCHEMA_VERSION,
        "status": status,
        "corpus": str(Path(corpus)),
        "counter": counter,
        "target_savings_pct": target_savings_pct,
        "adaptive": adaptive,
        "parameters": {
            "min_count": max(1, int(min_count)),
            "limit": max(1, int(limit)),
            "max_path_prefixes": max(0, int(max_path_prefixes)),
            "max_field_values": max(0, int(max_field_values)),
            "min_saved_tokens": max(0, int(min_saved_tokens)),
            "suggestion_limit": max(1, int(suggestion_limit)),
            "suggestion_min_saved_tokens": max(0, int(suggestion_min_saved_tokens)),
            "history_input_count": len(history_inputs),
            "check_ollama": check_ollama,
            "quality_budget_path": str(quality_budget_path) if quality_budget_path else None,
        },
        "thresholds": {
            "min_saved_pct": budget_values["min_saved_pct"],
            "max_privacy_findings": budget_values["max_privacy_findings"],
            "max_pass_through_rows": budget_values["max_pass_through_rows"],
            "max_raw_wire_loss_turns": budget_values["max_raw_wire_loss_turns"],
            "require_history": budget_values["require_history"],
            "max_history_regressions": budget_values["max_history_regressions"],
            "max_history_failures": budget_values["max_history_failures"],
            "max_doctor_warnings": budget_values["max_doctor_warnings"],
        },
        "quality_budget": quality_budget,
        "summary": summary,
        "checks": checks,
        "outputs": outputs,
        "artifacts": {
            "certification": _certification_reference(certification),
            "history": history,
            "doctor": doctor,
        },
    }
    write_turn_release_check_outputs(output_dir, report)
    return report


def load_quality_budget(path: Path | str) -> dict[str, Any]:
    """Load a machine-readable TokenSquash quality budget JSON file."""

    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema_version") != QUALITY_BUDGET_SCHEMA_VERSION:
        raise ValueError(f"Not a TokenSquash quality budget: {source}")
    turns = payload.get("turns", {})
    if not isinstance(turns, dict):
        raise ValueError("quality budget field `turns` must be an object")
    release_check = turns.get("release_check", {})
    if not isinstance(release_check, dict):
        raise ValueError("quality budget field `turns.release_check` must be an object")
    return payload


def build_quality_budget(
    *,
    min_saved_pct: float | None = None,
    max_privacy_findings: int | None = None,
    max_pass_through_rows: int | None = None,
    max_raw_wire_loss_turns: int | None = None,
    require_history: bool | None = None,
    max_history_regressions: int | None = None,
    max_history_failures: int | None = None,
    max_doctor_warnings: int | None = None,
) -> dict[str, Any]:
    """Build a canonical TokenSquash quality budget payload."""

    return {
        "schema_version": QUALITY_BUDGET_SCHEMA_VERSION,
        "turns": {
            "release_check": _build_release_budget(
                {},
                min_saved_pct=min_saved_pct,
                max_privacy_findings=max_privacy_findings,
                max_pass_through_rows=max_pass_through_rows,
                max_raw_wire_loss_turns=max_raw_wire_loss_turns,
                require_history=require_history,
                max_history_regressions=max_history_regressions,
                max_history_failures=max_history_failures,
                max_doctor_warnings=max_doctor_warnings,
            )
        },
    }


def initialize_quality_budget(
    path: Path | str = Path("quality-budget.json"),
    *,
    overwrite: bool = False,
    dry_run: bool = False,
    min_saved_pct: float | None = None,
    max_privacy_findings: int | None = None,
    max_pass_through_rows: int | None = None,
    max_raw_wire_loss_turns: int | None = None,
    require_history: bool | None = None,
    max_history_regressions: int | None = None,
    max_history_failures: int | None = None,
    max_doctor_warnings: int | None = None,
) -> dict[str, Any]:
    """Create a starter quality budget file unless one already exists."""

    target = Path(path)
    existed = target.exists()
    budget = build_quality_budget(
        min_saved_pct=min_saved_pct,
        max_privacy_findings=max_privacy_findings,
        max_pass_through_rows=max_pass_through_rows,
        max_raw_wire_loss_turns=max_raw_wire_loss_turns,
        require_history=require_history,
        max_history_regressions=max_history_regressions,
        max_history_failures=max_history_failures,
        max_doctor_warnings=max_doctor_warnings,
    )
    if dry_run:
        action = "would_overwrite" if existed and overwrite else "would_skip_existing" if existed else "would_create"
        status = "planned"
        written = False
    elif existed and not overwrite:
        action = "unchanged"
        status = "exists"
        written = False
        try:
            budget = load_quality_budget(target)
        except Exception:
            pass
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_json_report(target, budget)
        action = "overwritten" if existed else "created"
        status = "written"
        written = True

    validation = validate_quality_budget(target) if target.exists() else _validate_quality_budget_payload(budget, target)
    return {
        "schema_version": QUALITY_BUDGET_INIT_SCHEMA_VERSION,
        "status": status,
        "path": str(target),
        "dry_run": dry_run,
        "overwrite": overwrite,
        "summary": {
            "existed": existed,
            "written": written,
            "action": action,
            "validation_status": validation.get("status"),
        },
        "quality_budget": budget,
        "validation": validation,
    }


def validate_quality_budget(path: Path | str) -> dict[str, Any]:
    """Validate a TokenSquash quality budget and report the effective release-check policy."""

    source = Path(path)
    try:
        payload = load_quality_budget(source)
    except Exception as exc:
        return _quality_budget_validation_report(
            source,
            errors=[_budget_issue("schema", str(exc), path=str(source))],
            warnings=[],
            release_budget={},
            effective=None,
        )
    return _validate_quality_budget_payload(payload, source)


def format_quality_budget_init_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    budget = report.get("quality_budget") or {}
    release_budget = ((budget.get("turns") or {}).get("release_check") or {})
    lines = [
        "# TokenSquash Quality Budget Init",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Path: `{report.get('path')}`",
        f"- Action: `{summary.get('action')}`",
        f"- Written: `{summary.get('written')}`",
        f"- Dry run: `{report.get('dry_run')}`",
        f"- Validation: `{summary.get('validation_status')}`",
        "",
        "## Release Check Budget",
        "",
    ]
    for key in _RELEASE_BUDGET_KEYS:
        suffix = "%" if key == "min_saved_pct" else ""
        lines.append(f"- `{key}`: `{release_budget.get(key)}{suffix}`")
    return "\n".join(lines).rstrip() + "\n"


def _validate_quality_budget_payload(payload: dict[str, Any], source: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    release_budget: dict[str, Any] = {}
    effective: dict[str, Any] | None = None

    turns = payload.get("turns", {})
    release_budget = turns.get("release_check", {}) if isinstance(turns, dict) else {}
    if "release_check" not in turns:
        warnings.append(
            _budget_issue(
                "turns.release_check",
                "Missing release_check section; defaults will be used.",
                path=str(source),
            )
        )
    if isinstance(release_budget, dict):
        _validate_release_budget_values(release_budget, errors, warnings)
    else:
        errors.append(_budget_issue("turns.release_check", "release_check must be an object.", path=str(source)))
    if not errors:
        try:
            effective = _effective_quality_budget(source, release_budget)
        except Exception as exc:
            errors.append(_budget_issue("turns.release_check", str(exc), path=str(source)))

    return _quality_budget_validation_report(
        source,
        errors=errors,
        warnings=warnings,
        release_budget=release_budget,
        effective=effective,
    )


def _quality_budget_validation_report(
    source: Path,
    *,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    release_budget: dict[str, Any],
    effective: dict[str, Any] | None,
) -> dict[str, Any]:
    status = "fail" if errors else "warn" if warnings else "pass"
    return {
        "schema_version": QUALITY_BUDGET_VALIDATION_SCHEMA_VERSION,
        "status": status,
        "source": str(source),
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "release_check_key_count": len(release_budget) if isinstance(release_budget, dict) else 0,
            "effective_key_count": len((effective or {}).get("release_check", {})),
        },
        "quality_budget": effective,
        "errors": errors,
        "warnings": warnings,
    }


def format_quality_budget_validation_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    budget = report.get("quality_budget") or {}
    release_budget = budget.get("release_check") or {}
    lines = [
        "# TokenSquash Quality Budget Validation",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source')}`",
        f"- Errors: `{summary.get('error_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        "",
        "## Effective Release Check Budget",
        "",
    ]
    if release_budget:
        for key in _RELEASE_BUDGET_KEYS:
            suffix = "%" if key == "min_saved_pct" else ""
            lines.append(f"- `{key}`: `{release_budget.get(key)}{suffix}`")
    else:
        lines.append("No effective release-check budget.")
    if report.get("errors"):
        lines.extend(["", "## Errors", ""])
        for issue in report.get("errors", []):
            lines.append(f"- `{issue.get('field')}`: {issue.get('message')}")
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        for issue in report.get("warnings", []):
            lines.append(f"- `{issue.get('field')}`: {issue.get('message')}")
    return "\n".join(lines).rstrip() + "\n"


def format_turn_release_check_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs", {})
    budget = report.get("quality_budget", {})
    budget_values = budget.get("release_check", {})
    lines = [
        "# TokenSquash Turn Release Check",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Corpus: `{report.get('corpus')}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Saved percent: `{summary.get('saved_pct', 0.0)}%`",
        f"- Saved tokens: `{summary.get('saved_tokens', 0)}`",
        f"- Certification status: `{summary.get('certification_status')}`",
        f"- Doctor status: `{summary.get('doctor_status')}`",
        f"- History status: `{summary.get('history_status')}`",
        f"- Failed required checks: `{summary.get('failed_required_count', 0)}`",
        f"- Warnings: `{summary.get('warning_count', 0)}`",
        f"- Quality budget: `{budget.get('path') or budget.get('source')}`",
        "",
        "## Quality Budget",
        "",
        f"- Min saved percent: `{budget_values.get('min_saved_pct')}%`",
        f"- Max privacy findings: `{budget_values.get('max_privacy_findings')}`",
        f"- Max pass-through rows: `{budget_values.get('max_pass_through_rows')}`",
        f"- Max raw wire loss turns: `{budget_values.get('max_raw_wire_loss_turns')}`",
        f"- Require history: `{budget_values.get('require_history')}`",
        f"- Max history regressions: `{budget_values.get('max_history_regressions')}`",
        f"- Max history failures: `{budget_values.get('max_history_failures')}`",
        f"- Max doctor warnings: `{budget_values.get('max_doctor_warnings')}`",
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
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            f"- Release check: `{outputs.get('release_check')}`",
            f"- Markdown: `{outputs.get('markdown')}`",
            f"- Certification: `{outputs.get('certification')}`",
            f"- Quality budget: `{outputs.get('quality_budget')}`",
            f"- Quality budget validation: `{outputs.get('quality_budget_validation')}`",
            f"- Doctor: `{outputs.get('doctor')}`",
        ]
    )
    if outputs.get("history"):
        lines.append(f"- History: `{outputs.get('history')}`")
    history = (report.get("artifacts") or {}).get("history")
    if history:
        history_summary = history.get("summary", {})
        lines.extend(
            [
                "",
                "## History",
                "",
                f"- Certifications: `{history_summary.get('certification_count', 0)}`",
                f"- Net saved percent delta: `{history_summary.get('saved_pct_delta')}%`",
                f"- Adjacent regressions: `{history_summary.get('regressed_step_count', 0)}`",
                f"- Best saved percent: `{history_summary.get('best_saved_pct')}%`",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_turn_release_check_outputs(target: Path | str, report: dict[str, Any]) -> None:
    target_path = Path(target)
    target_path.mkdir(parents=True, exist_ok=True)
    artifacts = report.get("artifacts", {})
    outputs = report.setdefault("outputs", {})

    quality_budget = _quality_budget_payload_from_effective(report.get("quality_budget") or {})
    quality_budget_path = target_path / "quality-budget.json"
    quality_budget_validation_path = target_path / "quality-budget-validation.json"
    quality_budget_validation_markdown_path = target_path / "quality-budget-validation.md"
    quality_budget_validation = _validate_quality_budget_payload(quality_budget, quality_budget_path)
    _write_json_report(quality_budget_path, quality_budget)
    _write_json_report(quality_budget_validation_path, quality_budget_validation)
    quality_budget_validation_markdown_path.write_text(
        format_quality_budget_validation_markdown(quality_budget_validation),
        encoding="utf-8",
    )
    outputs["quality_budget"] = str(quality_budget_path)
    outputs["quality_budget_validation"] = str(quality_budget_validation_path)
    outputs["quality_budget_validation_markdown"] = str(quality_budget_validation_markdown_path)
    artifacts["quality_budget_validation"] = quality_budget_validation

    doctor = artifacts.get("doctor")
    if doctor:
        (target_path / "doctor.md").write_text(format_doctor_markdown(doctor), encoding="utf-8")
        _write_json_report(target_path / "doctor.json", doctor)
        outputs["doctor"] = str(target_path / "doctor.json")
        outputs["doctor_markdown"] = str(target_path / "doctor.md")

    history = artifacts.get("history")
    if history:
        (target_path / "history.md").write_text(format_turn_certification_history_markdown(history), encoding="utf-8")
        _write_json_report(target_path / "history.json", history)
        outputs["history"] = str(target_path / "history.json")
        outputs["history_markdown"] = str(target_path / "history.md")

    outputs["release_check"] = str(target_path / "release-check.json")
    outputs["markdown"] = str(target_path / "release-check.md")
    (target_path / "release-check.md").write_text(format_turn_release_check_markdown(report), encoding="utf-8")
    _write_json_report(target_path / "release-check.json", report)


def _history_release_check(
    history: dict[str, Any] | None,
    outputs: dict[str, str],
    budget: dict[str, Any],
) -> dict[str, Any]:
    if history is None:
        if bool(budget.get("require_history")):
            return _release_check(
                "certification_history",
                "fail",
                required=True,
                message="Quality budget requires baseline certification history.",
                data={"require_history": True},
            )
        return _release_check(
            "certification_history",
            "skip",
            required=False,
            message="No baseline certification history supplied.",
            data={},
        )
    status = history.get("status")
    summary = history.get("summary") or {}
    regressed_step_count = int(summary.get("regressed_step_count", 0))
    failed_step_count = int(summary.get("failed_step_count", 0))
    max_regressions = int(budget.get("max_history_regressions", 0))
    max_failures = int(budget.get("max_history_failures", 0))
    passed = (
        status != "failed"
        and regressed_step_count <= max_regressions
        and failed_step_count <= max_failures
    )
    return _release_check(
        "certification_history",
        "pass" if passed else "fail",
        required=True,
        message=(
            f"Certification history is within budget: {status}."
            if passed
            else f"Certification history is outside budget: {status}; inspect regressions before release."
        ),
        data={
            "artifact": outputs.get("history"),
            "history_status": status,
            "saved_pct_delta": summary.get("saved_pct_delta"),
            "regressed_step_count": regressed_step_count,
            "failed_step_count": failed_step_count,
            "max_history_regressions": max_regressions,
            "max_history_failures": max_failures,
        },
    )


def _doctor_warning_budget_check(doctor: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    warning_count = int((doctor.get("summary") or {}).get("warning_count", 0))
    max_warnings = int(budget.get("max_doctor_warnings", 0))
    passed = warning_count <= max_warnings
    return _release_check(
        "doctor_warning_budget",
        "pass" if passed else "fail",
        required=True,
        message=(
            f"Doctor warning count {warning_count} is within budget."
            if passed
            else f"Doctor warning count {warning_count} exceeds budget {max_warnings}."
        ),
        data={"warning_count": warning_count, "max_doctor_warnings": max_warnings},
    )


def _release_status(checks: list[dict[str, Any]]) -> str:
    if any(check.get("required") and check.get("status") == "fail" for check in checks):
        return "fail"
    if any(check.get("status") in {"warn", "skip"} for check in checks):
        return "warn"
    return "pass"


def _release_summary(
    certification: dict[str, Any],
    doctor: dict[str, Any],
    history: dict[str, Any] | None,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    cert_summary = certification.get("summary") or {}
    doctor_summary = doctor.get("summary") or {}
    history_summary = history.get("summary") if history else {}
    failed_required = [check for check in checks if check.get("required") and check.get("status") == "fail"]
    warnings = [check for check in checks if check.get("status") == "warn"]
    skips = [check for check in checks if check.get("status") == "skip"]
    return {
        "check_count": len(checks),
        "required_check_count": sum(1 for check in checks if check.get("required")),
        "failed_required_count": len(failed_required),
        "warning_count": len(warnings),
        "skip_count": len(skips),
        "certification_status": certification.get("status"),
        "doctor_status": doctor.get("status"),
        "history_status": history.get("status") if history else "skip",
        "turn_count": cert_summary.get("turn_count", 0),
        "saved_tokens": cert_summary.get("saved_tokens", 0),
        "saved_pct": cert_summary.get("saved_pct", 0.0),
        "prompt_saved_pct": cert_summary.get("prompt_saved_pct", 0.0),
        "reply_saved_pct": cert_summary.get("reply_saved_pct", 0.0),
        "privacy_finding_count": cert_summary.get("privacy_finding_count", 0),
        "pass_through_rows": cert_summary.get("pass_through_rows", 0),
        "raw_wire_loss_turns": cert_summary.get("raw_wire_loss_turns", 0),
        "failed_check_count": cert_summary.get("failed_check_count", 0),
        "suggestion_count": cert_summary.get("suggestion_count", 0),
        "doctor_failed_required_count": doctor_summary.get("failed_required_count", 0),
        "doctor_warning_count": doctor_summary.get("warning_count", 0),
        "history_saved_pct_delta": history_summary.get("saved_pct_delta") if history_summary else None,
        "history_regressed_step_count": history_summary.get("regressed_step_count", 0) if history_summary else 0,
        "history_failed_step_count": history_summary.get("failed_step_count", 0) if history_summary else 0,
    }


def _certification_reference(certification: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": certification.get("schema_version"),
        "status": certification.get("status"),
        "path": certification.get("path"),
        "counter": certification.get("counter"),
        "adaptive": certification.get("adaptive"),
        "target_savings_pct": certification.get("target_savings_pct"),
        "thresholds": certification.get("thresholds", {}),
        "summary": certification.get("summary", {}),
        "outputs": certification.get("outputs", {}),
    }


def _release_check(
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


def _path_list(paths: Iterable[Path | str] | Path | str | None) -> list[Path]:
    if paths is None:
        return []
    if isinstance(paths, (str, Path)):
        return [Path(paths)]
    return [Path(path) for path in paths]


def _quality_budget_payload_from_effective(effective: dict[str, Any]) -> dict[str, Any]:
    release_budget = dict(effective.get("release_check") or DEFAULT_RELEASE_BUDGET)
    return {
        "schema_version": QUALITY_BUDGET_SCHEMA_VERSION,
        "turns": {"release_check": release_budget},
    }


def _validate_release_budget_values(
    release_budget: dict[str, Any],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    unknown = sorted(set(release_budget) - set(_RELEASE_BUDGET_KEYS))
    for key in unknown:
        warnings.append(_budget_issue(f"turns.release_check.{key}", "Unknown release-check budget key."))
    for key, value in release_budget.items():
        field = f"turns.release_check.{key}"
        if key == "min_saved_pct":
            try:
                _coerce_budget_float(key, value)
            except ValueError as exc:
                errors.append(_budget_issue(field, str(exc)))
        elif key in _RELEASE_BUDGET_INT_KEYS:
            try:
                _coerce_budget_int(key, value)
            except ValueError as exc:
                errors.append(_budget_issue(field, str(exc)))
        elif key == "require_history":
            try:
                _coerce_budget_bool(key, value)
            except ValueError as exc:
                errors.append(_budget_issue(field, str(exc)))


def _resolve_quality_budget(
    path: Path | str | None,
    *,
    min_saved_pct: float | None,
    max_privacy_findings: int | None,
    max_pass_through_rows: int | None,
    max_raw_wire_loss_turns: int | None,
) -> dict[str, Any]:
    source_payload = load_quality_budget(path) if path else None
    release_budget = ((source_payload or {}).get("turns") or {}).get("release_check", {})
    if not isinstance(release_budget, dict):
        release_budget = {}
    return {
        "schema_version": QUALITY_BUDGET_SCHEMA_VERSION,
        "source": "file" if path else "defaults",
        "path": str(path) if path else None,
        "release_check": _build_release_budget(
            release_budget,
            min_saved_pct=min_saved_pct,
            max_privacy_findings=max_privacy_findings,
            max_pass_through_rows=max_pass_through_rows,
            max_raw_wire_loss_turns=max_raw_wire_loss_turns,
            require_history=None,
            max_history_regressions=None,
            max_history_failures=None,
            max_doctor_warnings=None,
        ),
    }


def _effective_quality_budget(source: Path, release_budget: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": QUALITY_BUDGET_SCHEMA_VERSION,
        "source": "file",
        "path": str(source),
        "release_check": _build_release_budget(
            release_budget,
            min_saved_pct=None,
            max_privacy_findings=None,
            max_pass_through_rows=None,
            max_raw_wire_loss_turns=None,
            require_history=None,
            max_history_regressions=None,
            max_history_failures=None,
            max_doctor_warnings=None,
        ),
    }


def _build_release_budget(
    release_budget: dict[str, Any],
    *,
    min_saved_pct: float | None,
    max_privacy_findings: int | None,
    max_pass_through_rows: int | None,
    max_raw_wire_loss_turns: int | None,
    require_history: bool | None,
    max_history_regressions: int | None,
    max_history_failures: int | None,
    max_doctor_warnings: int | None,
) -> dict[str, Any]:
    return {
        "min_saved_pct": _budget_float(release_budget, "min_saved_pct", min_saved_pct),
        "max_privacy_findings": _budget_int(release_budget, "max_privacy_findings", max_privacy_findings),
        "max_pass_through_rows": _budget_int(release_budget, "max_pass_through_rows", max_pass_through_rows),
        "max_raw_wire_loss_turns": _budget_int(
            release_budget,
            "max_raw_wire_loss_turns",
            max_raw_wire_loss_turns,
        ),
        "require_history": _budget_bool(release_budget, "require_history", require_history),
        "max_history_regressions": _budget_int(release_budget, "max_history_regressions", max_history_regressions),
        "max_history_failures": _budget_int(release_budget, "max_history_failures", max_history_failures),
        "max_doctor_warnings": _budget_int(release_budget, "max_doctor_warnings", max_doctor_warnings),
    }


def _budget_float(release_budget: dict[str, Any], name: str, explicit: float | None) -> float:
    value = explicit if explicit is not None else release_budget.get(name, DEFAULT_RELEASE_BUDGET[name])
    return _coerce_budget_float(name, value)


def _budget_int(release_budget: dict[str, Any], name: str, explicit: int | None) -> int:
    value = explicit if explicit is not None else release_budget.get(name, DEFAULT_RELEASE_BUDGET[name])
    return _coerce_budget_int(name, value)


def _budget_bool(release_budget: dict[str, Any], name: str, explicit: bool | None) -> bool:
    value = explicit if explicit is not None else release_budget.get(name, DEFAULT_RELEASE_BUDGET[name])
    return _coerce_budget_bool(name, value)


def _coerce_budget_float(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, not a boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(result) or result < 0 or result > 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return result


def _coerce_budget_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, not a boolean")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if result < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")
    return result


def _coerce_budget_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{name} must be a boolean")
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise ValueError(f"{name} must be a boolean")


def _budget_issue(field: str, message: str, *, path: str | None = None) -> dict[str, Any]:
    issue = {"field": field, "message": message}
    if path is not None:
        issue["path"] = path
    return issue


def _write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
