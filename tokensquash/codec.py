from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from typing import Any


WIRE_VERSION = "ts1"

OP_CODES = {
    "fix": "f",
    "add": "a",
    "refactor": "rf",
    "review": "rv",
    "docs": "d",
    "test": "t",
    "query": "q",
    "task": "x",
}
OP_NAMES = {value: key for key, value in OP_CODES.items()}

CONSTRAINT_CODES = {
    "small_diff": "sd",
    "no_refactor": "nr",
    "keep_api": "ka",
    "match_existing": "me",
    "no_deps": "nd",
}
CONSTRAINT_NAMES = {value: key for key, value in CONSTRAINT_CODES.items()}

VERIFY_CODES = {
    "tests": "t",
    "lint": "l",
    "typecheck": "tc",
    "build": "b",
}
VERIFY_NAMES = {value: key for key, value in VERIFY_CODES.items()}

RETURN_CODES = {
    "sum": "m",
    "files": "f",
    "diff": "d",
    "commands": "c",
    "risks": "r",
}
RETURN_NAMES = {value: key for key, value in RETURN_CODES.items()}

_PATH_RE = re.compile(
    r"(?<![\w.-])(?:[A-Za-z]:)?(?:[\w.-]+[\\/])+[\w.@()-]+|(?<![\w.-])[\w.-]+\.(?:py|js|ts|tsx|jsx|md|json|toml|yaml|yml|css|html|sql|go|rs|java|cs|cpp|c|h)(?![\w.-])",
    re.IGNORECASE,
)

_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Intent:
    """Compact representation of a human task request."""

    op: str = "task"
    query: str = ""
    constraints: tuple[str, ...] = ()
    verify: tuple[str, ...] = ()
    returns: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    version: str = WIRE_VERSION
    confidence: str = "medium"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_wire(self) -> str:
        parts = [self.version, _wire_atom(_encode_code(self.op, OP_CODES))]
        if self.query:
            parts.append(_wire_value(self.query))
        if self.constraints:
            parts.append(f"c={','.join(_wire_atom(_encode_code(item, CONSTRAINT_CODES)) for item in self.constraints)}")
        if self.verify:
            parts.append(f"v={','.join(_wire_atom(_encode_code(item, VERIFY_CODES)) for item in self.verify)}")
        if self.returns:
            parts.append(f"r={','.join(_wire_atom(_encode_code(item, RETURN_CODES)) for item in self.returns)}")
        if self.paths:
            parts.append(f"p={','.join(_wire_value(item) for item in self.paths)}")
        if self.confidence != "medium":
            parts.append(f"cf={_wire_atom(self.confidence)}")
        if self.warnings:
            parts.append(f"w={','.join(_wire_atom(item) for item in self.warnings)}")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "tokensquash.intent.v1",
            "wire_version": self.version,
            "op": self.op,
            "query": self.query,
            "constraints": list(self.constraints),
            "verify": list(self.verify),
            "returns": list(self.returns),
            "paths": list(self.paths),
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "wire": self.to_wire(),
        }


def encode_intent(text: str) -> Intent:
    """Encode human task text into the compact TokenSquash intent protocol."""

    original = _clean_text(text)
    if not original:
        return Intent(confidence="low", warnings=("empty",))

    lowered = original.lower()
    paths = tuple(_unique(_normalize_path(match.group(0)) for match in _PATH_RE.finditer(original)))
    constraints = _extract_constraints(lowered)
    verify = _extract_verification(lowered)
    returns = _extract_returns(lowered)
    op = _detect_operation(lowered)
    query = _build_query(original, paths, constraints, verify, returns)
    warnings: list[str] = []
    confidence = "medium"

    if not query:
        query = original
        confidence = "low"
        warnings.append("raw_query")
    elif len(query) > 180:
        query = query[:177].rstrip() + "..."
        confidence = "low"
        warnings.append("truncated_query")

    return Intent(
        op=op,
        query=query,
        constraints=tuple(constraints),
        verify=tuple(verify),
        returns=tuple(returns),
        paths=paths,
        confidence=confidence,
        warnings=tuple(warnings),
    )


