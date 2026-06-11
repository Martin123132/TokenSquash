from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from tokensquash.aliases import AliasTable, learn_reply_aliases, load_alias_table, write_alias_table
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
from tokensquash.mining import mine_reply_patterns
from tokensquash.reply import decode_reply, encode_reply, parse_reply_wire
from tokensquash.turns import (
    append_turn_record,
    benchmark_turn_alias_impact,
    benchmark_turns,
    diagnose_turn_corpus,
    learn_turn_aliases,
    load_turn_records,
    measure_turn_corpus,
    mine_turn_patterns,
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

    def test_mine_reply_patterns_reports_repeated_uncoded_values(self) -> None:
        records = [
            {
                "id": "a",
                "summary": "checked search flow",
                "files": ["tokensquash/search.py"],
                "verification": ["integration tests pass"],
                "commands": ["npm test"],
                "risks": ["staging database not seeded"],
                "text": "Done. I checked search and ran npm test. Risk: staging database not seeded.",
            },
            {
                "id": "b",
                "summary": "checked checkout flow",
                "files": ["tokensquash/checkout.py"],
                "verification": ["integration tests pass"],
                "commands": ["npm test"],
                "risks": ["staging database not seeded"],
                "text": "Done. I checked checkout and ran npm test. Risk: staging database not seeded.",
            },
        ]

        report = mine_reply_patterns(records, min_count=2)
        candidates = {(item["field"], item["value"]): item for item in report["top_candidates"]}

        self.assertEqual(report["schema_version"], "tokensquash.patterns.mine.v1")
        self.assertEqual(report["status"], "pass")
        self.assertIn(("commands", "npm test"), candidates)
        self.assertGreater(candidates[("commands", "npm test")]["estimated_new_saved_tokens"], 0)
        self.assertIn(("risks", "staging database not seeded"), candidates)
        path_prefix = next(item for item in report["path_patterns"] if item["value"] == "tokensquash/")
        self.assertEqual(path_prefix["existing_code"], "@t/")
        self.assertEqual(path_prefix["estimated_new_saved_tokens"], 0)

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

        self.assertTrue(wire.startswith("tr1 "))
        self.assertNotIn("tr1 d ", wire)
        self.assertIn("f=@t/reply.py,@t/cli.py", wire)
        self.assertIn("v=t", wire)
        self.assertIn("c=pyunit", wire)
        self.assertIn("r=0", wire)
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

    def test_reply_decode_expands_path_aliases(self) -> None:
        parsed = parse_reply_wire('tr1 "path aliases" f=@t/reply.py,@x/test_codec.py,@g/tests.yml')

        self.assertEqual(
            parsed.files,
            ("tokensquash/reply.py", "tests/test_codec.py", ".github/workflows/tests.yml"),
        )
        self.assertEqual(parsed.to_wire(), 'tr1 "path aliases" f=@t/reply.py,@x/test_codec.py,@g/tests.yml')

    def test_reply_supports_session_path_aliases(self) -> None:
        aliases = AliasTable({"packages/mobile/src/": "@0/"})
        reply = encode_reply(
            "updated mobile login",
            files=["packages/mobile/src/screens/login.tsx"],
        )

        wire = reply.to_wire(aliases=aliases)
        parsed = parse_reply_wire(wire, aliases=aliases)

        self.assertIn("f=@0/screens/login.tsx", wire)
        self.assertEqual(parsed.files, ("packages/mobile/src/screens/login.tsx",))
        self.assertEqual(parsed.to_wire(aliases=aliases), wire)

    def test_reply_benchmark_uses_session_aliases(self) -> None:
        records = [
            {
                "summary": "updated mobile login",
                "files": ["packages/mobile/src/screens/login.tsx"],
                "text": "Done. I updated packages/mobile/src/screens/login.tsx.",
            },
            {
                "summary": "updated mobile checkout",
                "files": ["packages/mobile/src/screens/checkout.tsx"],
                "text": "Done. I updated packages/mobile/src/screens/checkout.tsx.",
            },
        ]
        aliases = AliasTable({"packages/mobile/src/": "@0/"})

        base = benchmark_replies(records, counter="chars", target_savings_pct=0.0)
        custom = benchmark_replies(records, counter="chars", target_savings_pct=0.0, aliases=aliases)

        self.assertLess(custom["summary"]["wire_tokens"], base["summary"]["wire_tokens"])
        self.assertEqual(custom["aliases"]["custom_path_prefix_count"], 1)

    def test_learn_reply_aliases_selects_repeated_project_prefix(self) -> None:
        records = [
            {
                "id": "a",
                "summary": "updated login screen",
                "files": ["apps/customer-portal/src/screens/login.tsx"],
                "text": "Done. I updated the customer portal login screen.",
            },
            {
                "id": "b",
                "summary": "updated checkout screen",
                "files": ["apps/customer-portal/src/screens/checkout.tsx"],
                "text": "Done. I updated the customer portal checkout screen.",
            },
        ]

        report = learn_reply_aliases(records, counter="chars", min_count=2, max_path_prefixes=1)
        aliases = AliasTable.from_dict(report)
        prefix = next(iter(report["path_prefixes"]))

        self.assertEqual(report["schema_version"], "tokensquash.aliases.v1")
        self.assertTrue(prefix.startswith("apps/customer-portal/src/"))
        self.assertEqual(report["summary"]["selected_path_prefix_count"], 1)
        self.assertTrue(aliases.encode_path("apps/customer-portal/src/screens/login.tsx").startswith("@0/"))

    def test_learn_reply_aliases_preserves_base_aliases(self) -> None:
        records = [
            {
                "id": "a",
                "summary": "updated inventory view",
                "files": ["packages/admin/src/views/inventory.tsx"],
                "text": "Done. I updated inventory.",
            },
            {
                "id": "b",
                "summary": "updated orders view",
                "files": ["packages/admin/src/views/orders.tsx"],
                "text": "Done. I updated orders.",
            },
        ]

        report = learn_reply_aliases(
            records,
            counter="chars",
            min_count=2,
            max_path_prefixes=1,
            base_aliases=AliasTable({"packages/base/src/": "@0/"}),
        )

        self.assertEqual(report["path_prefixes"]["packages/base/src/"], "@0/")
        self.assertIn("@1/", report["path_prefixes"].values())

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learned-aliases.json"
            write_alias_table(path, report)
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertNotIn("source", payload)
            self.assertEqual(payload["path_prefixes"]["packages/base/src/"], "@0/")

    def test_alias_table_can_be_loaded_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aliases.json"
            write_alias_table(path, AliasTable({"packages/api/src/": "@0/"}))
            bom_path = Path(tmp) / "aliases-bom.json"
            bom_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8-sig")

            aliases = load_alias_table(path)
            bom_aliases = load_alias_table(bom_path)

            self.assertEqual(aliases.encode_path("packages/api/src/routes/user.py"), "@0/routes/user.py")
            self.assertEqual(bom_aliases.encode_path("packages/api/src/routes/user.py"), "@0/routes/user.py")

    def test_reply_decode_accepts_default_status_and_field_codes(self) -> None:
        parsed = parse_reply_wire('tr1 "compact reply added" v=t c=pyunit r=0')

        self.assertEqual(parsed.status, "done")
        self.assertEqual(parsed.summary, "compact reply added")
        self.assertEqual(parsed.verification, ("unit tests pass",))
        self.assertEqual(parsed.commands, ("python -m unittest discover -s tests",))
        self.assertEqual(parsed.risks, ("none",))

    def test_reply_wire_keeps_status_when_summary_looks_like_status(self) -> None:
        wire = encode_reply("done").to_wire()
        parsed = parse_reply_wire(wire)

        self.assertEqual(wire, "tr1 d done")
        self.assertEqual(parsed.status, "done")
        self.assertEqual(parsed.summary, "done")

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
            self.assertTrue(reply_payload["summary"])
            self.assertNotIn("python -m unittest", reply_payload["summary"])

    def test_append_turn_record_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "real.jsonl"

            first = append_turn_record(
                path,
                prompt="fix login",
                reply="Done. I fixed login and ran tests.",
                status="done",
                verification=["unit tests pass"],
            )
            second = append_turn_record(
                path,
                prompt="review checkout",
                reply="Done. Risk: payment sandbox not exercised.",
                risks=["payment sandbox not exercised"],
            )
            records = load_turn_records(path)

            self.assertEqual(first["id"], "turn-0001")
            self.assertEqual(second["id"], "turn-0002")
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["reply_fields"]["verification"], ["unit tests pass"])

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

    def test_measure_turn_corpus_reports_validation_and_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"t1","prompt":"please fix login bug and run tests","reply":"Done. I fixed login in src/auth.py and ran tests."}\n',
                encoding="utf-8",
            )

            report = measure_turn_corpus(path, target_savings_pct=0.0)

            self.assertEqual(report["schema_version"], "tokensquash.turns.measure.v1")
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["summary"]["turn_count"], 1)
            self.assertEqual(report["validation"]["status"], "pass")
            self.assertIn("benchmark", report)

    def test_measure_turn_corpus_reports_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-turns.jsonl"
            path.write_text('{"id":"t1","prompt":"missing reply"}\n', encoding="utf-8")

            report = measure_turn_corpus(path, target_savings_pct=0.0)

            self.assertEqual(report["status"], "fail")
            self.assertIsNone(report["benchmark"])
            self.assertEqual(report["validation"]["errors"][0]["code"], "missing_reply")

    def test_diagnose_turn_corpus_reports_pass_throughs_and_losses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"short","prompt":"ok","reply":"Done."}\n'
                '{"id":"win","prompt":"please fix the login bug, keep the diff small, run tests, and summarize files changed","reply":"Done. I fixed the login bug in src/auth.py and verified it with `python -m unittest discover -s tests`. Risks: none."}\n',
                encoding="utf-8",
            )

            report = diagnose_turn_corpus(path, limit=3)

            self.assertEqual(report["schema_version"], "tokensquash.turns.diagnose.v1")
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["summary"]["turn_count"], 2)
            self.assertGreaterEqual(report["summary"]["pass_through_rows"], 1)
            self.assertTrue(report["largest_losses"])
            loss_ids = [item["id"] for item in report["largest_losses"]]
            self.assertIn("short", loss_ids)
            short_loss = next(item for item in report["largest_losses"] if item["id"] == "short")
            self.assertIn("raw_wire_loss", short_loss["tags"])
            self.assertIn("prompt_passthrough", report["issue_counts"])

    def test_diagnose_turn_corpus_reports_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-turns.jsonl"
            path.write_text('{"id":"t1","prompt":"missing reply"}\n', encoding="utf-8")

            report = diagnose_turn_corpus(path)

            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["rows"], [])
            self.assertIsNone(report["benchmark_summary"])

    def test_mine_turn_patterns_uses_guessed_reply_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"a","prompt":"check search","reply":"Done. I checked search and ran `npm test`. Risk: staging database not seeded."}\n'
                '{"id":"b","prompt":"check checkout","reply":"Done. I checked checkout and ran `npm test`. Risk: staging database not seeded."}\n',
                encoding="utf-8",
            )

            report = mine_turn_patterns(path, min_count=2)
            candidates = {(item["field"], item["value"]): item for item in report["top_candidates"]}

            self.assertEqual(report["schema_version"], "tokensquash.turns.mine.v1")
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["summary"]["turn_count"], 2)
            self.assertIn(("commands", "npm test"), candidates)
            self.assertGreater(candidates[("commands", "npm test")]["estimated_new_saved_tokens"], 0)

    def test_learn_turn_aliases_uses_guessed_reply_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"a","prompt":"update login","reply":"Done. I changed packages/mobile/src/screens/login.tsx."}\n'
                '{"id":"b","prompt":"update checkout","reply":"Done. I changed packages/mobile/src/screens/checkout.tsx."}\n',
                encoding="utf-8",
            )

            report = learn_turn_aliases(path, counter="chars", min_count=2, max_path_prefixes=1)
            aliases = AliasTable.from_dict(report)

            self.assertEqual(report["schema_version"], "tokensquash.aliases.v1")
            self.assertEqual(report["summary"]["turn_count"], 2)
            self.assertEqual(report["summary"]["selected_path_prefix_count"], 1)
            self.assertTrue(aliases.encode_path("packages/mobile/src/screens/login.tsx").startswith("@0/"))

    def test_turn_alias_impact_reports_delta_and_break_even(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"a","prompt":"update login","reply":"Done. I changed packages/mobile/src/screens/login.tsx."}\n'
                '{"id":"b","prompt":"update checkout","reply":"Done. I changed packages/mobile/src/screens/checkout.tsx."}\n',
                encoding="utf-8",
            )

            report = benchmark_turn_alias_impact(
                path,
                counter="chars",
                target_savings_pct=0.0,
                max_path_prefixes=1,
            )

            self.assertEqual(report["schema_version"], "tokensquash.turns.alias_impact.v1")
            self.assertEqual(report["status"], "improved")
            self.assertEqual(report["summary"]["selected_path_prefix_count"], 1)
            self.assertGreater(report["summary"]["saved_tokens_delta"], 0)
            self.assertGreater(report["summary"]["aliased_saved_pct"], report["summary"]["baseline_saved_pct"])
            self.assertGreaterEqual(report["summary"]["break_even_corpora"], 1)
            self.assertIn("baseline", report)
            self.assertIn("aliased", report)

    def test_turn_alias_impact_has_no_setup_cost_without_new_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"a","prompt":"fix login","reply":"Done. I changed src/auth.py."}\n',
                encoding="utf-8",
            )

            report = benchmark_turn_alias_impact(path, counter="chars", target_savings_pct=0.0)

            self.assertEqual(report["status"], "same")
            self.assertEqual(report["summary"]["selected_path_prefix_count"], 0)
            self.assertEqual(report["summary"]["alias_setup_tokens"], 0)
            self.assertIsNone(report["summary"]["break_even_corpora"])


if __name__ == "__main__":
    unittest.main()
