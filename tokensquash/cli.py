from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .codec import decode_intent, encode_intent, parse_wire
from .metrics import benchmark_prompts, format_benchmark_markdown, load_prompts


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
    bench.add_argument("--json", action="store_true", help="Print benchmark JSON.")

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
            )
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print(format_benchmark_markdown(report), end="")
            return 0 if report["status"] in {"pass", "empty"} else 1
    except Exception as exc:
        print(f"tokensquash: error: {exc}", file=sys.stderr)
        return 2

    parser.error("unknown command")
    return 2