def parse_wire(wire: str) -> Intent:
    """Parse a TokenSquash wire string into an Intent."""

    text = wire.strip()
    if not text:
        raise ValueError("wire text must not be empty")
    if text.startswith("{"):
        payload = json.loads(text)
        return _intent_from_dict(payload)

    parts = shlex.split(text, posix=True)
    if not parts or parts[0] != WIRE_VERSION:
        raise ValueError(f"wire text must start with {WIRE_VERSION!r}")

    values: dict[str, str] = {}
    positional: list[str] = []
    for part in parts[1:]:
        if "=" not in part:
            positional.append(part)
            continue
        key, value = part.split("=", 1)
        values[key] = value

    if positional:
        values.setdefault("op", positional[0])
    if len(positional) > 1:
        values.setdefault("q", " ".join(positional[1:]))

    return Intent(
        op=_decode_code(values.get("op", "task") or "task", OP_NAMES),
        query=values.get("q", ""),
        constraints=tuple(_decode_code(item, CONSTRAINT_NAMES) for item in _split_list(values.get("c", ""))),
        verify=tuple(_decode_code(item, VERIFY_NAMES) for item in _split_list(values.get("v", ""))),
        returns=tuple(_decode_code(item, RETURN_NAMES) for item in _split_list(values.get("r", ""))),
        paths=tuple(_split_list(values.get("p", ""))),
        confidence=values.get("cf", "medium") or "medium",
        warnings=tuple(_split_list(values.get("w", ""))),
    )


def decode_intent(value: Intent | str | dict[str, Any]) -> str:
    """Decode compact intent into readable task text."""

    if isinstance(value, Intent):
        intent = value
    elif isinstance(value, str):
        intent = parse_wire(value)
    elif isinstance(value, dict):
        intent = _intent_from_dict(value)
    else:
        raise TypeError("decode_intent expects Intent, wire string, or dict")

    lines = [f"Task: {_operation_label(intent.op)}."]
    if intent.query:
        lines.append(f"Focus: {intent.query}.")
    if intent.paths:
        lines.append("Paths: " + ", ".join(intent.paths) + ".")
    if intent.constraints:
        lines.append("Constraints: " + ", ".join(_constraint_label(item) for item in intent.constraints) + ".")
    if intent.verify:
        lines.append("Verify: " + ", ".join(_verify_label(item) for item in intent.verify) + ".")
    if intent.returns:
        lines.append("Return: " + ", ".join(_return_label(item) for item in intent.returns) + ".")
    if intent.confidence == "low":
        lines.append("Codec confidence: low; inspect before relying on this intent.")
    return " ".join(lines)


def _intent_from_dict(payload: dict[str, Any]) -> Intent:
    if "wire" in payload and not payload.get("op"):
        return parse_wire(str(payload["wire"]))
    return Intent(
        op=str(payload.get("op", "task") or "task"),
        query=str(payload.get("query", payload.get("q", "")) or ""),
        constraints=tuple(str(item) for item in payload.get("constraints", payload.get("c", [])) or []),
        verify=tuple(str(item) for item in payload.get("verify", payload.get("v", [])) or []),
        returns=tuple(str(item) for item in payload.get("returns", payload.get("r", [])) or []),
        paths=tuple(str(item) for item in payload.get("paths", payload.get("p", [])) or []),
        confidence=str(payload.get("confidence", "medium") or "medium"),
        warnings=tuple(str(item) for item in payload.get("warnings", payload.get("w", [])) or []),
    )


