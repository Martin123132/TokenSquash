from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .aliases import AliasTable, DEFAULT_ALIAS_TABLE, PATH_PREFIX_CODES, coerce_alias_table


REPLY_WIRE_VERSION = "tr1"

STATUS_CODES = {
    "done": "d",
    "partial": "p",
    "blocked": "b",
    "failed": "e",
}
STATUS_NAMES = {value: key for key, value in STATUS_CODES.items()}

FIELD_CODES = {
    "files": "f",
    "verification": "v",
    "commands": "c",
    "risks": "r",
    "next_steps": "n",
    "warnings": "w",
}
FIELD_NAMES = {value: key for key, value in FIELD_CODES.items()}

FIELD_VALUE_CODES = {
    "verification": {
        "unit tests pass": "t",
        "tests pass": "t",
        "local tests pass": "lt",
        "ci pass": "ci",
        "github actions pass": "gha",
        "build pass": "b",
        "lint pass": "l",
        "exact benchmark pass": "x",
        "heuristic benchmark pass": "h",
        "exact benchmark skipped": "xs",
        "commands reviewed": "cr",
        "baseline compare pass": "bc",
        "reply cli smoke test pass": "rc",
        "no code changes made": "nc",
        "not implemented": "ni",
        "messy corpus validation warns only": "mw",
    },
    "commands": {
        "python -m unittest discover -s tests": "pyunit",
        "python -m tokensquash reply encode --summary example": "renc",
        "python -m tokensquash bench examples/messy-coding-prompts.jsonl": "benchmessy",
        "python -m tokensquash bench examples/messy-coding-prompts.jsonl --counter tiktoken:cl100k_base": "benchcl100k",
        "python -m tokensquash corpus validate examples/messy-coding-prompts.jsonl": "validmessy",
        "python -m tokensquash corpus redact examples/messy-coding-prompts.jsonl --out temp.redacted.jsonl": "redactmessy",
        "python -m tokensquash compare benchmarks/messy-cl100k.json benchmarks/messy-o200k.json": "cmpmessy",
        "gh run view latest": "ghrun",
    },
    "risks": {
        "none": "0",
        "synthetic corpus only": "syn",
        "sample corpus is synthetic": "syn",
        "examples remain synthetic": "synx",
        "redaction is not a privacy guarantee": "redact",
        "install tokenizer extra before comparing exact model counts": "tokextra",
    },
}
FIELD_VALUE_NAMES: dict[str, dict[str, str]] = {}
for field_name, values in FIELD_VALUE_CODES.items():
    decoded: dict[str, str] = {}
    for value, code in values.items():
        decoded.setdefault(code, value)
    FIELD_VALUE_NAMES[field_name] = decoded

PATH_PREFIX_NAMES = DEFAULT_ALIAS_TABLE.path_prefix_names()

_SPACE_RE = re.compile(r"\s+")
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*=")


@dataclass(frozen=True)
class AgentReply:
    """Compact representation of an agent work report."""

    status: str = "done"
    summary: str = ""
    files: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    version: str = REPLY_WIRE_VERSION
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_wire(self, aliases: AliasTable | dict[str, Any] | None = None) -> str:
        alias_table = coerce_alias_table(aliases)
        parts = [self.version]
        if self.status != "done" or _looks_like_status_token(self.summary):
            parts.append(_wire_atom(_encode_code(self.status, STATUS_CODES)))
        if self.summary:
            parts.append(_wire_value(self.summary))
        parts.extend(_field_parts("files", self.files, alias_table))
        parts.extend(_field_parts("verification", self.verification, alias_table))
        parts.extend(_field_parts("commands", self.commands, alias_table))
        parts.extend(_field_parts("risks", self.risks, alias_table))
        parts.extend(_field_parts("next_steps", self.next_steps, alias_table))
        parts.extend(_field_parts("warnings", self.warnings, alias_table))
        return " ".join(parts)

    def to_dict(self, aliases: AliasTable | dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "schema_version": "tokensquash.reply.v1",
            "wire_version": self.version,
            "status": self.status,
            "summary": self.summary,
            "files": list(self.files),
            "verification": list(self.verification),
            "commands": list(self.commands),
            "risks": list(self.risks),
            "next_steps": list(self.next_steps),
            "warnings": list(self.warnings),
            "wire": self.to_wire(aliases=aliases),
        }


