from __future__ import annotations

from pathlib import Path
from typing import Any


WORKSPACE_INIT_SCHEMA_VERSION = "tokensquash.workspace.init.v1"
PRIVATE_DIRECTORIES = ("private-turns", "private-prompts", "private-aliases")
GITIGNORE_PATTERNS = (
    "prompts/",
    "private-prompts/",
    "turns/",
    "private-turns/",
    "aliases/",
    "private-aliases/",
    "*.redacted.jsonl",
    "*.redacted-turns.jsonl",
)


def initialize_workspace(
    root: Path | str = ".",
    *,
    create_dirs: bool = True,
    update_gitignore: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Prepare a local TokenSquash workspace for private corpora and aliases."""

    target = Path(root)
    directory_reports = _initialize_directories(target, dry_run=dry_run) if create_dirs else []
    gitignore_report = _initialize_gitignore(target, dry_run=dry_run) if update_gitignore else None
    conflict_count = sum(1 for item in directory_reports if item.get("action") == "conflict")
    if gitignore_report and gitignore_report.get("action") == "conflict":
        conflict_count += 1
    changed = any(item.get("action") == "created" for item in directory_reports)
    if gitignore_report and gitignore_report.get("action") in {"created", "updated"}:
        changed = True
    status = "fail" if conflict_count else "dry-run" if dry_run else "changed" if changed else "ready"
    return {
        "schema_version": WORKSPACE_INIT_SCHEMA_VERSION,
        "status": status,
        "root": str(target),
        "dry_run": dry_run,
        "summary": {
            "directory_count": len(directory_reports),
            "created_directory_count": sum(1 for item in directory_reports if item.get("action") == "created"),
            "conflict_count": conflict_count,
            "gitignore_updated": bool(gitignore_report and gitignore_report.get("action") in {"created", "updated"}),
            "added_gitignore_pattern_count": len((gitignore_report or {}).get("added_patterns", [])),
        },
        "directories": directory_reports,
        "gitignore": gitignore_report,
    }


def format_workspace_init_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    gitignore = report.get("gitignore") or {}
    lines = [
        "# TokenSquash Workspace Init",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Root: `{report.get('root')}`",
        f"- Dry run: `{report.get('dry_run')}`",
        f"- Directories: `{summary.get('directory_count', 0)}`",
        f"- Created directories: `{summary.get('created_directory_count', 0)}`",
        f"- Conflicts: `{summary.get('conflict_count', 0)}`",
        f"- Gitignore updated: `{summary.get('gitignore_updated')}`",
        f"- Added gitignore patterns: `{summary.get('added_gitignore_pattern_count', 0)}`",
    ]
    if report.get("directories"):
        lines.extend(["", "## Directories", "", "| Path | Action |", "|---|---|"])
        for item in report.get("directories", []):
            lines.append(f"| `{_markdown_cell(str(item.get('path', '')))}` | `{item.get('action')}` |")
    if gitignore:
        lines.extend(
            [
                "",
                "## Gitignore",
                "",
                f"- Path: `{gitignore.get('path')}`",
                f"- Action: `{gitignore.get('action')}`",
            ]
        )
        added = gitignore.get("added_patterns", [])
        if added:
            lines.extend(["", "Added patterns:", ""])
            for pattern in added:
                lines.append(f"- `{pattern}`")
    return "\n".join(lines).rstrip() + "\n"


def _initialize_directories(root: Path, *, dry_run: bool) -> list[dict[str, Any]]:
    reports = []
    for name in PRIVATE_DIRECTORIES:
        path = root / name
        existed = path.exists()
        conflict = existed and not path.is_dir()
        action = "exists" if existed else "created"
        if conflict:
            action = "conflict"
        elif not existed and not dry_run:
            path.mkdir(parents=True, exist_ok=True)
        reports.append(
            {
                "path": str(path),
                "name": name,
                "existed": existed,
                "conflict": conflict,
                "action": "would_create" if dry_run and not existed else action,
            }
        )
    return reports


def _initialize_gitignore(root: Path, *, dry_run: bool) -> dict[str, Any]:
    path = root / ".gitignore"
    existed = path.exists()
    if existed and path.is_dir():
        return {
            "path": str(path),
            "existed": True,
            "action": "conflict",
            "added_patterns": [],
            "required_patterns": list(GITIGNORE_PATTERNS),
            "message": ".gitignore exists but is a directory.",
        }
    text = path.read_text(encoding="utf-8-sig") if existed else ""
    lines = text.splitlines()
    existing_patterns = {
        line.strip().replace("\\", "/")
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    }
    added = [pattern for pattern in GITIGNORE_PATTERNS if pattern not in existing_patterns]
    action = "unchanged"
    if added:
        action = "updated" if existed else "created"
        if dry_run:
            action = "would_update" if existed else "would_create"
        elif existed:
            path.write_text(_append_gitignore_patterns(text, added), encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(added) + "\n", encoding="utf-8")
    return {
        "path": str(path),
        "existed": existed,
        "action": action,
        "added_patterns": added,
        "required_patterns": list(GITIGNORE_PATTERNS),
    }


def _append_gitignore_patterns(text: str, patterns: list[str]) -> str:
    prefix = text
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + "\n".join(patterns) + "\n"


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
