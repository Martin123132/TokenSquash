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

FIELD_VALUE_ALIAS_FIELDS = ("verification", "commands", "risks", "next_steps", "warnings")
FIELD_VALUE_CODE_PREFIXES = {
    "verification": "v",
    "commands": "c",
    "risks": "r",
    "next_steps": "n",
    "warnings": "w",
}

_SAFE_CODE_RE = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9_-]*/$")
_SAFE_FIELD_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class AliasTable:
    """Shared sidecar aliases for compact reply fields."""

    path_prefix_codes: Mapping[str, str] = field(default_factory=dict)
    field_value_codes: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    include_builtins: bool = True

    def __post_init__(self) -> None:
        clean_path_codes = _clean_path_prefix_codes(self.path_prefix_codes)
        clean_field_codes = _clean_field_value_codes(self.field_value_codes)
        _validate_path_prefix_codes(clean_path_codes, self.include_builtins)
        _validate_field_value_codes(clean_field_codes)
        object.__setattr__(self, "path_prefix_codes", clean_path_codes)
        object.__setattr__(self, "field_value_codes", clean_field_codes)

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

    def field_code_for_value(self, field_name: str, value: str) -> str | None:
        field_codes = self.field_value_codes.get(field_name, {})
        value_key = _field_value_key(value)
        for stored_value, code in field_codes.items():
            if _field_value_key(stored_value) == value_key:
                return code
        return None

    def field_value_for_code(self, field_name: str, code: str) -> str | None:
        for value, stored_code in self.field_value_codes.get(field_name, {}).items():
            if stored_code == code:
                return value
        return None

    def with_path_prefixes(self, path_prefix_codes: Mapping[str, str]) -> "AliasTable":
        merged = dict(self.path_prefix_codes)
        merged.update(path_prefix_codes)
        return AliasTable(merged, self.field_value_codes, include_builtins=self.include_builtins)

    def with_field_values(self, field_value_codes: Mapping[str, Mapping[str, str]]) -> "AliasTable":
        merged = _copy_field_value_codes(self.field_value_codes)
        for field_name, values in field_value_codes.items():
            merged.setdefault(field_name, {})
            merged[field_name].update(values)
        return AliasTable(self.path_prefix_codes, merged, include_builtins=self.include_builtins)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ALIAS_SCHEMA_VERSION,
            "include_builtins": self.include_builtins,
            "path_prefixes": dict(self.path_prefix_codes),
            "field_values": _copy_field_value_codes(self.field_value_codes),
        }

    def to_summary(self) -> dict[str, Any]:
        return {
            "schema_version": ALIAS_SCHEMA_VERSION,
            "include_builtins": self.include_builtins,
            "custom_path_prefix_count": len(self.path_prefix_codes),
            "custom_field_value_count": sum(len(values) for values in self.field_value_codes.values()),
            "builtin_path_prefix_count": len(PATH_PREFIX_CODES) if self.include_builtins else 0,
            "path_prefix_count": len(self.all_path_prefix_codes()),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AliasTable":
        raw_prefixes = payload.get("path_prefixes", payload.get("path_prefix_codes", {}))
        raw_field_values = payload.get("field_values", payload.get("field_value_codes", {}))
        include_builtins = bool(payload.get("include_builtins", True))
        return cls(
            _coerce_path_prefix_codes(raw_prefixes),
            _coerce_field_value_codes(raw_field_values),
            include_builtins=include_builtins,
        )


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
    max_field_values: int = 8,
    min_saved_tokens: int = 1,
    base_aliases: AliasTable | Mapping[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Learn a session alias table from repeated reply paths and field values."""

    started = time.time()
    rows = list(records)
    base = coerce_alias_table(base_aliases)
    min_count = max(1, int(min_count))
    max_path_prefixes = max(0, int(max_path_prefixes))
    max_field_values = max(0, int(max_field_values))
    min_saved_tokens = max(0, int(min_saved_tokens))
    observations = _reply_path_observations(rows)
    field_observations = _reply_field_observations(rows)
    field_candidates = _select_field_value_aliases(
        field_observations,
        base,
        counter,
        min_count,
        max_field_values,
        min_saved_tokens,
    )
    candidate_prefixes = sorted(
        prefix
        for prefix, count in _prefix_counts(observations).items()
        if count >= min_count and base.path_code_for_prefix(prefix) is None
    )
    selected: list[dict[str, Any]] = []
    custom_codes: dict[str, str] = dict(base.path_prefix_codes)
    custom_field_codes = _copy_field_value_codes(base.field_value_codes)
    remaining = set(candidate_prefixes)

    while remaining and len(selected) < max_path_prefixes:
        table = base.with_path_prefixes(custom_codes).with_field_values(custom_field_codes)
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

    for item in field_candidates:
        field_name = str(item["field"])
        custom_field_codes.setdefault(field_name, {})
        custom_field_codes[field_name][str(item["value"])] = str(item["code"])

    table = AliasTable(custom_codes, custom_field_codes)
    status = "empty" if not rows else "pass"
    estimated_path_saved_tokens = sum(int(item["estimated_saved_tokens"]) for item in selected)
    estimated_field_saved_tokens = sum(int(item["estimated_saved_tokens"]) for item in field_candidates)
    summary = {
        "record_count": len(rows),
        "path_count": len(observations),
        "field_value_count": sum(len(values) for values in field_observations.values()),
        "candidate_prefix_count": len(candidate_prefixes),
        "selected_path_prefix_count": len(selected),
        "selected_field_value_count": len(field_candidates),
        "estimated_path_saved_tokens": estimated_path_saved_tokens,
        "estimated_field_saved_tokens": estimated_field_saved_tokens,
        "estimated_saved_tokens": estimated_path_saved_tokens + estimated_field_saved_tokens,
        "elapsed_seconds": round(time.time() - started, 4),
    }
    return {
        "schema_version": ALIAS_SCHEMA_VERSION,
        "status": status,
        "source": source,
        "counter": counter,
        "min_count": min_count,
        "max_path_prefixes": max_path_prefixes,
        "max_field_values": max_field_values,
        "min_saved_tokens": min_saved_tokens,
        "include_builtins": True,
        "path_prefixes": dict(custom_codes),
        "field_values": _copy_field_value_codes(custom_field_codes),
        "summary": summary,
        "selected_path_prefixes": selected,
        "selected_field_values": field_candidates,
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
        f"- Field values: `{summary.get('field_value_count', 0)}`",
        f"- Candidate prefixes: `{summary.get('candidate_prefix_count', 0)}`",
        f"- Selected prefixes: `{summary.get('selected_path_prefix_count', 0)}`",
        f"- Selected field values: `{summary.get('selected_field_value_count', 0)}`",
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
    lines.extend(["## Field Values", ""])
    selected_fields = list(report.get("selected_field_values", []) or [])
    if not selected_fields:
        lines.extend(["No custom field values selected.", ""])
    else:
        lines.extend(
            [
                "| Field | Code | Count | Est saved | Value |",
                "|---|---|---:|---:|---|",
            ]
        )
        for item in selected_fields:
            lines.append(
                f"| {_markdown_cell(str(item.get('field')))} | "
                f"`{_markdown_cell(str(item.get('code')))}` | "
                f"{item.get('count')} | "
                f"{item.get('estimated_saved_tokens')} | "
                f"{_markdown_cell(str(item.get('value')))} |"
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


def _reply_field_observations(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    from .reply import reply_from_dict

    observations: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for index, row in enumerate(rows, start=1):
        reply = reply_from_dict(row)
        row_id = str(row.get("id", f"row-{index:04d}"))
        sample = {"id": row_id, "index": index}
        for field_name in FIELD_VALUE_ALIAS_FIELDS:
            for value in getattr(reply, field_name):
                clean = _normalize_field_value(value)
                if not clean:
                    continue
                observations.setdefault((field_name, clean), []).append(sample)
    return observations


def _select_field_value_aliases(
    observations: dict[tuple[str, str], list[dict[str, Any]]],
    base: AliasTable,
    counter: str,
    min_count: int,
    max_field_values: int,
    min_saved_tokens: int,
) -> list[dict[str, Any]]:
    builtin_codes = _builtin_field_value_codes()
    selected: list[dict[str, Any]] = []
    custom_codes = _copy_field_value_codes(base.field_value_codes)
    remaining = {
        (field_name, value)
        for (field_name, value), occurrences in observations.items()
        if len(occurrences) >= min_count
        and field_name in FIELD_VALUE_ALIAS_FIELDS
        and base.field_code_for_value(field_name, value) is None
        and _builtin_field_code(field_name, value, builtin_codes) is None
    }

    while remaining and len(selected) < max_field_values:
        table = base.with_field_values(custom_codes)
        best = None
        for field_name, value in remaining:
            code = _next_field_code(field_name, table, builtin_codes)
            candidate = _evaluate_field_value(field_name, value, code, observations[(field_name, value)], counter)
            if best is None or _alias_sort_key(candidate) < _alias_sort_key(best):
                best = candidate
        if best is None or int(best["estimated_saved_tokens"]) < min_saved_tokens:
            break
        selected.append(best)
        custom_codes.setdefault(str(best["field"]), {})
        custom_codes[str(best["field"])][str(best["value"])] = str(best["code"])
        remaining.remove((str(best["field"]), str(best["value"])))
    return selected


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


def _evaluate_field_value(
    field_name: str,
    value: str,
    code: str,
    observations: list[dict[str, Any]],
    counter: str,
) -> dict[str, Any]:
    count = len(observations)
    current_tokens = _count_tokens(_wire_value(value), counter) * count
    aliased_tokens = _count_tokens(code, counter) * count
    estimated_saved_tokens = current_tokens - aliased_tokens
    return {
        "kind": "field_value",
        "field": field_name,
        "value": value,
        "code": code,
        "count": count,
        "current_tokens": current_tokens,
        "aliased_tokens": aliased_tokens,
        "estimated_saved_tokens": estimated_saved_tokens,
        "sample_ids": _sample_ids(observations),
    }


def _next_path_code(table: AliasTable) -> str:
    used = set(table.all_path_prefix_codes().values())
    for token in _path_code_tokens():
        code = f"@{token}/"
        if code not in used:
            return code
    raise ValueError("no path alias codes are available")


def _next_field_code(
    field_name: str,
    table: AliasTable,
    builtin_codes: Mapping[str, Mapping[str, str]],
) -> str:
    used = set(table.field_value_codes.get(field_name, {}).values())
    used.update(builtin_codes.get(field_name, {}).values())
    prefix = FIELD_VALUE_CODE_PREFIXES.get(field_name, "a")
    for token in _field_code_tokens():
        code = f"{prefix}{token}"
        if code not in used:
            return code
    raise ValueError(f"no field alias codes are available for {field_name}")


def _path_code_tokens() -> Iterable[str]:
    for char in "0123456789abcdefghijklmnopqrstuvwxyz":
        yield char
    for first in "0123456789abcdefghijklmnopqrstuvwxyz":
        for second in "0123456789abcdefghijklmnopqrstuvwxyz":
            yield first + second


def _field_code_tokens() -> Iterable[str]:
    for char in "0123456789abcdefghijklmnopqrstuvwxyz":
        yield char
    for first in "0123456789abcdefghijklmnopqrstuvwxyz":
        for second in "0123456789abcdefghijklmnopqrstuvwxyz":
            yield first + second


def _alias_sort_key(item: Mapping[str, Any]) -> tuple[int, int, str]:
    value = item.get("prefix", item.get("value", ""))
    return (-int(item.get("estimated_saved_tokens", 0)), -int(item.get("count", 0)), str(value))


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


def _coerce_field_value_codes(value: Any) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        result: dict[str, dict[str, str]] = {}
        for field_name, field_values in value.items():
            if isinstance(field_values, Mapping):
                result[str(field_name)] = {str(field_value): str(code) for field_value, code in field_values.items()}
                continue
            if isinstance(field_values, Iterable) and not isinstance(field_values, str):
                result[str(field_name)] = {}
                for item in field_values:
                    if not isinstance(item, Mapping):
                        raise ValueError("field_values list items must be objects")
                    field_value = item.get("value")
                    code = item.get("code")
                    if field_value is None or code is None:
                        raise ValueError("field_values list items must include value and code")
                    result[str(field_name)][str(field_value)] = str(code)
                continue
            raise ValueError("field_values entries must be objects or lists")
        return result
    raise ValueError("field_values must be an object")


def _clean_path_prefix_codes(path_prefix_codes: Mapping[str, str]) -> dict[str, str]:
    result = {}
    for prefix, code in path_prefix_codes.items():
        clean_prefix = _normalize_prefix(prefix)
        clean_code = str(code).strip()
        if not clean_prefix:
            continue
        result[clean_prefix] = clean_code
    return result


def _clean_field_value_codes(field_value_codes: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for field_name, values in field_value_codes.items():
        clean_field = str(field_name).strip()
        if clean_field not in FIELD_VALUE_ALIAS_FIELDS:
            continue
        result[clean_field] = {}
        for value, code in values.items():
            clean_value = _normalize_field_value(value)
            clean_code = str(code).strip()
            if clean_value:
                result[clean_field][clean_value] = clean_code
        if not result[clean_field]:
            result.pop(clean_field)
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


def _validate_field_value_codes(field_value_codes: Mapping[str, Mapping[str, str]]) -> None:
    for field_name, values in field_value_codes.items():
        if field_name not in FIELD_VALUE_ALIAS_FIELDS:
            raise ValueError(f"unsupported field alias field: {field_name}")
        code_to_value: dict[str, str] = {}
        for value, code in values.items():
            if not _SAFE_FIELD_CODE_RE.fullmatch(code):
                raise ValueError(f"field alias code must be alphanumeric: {code}")
            existing = code_to_value.get(code)
            if existing and existing != value:
                raise ValueError(f"field alias code {code} is used for both {existing} and {value}")
            code_to_value[code] = value


def _copy_field_value_codes(value: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, str]]:
    return {str(field_name): dict(values) for field_name, values in value.items()}


def _builtin_field_value_codes() -> dict[str, dict[str, str]]:
    from .reply import FIELD_VALUE_CODES

    return {field_name: dict(values) for field_name, values in FIELD_VALUE_CODES.items()}


def _builtin_field_code(
    field_name: str,
    value: str,
    builtin_codes: Mapping[str, Mapping[str, str]],
) -> str | None:
    value_key = _field_value_key(value)
    for stored_value, code in builtin_codes.get(field_name, {}).items():
        if _field_value_key(stored_value) == value_key:
            return code
    return None


def _normalize_prefix(prefix: str) -> str:
    normalized = _normalize_path(prefix).strip(" ;:")
    if normalized and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def _normalize_path(path: str) -> str:
    return _SPACE_RE.sub(" ", str(path).strip()).strip(" ;:").replace("\\", "/")


def _normalize_field_value(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value).strip()).strip(" .;:")


def _field_value_key(value: str) -> str:
    return _normalize_field_value(value).lower()


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
