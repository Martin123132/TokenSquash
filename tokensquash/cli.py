from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
from .reply import decode_reply, encode_reply, parse_reply_wire
from .turns import (
    benchmark_turns,
    format_turn_benchmark_markdown,
    format_turn_split_markdown,
    format_turn_stats_markdown,
    format_turn_validation_markdown,
    load_turn_records,
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
    encode.add_argument("--json", action="store_true", help="Print full intent JSON.")

    decode = sub.add_parser("decode", help="Decode TokenSquash wire text into readable task text.")
    decode.add_argument("wire", nargs="+", help="TokenSquash wire string or intent JSON.")
    decode.add_argument("--json", action="store_true", help="Print parsed intent JSON.")

    bench = sub.add_parser("bench", help="Benchmark a prompt corpus against TokenSquash encoding.")
    bench.add_argument("corpus", type=Path, help="JSONL or text corpus.")
    bench.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    bench.add_argument("--target", type=float, default=0.5, help="Target savings percentage.")
    bench.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
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
    turns_bench.add_argument("--out", type=Path, help="Write benchmark output to this file.")
    turns_bench.add_argument("--json", action="store_true", help="Print benchmark JSON.")

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
    reply_encode.add_argument("--json", action="store_true", help="Print full reply JSON.")

    reply_decode = reply_sub.add_parser("decode", help="Decode reply wire text into readable result text.")
    reply_decode.add_argument("wire", nargs="+", help="TokenSquash reply wire string or reply JSON.")
    reply_decode.add_argument("--json", action="store_true", help="Print parsed reply JSON.")

    reply_bench = reply_sub.add_parser("bench", help="Benchmark a structured reply corpus against reply wire format.")
    reply_bench.add_argument("corpus", type=Path, help="JSONL or JSON reply corpus.")
    reply_bench.add_argument("--counter", default="heuristic", help="heuristic, chars, char4, or tiktoken:<encoding>.")
    reply_bench.add_argument("--target", type=float, default=0.5, help="Target savings percentage.")
    reply_bench.add_argument("--no-adaptive", action="store_true", help="Always use wire format even when it is longer.")
    reply_bench.add_argument("--out", type=Path, help="Write benchmark output to this file.")
    reply_bench.add_argument("--json", action="store_true", help="Print benchmark JSON.")

    args = parser.parse_args(argv)

    try:
        if args.command == "encode":
            intent = encode_intent(" ".join(args.text))
            if args.json:
                print(json.dumps(intent.to_dict(), indent=2))
            else:
                print(intent.to_wire())
            return 0

        if args.command == "decode":
            intent = parse_wire(" ".join(args.wire))
            if args.json:
                print(json.dumps(intent.to_dict(), indent=2))
            else:
                print(decode_intent(intent))
            return 0

        if args.command == "bench":
            prompts = load_prompts(args.corpus)
            report = benchmark_prompts(
                prompts,
                counter=args.counter,
                target_savings_pct=args.target,
                adaptive=not args.no_adaptive,
                source=str(args.corpus),
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
                if args.json:
                    print(json.dumps(result.to_dict(), indent=2))
                else:
                    print(result.to_wire())
                return 0
            if args.reply_command == "decode":
                result = parse_reply_wire(" ".join(args.wire))
                if args.json:
                    print(json.dumps(result.to_dict(), indent=2))
                else:
                    print(decode_reply(result))
                return 0
            if args.reply_command == "bench":
                records = load_reply_records(args.corpus)
                report = benchmark_replies(
                    records,
                    counter=args.counter,
                    target_savings_pct=args.target,
                    adaptive=not args.no_adaptive,
                    source=str(args.corpus),
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
    except Exception as exc:
        print(f"tokensquash: error: {exc}", file=sys.stderr)
        return 2

    parser.error("unknown command")
    return 2
