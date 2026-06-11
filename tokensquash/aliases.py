from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ALIAS_SCHEMA_VERSION = "tokensquash.aliases.v1"

PATH_PREFIX_CODES = {
    "tokensquash/": "@t/",
    "tests/": "@x/",
    "examples/": "@e/",
    "benchmarks/": "@b/",
    ".github/workflows/": "@g/",
    "src/": "@s/",
}

_SAFE_CODE_RE = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9_-]*/$")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class AliasTable:
    """Shared sidecar aliases for compact reply fields."""

    path_prefix_codes: Mapping[str, str] = field(default_factory=dict)
    include_builtins: bool = True

    def __post_init__(self) -> None:
        clean_codes = _clean_path_prefix_codes(self.path_prefix_codes)
        _validate_path_prefix_codes(clean_codes, self.include_builtins)
        object.__setattr__(self, "path_prefix_codes", clean_codes)

    def all_path_prefix_codes(self) -> dict[str, str]:
        result = dict(PATH_PREFIX_CODES) if self.include_builtins else {}
        result.update(self.path_prefix_codes)
        return result

    def path_prefix_names(self) -> dict[str, str]:
        return {
            code: prefix
            for prefix, code in sorted(
                self.all_path_prefix_codes().items(),
                key=lambda item: len(item[1]),
                reverse=True,
            )
        }

    def encode_path(self, value: str) -> str:
        normalized = _normalize_path(value)
        for prefix, code in sorted(
            self.all_path_prefix_codes().items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if normalized.startswith(prefix):
                return code + normalized[len(prefix):]
        return normalized

    def decode_path(self, value: str) -> str:
        normalized = _normalize_path(value)
        for code, prefix in self.path_prefix_names().items():
            if normalized.startswith(code):
                return prefix + normalized[len(code):]
        return normalized

    def path_code_for_prefix(self, prefix: str) -> str | None:
        return self.all_path_prefix_codes().get(_normalize_prefix(prefix))

    def with_path_prefixes(self, path_prefix_codes: Mapping[str, str]) -> "AliasTable":
        merged = dict(self.path_prefix_codes)
        merged.update(path_prefix_codes)
        return AliasTable(merged, include_builtins=self.include_builtins)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ALIAS_SCHEMA_VERSION,
            "include_builtins": self.include_builtins,
            "path_prefixes": dict(self.path_prefix_codes),
        }

    def to_summary(self) -> dict[str, Any]:
        return {
            "schema_version": ALIAS_SCHEMA_VERSION,
            "include_builtins": self.include_builtins,
            "custom_path_prefix_count": len(self.path_prefix_codes),
            "builtin_path_prefix_count": len(PATH_PREFIX_CODES) if self.include_builtins else 0,
            "path_prefix_count": len(self.all_path_prefix_codes()),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AliasTable":
        raw_prefixes = payload.get("path_prefixes", payload.get("path_prefix_codes", {}))
        include_builtins = bool(payload.get("include_builtins", True))
        return cls(_coerce_path_prefix_codes(raw_prefixes), include_builtins=include_builtins)


def coerce_alias_table(value: AliasTable | Mapping[str, Any] | None) -> AliasTable:
    if value is None:
        return DEFAULT_ALIAS_TABLE
    if isinstance(value, AliasTable):
        return value
    if isinstance(value, Mapping):
        return AliasTable.from_dict(value)
    raise TypeError("aliases must be an AliasTable, mapping, or None")


def load_alias_table(path: Path | str | None) -> AliasTable:
    if path is None:
        return DEFAULT_ALIAS_TABLE
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("alias file must contain a JSON object")
    return AliasTable.from_dict(payload)


def write_alias_table(path: Path | str, report: Mapping[str, Any] | AliasTable) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(report, AliasTable):
        payload = report.to_dict()
    else:
        payload = AliasTable.from_dict(report).to_dict()
    target.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def learn_reply_aliases(
    records: Iterable[dict[str, Any]],
    *,
    counter: str = "heuristic",
    min_count: int = 2,
    max_path_prefixes: int = 8,
    min_saved_tokens: int = 1,
    base_aliases: AliasTable | Mapping[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Learn a session alias table from repeated reply file prefixes."""

    started = time.time()
    rows = list(records)
    base = coerce_alias_table(base_aliases)
    min_count = max(1, int(min_count))
    max_path_prefixes = max(0, int(max_path_prefixes))
    min_saved_tokens = max(0, int(min_saved_tokens))
    observations = _reply_path_observations(rows)
    candidate_prefixes = sorted(
        prefix
        for prefix, count in _prefix_counts(observations).items()
        if count >= min_count and base.path_code_for_prefix(prefix) is None
    )
    selected: list[dict[str, Any]] = []
    custom_codes: dict[str, str] = dict(base.path_prefix_codes)
    remaining = set(candidate_prefixes)

    while remaining and len(selected) < max_path_prefixes:
        table = base.with_path_prefixes(custom_codes)
        code = _next_path_code(table)
        best = None
        for prefix in remaining:
            candidate = _evaluate_path_prefix(prefix, code, observations, table, counter)
            if candidate["count"] < min_count:
                continue
            if best is None or _alias_sort_key(candidate) < _alias_sort_key(best):
                best = candidate
        if best is None or int(best["estimated_saved_tokens"]) < min_saved_tokens:
            break
        selected.append(best)
        custom_codes[str(best["prefix"])] = str(best["code"])
        remaining.remove(str(best["prefix"]))

    table = AliasTable(custom_codes)
    status = "empty" if not rows else "pass"
    summary = {
        "record_count": len(rows),
        "path_count": len(observations),
        "candidate_prefix_count": len(candidate_prefixes),
        "selected_path_prefix_count": len(selected),
        "estimated_saved_tokens": sum(int(item["estimated_saved_tokens"]) for item in selected),
        "elapsed_seconds": round(time.time() - started, 4),
    }
    return {
        "schema_version": ALIAS_SCHEMA_VERSION,
        "status": status,
        "source": source,
        "counter": counter,
        "min_count": min_count,
        "max_path_prefixes": max_path_prefixes,
        "min_saved_tokens": min_saved_tokens,
        "include_builtins": True,
        "path_prefixes": dict(custom_codes),
        "summary": summary,
        "selected_path_prefixes": selected,
        "aliases": table.to_summary(),
    }


def format_alias_report_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# TokenSquash Alias Table",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Source: `{report.get('source') or 'inline'}`",
        f"- Counter: `{report.get('counter')}`",
        f"- Records: `{summary.get('record_count', 0)}`",
        f"- Paths: `{summary.get('path_count', 0)}`",
        f"- Candidate prefixes: `{summary.get('candidate_prefix_count', 0)}`",
        f"- Selected prefixes: `{summary.get('selected_path_prefix_count', 0)}`",
        f"- Estimated saved tokens: `{summary.get('estimated_saved_tokens', 0)}`",
        "",
        "## Path Prefixes",
        "",
    ]
    selected = list(report.get("selected_path_prefixes", []) or [])
    if not selected:
        lines.extend(["No custom path prefixes selected.", ""])
    else:
        lines.extend(
            [
                "| Code | Prefix | Count | Est saved |",
                "|---|---|---:|---:|",
            ]
        )
        for item in selected:
            lines.append(
                f"| `{_markdown_cell(str(item.get('code')))}` | "
                f"{_markdown_cell(str(item.get('prefix')))} | "
                f"{item.get('count')} | "
                f"{item.get('estimated_saved_tokens')} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _reply_path_observations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .reply import reply_from_dict

    observations: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        reply = reply_from_dict(row)
        row_id = str(row.get("id", f"row-{index:04d}"))
        for path in reply.files:
            normalized = _normalize_path(path)
            if "/" not in normalized:
                continue
            observations.append({"path": normalized, "id": row_id, "index": index})
    return observations


def _prefix_counts(observations: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in observations:
        for prefix in _path_prefixes(str(item["path"])):
            counts[prefix] = counts.get(prefix, 0) + 1
    return counts


def _path_prefixes(path: str) -> list[str]:
    prefixes = []
    normalized = _normalize_path(path)
    for index, char in enumerate(normalized):
        if char == "/" and index > 0:
            prefix = normalized[: index + 1]
            if len(prefix) >= 4:
                prefixes.append(prefix)
    return prefixes


def _evaluate_path_prefix(
    prefix: str,
    code: str,
    observations: list[dict[str, Any]],
    table: AliasTable,
    counter: str,
) -> dict[str, Any]:
    matching = [item for item in observations if str(item["path"]).startswith(prefix)]
    current_tokens = 0
    aliased_tokens = 0
    for item in matching:
        path = str(item["path"])
        current_tokens += _count_tokens(_wire_value(table.encode_path(path)), counter)
        aliased_tokens += _count_tokens(_wire_value(code + path[len(prefix):]), counter)
    estimated_saved_tokens = current_tokens - aliased_tokens
    return {
        "kind": "path_prefix",
        "prefix": prefix,
        "code": code,
        "count": len(matching),
        "current_tokens": current_tokens,
        "aliased_tokens": aliased_tokens,
        "estimated_saved_tokens": estimated_saved_tokens,
        "sample_ids": _sample_ids(matching),
    }


def _next_path_code(table: AliasTable) -> str:
    used = set(table.all_path_prefix_codes().values())
    for token in _path_code_tokens():
        code = f"@{token}/"
        if code not in used:
            return code
    raise ValueError("no path alias codes are available")


def _path_code_tokens() -> Iterable[str]:
    for char in "0123456789abcdefghijklmnopqrstuvwxyz":
        yield char
    for first in "0123456789abcdefghijklmnopqrstuvwxyz":
        for second in "0123456789abcdefghijklmnopqrstuvwxyz":
            yield first + second


def _alias_sort_key(item: Mapping[str, Any]) -> tuple[int, int, str]:
    return (-int(item.get("estimated_saved_tokens", 0)), -int(item.get("count", 0)), str(item.get("prefix", "")))


def _sample_ids(observations: list[dict[str, Any]]) -> list[str]:
    result = []
    for item in observations:
        value = str(item.get("id"))
        if value not in result:
            result.append(value)
        if len(result) >= 3:
            break
    return result


def _coerce_path_prefix_codes(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(prefix): str(code) for prefix, code in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, str):
        result = {}
        for item in value:
            if not isinstance(item, Mapping):
                raise ValueError("path_prefixes list items must be objects")
            prefix = item.get("prefix")
            code = item.get("code")
            if prefix is None or code is None:
                raise ValueError("path_prefixes list items must include prefix and code")
            result[str(prefix)] = str(code)
        return result
    raise ValueError("path_prefixes must be an object or list")


def _clean_path_prefix_codes(path_prefix_codes: Mapping[str, str]) -> dict[str, str]:
    result = {}
    for prefix, code in path_prefix_codes.items():
        clean_prefix = _normalize_prefix(prefix)
        clean_code = str(code).strip()
        if not clean_prefix:
            continue
        result[clean_prefix] = clean_code
    return result


def _validate_path_prefix_codes(path_prefix_codes: Mapping[str, str], include_builtins: bool) -> None:
    prefix_to_code = dict(PATH_PREFIX_CODES) if include_builtins else {}
    prefix_to_code.update(path_prefix_codes)
    code_to_prefix: dict[str, str] = {}
    for prefix, code in prefix_to_code.items():
        if not prefix.endswith("/"):
            raise ValueError(f"path alias prefix must end with /: {prefix}")
        if not _SAFE_CODE_RE.fullmatch(code):
            raise ValueError(f"path alias code must look like @x/: {code}")
        existing = code_to_prefix.get(code)
        if existing and existing != prefix:
            raise ValueError(f"path alias code {code} is used for both {existing} and {prefix}")
        code_to_prefix[code] = prefix


def _normalize_prefix(prefix: str) -> str:
    normalized = _normalize_path(prefix).strip(" ;:")
    if normalized and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def _normalize_path(path: str) -> str:
    return _SPACE_RE.sub(" ", str(path).strip()).strip(" ;:").replace("\\", "/")


def _wire_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@()\\+=-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _count_tokens(text: str, counter: str) -> int:
    from .metrics import count_tokens

    return count_tokens(text, counter)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


DEFAULT_ALIAS_TABLE = AliasTable()
