from __future__ import annotations

import json
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


def run_turn_release_check(
    corpus: Path | str,
    *,
    out_dir: Path | str = Path("private-turns/release-check"),
    history_paths: Iterable[Path | str] | Path | str | None = None,
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
    min_saved_pct: float = 0.5,
    max_privacy_findings: int = 0,
    max_pass_through_rows: int = 0,
    max_raw_wire_loss_turns: int = 0,
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
        min_saved_pct=min_saved_pct,
        max_privacy_findings=max_privacy_findings,
        max_pass_through_rows=max_pass_through_rows,
        max_raw_wire_loss_turns=max_raw_wire_loss_turns,
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
        _history_release_check(history, outputs),
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
        },
        "thresholds": {
            "min_saved_pct": min_saved_pct,
            "max_privacy_findings": max_privacy_findings,
            "max_pass_through_rows": max_pass_through_rows,
            "max_raw_wire_loss_turns": max_raw_wire_loss_turns,
        },
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


def format_turn_release_check_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    outputs = report.get("outputs", {})
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


def _history_release_check(history: dict[str, Any] | None, outputs: dict[str, str]) -> dict[str, Any]:
    if history is None:
        return _release_check(
            "certification_history",
            "skip",
            required=False,
            message="No baseline certification history supplied.",
            data={},
        )
    status = history.get("status")
    passed = status in {"improved", "same"}
    return _release_check(
        "certification_history",
        "pass" if passed else "fail",
        required=True,
        message=(
            f"Certification history is {status}."
            if passed
            else f"Certification history is {status}; inspect regressions before release."
        ),
        data={
            "artifact": outputs.get("history"),
            "history_status": status,
            "saved_pct_delta": (history.get("summary") or {}).get("saved_pct_delta"),
            "regressed_step_count": (history.get("summary") or {}).get("regressed_step_count", 0),
            "failed_step_count": (history.get("summary") or {}).get("failed_step_count", 0),
        },
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


def _write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
