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
    benchmark_prompts,
    compare_benchmarks,
    format_benchmark_compare_markdown,
    format_benchmark_markdown,
    load_prompts,
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
    except Exception as exc:
        print(f"tokensquash: error: {exc}", file=sys.stderr)
        return 2

    parser.error("unknown command")
    return 2