def _detect_operation(text: str) -> str:
    text = re.sub(r"\b(?:no|do not|don't) refactor(?:ing)?\b", " ", text)
    patterns = [
        ("fix", (r"\bfix\b", r"\bbug\b", r"\berror\b", r"\bfailing\b", r"\bbroken\b", r"\bregression\b")),
        ("add", (r"\badd\b", r"\bcreate\b", r"\bimplement\b", r"\bbuild\b", r"\bscaffold\b")),
        ("review", (r"\breview\b", r"\baudit\b", r"\binspect\b", r"\bcheck\b")),
        ("refactor", (r"\brefactor\b", r"\bclean up\b", r"\bsimplify\b")),
        ("docs", (r"\bdocs?\b", r"\breadme\b", r"\bdocument\b", r"\bwrite up\b")),
        ("test", (r"\brun tests?\b", r"\btest\b", r"\bunit tests?\b")),
        ("query", (r"\bwhere\b", r"\bfind\b", r"\bhow does\b", r"\bexplain\b")),
    ]
    for op, checks in patterns:
        if any(re.search(pattern, text) for pattern in checks):
            return op
    return "task"


def _extract_constraints(text: str) -> list[str]:
    matches = []
    checks = [
        ("small_diff", (r"small(?:est)? (?:safe )?(?:change|diff|patch)", r"minimal (?:change|diff|patch)", r"keep (?:the )?diff small")),
        ("no_refactor", (r"no refactor", r"do not refactor", r"don't refactor")),
        ("keep_api", (r"keep (?:the )?(?:public )?(?:api|interface)", r"do not break (?:the )?(?:public )?(?:api|interface)", r"backwards compatible")),
        ("match_existing", (r"match (?:the )?existing", r"follow (?:the )?existing", r"same style", r"existing pattern")),
        ("no_deps", (r"no new dependenc", r"without adding dependenc", r"avoid new dependenc")),
    ]
    for code, patterns in checks:
        if any(re.search(pattern, text) for pattern in patterns):
            matches.append(code)
    return _unique(matches)


def _extract_verification(text: str) -> list[str]:
    checks = [
        ("tests", (r"run (?:the )?tests?", r"\bunit tests?\b", r"\btest suite\b")),
        ("lint", (r"\blint\b", r"\blinter\b")),
        ("typecheck", (r"\btype ?check\b", r"\btyping\b", r"\btsc\b", r"\bmypy\b")),
        ("build", (r"\bbuild\b", r"\bcompile\b")),
    ]
    found = []
    for code, patterns in checks:
        if any(re.search(pattern, text) for pattern in patterns):
            found.append(code)
    return _unique(found)


def _extract_returns(text: str) -> list[str]:
    checks = [
        ("sum", (r"\bsummar", r"\bsummary\b", r"\btell me what changed\b")),
        ("files", (r"files? changed", r"changed files?", r"\bfile list\b")),
        ("diff", (r"\breturn (?:the )?diff\b", r"\bshow (?:the )?diff\b", r"\bpatch\b")),
        ("commands", (r"\bcommands?\b", r"\bwhat you ran\b")),
        ("risks", (r"\brisks?\b", r"\bcaveats?\b")),
    ]
    found = []
    for code, patterns in checks:
        if any(re.search(pattern, text) for pattern in patterns):
            found.append(code)
    if not found and any(word in text for word in ("reply", "return", "tell me")):
        found.append("sum")
    return _unique(found)


