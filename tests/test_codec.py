from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from tokensquash.codec import decode_intent, encode_intent, parse_wire
from tokensquash.corpus import corpus_stats, redact_corpus, validate_corpus
from tokensquash.metrics import (
    benchmark_prompts,
    benchmark_replies,
    compare_benchmarks,
    count_tokens,
    load_prompts,
    load_reply_records,
)
from tokensquash.reply import decode_reply, encode_reply, parse_reply_wire
from tokensquash.turns import (
    benchmark_turns,
    load_turn_records,
    redact_turn_corpus,
    split_turn_corpus,
    validate_turn_corpus,
)


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

    def test_reply_benchmark_reports_savings(self) -> None:
        records = [
            {
                "status": "done",
                "summary": "added compact reply codec",
                "files": ["tokensquash/reply.py", "tokensquash/cli.py"],
                "verification": ["unit tests pass"],
                "commands": ["python -m unittest discover -s tests"],
                "risks": ["none"],
                "text": (
                    "Done. I added the compact reply codec in tokensquash/reply.py and wired it into "
                    "tokensquash/cli.py. Verification passed with python -m unittest discover -s tests. "
                    "Risks: none."
                ),
            }
        ]

        report = benchmark_replies(records, target_savings_pct=0.5)

        self.assertEqual(report["schema_version"], "tokensquash.reply.bench.v1")
        self.assertEqual(report["status"], "pass")
        self.assertGreater(report["summary"]["saved_tokens"], 0)
        self.assertGreater(report["summary"]["saved_pct"], 0.5)

    def test_load_jsonl_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompts.jsonl"
            path.write_text('{"text":"one"}\n{"prompt":"two"}\n', encoding="utf-8")

            self.assertEqual(load_prompts(path), ["one", "two"])

    def test_load_jsonl_reply_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "replies.jsonl"
            path.write_text(
                '{"status":"done","summary":"added tests","text":"Done. I added tests and verified them."}\n',
                encoding="utf-8",
            )

            records = load_reply_records(path)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["summary"], "added tests")

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

    def test_compare_accepts_reply_benchmarks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base-replies.json"
            target = Path(tmp) / "target-replies.json"
            base.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.reply.bench.v1",
                        "counter": "heuristic",
                        "adaptive": True,
                        "summary": {
                            "reply_count": 2,
                            "saved_pct": 1.0,
                            "wire_saved_pct": -2.0,
                            "saved_tokens": 3,
                            "passthroughs": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )
            target.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.reply.bench.v1",
                        "counter": "heuristic",
                        "adaptive": True,
                        "summary": {
                            "reply_count": 2,
                            "saved_pct": 1.5,
                            "wire_saved_pct": -1.0,
                            "saved_tokens": 5,
                            "passthroughs": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = compare_benchmarks(base, target)

            self.assertEqual(report["status"], "improved")
            self.assertEqual(report["base"]["item_count"], 2)
            self.assertEqual(report["delta"]["saved_tokens"], 2)

    def test_reply_wire_round_trip(self) -> None:
        reply = encode_reply(
            "added compact reply codec",
            files=["tokensquash/reply.py", "tokensquash/cli.py"],
            verification=["unit tests pass"],
            commands=["python -m unittest discover -s tests"],
            risks=["none"],
        )

        wire = reply.to_wire()
        parsed = parse_reply_wire(wire)

        self.assertEqual(parsed.status, "done")
        self.assertEqual(parsed.summary, "added compact reply codec")
        self.assertEqual(parsed.files, ("tokensquash/reply.py", "tokensquash/cli.py"))
        self.assertEqual(parsed.verification, ("unit tests pass",))
        self.assertEqual(parsed.commands, ("python -m unittest discover -s tests",))
        self.assertEqual(parsed.risks, ("none",))
        self.assertEqual(parsed.to_wire(), wire)

    def test_reply_decode_is_human_readable(self) -> None:
        text = decode_reply('tr1 p "benchmark added" f=benchmarks/reply.json v="tests pass" n="collect real replies"')

        self.assertIn("partially done", text)
        self.assertIn("benchmark added", text)
        self.assertIn("benchmarks/reply.json", text)
        self.assertIn("collect real replies", text)

    def test_reply_decode_allows_unquoted_field_words(self) -> None:
        parsed = parse_reply_wire("tr1 d compact reply added f=tokensquash/reply.py v=unit tests pass r=none")

        self.assertEqual(parsed.summary, "compact reply added")
        self.assertEqual(parsed.verification, ("unit tests pass",))
        self.assertEqual(parsed.risks, ("none",))

    def test_reply_accepts_json(self) -> None:
        wire = parse_reply_wire(
            json.dumps(
                {
                    "status": "blocked",
                    "summary": "need a private prompt export",
                    "next_steps": ["add local corpus"],
                }
            )
        )

        self.assertEqual(wire.status, "blocked")
        self.assertEqual(wire.summary, "need a private prompt export")
        self.assertEqual(wire.next_steps, ("add local corpus",))

    def test_load_and_validate_turn_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"t1","prompt":"fix login","reply":"Done. Contact dev@example.com for details."}\n',
                encoding="utf-8",
            )

            records = load_turn_records(path)
            report = validate_turn_corpus(path)

            self.assertEqual(records[0]["prompt"], "fix login")
            self.assertEqual(records[0]["reply_text"], "Done. Contact dev@example.com for details.")
            self.assertEqual(report["status"], "warn")
            self.assertEqual(report["privacy"]["findings"][0]["code"], "email")

    def test_redact_and_split_turn_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "turns.jsonl"
            redacted = Path(tmp) / "turns.redacted.jsonl"
            prompts = Path(tmp) / "prompts.jsonl"
            replies = Path(tmp) / "replies.jsonl"
            src.write_text(
                '{"id":"t1","prompt":"fix login for dev@example.com","reply":"Done. `python -m unittest discover -s tests` passed. api_key=secret123"}\n',
                encoding="utf-8",
            )

            redact_report = redact_turn_corpus(src, redacted)
            split_report = split_turn_corpus(redacted, prompts, replies)
            reply_payload = json.loads(replies.read_text(encoding="utf-8").splitlines()[0])

            self.assertEqual(redact_report["status"], "written")
            self.assertGreaterEqual(redact_report["redaction_count"], 2)
            self.assertEqual(split_report["turns"], 1)
            self.assertIn("[REDACTED_EMAIL]", prompts.read_text(encoding="utf-8"))
            self.assertIn("python -m unittest discover -s tests", reply_payload["commands"])

    def test_turn_benchmark_combines_prompt_and_reply(self) -> None:
        records = [
            {
                "id": "t1",
                "prompt": "please fix the login bug, keep the diff small, run tests, and summarize files changed",
                "reply_text": (
                    "Done. I fixed the login bug in src/auth.py and verified it with "
                    "`python -m unittest discover -s tests`. Risks: none."
                ),
                "reply_fields": {},
            }
        ]

        report = benchmark_turns(records, target_savings_pct=0.0)

        self.assertEqual(report["schema_version"], "tokensquash.turns.bench.v1")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["turn_count"], 1)
        self.assertIn("prompt_report", report)
        self.assertIn("reply_report", report)


if __name__ == "__main__":
    unittest.main()
