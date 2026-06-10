"""TokenSquash compact intent codec."""

from .codec import Intent, decode_intent, encode_intent, parse_wire
from .metrics import benchmark_prompts, count_tokens

__all__ = [
    "Intent",
    "benchmark_prompts",
    "count_tokens",
    "decode_intent",
    "encode_intent",
    "parse_wire",
]
