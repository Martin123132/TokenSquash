from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .about import PROJECT_NAME, package_requires_python, package_version


RELEASE_INFO_SCHEMA_VERSION = "tokensquash.release_info.v1"


def build_release_info(
    *,
    root: Path | str | None = None,
    require_clean: bool = False,
) -> dict[str, Any]:
    """Return package, git, and runtime metadata for a release candidate."""

    started = time.time()
    repo_root = Path(root) if root is not None else Path.cwd()
    git = _git_info(repo_root)
    dirty = bool(git.get("dirty"))
    git_ready = bool(git.get("inside_work_tree") and git.get("commit"))
    if require_clean and (not git_ready or dirty):
        status = "fail"
    elif not git_ready:
        status = "warn"
    else:
        status = "pass"
    return {
        "schema_version": RELEASE_INFO_SCHEMA_VERSION,
        "status": status,
        "root": str(repo_root),
        "require_clean": require_clean,
        "project": {
            "name": PROJECT_NAME,
            "version": package_version(repo_root),
            "requires_python": package_requires_python(repo_root),
        },
        "git": git,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "summary": {
            "git_ready": git_ready,
            "dirty": dirty,
            "status_line_count": len(git.get("status_lines", [])),
            "elapsed_seconds": round(time.time() - started, 4),
        },
    }


def format_release_info_markdown(report: dict[str, Any]) -> str:
    project = report.get("project", {})
    git = report.get("git", {})
    python = report.get("python", {})
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Release Info",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Root: `{report.get('root')}`",
        f"- Require clean: `{report.get('require_clean')}`",
        f"- Project: `{project.get('name')}`",
        f"- Version: `{project.get('version')}`",
        f"- Requires Python: `{project.get('requires_python')}`",
        f"- Python: `{python.get('version')}`",
        f"- Git ready: `{summary.get('git_ready')}`",
        f"- Dirty: `{summary.get('dirty')}`",
        f"- Commit: `{git.get('commit')}`",
        f"- Branch: `{git.get('branch')}`",
        f"- Remote: `{git.get('remote_origin')}`",
        f"- Status lines: `{summary.get('status_line_count', 0)}`",
    ]
    status_lines = git.get("status_lines", [])
    if status_lines:
        lines.extend(["", "## Git Status", ""])
        for line in status_lines[:20]:
            lines.append(f"- `{_markdown_cell(str(line))}`")
        if len(status_lines) > 20:
            lines.append(f"- `... {len(status_lines) - 20} more`")
    return "\n".join(lines).rstrip() + "\n"


def write_release_info_outputs(target: Path | str, report: dict[str, Any]) -> None:
    target_path = Path(target)
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "release-info.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (target_path / "release-info.md").write_text(format_release_info_markdown(report), encoding="utf-8")


def _git_info(root: Path) -> dict[str, Any]:
    git_executable = _find_git_executable()
    base = {
        "command": git_executable,
        "command_available": bool(git_executable),
        "inside_work_tree": False,
        "repository_root": None,
        "branch": None,
        "commit": None,
        "short_commit": None,
        "tag": None,
        "remote_origin": None,
        "dirty": None,
        "status_lines": [],
        "tracked_change_count": 0,
        "untracked_count": 0,
    }
    if not git_executable:
        return {**base, "message": "Git executable was not found."}

    inside = _run_git(root, git_executable, "rev-parse", "--is-inside-work-tree")
    if not inside["ok"] or inside["stdout"].strip() != "true":
        return {**base, "message": "Root is not inside a Git work tree."}

    repository_root = _run_git(root, git_executable, "rev-parse", "--show-toplevel")
    branch = _run_git(root, git_executable, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _run_git(root, git_executable, "rev-parse", "HEAD")
    short_commit = _run_git(root, git_executable, "rev-parse", "--short", "HEAD")
    tag = _run_git(root, git_executable, "describe", "--tags", "--exact-match", "HEAD")
    remote = _run_git(root, git_executable, "config", "--get", "remote.origin.url")
    status = _run_git(root, git_executable, "status", "--porcelain")
    status_lines = status["stdout"].splitlines() if status["ok"] else []
    return {
        **base,
        "inside_work_tree": True,
        "repository_root": repository_root["stdout"].strip() if repository_root["ok"] else None,
        "branch": branch["stdout"].strip() if branch["ok"] else None,
        "commit": commit["stdout"].strip() if commit["ok"] else None,
        "short_commit": short_commit["stdout"].strip() if short_commit["ok"] else None,
        "tag": tag["stdout"].strip() if tag["ok"] else None,
        "remote_origin": remote["stdout"].strip() if remote["ok"] else None,
        "dirty": bool(status_lines),
        "status_lines": status_lines,
        "tracked_change_count": sum(1 for line in status_lines if not line.startswith("??")),
        "untracked_count": sum(1 for line in status_lines if line.startswith("??")),
        "message": "Git metadata captured.",
    }


def _find_git_executable() -> str | None:
    discovered = shutil.which("git")
    if discovered:
        return discovered
    windows_fallback = Path("D:/Apps/Git/cmd/git.exe")
    if windows_fallback.exists():
        return str(windows_fallback)
    return None


def _run_git(root: Path, git_executable: str, *args: str) -> dict[str, Any]:
    completed = subprocess.run(
        [git_executable, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
