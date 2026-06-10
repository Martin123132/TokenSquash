from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tokensquash.codec import decode_intent, encode_intent, parse_wire
from tokensquash.metrics import benchmark_prompts, count_tokens, load_prompts


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

    def test_load_jsonl_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompts.jsonl"
            path.write_text('{"text":"one"}\n{"prompt":"two"}\n', encoding="utf-8")

            self.assertEqual(load_prompts(path), ["one", "two"])


if __name__ == "__main__":
    unittest.main()
