from __future__ import annotations

import argparse
import json
import sys
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
from .turns import (
    append_turn_record,
    benchmark_turn_alias_impact,
    benchmark_turns,
    diagnose_turn_corpus,
    evaluate_turn_corpus,
    format_turn_alias_impact_markdown,
    format_turn_add_markdown,
    format_turn_benchmark_markdown,
    format_turn_diagnose_markdown,
    format_turn_evaluate_markdown,
    format_turn_measure_markdown,
    format_turn_split_markdown,
    format_turn_stats_markdown,
    format_turn_validation_markdown,
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