def _build_query(
    text: str,
    paths: tuple[str, ...],
    constraints: list[str],
    verify: list[str],
    returns: list[str],
) -> str:
    query = f" {text} "
    for path in paths:
        query = query.replace(path, " ")
        query = query.replace(path.replace("/", "\\"), " ")

    removable_patterns = [
        r"\bplease\b",
        r"\bcan you\b",
        r"\bcould you\b",
        r"\bi want you to\b",
        r"\bi need you to\b",
        r"\bgo ahead and\b",
        r"\bmake sure to\b",
        r"\btell me\b",
        r"\bgive me\b",
        r"\bwhen you are done\b",
        r"\band then\b",
        r"\bafterward\b",
        r"\bafterwards\b",
        r"\bthe repo\b",
        r"\bthis repo\b",
        r"\bthe repository\b",
        r"\bshort summary\b",
    ]
    if "small_diff" in constraints:
        removable_patterns.extend(
            [
                r"\bkeep (?:the )?diff small\b",
                r"\bsmall(?:est)? (?:safe )?(?:change|diff|patch)\b",
                r"\bminimal (?:change|diff|patch)\b",
            ]
        )
    if "no_refactor" in constraints:
        removable_patterns.extend([r"\bno refactor(?:ing)?\b", r"\bdo not refactor\b", r"\bdon't refactor\b"])
    if "keep_api" in constraints:
        removable_patterns.extend([r"\bkeep (?:the )?(?:api|interface)\b", r"\bbackwards compatible\b"])
    if "match_existing" in constraints:
        removable_patterns.extend([r"\bmatch (?:the )?existing(?: style| patterns?)?\b", r"\bfollow (?:the )?existing(?: style| patterns?)?\b"])
    if "no_deps" in constraints:
        removable_patterns.extend([r"\bavoid new dependenc(?:y|ies)\b", r"\bno new dependenc(?:y|ies)\b"])
    if verify:
        removable_patterns.extend(
            [
                r"\brun (?:the )?tests?\b",
                r"\bunit tests?\b",
                r"\btest suite\b",
                r"\blint(?:er)?\b",
                r"\btype ?check\b",
                r"\bcompile\b",
            ]
        )
    if returns:
        removable_patterns.extend(
            [
                r"\bsummar(?:y|ise|ize)(?: the)?(?: files? changed| changes?)?\b",
                r"\bfiles? changed\b",
                r"\bchanged files?\b",
                r"\btell me what changed\b",
                r"\bwhat you ran\b",
                r"\breturn risks?\b",
                r"\brisks? plus\b",
            ]
        )

    for pattern in removable_patterns:
        query = re.sub(pattern, " ", query, flags=re.IGNORECASE)

    query = re.sub(
        r"\b(?:and|then|also|just|the|a|an|to|for|of|in|is|me|which|return|give|short|run|suite|with|make|plus|keep)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"\b(?:fix|add|review|refactor|update|find|explain|inspect)\b", " ", query, flags=re.IGNORECASE)
    query = re.sub(r"[,.;:?!]", " ", query)
    return _clean_text(query)


def _wire_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@()\\-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _wire_atom(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:/@()-]+", "_", value.strip()).strip("_") or "x"


def _encode_code(value: str, table: dict[str, str]) -> str:
    return table.get(value, value)


def _decode_code(value: str, table: dict[str, str]) -> str:
    return table.get(value, value)


def _split_list(value: str) -> list[str]:
    if not value:
        return []
    return [item for item in (part.strip() for part in value.split(",")) if item]


def _clean_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text.strip())


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _unique(values: Any) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _operation_label(op: str) -> str:
    return {
        "fix": "fix a bug or failure",
        "add": "add or implement functionality",
        "refactor": "refactor code",
        "review": "review or inspect",
        "docs": "update documentation",
        "test": "run or improve tests",
        "query": "answer a repository question",
        "task": "complete the task",
    }.get(op, op)


def _constraint_label(code: str) -> str:
    return {
        "small_diff": "keep the change small",
        "no_refactor": "avoid refactoring",
        "keep_api": "preserve the public API",
        "match_existing": "match existing style",
        "no_deps": "avoid new dependencies",
    }.get(code, code)


def _verify_label(code: str) -> str:
    return {
        "tests": "run tests",
        "lint": "run lint",
        "typecheck": "run type checks",
        "build": "run the build",
    }.get(code, code)


def _return_label(code: str) -> str:
    return {
        "sum": "a concise summary",
        "files": "changed files",
        "diff": "diff or patch details",
        "commands": "commands run",
        "risks": "risks or caveats",
    }.get(code, code)
