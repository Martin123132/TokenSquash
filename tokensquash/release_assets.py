from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .candidate import verify_release_candidate_pack


RELEASE_ASSETS_SCHEMA_VERSION = "tokensquash.release_assets.v1"
DEFAULT_RELEASE_ASSETS_OUT_DIR = Path("private-turns/release-assets")
RELEASE_VERIFICATION_SECTION_START = "<!-- tokensquash-release-assets:start -->"
RELEASE_VERIFICATION_SECTION_END = "<!-- tokensquash-release-assets:end -->"


def prepare_release_assets(
    pack: Path | str,
    *,
    tag: str,
    repo: str | None = None,
    out_dir: Path | str = DEFAULT_RELEASE_ASSETS_OUT_DIR,
    require_release_candidate_pass: bool = True,
    upload: bool = False,
    clobber: bool = False,
    gh_executable: str = "gh",
    verification_doc: Path | str | None = None,
    ci_run: str | None = None,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Stage public release assets from a verified release-candidate pack."""

    started = time.time()
    root = Path(cwd) if cwd is not None else Path.cwd()
    source = _resolve_path(root, Path(pack))
    output_dir = _resolve_path(root, Path(out_dir))
    clean_tag = tag.strip()
    if not clean_tag:
        raise ValueError("release tag must not be empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir = source if source.is_dir() else source.parent
    verification = verify_release_candidate_pack(
        source,
        require_release_candidate_pass=require_release_candidate_pass,
    )
    verify_asset_path = output_dir / "verify-release-candidate.json"
    verify_asset_path.write_text(json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    release_info = _read_json(candidate_dir / "release-info.json")
    resolved_repo = repo or _infer_github_repo(((release_info or {}).get("git") or {}).get("remote_origin"))
    errors: list[str] = []
    notes: list[str] = []
    assets: list[dict[str, Any]] = []

    if verification.get("status") == "pass":
        assets.extend(_stage_pack_assets(candidate_dir, output_dir, verification, errors))
        assets.append(_asset_entry("verify_release_candidate", verify_asset_path, verify_asset_path))
    else:
        errors.append(f"release-candidate verification status is {verification.get('status')!r}")

    upload_result: dict[str, Any] | None = None
    upload_command = _build_upload_command(
        clean_tag,
        [Path(asset["path"]) for asset in assets],
        repo=resolved_repo,
        clobber=clobber,
        gh_executable=gh_executable,
    )
    if upload and assets and not errors:
        upload_result = _run_upload(upload_command, cwd=root)
        if upload_result["status"] != "pass":
            errors.append("GitHub release upload failed.")
    elif upload and not assets:
        errors.append("no staged assets were available to upload")
    else:
        notes.append("Upload not attempted; pass --upload after reviewing staged assets.")

    status = "fail" if errors else "pass"
    report = {
        "schema_version": RELEASE_ASSETS_SCHEMA_VERSION,
        "status": status,
        "tag": clean_tag,
        "repo": resolved_repo,
        "source": str(source),
        "out_dir": str(output_dir),
        "require_release_candidate_pass": require_release_candidate_pass,
        "upload": upload,
        "clobber": clobber,
        "gh_executable": gh_executable,
        "summary": {
            "asset_count": len(assets),
            "verification_status": verification.get("status"),
            "release_candidate_status": (verification.get("summary") or {}).get("release_candidate_status"),
            "release_info_commit": (verification.get("summary") or {}).get("release_info_commit"),
            "release_attestation_status": (verification.get("summary") or {}).get("release_attestation_status"),
            "scorecard_pack_status": (verification.get("summary") or {}).get("scorecard_pack_status"),
            "scorecard_status": (verification.get("summary") or {}).get("scorecard_status"),
            "scorecard_turn_count": (verification.get("summary") or {}).get("scorecard_turn_count"),
            "wheel": _asset_hash(assets, "wheel"),
            "sdist": _asset_hash(assets, "sdist"),
            "artifact_manifest": _asset_hash(assets, "artifact_manifest"),
            "scorecard_pack": _asset_hash(assets, "scorecard_pack"),
            "scorecard": _asset_hash(assets, "scorecard"),
            "verify_release_candidate": _asset_hash(assets, "verify_release_candidate"),
            "uploaded": bool(upload_result and upload_result.get("status") == "pass"),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "assets": assets,
        "verification": {
            "schema_version": verification.get("schema_version"),
            "status": verification.get("status"),
            "summary": verification.get("summary", {}),
        },
        "commands": {
            "upload": _format_command(upload_command),
        },
        "outputs": {
            "asset_dir": str(output_dir),
            "verify_release_candidate": str(verify_asset_path),
            "report": str(output_dir / "release-assets.json"),
            "markdown": str(output_dir / "release-assets.md"),
        },
        "upload_result": upload_result,
        "errors": errors,
        "notes": notes,
    }
    if verification_doc is not None and not errors:
        doc_result = update_release_verification_doc(
            report,
            _resolve_path(root, Path(verification_doc)),
            ci_run=ci_run,
        )
        report["outputs"]["verification_doc"] = doc_result["path"]
        report["summary"]["verification_doc_updated"] = True
        report["notes"].append(f"Release verification doc updated: {doc_result['path']}")
    elif verification_doc is not None:
        report["summary"]["verification_doc_updated"] = False
        report["notes"].append("Release verification doc not updated because release asset staging failed.")
    else:
        report["summary"]["verification_doc_updated"] = False
    report["status"] = "fail" if report["errors"] else "pass"
    write_release_assets_outputs(output_dir, report)
    return report


def write_release_assets_outputs(target: Path | str, report: dict[str, Any]) -> None:
    target_path = Path(target)
    target_path.mkdir(parents=True, exist_ok=True)
    report.setdefault("outputs", {})
    report["outputs"]["asset_dir"] = str(target_path)
    report["outputs"]["report"] = str(target_path / "release-assets.json")
    report["outputs"]["markdown"] = str(target_path / "release-assets.md")
    (target_path / "release-assets.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (target_path / "release-assets.md").write_text(format_release_assets_markdown(report), encoding="utf-8")


def format_release_assets_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Release Assets",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Tag: `{report.get('tag')}`",
        f"- Repo: `{report.get('repo')}`",
        f"- Source: `{report.get('source')}`",
        f"- Output dir: `{report.get('out_dir')}`",
        f"- Verification status: `{summary.get('verification_status')}`",
        f"- Release-candidate status: `{summary.get('release_candidate_status')}`",
        f"- Git commit: `{summary.get('release_info_commit')}`",
        f"- Scorecard pack status: `{summary.get('scorecard_pack_status')}`",
        f"- Scorecard status: `{summary.get('scorecard_status')}`",
        f"- Scorecard turns: `{summary.get('scorecard_turn_count')}`",
        f"- Assets: `{summary.get('asset_count', 0)}`",
        f"- Uploaded: `{summary.get('uploaded')}`",
        "",
        "## Assets",
        "",
        "| Role | Name | Bytes | SHA-256 |",
        "|---|---|---:|---|",
    ]
    for asset in report.get("assets", []):
        lines.append(
            "| "
            f"{_markdown_cell(str(asset.get('role', '')))} | "
            f"`{_markdown_cell(str(asset.get('name', '')))}` | "
            f"{asset.get('bytes', 0)} | "
            f"`{asset.get('sha256')}` |"
        )
    lines.extend(["", "## Upload Command", "", f"```powershell\n{report.get('commands', {}).get('upload')}\n```"])
    if report.get("errors"):
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {_markdown_cell(str(error))}" for error in report.get("errors", []))
    if report.get("notes"):
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {_markdown_cell(str(note))}" for note in report.get("notes", []))
    return "\n".join(lines).rstrip() + "\n"


def update_release_verification_doc(
    report: dict[str, Any],
    path: Path | str,
    *,
    ci_run: str | None = None,
) -> dict[str, Any]:
    """Update a release-verification markdown doc from a release-assets report."""

    doc_path = Path(path)
    section = _wrapped_release_verification_section(report, ci_run=ci_run)
    if doc_path.exists():
        current = doc_path.read_text(encoding="utf-8")
        updated = _replace_or_append_generated_section(current, section)
    else:
        updated = _default_release_verification_doc(section)
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(updated, encoding="utf-8")
    return {
        "path": str(doc_path),
        "tag": report.get("tag"),
        "asset_count": len(report.get("assets", [])),
        "bytes": doc_path.stat().st_size,
    }


def format_release_verification_section(report: dict[str, Any], *, ci_run: str | None = None) -> str:
    tag = str(report.get("tag") or "").strip()
    if not tag:
        raise ValueError("release-assets report is missing tag")
    assets = report.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("release-assets report has no assets")
    repo = report.get("repo")
    summary = report.get("summary") or {}
    verification = report.get("verification") or {}
    verification_summary = verification.get("summary") or {}
    release_url = f"https://github.com/{repo}/releases/tag/{tag}" if repo else None
    ci_run_value = ci_run or report.get("ci_run")
    lines = [
        f"## {tag} Assets",
        "",
        f"The `{tag}` GitHub Release includes:",
        "",
    ]
    for asset in assets:
        name = asset.get("name")
        if name:
            lines.append(f"- `{name}`")
    if release_url:
        lines.extend(["", f"Release URL: [{tag}]({release_url})"])
    lines.extend(
        [
            "",
            "Expected SHA-256 values from the release asset report:",
            "",
            "| Asset | SHA-256 |",
            "|---|---|",
        ]
    )
    for asset in assets:
        lines.append(f"| `{_markdown_cell(str(asset.get('name', '')))}` | `{asset.get('sha256')}` |")
    lines.extend(
        [
            "",
            "Release evidence:",
            "",
            f"- tag: `{tag}`",
            f"- release commit: `{summary.get('release_info_commit')}`",
            f"- release-candidate verifier status: `{summary.get('verification_status')}`",
            f"- release-candidate status: `{summary.get('release_candidate_status')}`",
            f"- release attestation status: `{summary.get('release_attestation_status')}`",
            f"- release attestation evidence hash: `{verification_summary.get('release_attestation_evidence_hash')}`",
            f"- scorecard pack status: `{summary.get('scorecard_pack_status')}`",
            f"- scorecard status: `{summary.get('scorecard_status')}`",
            f"- scorecard turns: `{summary.get('scorecard_turn_count')}`",
        ]
    )
    if ci_run_value:
        lines.append(f"- GitHub Actions run: `{ci_run_value}`")
    lines.extend(
        [
            "- packaged license evidence: inspect `verify-release-candidate.json` "
            "for `LICENSE` and `COMMERCIAL-LICENSE.md` checks on the wheel and source distribution",
            "- scorecard evidence: inspect `scorecard-pack.json` and `scorecard.json` for public-corpus "
            "codec health, saved percent, and milestone status",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _wrapped_release_verification_section(report: dict[str, Any], *, ci_run: str | None) -> str:
    return (
        RELEASE_VERIFICATION_SECTION_START
        + "\n"
        + format_release_verification_section(report, ci_run=ci_run).rstrip()
        + "\n"
        + RELEASE_VERIFICATION_SECTION_END
        + "\n"
    )


def _replace_or_append_generated_section(current: str, section: str) -> str:
    start = current.find(RELEASE_VERIFICATION_SECTION_START)
    end = current.find(RELEASE_VERIFICATION_SECTION_END)
    if start != -1 and end != -1 and start < end:
        end += len(RELEASE_VERIFICATION_SECTION_END)
        return current[:start].rstrip() + "\n\n" + section.rstrip() + "\n\n" + current[end:].lstrip()
    return current.rstrip() + "\n\n" + section


def _default_release_verification_doc(section: str) -> str:
    return (
        "# Release Verification\n\n"
        "This guide explains how to inspect TokenSquash release assets and evidence.\n"
        "Release assets are attached to GitHub Releases so reviewers do not need access\n"
        "to local `private-turns/` storage or expired CI artifacts.\n\n"
        + section
    )


def _stage_pack_assets(
    candidate_dir: Path,
    output_dir: Path,
    verification: dict[str, Any],
    errors: list[str],
) -> list[dict[str, Any]]:
    summary = verification.get("summary") or {}
    sources = [
        ("wheel", _summary_path(summary, "wheel"), None),
        ("sdist", _summary_path(summary, "sdist"), None),
        ("release_attestation", candidate_dir / "release-attestation.json", "release-attestation.json"),
        ("artifact_manifest", candidate_dir / "artifact-manifest.json", "artifact-manifest.json"),
        ("scorecard_pack", candidate_dir / "scorecard-pack.json", "scorecard-pack.json"),
        ("scorecard", candidate_dir / "scorecard-pack" / "scorecard.json", "scorecard.json"),
    ]
    staged: list[dict[str, Any]] = []
    for role, source, destination_name in sources:
        if source is None or not source.exists() or not source.is_file():
            errors.append(f"missing release asset for {role}: {source}")
            continue
        destination = output_dir / (destination_name or source.name)
        _copy_file(source, destination)
        staged.append(_asset_entry(role, destination, source))
    return staged


def _summary_path(summary: dict[str, Any], key: str) -> Path | None:
    value = summary.get(key)
    return Path(str(value)) if value else None


def _asset_entry(role: str, path: Path, source: Path) -> dict[str, Any]:
    return {
        "role": role,
        "name": path.name,
        "path": str(path),
        "source": str(source),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _asset_hash(assets: list[dict[str, Any]], role: str) -> str | None:
    for asset in assets:
        if asset.get("role") == role:
            return str(asset.get("sha256"))
    return None


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == destination.resolve():
        return
    shutil.copy2(source, destination)


def _build_upload_command(
    tag: str,
    assets: list[Path],
    *,
    repo: str | None,
    clobber: bool,
    gh_executable: str,
) -> list[str]:
    command = [gh_executable, "release", "upload", tag]
    command.extend(str(path) for path in assets)
    if repo:
        command.extend(["--repo", repo])
    if clobber:
        command.append("--clobber")
    return command


def _run_upload(command: list[str], *, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "status": "pass" if completed.returncode == 0 else "fail",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _infer_github_repo(remote: Any) -> str | None:
    if not isinstance(remote, str) or not remote.strip():
        return None
    value = remote.strip()
    prefixes = ("https://github.com/", "http://github.com/", "ssh://git@github.com/")
    for prefix in prefixes:
        if value.startswith(prefix):
            return _clean_github_repo(value[len(prefix) :])
    if value.startswith("git@github.com:"):
        return _clean_github_repo(value[len("git@github.com:") :])
    return None


def _clean_github_repo(value: str) -> str | None:
    cleaned = value.strip().strip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    parts = [part for part in cleaned.split("/") if part]
    if len(parts) < 2:
        return None
    return "/".join(parts[:2])


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_command(command: list[str]) -> str:
    return " ".join(_quote_command_part(part) for part in command)


def _quote_command_part(value: str) -> str:
    if value and not any(char.isspace() for char in value):
        return value
    return '"' + value.replace('"', '\\"') + '"'


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
