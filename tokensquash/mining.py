from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any, Iterable

from .aliases import AliasTable, coerce_alias_table
from .metrics import count_tokens
from .reply import FIELD_VALUE_CODES, reply_from_dict


MINE_FIELDS = ("verification", "commands", "risks", "next_steps", "warnings")

_SPACE_RE = re.compile(r"\s+")
_PATH_RE = re.compile(
    r"(?<![\w.-])(?:[A-Za-z]:)?(?:[\w.-]+[\\/])+[\w.@()-]+|(?<![\w.-])[\w.-]+\.(?:py|js|ts|tsx|jsx|md|json|toml|yaml|yml|css|html|sql|go|rs|java|cs|cpp|c|h)(?![\w.-])",
    re.IGNORECASE,
)


def mine_reply_patterns(
    records: Iterable[dict[str, Any]],
    *,
    counter: str = "heuristic",
    min_count: int = 2,
    limit: int = 10,
    source: str | None = None,
    source_type: str = "reply",
    aliases: AliasTable | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Find repeated reply values that may deserve compact field codes."""

    started = time.time()
    alias_table = coerce_alias_table(aliases)
    rows = list(records)
    min_count = max(1, int(min_count))
    limit = max(1, int(limit))
    field_occurrences = _collect_field_occurrences(rows, alias_table)
    path_occurrences = _collect_path_occurrences(rows, alias_table)
    field_candidates = [
        _field_candidate(field, value, occurrences, counter, alias_table)
        for (field, value), occurrences in field_occurrences.items()
        if len(occurrences) >= min_count
    ]
    path_candidates = [
        _path_candidate(pattern_type, value, occurrences, counter, alias_table)
        for (pattern_type, value), occurrences in path_occurrences.items()
        if len(occurrences) >= min_count
    ]
    field_candidates.sort(key=_candidate_sort_key)
    path_candidates.sort(key=_candidate_sort_key)
    new_candidates = [item for item in field_candidates if not item["already_coded"] and item["estimated_new_saved_tokens"] > 0]
    existing_candidates = [item for item in field_candidates if item["already_coded"]]

    return {
        "schema_version": "tokensquash.patterns.mine.v1",
        "status": "empty" if not rows else "pass",
        "source_type": source_type,
        "source": source,
        "counter": counter,
        "min_count": min_count,
        "limit": limit,
        "summary": {
            "record_count": len(rows),
            "field_candidate_count": len(field_candidates),
            "new_candidate_count": len(new_candidates),
            "existing_code_count": len(existing_candidates),
            "path_candidate_count": len(path_candidates),
            "estimated_new_saved_tokens": sum(int(item["estimated_new_saved_tokens"]) for item in new_candidates),
            "estimated_path_saved_tokens": sum(int(item["estimated_new_saved_tokens"]) for item in path_candidates),
            "elapsed_seconds": round(time.time() - started, 4),
        },
        "top_candidates": new_candidates[:limit],
        "existing_codes": existing_candidates[:limit],
        "path_patterns": path_candidates[:limit],
        "fields": _group_candidates_by_field(field_candidates, limit),
    }


def format_pattern_mine_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Pattern Mine",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source type: `{report.get('source_type')}`",
        f"- Source: `{report.get('source') or 'inline'}`",
        f"- Counter: `{report.get('counter')}`",
    ]
    if "turn_count" in summary:
        lines.append(f"- Turns: `{summary.get('turn_count', 0)}`")
    lines.append(f"- Records: `{summary.get('record_count', 0)}`")
    if "prompt_path_record_count" in summary:
        lines.append(f"- Prompt path records: `{summary.get('prompt_path_record_count', 0)}`")
    lines.extend(
        [
            f"- New candidates: `{summary.get('new_candidate_count', 0)}`",
            f"- Existing coded values seen: `{summary.get('existing_code_count', 0)}`",
            f"- Path candidates: `{summary.get('path_candidate_count', 0)}`",
            f"- Estimated new saved tokens: `{summary.get('estimated_new_saved_tokens', 0)}`",
            f"- Estimated path saved tokens: `{summary.get('estimated_path_saved_tokens', 0)}`",
            "",
        ]
    )
    _append_candidate_table(lines, "Top New Field Candidates", report.get("top_candidates", []), include_field=True)
    _append_candidate_table(lines, "Existing Codes Seen", report.get("existing_codes", []), include_field=True)
    _append_candidate_table(lines, "Path Patterns", report.get("path_patterns", []), include_field=False)
    return "\n".join(lines).rstrip() + "\n"


def _collect_field_occurrences(
    rows: list[dict[str, Any]],
    aliases: AliasTable,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    occurrences: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows, start=1):
        reply = reply_from_dict(row, aliases=aliases)
        sample = {"id": str(row.get("id", f"row-{index:04d}")), "index": index}
        for field in MINE_FIELDS:
            for value in getattr(reply, field):
                clean = _clean_value(value)
                if clean:
                    occurrences[(field, clean)].append(sample)
    return occurrences


def _collect_path_occurrences(
    rows: list[dict[str, Any]],
    aliases: AliasTable,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    occurrences: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows, start=1):
        reply = reply_from_dict(row, aliases=aliases)
        sample = {"id": str(row.get("id", f"row-{index:04d}")), "index": index}
        values = set(_normalize_path(value) for value in reply.files)
        for key in ("text", "reply", "human"):
            if row.get(key):
                values.update(_normalize_path(match.group(0)) for match in _PATH_RE.finditer(str(row[key])))
        for path in sorted(values):
            if not path:
                continue
            occurrences[("exact_path", path)].append(sample)
            prefix = _path_prefix(path)
            if prefix:
                occurrences[("path_prefix", prefix)].append(sample)
            extension = _path_extension(path)
            if extension:
                occurrences[("path_extension", extension)].append(sample)
    return occurrences


def _field_candidate(
    field: str,
    value: str,
    occurrences: list[dict[str, Any]],
    counter: str,
    aliases: AliasTable,
) -> dict[str, Any]:
    existing_code = _existing_field_code(field, value, aliases)
    suggested_code = existing_code or _suggest_code(field, value, len(occurrences))
    encoded_value = existing_code or value
    gross_saved = _estimated_saved_tokens(encoded_value, suggested_code, len(occurrences), counter)
    return {
        "kind": "field_value",
        "field": field,
        "value": value,
        "count": len(occurrences),
        "existing_code": existing_code,
        "suggested_code": suggested_code,
        "already_coded": existing_code is not None,
        "value_tokens": count_tokens(_wire_value(encoded_value), counter),
        "code_tokens": count_tokens(suggested_code, counter),
        "gross_saved_tokens": gross_saved,
        "estimated_new_saved_tokens": 0 if existing_code else max(0, gross_saved),
        "sample_ids": _sample_ids(occurrences),
    }


def _path_candidate(
    pattern_type: str,
    value: str,
    occurrences: list[dict[str, Any]],
    counter: str,
    aliases: AliasTable,
) -> dict[str, Any]:
    existing_code = _existing_path_code(pattern_type, value, aliases)
    suggested_code = existing_code or _suggest_path_code(pattern_type, value)
    encoded_value = _current_path_wire_value(value, aliases)
    gross_saved = _estimated_saved_tokens(encoded_value, suggested_code, len(occurrences), counter)
    return {
        "kind": "path_pattern",
        "pattern_type": pattern_type,
        "value": value,
        "count": len(occurrences),
        "existing_code": existing_code,
        "suggested_code": suggested_code,
        "already_coded": existing_code is not None,
        "value_tokens": count_tokens(_wire_value(encoded_value), counter),
        "code_tokens": count_tokens(suggested_code, counter),
        "gross_saved_tokens": gross_saved,
        "estimated_new_saved_tokens": 0 if existing_code else max(0, gross_saved),
        "sample_ids": _sample_ids(occurrences),
    }


def _estimated_saved_tokens(value: str, code: str, count: int, counter: str) -> int:
    return (count_tokens(_wire_value(value), counter) - count_tokens(code, counter)) * count


def _candidate_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    return (-int(item.get("estimated_new_saved_tokens", 0)), -int(item.get("gross_saved_tokens", 0)), str(item.get("value", "")))


def _group_candidates_by_field(candidates: list[dict[str, Any]], limit: int) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        field = str(item.get("field", "unknown"))
        grouped.setdefault(field, [])
        if len(grouped[field]) < limit:
            grouped[field].append(item)
    return grouped


def _existing_field_code(field: str, value: str, aliases: AliasTable) -> str | None:
    return FIELD_VALUE_CODES.get(field, {}).get(value.lower().strip(" .;:")) or aliases.field_code_for_value(field, value)


def _suggest_code(field: str, value: str, count: int) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value.lower())
    stem = "".join(word[0] for word in words[:4]) or field[:1]
    if len(stem) < 2:
        stem = f"{field[:1]}{count}"
    return stem[:6]


def _suggest_path_code(pattern_type: str, value: str) -> str:
    prefix = {"exact_path": "p", "path_prefix": "pf", "path_extension": "px"}.get(pattern_type, "p")
    words = re.findall(r"[A-Za-z0-9]+", value.lower())
    stem = "".join(word[0] for word in words[:3]) or "x"
    return f"{prefix}{stem[:4]}"


def _existing_path_code(pattern_type: str, value: str, aliases: AliasTable) -> str | None:
    if pattern_type == "path_prefix":
        return aliases.path_code_for_prefix(value)
    return None


def _current_path_wire_value(value: str, aliases: AliasTable) -> str:
    return aliases.encode_path(value)


def _path_prefix(path: str) -> str:
    if "/" not in path:
        return ""
    return path.rsplit("/", 1)[0] + "/"


def _path_extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _sample_ids(occurrences: list[dict[str, Any]]) -> list[str]:
    result = []
    for item in occurrences:
        value = str(item.get("id"))
        if value not in result:
            result.append(value)
        if len(result) >= 3:
            break
    return result


def _append_candidate_table(
    lines: list[str],
    title: str,
    candidates: list[dict[str, Any]],
    *,
    include_field: bool,
) -> None:
    lines.extend([f"## {title}", ""])
    if not candidates:
        lines.extend(["No candidates.", ""])
        return
    if include_field:
        lines.extend(
            [
                "| Field | Count | Est new saved | Code | Value |",
                "|---|---:|---:|---|---|",
            ]
        )
        for item in candidates:
            code = item.get("existing_code") or item.get("suggested_code")
            lines.append(
                f"| {_markdown_cell(str(item.get('field')))} | {item.get('count')} | "
                f"{item.get('estimated_new_saved_tokens')} | `{_markdown_cell(str(code))}` | "
                f"{_markdown_cell(str(item.get('value')))} |"
            )
    else:
        lines.extend(
            [
                "| Pattern | Count | Est new saved | Code | Value |",
                "|---|---:|---:|---|---|",
            ]
        )
        for item in candidates:
            code = item.get("existing_code") or item.get("suggested_code")
            lines.append(
                f"| {_markdown_cell(str(item.get('pattern_type')))} | {item.get('count')} | "
                f"{item.get('estimated_new_saved_tokens')} | `{_markdown_cell(str(code))}` | "
                f"{_markdown_cell(str(item.get('value')))} |"
            )
    lines.append("")


def _wire_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@()\\+=-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _clean_value(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value).strip()).strip(" .;:")


def _normalize_path(path: str) -> str:
    return _SPACE_RE.sub(" ", str(path).strip()).strip(" ;:").replace("\\", "/")


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
