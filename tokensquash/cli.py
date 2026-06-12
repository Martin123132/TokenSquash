from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .aliases import format_alias_report_markdown, learn_reply_aliases, load_alias_table, write_alias_table
from .codec import decode_intent, encode_intent, parse_wire
from .corpus import (
    corpus_stats,
    format_corpus_stats_markdown,
    format_validation_markdown,
    redact_corpus,
    validate_corpus,
)
from .demo import DEFAULT_DEMO_CORPUS, format_demo_markdown, run_demo, write_demo_outputs
from .doctor import format_doctor_markdown, run_doctor
from .metrics import (
    benchmark_replies,
    benchmark_prompts,
    compare_benchmarks,
    format_benchmark_compare_markdown,
    format_benchmark_markdown,
    format_reply_benchmark_markdown,
    load_reply_records,
    load_prompts,
)
from .mining import format_pattern_mine_markdown, mine_reply_patterns
from .reply import decode_reply, encode_reply, parse_reply_wire
from .sidecar import (
    DEFAULT_OLLAMA_ENDPOINT,
    DEFAULT_OLLAMA_MODEL,
    build_sidecar_request,
    certify_sidecar_report,
    compare_sidecar_evaluations,
    decode_semantic,
    evaluate_sidecar_turns,
    format_sidecar_certification_markdown,
    format_sidecar_decode_markdown,
    format_sidecar_evaluation_compare_markdown,
    format_sidecar_evaluation_markdown,
    format_sidecar_experiment_markdown,
    format_sidecar_gate_markdown,
    format_sidecar_request_markdown,
    format_sidecar_review_markdown,
    format_sidecar_roundtrip_markdown,
    format_sidecar_suggestions_markdown,
    format_sidecar_sweep_markdown,
    format_sidecar_translation_markdown,
    parse_semantic_json,
    gate_sidecar_report,
    review_sidecar_evaluation,
    roundtrip_with_ollama,
    suggest_sidecar_review,
    translate_with_ollama,
)
from .turns import (
    append_turn_record,
    benchmark_turn_alias_impact,
    benchmark_turns,
    capture_turn_record,
    compare_turn_reports,
    diagnose_turn_corpus,
    evaluate_turn_corpus,
    format_turn_alias_impact_markdown,
    format_turn_add_markdown,
    format_turn_benchmark_markdown,
    format_turn_capture_markdown,
    format_turn_diagnose_markdown,
    format_turn_report_markdown,
    format_turn_report_compare_markdown,
    format_turn_gate_markdown,
    format_turn_suggestions_markdown,
    format_turn_evaluate_markdown,
    format_turn_import_markdown,
    format_turn_measure_markdown,
    format_turn_split_markdown,
    format_turn_stats_markdown,
    format_turn_validation_markdown,
    gate_turn_report,
    report_turn_corpus,
    suggest_turn_improvements,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tokensquash",
        description="Compact AI-agent intent codec and benchmark tools.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    encode = sub.add_parser("encode", help="Encode human task text into TokenSquash wire format.")
    encode.add_argument("text", nargs="+", help="Human task text.")
    encode.add_argument("--aliases", type=Path, help="Session alias JSON for prompt path prefixes.")
    encode.add_argument("--json", action="store_true", help="Print full intent JSON.")

    decode = sub.add_parser("decode", help="Decode TokenSquash wire text into readable task text.")
    decode.add_argument("wire", nargs="+", help="TokenSquash wire string or intent JSON.")
    decode.add_argument("--aliases", type=Path, help="Session alias JSON for prompt path prefixes.")
    decode.add_argument("--json", action="store_true", help="Print parsed intent JSON.")

    bench = sub.add_parser("bench", help="Benchmark a prompt corpus against TokenSquash encoding.")
    bench.add_argument("corpus", type=Path, help="JSONL or text corpus.")
    bench.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    bench.add_argument("--target", type=float, default=0.5, help="Target savings percentage.")
    bench.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
    bench.add_argument("--aliases", type=Path, help="Session alias JSON for prompt path prefixes.")
    bench.add_argument("--out", type=Path, help="Write benchmark output to this file.")
    bench.add_argument("--json", action="store_true", help="Print benchmark JSON.")

    compare = sub.add_parser("compare", help="Compare two benchmark JSON reports.")
    compare.add_argument("base", type=Path)
    compare.add_argument("target", type=Path)
    compare.add_argument("--json", action="store_true", help="Print comparison JSON.")

    demo = sub.add_parser("demo", help="Run the public deterministic TokenSquash demo workflow.")
    demo.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_DEMO_CORPUS,
        help="Public turn corpus to use for the demo.",
    )
    demo.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    demo.add_argument("--target", type=float, default=0.0, help="Target savings percentage.")
    demo.add_argument("--out-dir", type=Path, help="Write demo.json, demo.md, and the turn evaluation pack.")
    demo.add_argument("--json", action="store_true", help="Print demo JSON.")

    doctor = sub.add_parser("doctor", help="Check the local TokenSquash install and workspace health.")
    doctor.add_argument("--check-ollama", action="store_true", help="Try to reach the local Ollama endpoint.")
    doctor.add_argument("--ollama-endpoint", default=DEFAULT_OLLAMA_ENDPOINT, help="Ollama endpoint.")
    doctor.add_argument("--ollama-timeout", type=float, default=2.0, help="Ollama check timeout in seconds.")
    doctor.add_argument("--json", action="store_true", help="Print doctor JSON.")

    sidecar = sub.add_parser("sidecar", help="Experimental local-AI semantic translator sidecar.")
    sidecar_sub = sidecar.add_subparsers(dest="sidecar_command", required=True)

    sidecar_translate = sidecar_sub.add_parser("translate", help="Translate English into compact semantic JSON with Ollama.")
    sidecar_translate.add_argument("mode", choices=("prompt", "reply"), help="Translate a user prompt or assistant reply.")
    sidecar_translate.add_argument("text", nargs="*", help="English text to translate.")
    sidecar_translate.add_argument("--text-file", type=Path, help="File containing English text to translate.")
    sidecar_translate.add_argument("--model", default=DEFAULT_OLLAMA_MODEL, help="Ollama model name.")
    sidecar_translate.add_argument("--endpoint", default=DEFAULT_OLLAMA_ENDPOINT, help="Ollama endpoint.")
    sidecar_translate.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    sidecar_translate.add_argument("--timeout", type=float, default=60.0, help="Ollama request timeout in seconds.")
    sidecar_translate.add_argument("--dry-run", action="store_true", help="Print the Ollama request without sending it.")
    sidecar_translate.add_argument("--out", type=Path, help="Write sidecar output to this file.")
    sidecar_translate.add_argument("--json", action="store_true", help="Print sidecar JSON.")

    sidecar_decode = sidecar_sub.add_parser("decode", help="Decode semantic JSON into readable English.")
    sidecar_decode.add_argument("mode", choices=("prompt", "reply"), help="Decode a user prompt or assistant reply payload.")
    sidecar_decode.add_argument("semantic", nargs="*", help="Semantic JSON payload to decode.")
    sidecar_decode.add_argument("--semantic-file", type=Path, help="File containing semantic JSON to decode.")
    sidecar_decode.add_argument("--json", action="store_true", help="Print decoded JSON.")

    sidecar_roundtrip = sidecar_sub.add_parser(
        "roundtrip",
        help="Translate and decode English to evaluate semantic round-trip quality.",
    )
    sidecar_roundtrip.add_argument("mode", choices=("prompt", "reply"), help="Translate a user prompt or assistant reply.")
    sidecar_roundtrip.add_argument("text", nargs="*", help="English text to translate and decode.")
    sidecar_roundtrip.add_argument("--text-file", type=Path, help="File containing English text to translate.")
    sidecar_roundtrip.add_argument("--model", default=DEFAULT_OLLAMA_MODEL, help="Ollama model name.")
    sidecar_roundtrip.add_argument("--endpoint", default=DEFAULT_OLLAMA_ENDPOINT, help="Ollama endpoint.")
    sidecar_roundtrip.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    sidecar_roundtrip.add_argument("--timeout", type=float, default=60.0, help="Ollama request timeout in seconds.")
    sidecar_roundtrip.add_argument("--out", type=Path, help="Write sidecar output to this file.")
    sidecar_roundtrip.add_argument("--json", action="store_true", help="Print sidecar JSON.")

    sidecar_evaluate = sidecar_sub.add_parser(
        "evaluate",
        help="Run sidecar round-trip evaluation over a turn corpus.",
    )
    sidecar_evaluate.add_argument(
        "corpus",
        nargs="?",
        type=Path,
        default=Path("private-turns/real.redacted-turns.jsonl"),
        help="Redacted turn corpus to evaluate.",
    )
    sidecar_evaluate.add_argument(
        "--mode",
        choices=("prompt", "reply", "both"),
        default="both",
        help="Evaluate prompts, replies, or both.",
    )
    sidecar_evaluate.add_argument("--limit", type=int, default=0, help="Maximum prompt/reply items to evaluate; 0 means all.")
    sidecar_evaluate.add_argument("--model", default=DEFAULT_OLLAMA_MODEL, help="Ollama model name.")
    sidecar_evaluate.add_argument("--endpoint", default=DEFAULT_OLLAMA_ENDPOINT, help="Ollama endpoint.")
    sidecar_evaluate.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    sidecar_evaluate.add_argument("--timeout", type=float, default=60.0, help="Ollama request timeout in seconds.")
    sidecar_evaluate.add_argument("--out-dir", type=Path, help="Write sidecar evaluation JSON files to this directory.")
    sidecar_evaluate.add_argument("--json", action="store_true", help="Print sidecar evaluation JSON.")

    sidecar_experiment = sidecar_sub.add_parser(
        "experiment",
        help="Run a named sidecar corpus experiment and write a repeatable evidence pack.",
    )
    sidecar_experiment.add_argument(
        "corpus",
        nargs="?",
        type=Path,
        default=Path("private-turns/real.redacted-turns.jsonl"),
        help="Redacted turn corpus to evaluate.",
    )
    sidecar_experiment.add_argument("--name", default="sidecar", help="Human-friendly experiment name.")
    sidecar_experiment.add_argument("--run-id", help="Stable run id for repeatable or scripted output paths.")
    sidecar_experiment.add_argument(
        "--out-root",
        type=Path,
        default=Path("private-turns/sidecar-experiments"),
        help="Directory that will contain this experiment run folder.",
    )
    sidecar_experiment.add_argument(
        "--mode",
        choices=("prompt", "reply", "both"),
        default="both",
        help="Evaluate prompts, replies, or both.",
    )
    sidecar_experiment.add_argument("--limit", type=int, default=0, help="Maximum prompt/reply items to evaluate; 0 means all.")
    sidecar_experiment.add_argument("--model", default=DEFAULT_OLLAMA_MODEL, help="Ollama model name.")
    sidecar_experiment.add_argument("--endpoint", default=DEFAULT_OLLAMA_ENDPOINT, help="Ollama endpoint.")
    sidecar_experiment.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    sidecar_experiment.add_argument("--timeout", type=float, default=60.0, help="Ollama request timeout in seconds.")
    sidecar_experiment.add_argument("--json", action="store_true", help="Print experiment JSON.")

    sidecar_sweep = sidecar_sub.add_parser(
        "sweep",
        help="Run a small matrix of sidecar corpus experiments and compare the results.",
    )
    sidecar_sweep.add_argument(
        "corpora",
        nargs="*",
        type=Path,
        help="Redacted turn corpora to evaluate; defaults to private-turns/real.redacted-turns.jsonl.",
    )
    sidecar_sweep.add_argument("--name", default="sidecar-sweep", help="Human-friendly sweep name.")
    sidecar_sweep.add_argument("--run-id", help="Stable sweep id for repeatable or scripted output paths.")
    sidecar_sweep.add_argument(
        "--out-root",
        type=Path,
        default=Path("private-turns/sidecar-sweeps"),
        help="Directory that will contain this sweep folder.",
    )
    sidecar_sweep.add_argument(
        "--mode",
        choices=("prompt", "reply", "both"),
        default="both",
        help="Evaluate prompts, replies, or both.",
    )
    sidecar_sweep.add_argument("--limit", type=int, default=0, help="Maximum prompt/reply items per run; 0 means all.")
    sidecar_sweep.add_argument(
        "--model",
        dest="models",
        action="append",
        help="Ollama model name. Repeat to evaluate multiple models.",
    )
    sidecar_sweep.add_argument("--endpoint", default=DEFAULT_OLLAMA_ENDPOINT, help="Ollama endpoint.")
    sidecar_sweep.add_argument(
        "--counter",
        dest="counters",
        action="append",
        help="heuristic, chars, char4, or tiktoken:<encoding>. Repeat to evaluate multiple counters.",
    )
    sidecar_sweep.add_argument("--timeout", type=float, default=60.0, help="Ollama request timeout in seconds.")
    sidecar_sweep.add_argument("--json", action="store_true", help="Print sweep JSON.")

    sidecar_review = sidecar_sub.add_parser(
        "review",
        help="Review a saved sidecar evaluation for meaning-risk signals.",
    )
    sidecar_review.add_argument("evaluation", type=Path, help="Saved sidecar evaluation JSON.")
    sidecar_review.add_argument(
        "--out-dir",
        type=Path,
        help="Write review.json and review.md to this directory; defaults to the evaluation directory.",
    )
    sidecar_review.add_argument(
        "--high-savings-pct",
        type=float,
        default=40.0,
        help="Saved percentage that makes a short decoded preview suspicious.",
    )
    sidecar_review.add_argument(
        "--short-ratio",
        type=float,
        default=0.45,
        help="Decoded/original preview length ratio below which high-savings rows are flagged.",
    )
    sidecar_review.add_argument("--json", action="store_true", help="Print review JSON.")

    sidecar_suggestions = sidecar_sub.add_parser(
        "suggestions",
        help="Turn a sidecar review report into prioritized tuning suggestions.",
    )
    sidecar_suggestions.add_argument("review", type=Path, help="Saved sidecar review JSON.")
    sidecar_suggestions.add_argument(
        "--out-dir",
        type=Path,
        help="Write suggestions.json and suggestions.md to this directory; defaults to the review directory.",
    )
    sidecar_suggestions.add_argument("--min-count", type=int, default=1, help="Minimum flag count to include.")
    sidecar_suggestions.add_argument("--max-examples", type=int, default=5, help="Maximum examples per suggestion.")
    sidecar_suggestions.add_argument("--json", action="store_true", help="Print suggestions JSON.")

    sidecar_gate = sidecar_sub.add_parser(
        "gate",
        help="Pass or fail a sidecar evaluation/review against quality thresholds.",
    )
    sidecar_gate.add_argument("report", type=Path, help="Saved sidecar evaluation.json or review.json.")
    sidecar_gate.add_argument("--min-saved-pct", type=float, default=0.5, help="Minimum saved percent required.")
    sidecar_gate.add_argument("--max-review-count", type=int, default=0, help="Maximum rows needing review.")
    sidecar_gate.add_argument("--max-high-risk", type=int, default=0, help="Maximum high-risk review rows.")
    sidecar_gate.add_argument("--max-medium-risk", type=int, default=0, help="Maximum medium-risk review rows.")
    sidecar_gate.add_argument("--max-loss-items", type=int, default=0, help="Maximum rows where semantic output is longer.")
    sidecar_gate.add_argument(
        "--high-savings-pct",
        type=float,
        default=40.0,
        help="Evaluation input only: saved percentage that makes short decoded previews suspicious.",
    )
    sidecar_gate.add_argument(
        "--short-ratio",
        type=float,
        default=0.45,
        help="Evaluation input only: decoded/original ratio below which high-savings rows are flagged.",
    )
    sidecar_gate.add_argument("--out", type=Path, help="Write gate output to this file.")
    sidecar_gate.add_argument("--json", action="store_true", help="Print gate JSON.")

    sidecar_certify = sidecar_sub.add_parser(
        "certify",
        help="Write review, gate, and suggestion artifacts for a saved sidecar report.",
    )
    sidecar_certify.add_argument("report", type=Path, help="Saved sidecar evaluation.json or review.json.")
    sidecar_certify.add_argument(
        "--out-dir",
        type=Path,
        help="Write certification artifacts here; defaults to a certification folder next to the input.",
    )
    sidecar_certify.add_argument("--min-saved-pct", type=float, default=0.5, help="Minimum saved percent required.")
    sidecar_certify.add_argument("--max-review-count", type=int, default=0, help="Maximum rows needing review.")
    sidecar_certify.add_argument("--max-high-risk", type=int, default=0, help="Maximum high-risk review rows.")
    sidecar_certify.add_argument("--max-medium-risk", type=int, default=0, help="Maximum medium-risk review rows.")
    sidecar_certify.add_argument(
        "--max-loss-items",
        type=int,
        default=0,
        help="Maximum rows where semantic output is longer.",
    )
    sidecar_certify.add_argument(
        "--high-savings-pct",
        type=float,
        default=40.0,
        help="Evaluation input only: saved percentage that makes short decoded previews suspicious.",
    )
    sidecar_certify.add_argument(
        "--short-ratio",
        type=float,
        default=0.45,
        help="Evaluation input only: decoded/original ratio below which high-savings rows are flagged.",
    )
    sidecar_certify.add_argument("--min-count", type=int, default=1, help="Minimum flag count for suggestions.")
    sidecar_certify.add_argument("--max-examples", type=int, default=5, help="Maximum examples per suggestion.")
    sidecar_certify.add_argument("--json", action="store_true", help="Print certification JSON.")

    sidecar_compare_evaluations = sidecar_sub.add_parser(
        "compare-evaluations",
        help="Compare two saved sidecar evaluation JSON reports.",
    )
    sidecar_compare_evaluations.add_argument("base", type=Path, help="Base sidecar evaluation JSON.")
    sidecar_compare_evaluations.add_argument("target", type=Path, help="Target sidecar evaluation JSON.")
    sidecar_compare_evaluations.add_argument("--out", type=Path, help="Write comparison output to this file.")
    sidecar_compare_evaluations.add_argument("--json", action="store_true", help="Print comparison JSON.")

    corpus = sub.add_parser("corpus", help="Inspect and prepare prompt corpora.")
    corpus_sub = corpus.add_subparsers(dest="corpus_command", required=True)

    corpus_stats_cmd = corpus_sub.add_parser("stats", help="Show corpus size and length stats.")
    corpus_stats_cmd.add_argument("corpus", type=Path)
    corpus_stats_cmd.add_argument("--json", action="store_true")

    corpus_validate = corpus_sub.add_parser("validate", help="Validate corpus shape and privacy findings.")
    corpus_validate.add_argument("corpus", type=Path)
    corpus_validate.add_argument("--json", action="store_true")

    corpus_redact = corpus_sub.add_parser("redact", help="Write a redacted copy of a corpus.")
    corpus_redact.add_argument("corpus", type=Path)
    corpus_redact.add_argument("--out", type=Path, required=True)
    corpus_redact.add_argument("--json", action="store_true")

    turns = sub.add_parser("turns", help="Inspect, redact, split, and benchmark prompt/reply turn corpora.")
    turns_sub = turns.add_subparsers(dest="turns_command", required=True)

    turns_stats_cmd = turns_sub.add_parser("stats", help="Show prompt/reply turn corpus stats.")
    turns_stats_cmd.add_argument("corpus", type=Path)
    turns_stats_cmd.add_argument("--json", action="store_true")

    turns_validate = turns_sub.add_parser("validate", help="Validate turn corpus shape and privacy findings.")
    turns_validate.add_argument("corpus", type=Path)
    turns_validate.add_argument("--json", action="store_true")

    turns_redact = turns_sub.add_parser("redact", help="Write a redacted copy of a turn corpus.")
    turns_redact.add_argument("corpus", type=Path)
    turns_redact.add_argument("--out", type=Path, required=True)
    turns_redact.add_argument("--json", action="store_true")

    turns_add = turns_sub.add_parser("add", help="Append one prompt/reply turn to a local JSONL corpus.")
    turns_add.add_argument("--out", type=Path, default=Path("private-turns/real.jsonl"))
    turns_add.add_argument("--id", dest="item_id", help="Optional stable turn id.")
    turns_add.add_argument("--prompt", help="Human prompt text.")
    turns_add.add_argument("--prompt-file", type=Path, help="File containing human prompt text.")
    turns_add.add_argument("--reply", help="Assistant reply text.")
    turns_add.add_argument("--reply-file", type=Path, help="File containing assistant reply text.")
    turns_add.add_argument("--status", choices=("done", "partial", "blocked", "failed"), help="Optional reply status.")
    turns_add.add_argument("--summary", help="Optional reply summary.")
    turns_add.add_argument("--changed-file", dest="files", action="append", default=[], help="Changed or relevant file.")
    turns_add.add_argument("--verify", dest="verification", action="append", default=[], help="Verification result.")
    turns_add.add_argument("--command", dest="commands", action="append", default=[], help="Command that was run.")
    turns_add.add_argument("--risk", dest="risks", action="append", default=[], help="Risk or caveat.")
    turns_add.add_argument("--next", dest="next_steps", action="append", default=[], help="Suggested next step.")
    turns_add.add_argument("--json", action="store_true")

    turns_capture = turns_sub.add_parser("capture", help="Capture one raw turn, regenerate redacted data, and optionally evaluate.")
    turns_capture.add_argument("--raw-out", type=Path, default=Path("private-turns/real.jsonl"))
    turns_capture.add_argument("--redacted-out", type=Path, default=Path("private-turns/real.redacted-turns.jsonl"))
    turns_capture.add_argument("--id", dest="item_id", help="Optional stable turn id.")
    turns_capture.add_argument("--prompt", help="Human prompt text.")
    turns_capture.add_argument("--prompt-file", type=Path, help="File containing human prompt text.")
    turns_capture.add_argument("--reply", help="Assistant reply text.")
    turns_capture.add_argument("--reply-file", type=Path, help="File containing assistant reply text.")
    turns_capture.add_argument(
        "--stdin",
        action="store_true",
        help="Read prompt and reply from stdin, separated by a line containing ---reply---.",
    )
    turns_capture.add_argument("--status", choices=("done", "partial", "blocked", "failed"), help="Optional reply status.")
    turns_capture.add_argument("--summary", help="Optional reply summary.")
    turns_capture.add_argument("--changed-file", dest="files", action="append", default=[], help="Changed or relevant file.")
    turns_capture.add_argument("--verify", dest="verification", action="append", default=[], help="Verification result.")
    turns_capture.add_argument("--command", dest="commands", action="append", default=[], help="Command that was run.")
    turns_capture.add_argument("--risk", dest="risks", action="append", default=[], help="Risk or caveat.")
    turns_capture.add_argument("--next", dest="next_steps", action="append", default=[], help="Suggested next step.")
    turns_capture.add_argument("--evaluate", action="store_true", help="Run a turn evaluation report pack after capture.")
    turns_capture.add_argument("--eval-out-dir", type=Path, default=Path("private-turns/eval-real"))
    turns_capture.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_capture.add_argument("--target", type=float, default=0.0, help="Target savings percentage.")
    turns_capture.add_argument("--json", action="store_true")

    turns_report = turns_sub.add_parser("report", help="Generate a compact turn-corpus feedback report.")
    turns_report.add_argument("corpus", nargs="?", type=Path, default=Path("private-turns/real.redacted-turns.jsonl"))
    turns_report.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_report.add_argument("--target", type=float, default=0.0, help="Target savings percentage.")
    turns_report.add_argument("--limit", type=int, default=3, help="Rows to show per top section.")
    turns_report.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
    turns_report.add_argument("--no-guess", action="store_true", help="Do not guess reply fields from raw reply text.")
    turns_report.add_argument("--min-count", type=int, default=2, help="Minimum alias/pattern occurrences before reporting.")
    turns_report.add_argument("--max-prefixes", type=int, default=8, help="Maximum custom path prefixes to show.")
    turns_report.add_argument("--max-fields", type=int, default=8, help="Maximum custom field values to show.")
    turns_report.add_argument("--min-saved-tokens", type=int, default=1, help="Minimum estimated token savings per alias.")
    turns_report.add_argument("--base-aliases", type=Path, help="Existing session alias JSON to extend.")
    turns_report.add_argument("--out", type=Path, help="Write report output to this file.")
    turns_report.add_argument("--json", action="store_true")

    turns_compare_reports = turns_sub.add_parser("compare-reports", help="Compare two saved turn report JSON files.")
    turns_compare_reports.add_argument("base", type=Path)
    turns_compare_reports.add_argument("target", type=Path)
    turns_compare_reports.add_argument("--out", type=Path, help="Write comparison output to this file.")
    turns_compare_reports.add_argument("--json", action="store_true", help="Print comparison JSON.")

    turns_gate = turns_sub.add_parser("gate", help="Pass or fail a turn report/evaluation against quality thresholds.")
    turns_gate.add_argument("report", type=Path, help="Saved turns report JSON or evaluation.json.")
    turns_gate.add_argument("--min-saved-pct", type=float, default=0.5, help="Minimum saved percent required.")
    turns_gate.add_argument("--max-privacy-findings", type=int, default=0, help="Maximum privacy findings allowed.")
    turns_gate.add_argument("--max-pass-through-rows", type=int, default=0, help="Maximum adaptive pass-through rows allowed.")
    turns_gate.add_argument("--max-raw-wire-loss-turns", type=int, default=0, help="Maximum rows where raw wire is longer.")
    turns_gate.add_argument("--out", type=Path, help="Write gate output to this file.")
    turns_gate.add_argument("--json", action="store_true", help="Print gate JSON.")

    turns_suggestions = turns_sub.add_parser("suggestions", help="Suggest next codec improvements from a turn report JSON.")
    turns_suggestions.add_argument("report", type=Path)
    turns_suggestions.add_argument("--limit", type=int, default=5, help="Maximum suggestions to show.")
    turns_suggestions.add_argument("--min-saved-tokens", type=int, default=1, help="Minimum estimated token saving to include.")
    turns_suggestions.add_argument("--out", type=Path, help="Write suggestions output to this file.")
    turns_suggestions.add_argument("--json", action="store_true", help="Print suggestions JSON.")

    turns_import = turns_sub.add_parser("import", help="Import a JSON/JSONL turn corpus into private raw/redacted storage.")
    turns_import.add_argument("corpus", type=Path)
    turns_import.add_argument("--raw-out", type=Path, default=Path("private-turns/real.jsonl"))
    turns_import.add_argument("--redacted-out", type=Path, default=Path("private-turns/real.redacted-turns.jsonl"))
    turns_import.add_argument("--evaluate", action="store_true", help="Run a turn evaluation report pack after import.")
    turns_import.add_argument("--eval-out-dir", type=Path, default=Path("private-turns/eval-real"))
    turns_import.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_import.add_argument("--target", type=float, default=0.0, help="Target savings percentage.")
    turns_import.add_argument("--json", action="store_true")

    turns_split = turns_sub.add_parser("split", help="Split turns into prompt and reply corpora.")
    turns_split.add_argument("corpus", type=Path)
    turns_split.add_argument("--prompts-out", type=Path, required=True)
    turns_split.add_argument("--replies-out", type=Path, required=True)
    turns_split.add_argument("--no-guess", action="store_true", help="Do not guess reply fields from raw reply text.")
    turns_split.add_argument("--json", action="store_true")

    turns_bench = turns_sub.add_parser("bench", help="Benchmark prompt and reply savings from one turn corpus.")
    turns_bench.add_argument("corpus", type=Path)
    turns_bench.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_bench.add_argument("--target", type=float, default=0.5, help="Target savings percentage.")
    turns_bench.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
    turns_bench.add_argument("--no-guess", action="store_true", help="Do not guess reply fields from raw reply text.")
    turns_bench.add_argument("--aliases", type=Path, help="Session alias JSON for prompt/reply aliases.")
    turns_bench.add_argument("--out", type=Path, help="Write benchmark output to this file.")
    turns_bench.add_argument("--json", action="store_true", help="Print benchmark JSON.")

    turns_measure = turns_sub.add_parser("measure", help="Validate, summarize, and benchmark a turn corpus.")
    turns_measure.add_argument("corpus", type=Path)
    turns_measure.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_measure.add_argument("--target", type=float, default=0.5, help="Target savings percentage.")
    turns_measure.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
    turns_measure.add_argument("--no-guess", action="store_true", help="Do not guess reply fields from raw reply text.")
    turns_measure.add_argument("--aliases", type=Path, help="Session alias JSON for prompt/reply aliases.")
    turns_measure.add_argument("--out", type=Path, help="Write measure output to this file.")
    turns_measure.add_argument("--json", action="store_true", help="Print measure JSON.")

    turns_evaluate = turns_sub.add_parser("evaluate", help="Run the full turn measurement and alias-impact workflow.")
    turns_evaluate.add_argument("corpus", type=Path)
    turns_evaluate.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_evaluate.add_argument("--target", type=float, default=0.0, help="Target savings percentage.")
    turns_evaluate.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
    turns_evaluate.add_argument("--no-guess", action="store_true", help="Do not guess reply fields from raw reply text.")
    turns_evaluate.add_argument("--min-count", type=int, default=2, help="Minimum alias/pattern occurrences before selection.")
    turns_evaluate.add_argument("--limit", type=int, default=10, help="Rows to show per diagnostic or mining section.")
    turns_evaluate.add_argument("--max-prefixes", type=int, default=8, help="Maximum custom path prefixes to select.")
    turns_evaluate.add_argument("--max-fields", type=int, default=8, help="Maximum custom field values to select.")
    turns_evaluate.add_argument("--min-saved-tokens", type=int, default=1, help="Minimum estimated token saving per alias.")
    turns_evaluate.add_argument("--base-aliases", type=Path, help="Existing session alias JSON to extend.")
    turns_evaluate.add_argument("--out-dir", type=Path, help="Write a JSON report pack to this directory.")
    turns_evaluate.add_argument("--json", action="store_true", help="Print evaluation JSON.")

    turns_diagnose = turns_sub.add_parser("diagnose", help="Show turn-level wins, losses, and pass-throughs.")
    turns_diagnose.add_argument("corpus", type=Path)
    turns_diagnose.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_diagnose.add_argument("--limit", type=int, default=5, help="Rows to show per diagnostic section.")
    turns_diagnose.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
    turns_diagnose.add_argument("--no-guess", action="store_true", help="Do not guess reply fields from raw reply text.")
    turns_diagnose.add_argument("--aliases", type=Path, help="Session alias JSON for prompt/reply aliases.")
    turns_diagnose.add_argument("--out", type=Path, help="Write diagnostic output to this file.")
    turns_diagnose.add_argument("--json", action="store_true", help="Print diagnostic JSON.")

    turns_mine = turns_sub.add_parser("mine", help="Mine repeated turn reply patterns worth compacting.")
    turns_mine.add_argument("corpus", type=Path)
    turns_mine.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_mine.add_argument("--min-count", type=int, default=2, help="Minimum occurrences before reporting a pattern.")
    turns_mine.add_argument("--limit", type=int, default=10, help="Rows to show per mining section.")
    turns_mine.add_argument("--no-guess", action="store_true", help="Do not guess reply fields from raw reply text.")
    turns_mine.add_argument("--aliases", type=Path, help="Session alias JSON for prompt/reply aliases.")
    turns_mine.add_argument("--out", type=Path, help="Write mining output to this file.")
    turns_mine.add_argument("--json", action="store_true", help="Print mining JSON.")

    turns_aliases = turns_sub.add_parser("aliases", help="Learn a session alias table from turn prompt paths and reply fields.")
    turns_aliases.add_argument("corpus", type=Path)
    turns_aliases.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_aliases.add_argument("--min-count", type=int, default=2, help="Minimum prefix occurrences before selection.")
    turns_aliases.add_argument("--max-prefixes", type=int, default=8, help="Maximum custom path prefixes to select.")
    turns_aliases.add_argument("--max-fields", type=int, default=8, help="Maximum custom field values to select.")
    turns_aliases.add_argument("--min-saved-tokens", type=int, default=1, help="Minimum estimated token saving per alias.")
    turns_aliases.add_argument("--no-guess", action="store_true", help="Do not guess reply fields from raw reply text.")
    turns_aliases.add_argument("--base-aliases", type=Path, help="Existing session alias JSON to extend.")
    turns_aliases.add_argument("--out", type=Path, help="Write learned alias JSON to this file.")
    turns_aliases.add_argument("--json", action="store_true", help="Print learned alias JSON.")

    turns_alias_impact = turns_sub.add_parser("alias-impact", help="Learn aliases and compare turn savings with and without them.")
    turns_alias_impact.add_argument("corpus", type=Path)
    turns_alias_impact.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    turns_alias_impact.add_argument("--target", type=float, default=0.5, help="Target savings percentage.")
    turns_alias_impact.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
    turns_alias_impact.add_argument("--no-guess", action="store_true", help="Do not guess reply fields from raw reply text.")
    turns_alias_impact.add_argument("--min-count", type=int, default=2, help="Minimum prefix occurrences before selection.")
    turns_alias_impact.add_argument("--max-prefixes", type=int, default=8, help="Maximum custom path prefixes to select.")
    turns_alias_impact.add_argument("--max-fields", type=int, default=8, help="Maximum custom field values to select.")
    turns_alias_impact.add_argument("--min-saved-tokens", type=int, default=1, help="Minimum estimated token saving per alias.")
    turns_alias_impact.add_argument("--base-aliases", type=Path, help="Existing session alias JSON to extend.")
    turns_alias_impact.add_argument("--out", type=Path, help="Write alias impact report to this file.")
    turns_alias_impact.add_argument("--json", action="store_true", help="Print alias impact JSON.")

    reply = sub.add_parser("reply", help="Encode and decode compact agent replies.")
    reply_sub = reply.add_subparsers(dest="reply_command", required=True)

    reply_encode = reply_sub.add_parser("encode", help="Encode structured result fields into reply wire format.")
    reply_encode.add_argument("--status", default="done", choices=("done", "partial", "blocked", "failed"))
    reply_encode.add_argument("--summary", required=True, help="Short human-readable result summary.")
    reply_encode.add_argument("--file", dest="files", action="append", default=[], help="Changed or relevant file.")
    reply_encode.add_argument("--verify", dest="verification", action="append", default=[], help="Verification result.")
    reply_encode.add_argument("--command", dest="commands", action="append", default=[], help="Command that was run.")
    reply_encode.add_argument("--risk", dest="risks", action="append", default=[], help="Risk or caveat.")
    reply_encode.add_argument("--next", dest="next_steps", action="append", default=[], help="Suggested next step.")
    reply_encode.add_argument("--aliases", type=Path, help="Session alias JSON for reply path prefixes and field values.")
    reply_encode.add_argument("--json", action="store_true", help="Print full reply JSON.")

    reply_decode = reply_sub.add_parser("decode", help="Decode reply wire text into readable result text.")
    reply_decode.add_argument("wire", nargs="+", help="TokenSquash reply wire string or reply JSON.")
    reply_decode.add_argument("--aliases", type=Path, help="Session alias JSON for reply path prefixes and field values.")
    reply_decode.add_argument("--json", action="store_true", help="Print parsed reply JSON.")

    reply_bench = reply_sub.add_parser("bench", help="Benchmark a structured reply corpus against reply wire format.")
    reply_bench.add_argument("corpus", type=Path, help="JSONL or JSON reply corpus.")
    reply_bench.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    reply_bench.add_argument("--target", type=float, default=0.5, help="Target savings percentage.")
    reply_bench.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
    reply_bench.add_argument("--aliases", type=Path, help="Session alias JSON for reply path prefixes and field values.")
    reply_bench.add_argument("--out", type=Path, help="Write benchmark output to this file.")
    reply_bench.add_argument("--json", action="store_true", help="Print benchmark JSON.")

    reply_mine = reply_sub.add_parser("mine", help="Mine repeated reply values worth compacting.")
    reply_mine.add_argument("corpus", type=Path, help="JSONL or JSON reply corpus.")
    reply_mine.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    reply_mine.add_argument("--min-count", type=int, default=2, help="Minimum occurrences before reporting a pattern.")
    reply_mine.add_argument("--limit", type=int, default=10, help="Rows to show per mining section.")
    reply_mine.add_argument("--aliases", type=Path, help="Session alias JSON for reply path prefixes and field values.")
    reply_mine.add_argument("--out", type=Path, help="Write mining output to this file.")
    reply_mine.add_argument("--json", action="store_true", help="Print mining JSON.")

    reply_aliases = reply_sub.add_parser("aliases", help="Learn a session alias table from repeated reply file paths and field values.")
    reply_aliases.add_argument("corpus", type=Path, help="JSONL or JSON reply corpus.")
    reply_aliases.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    reply_aliases.add_argument("--min-count", type=int, default=2, help="Minimum prefix occurrences before selection.")
    reply_aliases.add_argument("--max-prefixes", type=int, default=8, help="Maximum custom path prefixes to select.")
    reply_aliases.add_argument("--max-fields", type=int, default=8, help="Maximum custom field values to select.")
    reply_aliases.add_argument("--min-saved-tokens", type=int, default=1, help="Minimum estimated token saving per alias.")
    reply_aliases.add_argument("--base-aliases", type=Path, help="Existing session alias JSON to extend.")
    reply_aliases.add_argument("--out", type=Path, help="Write learned alias JSON to this file.")
    reply_aliases.add_argument("--json", action="store_true", help="Print learned alias JSON.")

    args = parser.parse_args(argv)

    try:
        if args.command == "encode":
            intent = encode_intent(" ".join(args.text))
            aliases = _load_optional_aliases(args.aliases)
            if args.json:
                print(json.dumps(intent.to_dict(aliases=aliases), indent=2))
            else:
                print(intent.to_wire(aliases=aliases))
            return 0

        if args.command == "decode":
            aliases = _load_optional_aliases(args.aliases)
            intent = parse_wire(" ".join(args.wire), aliases=aliases)
            if args.json:
                print(json.dumps(intent.to_dict(aliases=aliases), indent=2))
            else:
                print(decode_intent(intent, aliases=aliases))
            return 0

        if args.command == "bench":
            prompts = load_prompts(args.corpus)
            report = benchmark_prompts(
                prompts,
                counter=args.counter,
                target_savings_pct=args.target,
                adaptive=not args.no_adaptive,
                source=str(args.corpus),
                aliases=_load_optional_aliases(args.aliases),
            )
            output = (
                json.dumps(report, indent=2) + "\n"
                if args.json
                else format_benchmark_markdown(report)
            )
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(output, encoding="utf-8")
            if args.json:
                print(output, end="")
            else:
                print(output, end="")
            return 0 if report["status"] in {"pass", "empty"} else 1

        if args.command == "compare":
            report = compare_benchmarks(args.base, args.target)
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print(format_benchmark_compare_markdown(report), end="")
            return 0

        if args.command == "demo":
            report = run_demo(
                args.corpus,
                counter=args.counter,
                target_savings_pct=args.target,
                out_dir=args.out_dir,
            )
            if args.out_dir:
                write_demo_outputs(args.out_dir, report)
            output = json.dumps(report, indent=2) + "\n" if args.json else format_demo_markdown(report)
            print(output, end="")
            return 0 if report["status"] in {"pass", "warn"} else 1

        if args.command == "doctor":
            report = run_doctor(
                check_ollama=args.check_ollama,
                ollama_endpoint=args.ollama_endpoint,
                ollama_timeout=args.ollama_timeout,
            )
            output = json.dumps(report, indent=2) + "\n" if args.json else format_doctor_markdown(report)
            print(output, end="")
            return 0 if report["status"] in {"pass", "warn"} else 1

        if args.command == "sidecar":
            if args.sidecar_command == "translate":
                text = _read_text_argument(args.text, args.text_file, "sidecar text")
                if args.dry_run:
                    report = build_sidecar_request(
                        text,
                        mode=args.mode,
                        model=args.model,
                        endpoint=args.endpoint,
                    )
                    output = (
                        json.dumps(report, indent=2) + "\n"
                        if args.json
                        else format_sidecar_request_markdown(report)
                    )
                else:
                    report = translate_with_ollama(
                        text,
                        mode=args.mode,
                        model=args.model,
                        endpoint=args.endpoint,
                        counter=args.counter,
                        timeout_seconds=args.timeout,
                    )
                    output = (
                        json.dumps(report, indent=2) + "\n"
                        if args.json
                        else format_sidecar_translation_markdown(report)
                    )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0
            if args.sidecar_command == "decode":
                semantic_text = _read_json_argument(args.semantic, args.semantic_file, "semantic")
                semantic = parse_semantic_json(semantic_text)
                report = decode_semantic(semantic, mode=args.mode)
                output = json.dumps(report, indent=2) + "\n" if args.json else format_sidecar_decode_markdown(report)
                print(output, end="")
                return 0
            if args.sidecar_command == "roundtrip":
                text = _read_text_argument(args.text, args.text_file, "sidecar text")
                report = roundtrip_with_ollama(
                    text,
                    mode=args.mode,
                    model=args.model,
                    endpoint=args.endpoint,
                    counter=args.counter,
                    timeout_seconds=args.timeout,
                )
                output = json.dumps(report, indent=2) + "\n" if args.json else format_sidecar_roundtrip_markdown(report)
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0
            if args.sidecar_command == "evaluate":
                records = load_turn_records(args.corpus)
                report = evaluate_sidecar_turns(
                    records,
                    source=str(args.corpus),
                    part=args.mode,
                    limit=args.limit,
                    model=args.model,
                    endpoint=args.endpoint,
                    counter=args.counter,
                    timeout_seconds=args.timeout,
                )
                if args.out_dir:
                    _write_sidecar_evaluation_outputs(args.out_dir, report)
                output = json.dumps(report, indent=2) + "\n" if args.json else format_sidecar_evaluation_markdown(report)
                print(output, end="")
                return 0 if report["status"] in {"pass", "warn", "empty"} else 1
            if args.sidecar_command == "experiment":
                records = load_turn_records(args.corpus)
                evaluation = evaluate_sidecar_turns(
                    records,
                    source=str(args.corpus),
                    part=args.mode,
                    limit=args.limit,
                    model=args.model,
                    endpoint=args.endpoint,
                    counter=args.counter,
                    timeout_seconds=args.timeout,
                )
                run_id = args.run_id or _sidecar_experiment_run_id(args.name)
                output_dir = args.out_root / run_id
                report = _write_sidecar_experiment_outputs(
                    output_dir,
                    evaluation,
                    name=args.name,
                    run_id=run_id,
                    source=str(args.corpus),
                    mode=args.mode,
                    model=args.model,
                    endpoint=args.endpoint,
                    counter=args.counter,
                    limit=args.limit,
                )
                output = json.dumps(report, indent=2) + "\n" if args.json else format_sidecar_experiment_markdown(report)
                print(output, end="")
                return 0 if report["status"] in {"pass", "warn", "empty"} else 1
            if args.sidecar_command == "sweep":
                corpora = args.corpora or [Path("private-turns/real.redacted-turns.jsonl")]
                models = args.models or [DEFAULT_OLLAMA_MODEL]
                counters = args.counters or ["heuristic"]
                run_id = args.run_id or _sidecar_experiment_run_id(args.name)
                output_dir = args.out_root / run_id
                runs = []
                run_number = 0
                for corpus in corpora:
                    records = load_turn_records(corpus)
                    for model in models:
                        for counter in counters:
                            run_number += 1
                            evaluation = evaluate_sidecar_turns(
                                records,
                                source=str(corpus),
                                part=args.mode,
                                limit=args.limit,
                                model=model,
                                endpoint=args.endpoint,
                                counter=counter,
                                timeout_seconds=args.timeout,
                            )
                            child_run_id = _sidecar_sweep_child_run_id(run_number, corpus, model, counter)
                            child_name = f"{args.name}: {corpus.stem} / {model} / {counter}"
                            runs.append(
                                _write_sidecar_experiment_outputs(
                                    output_dir / "runs" / child_run_id,
                                    evaluation,
                                    name=child_name,
                                    run_id=child_run_id,
                                    source=str(corpus),
                                    mode=args.mode,
                                    model=model,
                                    endpoint=args.endpoint,
                                    counter=counter,
                                    limit=args.limit,
                                )
                            )
                report = _write_sidecar_sweep_outputs(
                    output_dir,
                    runs,
                    name=args.name,
                    run_id=run_id,
                    corpora=[str(corpus) for corpus in corpora],
                    models=models,
                    counters=counters,
                    mode=args.mode,
                    endpoint=args.endpoint,
                    limit=args.limit,
                )
                output = json.dumps(report, indent=2) + "\n" if args.json else format_sidecar_sweep_markdown(report)
                print(output, end="")
                return 0 if report["status"] in {"pass", "warn", "empty"} else 1
            if args.sidecar_command == "review":
                report = review_sidecar_evaluation(
                    args.evaluation,
                    high_savings_pct=args.high_savings_pct,
                    short_ratio=args.short_ratio,
                )
                _write_sidecar_review_outputs(args.out_dir or args.evaluation.parent, report)
                output = json.dumps(report, indent=2) + "\n" if args.json else format_sidecar_review_markdown(report)
                print(output, end="")
                return 0
            if args.sidecar_command == "suggestions":
                report = suggest_sidecar_review(
                    args.review,
                    min_count=args.min_count,
                    max_examples=args.max_examples,
                )
                _write_sidecar_suggestions_outputs(args.out_dir or args.review.parent, report)
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_sidecar_suggestions_markdown(report)
                )
                print(output, end="")
                return 0
            if args.sidecar_command == "gate":
                report = gate_sidecar_report(
                    args.report,
                    min_saved_pct=args.min_saved_pct,
                    max_review_count=args.max_review_count,
                    max_high_risk=args.max_high_risk,
                    max_medium_risk=args.max_medium_risk,
                    max_loss_items=args.max_loss_items,
                    high_savings_pct=args.high_savings_pct,
                    short_ratio=args.short_ratio,
                )
                output = json.dumps(report, indent=2) + "\n" if args.json else format_sidecar_gate_markdown(report)
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] == "pass" else 1
            if args.sidecar_command == "certify":
                report = certify_sidecar_report(
                    args.report,
                    min_saved_pct=args.min_saved_pct,
                    max_review_count=args.max_review_count,
                    max_high_risk=args.max_high_risk,
                    max_medium_risk=args.max_medium_risk,
                    max_loss_items=args.max_loss_items,
                    high_savings_pct=args.high_savings_pct,
                    short_ratio=args.short_ratio,
                    min_count=args.min_count,
                    max_examples=args.max_examples,
                )
                out_dir = args.out_dir or (args.report.parent / "certification")
                _write_sidecar_certification_outputs(out_dir, report)
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_sidecar_certification_markdown(report)
                )
                print(output, end="")
                return 0 if report["status"] == "pass" else 1
            if args.sidecar_command == "compare-evaluations":
                report = compare_sidecar_evaluations(args.base, args.target)
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_sidecar_evaluation_compare_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0

        if args.command == "corpus":
            if args.corpus_command == "stats":
                report = corpus_stats(args.corpus)
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(format_corpus_stats_markdown(report), end="")
                return 0
            if args.corpus_command == "validate":
                report = validate_corpus(args.corpus)
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(format_validation_markdown(report), end="")
                return 0 if report["status"] in {"pass", "warn"} else 1
            if args.corpus_command == "redact":
                report = redact_corpus(args.corpus, args.out)
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(f"wrote {report['output']} with {report['redaction_count']} redactions\n", end="")
                return 0

        if args.command == "turns":
            if args.turns_command == "stats":
                report = turn_stats(args.corpus)
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(format_turn_stats_markdown(report), end="")
                return 0
            if args.turns_command == "validate":
                report = validate_turn_corpus(args.corpus)
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(format_turn_validation_markdown(report), end="")
                return 0 if report["status"] in {"pass", "warn"} else 1
            if args.turns_command == "redact":
                report = redact_turn_corpus(args.corpus, args.out)
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(f"wrote {report['output']} with {report['redaction_count']} redactions\n", end="")
                return 0
            if args.turns_command == "add":
                prompt_text = args.prompt if args.prompt is not None else _read_required_text(args.prompt_file, "prompt")
                reply_text = args.reply if args.reply is not None else _read_required_text(args.reply_file, "reply")
                report = append_turn_record(
                    args.out,
                    prompt=prompt_text,
                    reply=reply_text,
                    item_id=args.item_id,
                    status=args.status,
                    summary=args.summary,
                    files=args.files,
                    verification=args.verification,
                    commands=args.commands,
                    risks=args.risks,
                    next_steps=args.next_steps,
                )
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(format_turn_add_markdown(report), end="")
                return 0
            if args.turns_command == "capture":
                if args.stdin:
                    prompt_text, reply_text = _read_capture_stdin(args)
                else:
                    prompt_text = args.prompt if args.prompt is not None else _read_required_text(args.prompt_file, "prompt")
                    reply_text = args.reply if args.reply is not None else _read_required_text(args.reply_file, "reply")
                report = capture_turn_record(
                    prompt=prompt_text,
                    reply=reply_text,
                    raw_output_path=args.raw_out,
                    redacted_output_path=args.redacted_out,
                    item_id=args.item_id,
                    status=args.status,
                    summary=args.summary,
                    files=args.files,
                    verification=args.verification,
                    commands=args.commands,
                    risks=args.risks,
                    next_steps=args.next_steps,
                    evaluate=args.evaluate,
                    evaluation_output_dir=args.eval_out_dir,
                    counter=args.counter,
                    target_savings_pct=args.target,
                )
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(format_turn_capture_markdown(report), end="")
                return 0 if report["status"] in {"written", "pass", "warn", "miss", "empty"} else 1
            if args.turns_command == "report":
                report = report_turn_corpus(
                    args.corpus,
                    counter=args.counter,
                    target_savings_pct=args.target,
                    limit=args.limit,
                    adaptive=not args.no_adaptive,
                    guess_reply_fields=not args.no_guess,
                    min_count=args.min_count,
                    max_path_prefixes=args.max_prefixes,
                    max_field_values=args.max_fields,
                    min_saved_tokens=args.min_saved_tokens,
                    base_aliases=_load_optional_aliases(args.base_aliases),
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_turn_report_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] in {"pass", "warn", "miss", "empty"} else 1
            if args.turns_command == "compare-reports":
                report = compare_turn_reports(args.base, args.target)
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_turn_report_compare_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0
            if args.turns_command == "gate":
                report = gate_turn_report(
                    args.report,
                    min_saved_pct=args.min_saved_pct,
                    max_privacy_findings=args.max_privacy_findings,
                    max_pass_through_rows=args.max_pass_through_rows,
                    max_raw_wire_loss_turns=args.max_raw_wire_loss_turns,
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_turn_gate_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] == "pass" else 1
            if args.turns_command == "suggestions":
                report = suggest_turn_improvements(
                    args.report,
                    limit=args.limit,
                    min_saved_tokens=args.min_saved_tokens,
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_turn_suggestions_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0
            if args.turns_command == "import":
                report = import_turn_corpus(
                    args.corpus,
                    raw_output_path=args.raw_out,
                    redacted_output_path=args.redacted_out,
                    evaluate=args.evaluate,
                    evaluation_output_dir=args.eval_out_dir,
                    counter=args.counter,
                    target_savings_pct=args.target,
                )
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(format_turn_import_markdown(report), end="")
                return 0 if report["status"] in {"written", "pass", "warn", "miss", "empty"} else 1
            if args.turns_command == "split":
                report = split_turn_corpus(
                    args.corpus,
                    args.prompts_out,
                    args.replies_out,
                    guess_reply_fields=not args.no_guess,
                )
                if args.json:
                    print(json.dumps(report, indent=2))
                else:
                    print(format_turn_split_markdown(report), end="")
                return 0
            if args.turns_command == "bench":
                records = load_turn_records(args.corpus)
                report = benchmark_turns(
                    records,
                    counter=args.counter,
                    target_savings_pct=args.target,
                    adaptive=not args.no_adaptive,
                    source=str(args.corpus),
                    guess_reply_fields=not args.no_guess,
                    aliases=_load_optional_aliases(args.aliases),
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_turn_benchmark_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] in {"pass", "empty"} else 1
            if args.turns_command == "measure":
                report = measure_turn_corpus(
                    args.corpus,
                    counter=args.counter,
                    target_savings_pct=args.target,
                    adaptive=not args.no_adaptive,
                    guess_reply_fields=not args.no_guess,
                    aliases=_load_optional_aliases(args.aliases),
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_turn_measure_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] in {"pass", "warn", "empty"} else 1
            if args.turns_command == "evaluate":
                report = evaluate_turn_corpus(
                    args.corpus,
                    counter=args.counter,
                    target_savings_pct=args.target,
                    adaptive=not args.no_adaptive,
                    guess_reply_fields=not args.no_guess,
                    min_count=args.min_count,
                    limit=args.limit,
                    max_path_prefixes=args.max_prefixes,
                    max_field_values=args.max_fields,
                    min_saved_tokens=args.min_saved_tokens,
                    base_aliases=_load_optional_aliases(args.base_aliases),
                    out_dir=args.out_dir,
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_turn_evaluate_markdown(report)
                )
                print(output, end="")
                return 0 if report["status"] in {"pass", "warn", "miss", "empty"} else 1
            if args.turns_command == "diagnose":
                report = diagnose_turn_corpus(
                    args.corpus,
                    counter=args.counter,
                    adaptive=not args.no_adaptive,
                    guess_reply_fields=not args.no_guess,
                    aliases=_load_optional_aliases(args.aliases),
                    limit=args.limit,
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_turn_diagnose_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] in {"pass", "warn", "empty"} else 1
            if args.turns_command == "mine":
                report = mine_turn_patterns(
                    args.corpus,
                    counter=args.counter,
                    min_count=args.min_count,
                    limit=args.limit,
                    guess_reply_fields=not args.no_guess,
                    aliases=_load_optional_aliases(args.aliases),
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_pattern_mine_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] in {"pass", "warn", "empty"} else 1
            if args.turns_command == "aliases":
                report = learn_turn_aliases(
                    args.corpus,
                    counter=args.counter,
                    min_count=args.min_count,
                    max_path_prefixes=args.max_prefixes,
                    max_field_values=args.max_fields,
                    min_saved_tokens=args.min_saved_tokens,
                    guess_reply_fields=not args.no_guess,
                    base_aliases=_load_optional_aliases(args.base_aliases),
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_alias_report_markdown(report)
                )
                if args.out:
                    write_alias_table(args.out, report)
                print(output, end="")
                return 0 if report["status"] in {"pass", "warn", "empty"} else 1
            if args.turns_command == "alias-impact":
                report = benchmark_turn_alias_impact(
                    args.corpus,
                    counter=args.counter,
                    target_savings_pct=args.target,
                    adaptive=not args.no_adaptive,
                    guess_reply_fields=not args.no_guess,
                    min_count=args.min_count,
                    max_path_prefixes=args.max_prefixes,
                    max_field_values=args.max_fields,
                    min_saved_tokens=args.min_saved_tokens,
                    base_aliases=_load_optional_aliases(args.base_aliases),
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_turn_alias_impact_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] in {"improved", "same", "warn", "empty"} else 1

        if args.command == "reply":
            if args.reply_command == "encode":
                result = encode_reply(
                    args.summary,
                    status=args.status,
                    files=args.files,
                    verification=args.verification,
                    commands=args.commands,
                    risks=args.risks,
                    next_steps=args.next_steps,
                )
                aliases = _load_optional_aliases(args.aliases)
                if args.json:
                    print(json.dumps(result.to_dict(aliases=aliases), indent=2))
                else:
                    print(result.to_wire(aliases=aliases))
                return 0
            if args.reply_command == "decode":
                aliases = _load_optional_aliases(args.aliases)
                result = parse_reply_wire(" ".join(args.wire), aliases=aliases)
                if args.json:
                    print(json.dumps(result.to_dict(aliases=aliases), indent=2))
                else:
                    print(decode_reply(result, aliases=aliases))
                return 0
            if args.reply_command == "bench":
                records = load_reply_records(args.corpus)
                report = benchmark_replies(
                    records,
                    counter=args.counter,
                    target_savings_pct=args.target,
                    adaptive=not args.no_adaptive,
                    source=str(args.corpus),
                    aliases=_load_optional_aliases(args.aliases),
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_reply_benchmark_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] in {"pass", "empty"} else 1
            if args.reply_command == "mine":
                records = load_reply_records(args.corpus)
                report = mine_reply_patterns(
                    records,
                    counter=args.counter,
                    min_count=args.min_count,
                    limit=args.limit,
                    source=str(args.corpus),
                    source_type="reply",
                    aliases=_load_optional_aliases(args.aliases),
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_pattern_mine_markdown(report)
                )
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(output, encoding="utf-8")
                print(output, end="")
                return 0 if report["status"] in {"pass", "empty"} else 1
            if args.reply_command == "aliases":
                records = load_reply_records(args.corpus)
                report = learn_reply_aliases(
                    records,
                    counter=args.counter,
                    min_count=args.min_count,
                    max_path_prefixes=args.max_prefixes,
                    max_field_values=args.max_fields,
                    min_saved_tokens=args.min_saved_tokens,
                    base_aliases=_load_optional_aliases(args.base_aliases),
                    source=str(args.corpus),
                )
                output = (
                    json.dumps(report, indent=2) + "\n"
                    if args.json
                    else format_alias_report_markdown(report)
                )
                if args.out:
                    write_alias_table(args.out, report)
                print(output, end="")
                return 0 if report["status"] in {"pass", "empty"} else 1
    except Exception as exc:
        print(f"tokensquash: error: {exc}", file=sys.stderr)
        return 2

    parser.error("unknown command")
    return 2


def _load_optional_aliases(path: Path | None):
    return load_alias_table(path) if path else None


def _read_required_text(path: Path | None, label: str) -> str:
    if path is None:
        raise ValueError(f"{label} must be provided with --{label} or --{label}-file")
    return path.read_text(encoding="utf-8-sig")


def _read_text_argument(parts: list[str], path: Path | None, label: str) -> str:
    if parts and path is not None:
        raise ValueError(f"{label} must be provided as inline text or --text-file, not both")
    if path is not None:
        text = path.read_text(encoding="utf-8-sig")
    else:
        text = " ".join(parts)
    if not text.strip():
        raise ValueError(f"{label} must not be empty")
    return text


def _read_json_argument(parts: list[str], path: Path | None, label: str) -> str:
    if parts and path is not None:
        raise ValueError(f"{label} must be provided as inline text or --{label}-file, not both")
    if path is not None:
        text = path.read_text(encoding="utf-8-sig")
    else:
        text = " ".join(parts)
    if not text.strip():
        raise ValueError(f"{label} must not be empty")
    return text


def _write_sidecar_evaluation_outputs(out_dir: Path, report: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    evaluation_path = out_dir / "evaluation.json"
    rows_path = out_dir / "rows.jsonl"
    report.setdefault("outputs", {})
    report["outputs"]["evaluation"] = str(evaluation_path)
    report["outputs"]["rows"] = str(rows_path)
    rows = report.get("rows", [])
    rows_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=True, separators=(",", ":")) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    evaluation_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_sidecar_review_outputs(out_dir: Path, report: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "review.json"
    markdown_path = out_dir / "review.md"
    report.setdefault("outputs", {})
    report["outputs"]["review"] = str(review_path)
    report["outputs"]["markdown"] = str(markdown_path)
    markdown_path.write_text(format_sidecar_review_markdown(report), encoding="utf-8")
    review_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_sidecar_suggestions_outputs(out_dir: Path, report: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    suggestions_path = out_dir / "suggestions.json"
    markdown_path = out_dir / "suggestions.md"
    report.setdefault("outputs", {})
    report["outputs"]["suggestions"] = str(suggestions_path)
    report["outputs"]["markdown"] = str(markdown_path)
    markdown_path.write_text(format_sidecar_suggestions_markdown(report), encoding="utf-8")
    suggestions_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_sidecar_certification_outputs(out_dir: Path, report: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = report.get("artifacts", {})
    review = artifacts.get("review", {})
    gate = artifacts.get("gate", {})
    suggestions = artifacts.get("suggestions", {})

    review_path = out_dir / "review.json"
    review_markdown_path = out_dir / "review.md"
    gate_path = out_dir / "gate.json"
    gate_markdown_path = out_dir / "gate.md"
    suggestions_path = out_dir / "suggestions.json"
    suggestions_markdown_path = out_dir / "suggestions.md"
    certification_path = out_dir / "certification.json"
    certification_markdown_path = out_dir / "certification.md"

    review.setdefault("outputs", {})
    review["outputs"]["review"] = str(review_path)
    review["outputs"]["markdown"] = str(review_markdown_path)
    gate.setdefault("outputs", {})
    gate["outputs"]["gate"] = str(gate_path)
    gate["outputs"]["markdown"] = str(gate_markdown_path)
    suggestions.setdefault("outputs", {})
    suggestions["outputs"]["suggestions"] = str(suggestions_path)
    suggestions["outputs"]["markdown"] = str(suggestions_markdown_path)
    report.setdefault("outputs", {})
    report["outputs"].update(
        {
            "certification": str(certification_path),
            "markdown": str(certification_markdown_path),
            "review": str(review_path),
            "review_markdown": str(review_markdown_path),
            "gate": str(gate_path),
            "gate_markdown": str(gate_markdown_path),
            "suggestions": str(suggestions_path),
            "suggestions_markdown": str(suggestions_markdown_path),
        }
    )

    review_markdown_path.write_text(format_sidecar_review_markdown(review), encoding="utf-8")
    review_path.write_text(json.dumps(review, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    gate_markdown_path.write_text(format_sidecar_gate_markdown(gate), encoding="utf-8")
    gate_path.write_text(json.dumps(gate, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    suggestions_markdown_path.write_text(format_sidecar_suggestions_markdown(suggestions), encoding="utf-8")
    suggestions_path.write_text(json.dumps(suggestions, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    certification_markdown_path.write_text(format_sidecar_certification_markdown(report), encoding="utf-8")
    certification_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_sidecar_experiment_outputs(
    out_dir: Path,
    evaluation: dict,
    *,
    name: str,
    run_id: str,
    source: str,
    mode: str,
    model: str,
    endpoint: str,
    counter: str,
    limit: int,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_sidecar_evaluation_outputs(out_dir, evaluation)
    outputs = dict(evaluation.get("outputs", {}))
    run_path = out_dir / "run.json"
    summary_path = out_dir / "summary.md"
    outputs["run"] = str(run_path)
    outputs["summary"] = str(summary_path)
    report = {
        "schema_version": "tokensquash.sidecar.experiment.v1",
        "status": evaluation.get("status"),
        "name": name,
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "mode": mode,
        "model": model,
        "endpoint": endpoint.rstrip("/"),
        "counter": counter,
        "limit": limit,
        "output_dir": str(out_dir),
        "summary": evaluation.get("summary", {}),
        "outputs": outputs,
    }
    summary_path.write_text(format_sidecar_experiment_markdown(report), encoding="utf-8")
    run_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return report


def _write_sidecar_sweep_outputs(
    out_dir: Path,
    runs: list[dict],
    *,
    name: str,
    run_id: str,
    corpora: list[str],
    models: list[str],
    counters: list[str],
    mode: str,
    endpoint: str,
    limit: int,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    comparisons = _write_sidecar_sweep_comparisons(out_dir, runs)
    sweep_path = out_dir / "sweep.json"
    summary_path = out_dir / "summary.md"
    outputs = {
        "sweep": str(sweep_path),
        "summary": str(summary_path),
    }
    report = {
        "schema_version": "tokensquash.sidecar.sweep.v1",
        "status": _sidecar_sweep_status(runs),
        "name": name,
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "corpora": corpora,
        "models": models,
        "counters": counters,
        "mode": mode,
        "endpoint": endpoint.rstrip("/"),
        "limit": limit,
        "output_dir": str(out_dir),
        "summary": _sidecar_sweep_summary(runs, comparisons),
        "runs": [_sidecar_sweep_run_brief(run) for run in runs],
        "comparisons": comparisons,
        "outputs": outputs,
    }
    summary_path.write_text(format_sidecar_sweep_markdown(report), encoding="utf-8")
    sweep_path.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return report


def _write_sidecar_sweep_comparisons(out_dir: Path, runs: list[dict]) -> list[dict]:
    if len(runs) < 2:
        return []
    comparison_dir = out_dir / "comparisons"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    base = runs[0]
    base_path = Path(base["outputs"]["evaluation"])
    comparisons = []
    for target in runs[1:]:
        target_path = Path(target["outputs"]["evaluation"])
        if _sidecar_sweep_runs_are_comparable(base, target):
            comparison = compare_sidecar_evaluations(base_path, target_path)
            comparison["base"]["run_id"] = base["run_id"]
            comparison["target"]["run_id"] = target["run_id"]
        else:
            comparison = _sidecar_sweep_skipped_comparison(base, target)
        stem = f"{base['run_id']}__vs__{target['run_id']}"
        json_path = comparison_dir / f"{stem}.json"
        markdown_path = comparison_dir / f"{stem}.md"
        comparison["outputs"] = {
            "json": str(json_path),
            "markdown": str(markdown_path),
        }
        json_path.write_text(json.dumps(comparison, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        markdown_path.write_text(format_sidecar_evaluation_compare_markdown(comparison), encoding="utf-8")
        comparisons.append(
            {
                "status": comparison.get("status"),
                "base": comparison.get("base", {}),
                "target": comparison.get("target", {}),
                "delta": comparison.get("delta", {}),
                "notes": comparison.get("notes", []),
                "outputs": comparison["outputs"],
            }
        )
    return comparisons


def _sidecar_sweep_summary(runs: list[dict], comparisons: list[dict]) -> dict:
    return {
        "run_count": len(runs),
        "comparison_count": len(comparisons),
        "pass_count": sum(1 for run in runs if run.get("status") == "pass"),
        "warn_count": sum(1 for run in runs if run.get("status") == "warn"),
        "fail_count": sum(1 for run in runs if run.get("status") == "fail"),
        "empty_count": sum(1 for run in runs if run.get("status") == "empty"),
        "skipped_comparison_count": sum(1 for comparison in comparisons if comparison.get("status") == "skipped"),
        "best_run": _sidecar_sweep_best_run(runs),
    }


def _sidecar_sweep_status(runs: list[dict]) -> str:
    statuses = {run.get("status") for run in runs}
    if not runs or statuses == {"empty"}:
        return "empty"
    if "fail" in statuses:
        return "fail"
    if statuses & {"warn", "empty"}:
        return "warn"
    return "pass"


def _sidecar_sweep_best_run(runs: list[dict]) -> dict | None:
    if not runs:
        return None
    best = max(
        runs,
        key=lambda run: (
            run.get("summary", {}).get("saved_tokens", 0),
            run.get("summary", {}).get("saved_pct", 0.0),
        ),
    )
    return _sidecar_sweep_run_brief(best)


def _sidecar_sweep_run_brief(run: dict) -> dict:
    return {
        "status": run.get("status"),
        "name": run.get("name"),
        "run_id": run.get("run_id"),
        "source": run.get("source"),
        "mode": run.get("mode"),
        "model": run.get("model"),
        "counter": run.get("counter"),
        "output_dir": run.get("output_dir"),
        "summary": run.get("summary", {}),
        "outputs": run.get("outputs", {}),
    }


def _sidecar_sweep_runs_are_comparable(base: dict, target: dict) -> bool:
    return (
        base.get("source") == target.get("source")
        and base.get("mode") == target.get("mode")
        and base.get("counter") == target.get("counter")
    )


def _sidecar_sweep_skipped_comparison(base: dict, target: dict) -> dict:
    return {
        "schema_version": "tokensquash.sidecar.sweep.compare.v1",
        "status": "skipped",
        "base": _sidecar_sweep_comparison_brief(base),
        "target": _sidecar_sweep_comparison_brief(target),
        "delta": {
            "saved_tokens": 0,
            "saved_pct": 0.0,
            "warning_count": 0,
            "failure_count": 0,
        },
        "notes": [
            "Comparison skipped because source, mode, or counter differs; token deltas would not be like-for-like.",
        ],
    }


def _sidecar_sweep_comparison_brief(run: dict) -> dict:
    return {
        "path": run.get("outputs", {}).get("evaluation"),
        "status": run.get("status"),
        "source": run.get("source"),
        "mode": run.get("mode"),
        "model": run.get("model"),
        "counter": run.get("counter"),
        "summary": run.get("summary", {}),
        "run_id": run.get("run_id"),
    }


def _sidecar_sweep_child_run_id(index: int, corpus: Path, model: str, counter: str) -> str:
    pieces = [
        f"{index:03d}",
        _slugify_sidecar_experiment_name(corpus.stem),
        _slugify_sidecar_experiment_name(model),
        _slugify_sidecar_experiment_name(counter),
    ]
    return "-".join(piece for piece in pieces if piece)


def _sidecar_experiment_run_id(name: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    slug = _slugify_sidecar_experiment_name(name)
    return f"{stamp}-{slug}" if slug else stamp


def _slugify_sidecar_experiment_name(name: str) -> str:
    pieces = []
    previous_dash = False
    for char in name.strip().lower():
        if char.isalnum():
            pieces.append(char)
            previous_dash = False
        elif char in {" ", "-", "_"} and not previous_dash:
            pieces.append("-")
            previous_dash = True
    return "".join(pieces).strip("-")


def _read_capture_stdin(args: argparse.Namespace) -> tuple[str, str]:
    if args.prompt is not None or args.prompt_file is not None or args.reply is not None or args.reply_file is not None:
        raise ValueError("--stdin cannot be combined with --prompt, --prompt-file, --reply, or --reply-file")

    text = sys.stdin.read()
    delimiter = None
    for candidate in ("\n---reply---\n", "\n---REPLY---\n"):
        if candidate in text:
            delimiter = candidate
            break
    if delimiter is None:
        raise ValueError("--stdin input must contain a line with ---reply--- between prompt and reply")

    prompt, reply = text.split(delimiter, 1)
    return prompt, reply
