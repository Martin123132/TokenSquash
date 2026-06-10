from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


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

    def to_wire(self) -> str:
        parts = [self.version, _wire_atom(_encode_code(self.status, STATUS_CODES))]
        if self.summary:
            parts.append(_wire_value(self.summary))
        parts.extend(_repeated_field("files", self.files))
        parts.extend(_repeated_field("verification", self.verification))
        parts.extend(_repeated_field("commands", self.commands))
        parts.extend(_repeated_field("risks", self.risks))
        parts.extend(_repeated_field("next_steps", self.next_steps))
        parts.extend(_repeated_field("warnings", self.warnings))
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
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
            "wire": self.to_wire(),
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


def parse_reply_wire(wire: str) -> AgentReply:
    """Parse a TokenSquash reply wire string into an AgentReply."""

    text = wire.strip()
    if not text:
        raise ValueError("reply wire text must not be empty")
    if text.startswith("{"):
        payload = json.loads(text)
        return reply_from_dict(payload)

    parts = shlex.split(text, posix=True)
    if not parts or parts[0] != REPLY_WIRE_VERSION:
        raise ValueError(f"reply wire text must start with {REPLY_WIRE_VERSION!r}")

    status = "done"
    index = 1
    if index < len(parts) and "=" not in parts[index]:
        status = _decode_code(parts[index], STATUS_NAMES)
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
        files=tuple(_unique(values["files"])),
        verification=tuple(_unique(values["verification"])),
        commands=tuple(_unique(values["commands"])),
        risks=tuple(_unique(values["risks"])),
        next_steps=tuple(_unique(values["next_steps"])),
        warnings=tuple(_unique(values["warnings"])),
    )


def reply_from_dict(payload: dict[str, Any]) -> AgentReply:
    """Build an AgentReply from a JSON-like object."""

    if "wire" in payload and not payload.get("summary") and not payload.get("status"):
        return parse_reply_wire(str(payload["wire"]))
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


def decode_reply(value: AgentReply | str | dict[str, Any]) -> str:
    """Decode a compact reply into readable result text."""

    if isinstance(value, AgentReply):
        reply = value
    elif isinstance(value, str):
        reply = parse_reply_wire(value)
    elif isinstance(value, dict):
        reply = reply_from_dict(value)
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


def _repeated_field(name: str, values: tuple[str, ...]) -> list[str]:
    key = FIELD_CODES[name]
    return [f"{key}={_wire_value(value)}" for value in values if value]


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