def encode_reply(
    summary: str,
    *,
    status: str = "done",
    files: Iterable[str] = (),
    verification: Iterable[str] = (),
    commands: Iterable[str] = (),
    risks: Iterable[str] = (),
    next_steps: Iterable[str] = (),
    warnings: Iterable[str] = (),
) -> AgentReply:
    """Encode structured agent result fields into the compact reply protocol."""

    clean_summary = _clean_text(summary)
    clean_warnings = tuple(_clean_items(warnings))
    if not clean_summary:
        clean_warnings = _unique((*clean_warnings, "empty_summary"))

    return AgentReply(
        status=_normalize_status(status),
        summary=clean_summary,
        files=tuple(_clean_items(files)),
        verification=tuple(_clean_items(verification)),
        commands=tuple(_clean_items(commands)),
        risks=tuple(_clean_items(risks)),
        next_steps=tuple(_clean_items(next_steps)),
        warnings=clean_warnings,
    )


def parse_reply_wire(wire: str, aliases: AliasTable | dict[str, Any] | None = None) -> AgentReply:
    """Parse a TokenSquash reply wire string into an AgentReply."""

    alias_table = coerce_alias_table(aliases)
    text = wire.strip()
    if not text:
        raise ValueError("reply wire text must not be empty")
    if text.startswith("{"):
        payload = json.loads(text)
        return reply_from_dict(payload, aliases=alias_table)

    parts = shlex.split(text, posix=True)
    if not parts or parts[0] != REPLY_WIRE_VERSION:
        raise ValueError(f"reply wire text must start with {REPLY_WIRE_VERSION!r}")

    status = "done"
    index = 1
    if index < len(parts) and "=" not in parts[index]:
        candidate = _decode_code(parts[index], STATUS_NAMES)
        if candidate in STATUS_CODES:
            status = candidate
            index += 1

    summary_parts: list[str] = []
    values: dict[str, list[str]] = {
        "files": [],
        "verification": [],
        "commands": [],
        "risks": [],
        "next_steps": [],
        "warnings": [],
    }

    current_field: str | None = None
    for part in parts[index:]:
        if _KEY_RE.match(part):
            key, value = part.split("=", 1)
            field = _decode_code(key, FIELD_NAMES)
            if field in values:
                values[field].append(value)
                current_field = field
                continue
            current_field = None
        elif current_field and values[current_field]:
            values[current_field][-1] = _clean_text(f"{values[current_field][-1]} {part}")
            continue
        summary_parts.append(part)

    return AgentReply(
        status=_normalize_status(status),
        summary=_clean_text(" ".join(summary_parts)),
        files=_split_field_values("files", values["files"], alias_table),
        verification=_split_field_values("verification", values["verification"], alias_table),
        commands=_split_field_values("commands", values["commands"], alias_table),
        risks=_split_field_values("risks", values["risks"], alias_table),
        next_steps=_split_field_values("next_steps", values["next_steps"], alias_table),
        warnings=_split_field_values("warnings", values["warnings"], alias_table),
    )


def reply_from_dict(payload: dict[str, Any], aliases: AliasTable | dict[str, Any] | None = None) -> AgentReply:
    """Build an AgentReply from a JSON-like object."""

    alias_table = coerce_alias_table(aliases)
    if "wire" in payload and not payload.get("summary") and not payload.get("status"):
        return parse_reply_wire(str(payload["wire"]), aliases=alias_table)
    return encode_reply(
        str(payload.get("summary", "") or ""),
        status=str(payload.get("status", "done") or "done"),
        files=_coerce_items(payload.get("files", payload.get("f", []))),
        verification=_coerce_items(payload.get("verification", payload.get("verify", payload.get("v", [])))),
        commands=_coerce_items(payload.get("commands", payload.get("c", []))),
        risks=_coerce_items(payload.get("risks", payload.get("r", []))),
        next_steps=_coerce_items(payload.get("next_steps", payload.get("next", payload.get("n", [])))),
        warnings=_coerce_items(payload.get("warnings", payload.get("w", []))),
    )


