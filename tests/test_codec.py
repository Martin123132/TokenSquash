from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from tokensquash.codec import decode_intent, encode_intent, parse_wire
from tokensquash.corpus import corpus_stats, redact_corpus, validate_corpus
from tokensquash.metrics import benchmark_prompts, compare_benchmarks, count_tokens, load_prompts


class TokenSquashCodecTests(unittest.TestCase):
    def test_encode_common_fix_request(self) -> None:
        intent = encode_intent(
            "Please fix the login bug, keep the diff small, run tests, "
            "and summarize the files changed."
        )

        self.assertEqual(intent.op, "fix")
        self.assertEqual(intent.constraints, ("small_diff",))
        self.assertEqual(intent.verify, ("tests",))
        self.assertEqual(intent.returns, ("sum", "files"))
        self.assertIn("login", intent.query)
        self.assertLess(count_tokens(intent.to_wire()), count_tokens("Please fix the login bug, keep the diff small, run tests, and summarize the files changed."))

    def test_wire_round_trip(self) -> None:
        intent = encode_intent(
            "Add a dark mode toggle in src/App.tsx, match existing style, "
            "run tests, and summarize files changed."
        )
        wire = intent.to_wire()
        parsed = parse_wire(wire)

        self.assertEqual(parsed.op, "add")
        self.assertIn("match_existing", parsed.constraints)
        self.assertIn("src/App.tsx", parsed.paths)
        self.assertEqual(parsed.to_wire(), wire)

    def test_decode_is_human_readable(self) -> None:
        text = decode_intent('ts1 f "login bug" c=sd v=t r=m,f')

        self.assertIn("fix", text)
        self.assertIn("login bug", text)
        self.assertIn("keep the change small", text)
        self.assertIn("run tests", text)

    def test_decode_accepts_unquoted_query_words(self) -> None:
        parsed = parse_wire("ts1 f login bug c=sd")

        self.assertEqual(parsed.op, "fix")
        self.assertEqual(parsed.query, "login bug")
        self.assertEqual(parsed.constraints, ("small_diff",))

    def test_benchmark_reports_savings(self) -> None:
        prompts = [
            "Please fix the login bug, keep the diff small, run tests, and summarize the files changed.",
            "Can you review the checkout flow, do not refactor unrelated code, and return risks plus files changed?",
        ]

        report = benchmark_prompts(prompts, target_savings_pct=0.5)

        self.assertEqual(report["schema_version"], "tokensquash.bench.v1")
        self.assertEqual(report["status"], "pass")
        self.assertGreater(report["summary"]["saved_tokens"], 0)
        self.assertGreater(report["summary"]["saved_pct"], 0.5)
        self.assertIn("wire_saved_pct", report["summary"])

    def test_benchmark_adaptive_passthrough(self) -> None:
        report = benchmark_prompts(["ok"], target_savings_pct=0.0)

        self.assertEqual(report["rows"][0]["mode"], "passthrough")
        self.assertEqual(report["summary"]["passthroughs"], 1)
        self.assertEqual(report["summary"]["saved_tokens"], 0)

    def test_load_jsonl_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompts.jsonl"
            path.write_text('{"text":"one"}\n{"prompt":"two"}\n', encoding="utf-8")

            self.assertEqual(load_prompts(path), ["one", "two"])

    def test_corpus_stats_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompts.jsonl"
            path.write_text(
                '{"id":"a","text":"fix login"}\n'
                '{"id":"b","prompt":"email me at dev@example.com"}\n',
                encoding="utf-8",
            )

            stats = corpus_stats(path)
            validation = validate_corpus(path)

            self.assertEqual(stats["summary"]["prompt_count"], 2)
            self.assertEqual(validation["status"], "warn")
            self.assertEqual(validation["summary"]["privacy_finding_count"], 1)
            self.assertEqual(validation["privacy"]["findings"][0]["code"], "email")

    def test_validate_reports_line_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            path.write_text('{"id":"a","text":"ok"}\n{"id":"b"}\n', encoding="utf-8")

            report = validate_corpus(path)

            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["errors"][0]["line"], 2)
            self.assertEqual(report["errors"][0]["code"], "missing_prompt")

    def test_redact_corpus_writes_safe_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "prompts.jsonl"
            out = Path(tmp) / "redacted.jsonl"
            src.write_text(
                '{"text":"contact dev@example.com with api_key=secret123"}\n',
                encoding="utf-8",
            )

            report = redact_corpus(src, out)
            payload = json.loads(out.read_text(encoding="utf-8"))

            self.assertEqual(report["status"], "written")
            self.assertGreaterEqual(report["redaction_count"], 2)
            self.assertIn("[REDACTED_EMAIL]", payload["text"])
            self.assertIn("[REDACTED_SECRET]", payload["text"])

    def test_compare_benchmarks_reports_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.json"
            target = Path(tmp) / "target.json"
            base.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.bench.v1",
                        "counter": "heuristic",
                        "adaptive": True,
                        "summary": {
                            "saved_pct": 1.0,
                            "wire_saved_pct": 0.5,
                            "saved_tokens": 10,
                            "passthroughs": 2,
                            "prompt_count": 5,
                        },
                    }
                ),
                encoding="utf-8",
            )
            target.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.bench.v1",
                        "counter": "heuristic",
                        "adaptive": True,
                        "summary": {
                            "saved_pct": 2.5,
                            "wire_saved_pct": 1.5,
                            "saved_tokens": 15,
                            "passthroughs": 3,
                            "prompt_count": 5,
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = compare_benchmarks(base, target)

            self.assertEqual(report["status"], "improved")
            self.assertEqual(report["delta"]["saved_pct"], 1.5)
            self.assertEqual(report["delta"]["saved_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
