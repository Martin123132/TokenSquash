"""TokenSquash compact intent codec."""

from .about import build_product_manifest, package_version
from .aliases import AliasTable, learn_reply_aliases, load_alias_table
from .codec import Intent, decode_intent, encode_intent, parse_wire
from .corpus import corpus_stats, load_prompt_records, redact_corpus, validate_corpus
from .demo import run_demo
from .doctor import run_doctor
from .metrics import benchmark_prompts, benchmark_replies, compare_benchmarks, count_tokens, load_reply_records
from .mining import mine_reply_patterns
from .reply import AgentReply, decode_reply, encode_reply, parse_reply_wire
from .turns import (
    append_turn_record,
    benchmark_turn_alias_impact,
    benchmark_turns,
    build_turn_certification_history,
    capture_turn_record,
    diagnose_turn_corpus,
    compare_turn_certifications,
    evaluate_turn_corpus,
    import_turn_corpus,
    learn_turn_aliases,
    load_turn_records,
    measure_turn_corpus,
    mine_turn_patterns,
    redact_turn_corpus,
    split_turn_corpus,
    turn_stats,
    validate_turn_corpus,
)
from .workspace import initialize_workspace

__version__ = package_version()

__all__ = [
    "AgentReply",
    "AliasTable",
    "Intent",
    "__version__",
    "append_turn_record",
    "benchmark_turn_alias_impact",
    "benchmark_prompts",
    "benchmark_replies",
    "benchmark_turns",
    "build_product_manifest",
    "build_turn_certification_history",
    "capture_turn_record",
    "compare_turn_certifications",
    "compare_benchmarks",
    "count_tokens",
    "corpus_stats",
    "decode_intent",
    "decode_reply",
    "diagnose_turn_corpus",
    "encode_intent",
    "encode_reply",
    "evaluate_turn_corpus",
    "import_turn_corpus",
    "initialize_workspace",
    "load_prompt_records",
    "load_alias_table",
    "load_reply_records",
    "load_turn_records",
    "measure_turn_corpus",
    "learn_reply_aliases",
    "learn_turn_aliases",
    "mine_reply_patterns",
    "mine_turn_patterns",
    "parse_wire",
    "parse_reply_wire",
    "redact_corpus",
    "redact_turn_corpus",
    "run_demo",
    "run_doctor",
    "split_turn_corpus",
    "turn_stats",
    "validate_corpus",
    "validate_turn_corpus",
]