def decode_reply(value: AgentReply | str | dict[str, Any], aliases: AliasTable | dict[str, Any] | None = None) -> str:
    """Decode a compact reply into readable result text."""

    if isinstance(value, AgentReply):
        reply = value
    elif isinstance(value, str):
        reply = parse_reply_wire(value, aliases=aliases)
    elif isinstance(value, dict):
        reply = reply_from_dict(value, aliases=aliases)
    else:
        raise TypeError("decode_reply expects AgentReply, wire string, or dict")

    lines = [f"Status: {_status_label(reply.status)}."]
    if reply.summary:
        lines.append(f"Summary: {reply.summary}.")
    if reply.files:
        lines.append("Files: " + ", ".join(reply.files) + ".")
    if reply.verification:
        lines.append("Verification: " + ", ".join(reply.verification) + ".")
    if reply.commands:
        lines.append("Commands: " + ", ".join(reply.commands) + ".")
    if reply.risks:
        lines.append("Risks: " + ", ".join(reply.risks) + ".")
    if reply.next_steps:
        lines.append("Next steps: " + ", ".join(reply.next_steps) + ".")
    if reply.warnings:
        lines.append("Codec warnings: " + ", ".join(reply.warnings) + ".")
    return " ".join(lines)


def _field_parts(name: str, values: tuple[str, ...], aliases: AliasTable) -> list[str]:
    key = FIELD_CODES[name]
    clean_values = [_encode_field_value(name, value, aliases) for value in values if value]
    if len(clean_values) > 1 and all("," not in value for value in clean_values):
        return [f"{key}={','.join(_wire_value(value) for value in clean_values)}"]
    return [f"{key}={_wire_value(value)}" for value in clean_values]


def _split_field_values(name: str, values: Iterable[str], aliases: AliasTable) -> tuple[str, ...]:
    items = []
    for value in values:
        items.extend(_decode_field_value(name, part.strip(), aliases) for part in value.split(","))
    return _unique(items)


def _encode_field_value(name: str, value: str, aliases: AliasTable) -> str:
    if name == "files":
        return _encode_path_alias(value, aliases)
    return FIELD_VALUE_CODES.get(name, {}).get(value.lower().strip(" .;:"), value)


def _decode_field_value(name: str, value: str, aliases: AliasTable) -> str:
    if name == "files":
        return _decode_path_alias(value, aliases)
    return FIELD_VALUE_NAMES.get(name, {}).get(value, value)


def _encode_path_alias(value: str, aliases: AliasTable) -> str:
    return aliases.encode_path(value)


def _decode_path_alias(value: str, aliases: AliasTable) -> str:
    return aliases.decode_path(value)


def _wire_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@()\\+=-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _wire_atom(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:/@()-]+", "_", value.strip()).strip("_") or "x"


def _encode_code(value: str, table: dict[str, str]) -> str:
    return table.get(value, value)


def _decode_code(value: str, table: dict[str, str]) -> str:
    return table.get(value, value)


def _looks_like_status_token(value: str) -> bool:
    text = _clean_text(value)
    return bool(text) and " " not in text and _decode_code(text, STATUS_NAMES) in STATUS_CODES


def _normalize_status(status: str) -> str:
    normalized = _decode_code(_wire_atom(status.lower()), STATUS_NAMES)
    if normalized not in STATUS_CODES:
        raise ValueError(f"reply status must be one of: {', '.join(STATUS_CODES)}")
    return normalized


def _status_label(status: str) -> str:
    return {
        "done": "done",
        "partial": "partially done",
        "blocked": "blocked",
        "failed": "failed",
    }.get(status, status)


def _clean_items(values: Iterable[str]) -> tuple[str, ...]:
    return _unique(_clean_text(str(value)) for value in values)


def _coerce_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    return [str(value)]


def _clean_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text.strip())


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
