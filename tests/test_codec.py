from __future__ import annotations

import tempfile
import unittest
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tokensquash.aliases import AliasTable, learn_reply_aliases, load_alias_table, write_alias_table
from tokensquash.cli import main as cli_main
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
from tokensquash.sidecar import (
    compact_semantic_payload,
    compare_sidecar_evaluations,
    decode_semantic,
    evaluate_sidecar_turns,
    parse_semantic_json,
    translate_with_ollama,
)
from tokensquash.turns import (
    append_turn_record,
    benchmark_turn_alias_impact,
    benchmark_turns,
    capture_turn_record,
    diagnose_turn_corpus,
    evaluate_turn_corpus,
    import_turn_corpus,
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

    def test_prompt_supports_session_path_aliases(self) -> None:
        aliases = AliasTable({"packages/mobile/src/": "@0/"})
        intent = encode_intent("Fix packages/mobile/src/screens/login.tsx, run tests, and summarize files changed.")

        wire = intent.to_wire(aliases=aliases)
        parsed = parse_wire(wire, aliases=aliases)

        self.assertIn("p=@0/screens/login.tsx", wire)
        self.assertEqual(parsed.paths, ("packages/mobile/src/screens/login.tsx",))
        self.assertEqual(parsed.to_wire(aliases=aliases), wire)

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

    def test_prompt_benchmark_uses_session_aliases(self) -> None:
        prompts = [
            "Please review packages/mobile/src/screens/login.tsx and summarize files changed.",
            "Please review packages/mobile/src/screens/checkout.tsx and summarize files changed.",
        ]
        aliases = AliasTable({"packages/mobile/src/": "@0/"})

        base = benchmark_prompts(prompts, counter="chars", target_savings_pct=0.0)
        custom = benchmark_prompts(prompts, counter="chars", target_savings_pct=0.0, aliases=aliases)

        self.assertLess(custom["summary"]["wire_tokens"], base["summary"]["wire_tokens"])
        self.assertEqual(custom["aliases"]["custom_path_prefix_count"], 1)

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

    def test_sidecar_dry_run_cli_outputs_ollama_request(self) -> None:
        stdout = StringIO()

        with redirect_stdout(stdout):
            code = cli_main(
                [
                    "sidecar",
                    "translate",
                    "prompt",
                    "fix",
                    "the",
                    "login",
                    "bug",
                    "--model",
                    "tiny-local",
                    "--dry-run",
                    "--json",
                ]
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema_version"], "tokensquash.sidecar.request.v1")
        self.assertEqual(payload["backend"], "ollama")
        self.assertEqual(payload["model"], "tiny-local")
        self.assertEqual(payload["mode"], "prompt")
        self.assertFalse(payload["payload"]["stream"])
        self.assertEqual(payload["payload"]["format"], "json")
        self.assertIn("fix the login bug", payload["payload"]["prompt"])
        self.assertIn("Required prompt keys: o, q.", payload["payload"]["prompt"])
        self.assertIn("q must be the actual task gist in 1-5 words", payload["payload"]["prompt"])
        self.assertIn("Values must come from the English text only", payload["payload"]["prompt"])
        self.assertIn("Use ONLY the short keys", payload["payload"]["prompt"])
        self.assertIn("do not include a kind key", payload["payload"]["prompt"])
        self.assertIn("Never output schema placeholders as values", payload["payload"]["prompt"])

    def test_parse_semantic_json_accepts_fenced_model_output(self) -> None:
        payload = parse_semantic_json('```json\n{"kind":"reply","status":"done","summary":"fixed login"}\n```')

        self.assertEqual(payload["kind"], "reply")
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["summary"], "fixed login")

    def test_translate_with_ollama_uses_local_response(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "response": json.dumps(
                            {
                                "kind": "reply",
                                "status": "done",
                                "summary": "fixed login",
                                "files": ["src/auth.py"],
                                "verification": ["tests pass"],
                                "commands": [],
                                "risks": [],
                                "next_steps": [],
                            }
                        )
                    }
                ).encode("utf-8")

        with patch("tokensquash.sidecar.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            report = translate_with_ollama(
                "Done. I fixed login in src/auth.py and tests pass.",
                mode="reply",
                model="tiny-local",
                endpoint="http://localhost:11434",
                counter="chars",
            )

        self.assertEqual(report["schema_version"], "tokensquash.sidecar.semantic.v1")
        self.assertEqual(report["backend"], "ollama")
        self.assertEqual(report["model"], "tiny-local")
        self.assertEqual(report["semantic"]["summary"], "fixed login")
        self.assertEqual(report["semantic_compact"]["m"], "fixed login")
        self.assertNotIn("summary", report["semantic_wire"])
        self.assertNotIn('"k"', report["semantic_wire"])
        self.assertIn("semantic_tokens", report["summary"])
        self.assertTrue(mocked_urlopen.called)

    def test_compact_semantic_payload_uses_short_keys(self) -> None:
        compact = compact_semantic_payload(
            {
                "kind": "reply",
                "status": "done",
                "summary": "fixed login",
                "files": ["src/auth.py"],
                "verification": ["Verified with pytest"],
                "commands": [],
                "risks": [],
                "next_steps": [],
            },
            mode="reply",
        )

        self.assertEqual(compact, {"s": "d", "m": "fixed login", "f": ["src/auth.py"], "v": ["pytest"]})

    def test_translate_with_ollama_drops_unanchored_paths(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "response": json.dumps(
                            {
                                "o": "review",
                                "q": "checkout flow",
                                "p": ["src/checkout.py", "/invented-checkout-notes.txt"],
                                "r": ["risks"],
                            }
                        )
                    }
                ).encode("utf-8")

        with patch("tokensquash.sidecar.urlopen", return_value=FakeResponse()):
            report = translate_with_ollama(
                "review checkout flow in src/checkout.py and return risks",
                mode="prompt",
                model="tiny-local",
                counter="chars",
            )

        self.assertEqual(report["semantic"]["paths"], ["src/checkout.py"])
        self.assertEqual(report["semantic_compact"]["p"], ["src/checkout.py"])
        self.assertNotIn("invented-checkout", report["semantic_wire"])

    def test_translate_with_ollama_drops_unanchored_reply_next_steps(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "response": json.dumps(
                            {
                                "s": "d",
                                "m": "fixed login",
                                "f": ["src/auth.py", "src/ghost.py"],
                                "v": ["Verified with pytest"],
                                "n": ["Review code"],
                            }
                        )
                    }
                ).encode("utf-8")

        with patch("tokensquash.sidecar.urlopen", return_value=FakeResponse()):
            report = translate_with_ollama(
                "Done. I fixed login in src/auth.py. Verified with pytest.",
                mode="reply",
                model="tiny-local",
                counter="chars",
            )

        self.assertEqual(report["semantic"]["files"], ["src/auth.py"])
        self.assertEqual(report["semantic"]["next_steps"], [])
        self.assertEqual(report["semantic_compact"]["v"], ["pytest"])
        self.assertNotIn("Review code", report["semantic_wire"])
        self.assertNotIn("src/ghost.py", report["semantic_wire"])

    def test_sidecar_decode_prompt_is_deterministic(self) -> None:
        report = decode_semantic(
            {
                "kind": "prompt",
                "op": "fix",
                "query": "login bug",
                "paths": ["src/auth.py"],
                "constraints": ["small_diff"],
                "verify": ["tests"],
                "returns": ["summary", "files"],
            },
            mode="prompt",
        )

        self.assertEqual(report["schema_version"], "tokensquash.sidecar.decode.v1")
        self.assertEqual(report["status"], "pass")
        self.assertIn("Fix", report["text"])
        self.assertIn("login bug", report["text"])
        self.assertIn("src/auth.py", report["text"])
        self.assertFalse(report["warnings"])

    def test_sidecar_decode_warns_on_schema_placeholders(self) -> None:
        report = decode_semantic(
            {
                "o": "refactor",
                "q": "<=5 words",
                "c": ["constraint1", "constraint2"],
                "v": ["verify"],
                "r": ["returns:evaluation results"],
            },
            mode="prompt",
        )

        self.assertEqual(report["status"], "warn")
        self.assertIn("semantic.query looks like schema placeholder: <=5 words", report["warnings"])
        self.assertIn("semantic.constraints looks like schema placeholder: constraint1", report["warnings"])
        self.assertIn("semantic.verify looks like schema placeholder: verify", report["warnings"])
        self.assertIn(
            "semantic.returns looks like schema placeholder: returns:evaluation results",
            report["warnings"],
        )

    def test_sidecar_decode_reply_is_deterministic(self) -> None:
        report = decode_semantic(
            {
                "kind": "reply",
                "status": "done",
                "summary": "fixed login",
                "files": ["src/auth.py"],
                "verification": ["tests pass"],
                "commands": ["pytest"],
                "risks": ["none"],
                "next_steps": ["review auth"],
            },
            mode="reply",
        )

        self.assertEqual(report["schema_version"], "tokensquash.sidecar.decode.v1")
        self.assertEqual(report["mode"], "reply")
        self.assertIn("Done: fixed login.", report["text"])
        self.assertIn("src/auth.py", report["text"])
        self.assertIn("Commands", report["text"])
        self.assertFalse(report["warnings"])

    def test_sidecar_decode_cli_json(self) -> None:
        stdout = StringIO()
        semantic = '{"k":"p","o":"fix","q":"login bug"}'

        with redirect_stdout(stdout):
            code = cli_main(["sidecar", "decode", "prompt", semantic, "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema_version"], "tokensquash.sidecar.decode.v1")
        self.assertEqual(payload["mode"], "prompt")
        self.assertIn("Fix", payload["text"])
        self.assertEqual(payload["semantic"]["kind"], "prompt")

    def test_sidecar_roundtrip_cli_json(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "response": json.dumps(
                            {
                                "kind": "reply",
                                "status": "done",
                                "summary": "fixed login",
                                "files": ["src/auth.py"],
                                "verification": ["tests pass"],
                                "commands": ["pytest"],
                                "risks": ["none"],
                                "next_steps": [],
                            }
                        )
                    }
                ).encode("utf-8")

        stdout = StringIO()
        with patch("tokensquash.sidecar.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            with redirect_stdout(stdout):
                code = cli_main(
                    [
                        "sidecar",
                        "roundtrip",
                        "reply",
                        "Done.",
                        "I",
                        "fixed",
                        "login",
                        "in",
                        "src/auth.py",
                        "--model",
                        "tiny-local",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["schema_version"], "tokensquash.sidecar.roundtrip.v1")
        self.assertEqual(payload["mode"], "reply")
        self.assertIn("semantic", payload)
        self.assertIn("decoded_text", payload)
        self.assertIn("semantic_tokens", payload["summary"])
        self.assertTrue(mocked_urlopen.called)

    def test_sidecar_roundtrip_markdown_output(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "response": json.dumps(
                            {
                                "kind": "reply",
                                "status": "done",
                                "summary": "fixed login",
                                "files": ["src/auth.py"],
                                "verification": ["tests pass"],
                                "commands": ["pytest"],
                                "risks": ["none"],
                                "next_steps": [],
                            }
                        )
                    }
                ).encode("utf-8")

        stdout = StringIO()
        with patch("tokensquash.sidecar.urlopen", return_value=FakeResponse()):
            with redirect_stdout(stdout):
                code = cli_main(
                    [
                        "sidecar",
                        "roundtrip",
                        "reply",
                        "Done.",
                        "I",
                        "fixed",
                        "login",
                        "in",
                        "src/auth.py",
                    ]
                )

        output = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("TokenSquash Sidecar Roundtrip", output)
        self.assertIn("## Original", output)
        self.assertIn("## Semantic", output)
        self.assertIn("## Decoded", output)
        self.assertIn("Saved percent", output)
        self.assertIn("Done: fixed login.", output)
        self.assertIn("Files: src/auth.py.", output)

    def test_sidecar_evaluate_turns_reports_batch_summary(self) -> None:
        class FakeResponse:
            def __init__(self, semantic):
                self.semantic = semantic

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"response": json.dumps(self.semantic)}).encode("utf-8")

        def fake_urlopen(request, timeout):
            body = json.loads(request.data.decode("utf-8"))
            if "Required prompt keys" in body["prompt"]:
                semantic = {
                    "o": "fix",
                    "q": "login bug",
                    "p": ["src/auth.py"],
                    "v": ["tests"],
                    "r": ["summary"],
                }
            else:
                semantic = {
                    "s": "d",
                    "m": "fixed login",
                    "f": ["src/auth.py"],
                    "v": ["tests pass"],
                }
            return FakeResponse(semantic)

        records = [
            {
                "id": "turn-1",
                "prompt": "fix the login bug in src/auth.py and run tests",
                "reply_text": "Done. I fixed login in src/auth.py and tests pass.",
            }
        ]
        with patch("tokensquash.sidecar.urlopen", side_effect=fake_urlopen):
            report = evaluate_sidecar_turns(records, source="memory", part="both", counter="chars")

        self.assertEqual(report["schema_version"], "tokensquash.sidecar.evaluate.v1")
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["summary"]["turn_count"], 1)
        self.assertEqual(report["summary"]["item_count"], 2)
        self.assertEqual(report["summary"]["prompt_items"], 1)
        self.assertEqual(report["summary"]["reply_items"], 1)
        self.assertIn("best_examples", report)
        self.assertIn("worst_examples", report)

    def test_sidecar_evaluate_cli_writes_report_pack(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "response": json.dumps(
                            {
                                "kind": "reply",
                                "status": "done",
                                "summary": "fixed login",
                                "files": ["src/auth.py"],
                                "verification": ["tests pass"],
                                "commands": [],
                                "risks": [],
                                "next_steps": [],
                            }
                        )
                    }
                ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "turns.jsonl"
            out_dir = Path(tmp) / "sidecar-eval"
            corpus.write_text(
                '{"id":"turn-1","prompt":"fix login","reply":"Done. I fixed login in src/auth.py."}\n',
                encoding="utf-8",
            )
            stdout = StringIO()

            with patch("tokensquash.sidecar.urlopen", return_value=FakeResponse()):
                with redirect_stdout(stdout):
                    code = cli_main(
                        [
                            "sidecar",
                            "evaluate",
                            str(corpus),
                            "--mode",
                            "reply",
                            "--limit",
                            "1",
                            "--out-dir",
                            str(out_dir),
                            "--counter",
                            "chars",
                            "--json",
                        ]
                    )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema_version"], "tokensquash.sidecar.evaluate.v1")
            self.assertEqual(payload["summary"]["item_count"], 1)
            self.assertEqual(payload["summary"]["reply_items"], 1)
            self.assertTrue((out_dir / "evaluation.json").exists())
            self.assertTrue((out_dir / "rows.jsonl").exists())
            self.assertIn("outputs", payload)

    def test_sidecar_experiment_cli_writes_evidence_pack(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "response": json.dumps(
                            {
                                "kind": "reply",
                                "status": "done",
                                "summary": "fixed login",
                                "files": ["src/auth.py"],
                                "verification": ["tests pass"],
                                "commands": [],
                                "risks": [],
                                "next_steps": [],
                            }
                        )
                    }
                ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "turns.jsonl"
            out_root = Path(tmp) / "experiments"
            run_dir = out_root / "run-001"
            corpus.write_text(
                '{"id":"turn-1","prompt":"fix login","reply":"Done. I fixed login in src/auth.py."}\n',
                encoding="utf-8",
            )
            stdout = StringIO()

            with patch("tokensquash.sidecar.urlopen", return_value=FakeResponse()):
                with redirect_stdout(stdout):
                    code = cli_main(
                        [
                            "sidecar",
                            "experiment",
                            str(corpus),
                            "--name",
                            "llama baseline",
                            "--run-id",
                            "run-001",
                            "--out-root",
                            str(out_root),
                            "--mode",
                            "reply",
                            "--limit",
                            "1",
                            "--counter",
                            "chars",
                            "--json",
                        ]
                    )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema_version"], "tokensquash.sidecar.experiment.v1")
            self.assertEqual(payload["name"], "llama baseline")
            self.assertEqual(payload["run_id"], "run-001")
            self.assertEqual(payload["output_dir"], str(run_dir))
            self.assertEqual(payload["summary"]["item_count"], 1)
            self.assertTrue((run_dir / "evaluation.json").exists())
            self.assertTrue((run_dir / "rows.jsonl").exists())
            self.assertTrue((run_dir / "summary.md").exists())
            self.assertTrue((run_dir / "run.json").exists())
            self.assertIn("TokenSquash Sidecar Experiment", (run_dir / "summary.md").read_text(encoding="utf-8"))

    def test_sidecar_sweep_cli_writes_runs_and_comparisons(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "response": json.dumps(
                            {
                                "s": "d",
                                "m": "fixed login",
                                "f": ["src/auth.py"],
                                "v": ["tests pass"],
                            }
                        )
                    }
                ).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "turns.jsonl"
            out_root = Path(tmp) / "sweeps"
            sweep_dir = out_root / "sweep-001"
            corpus.write_text(
                '{"id":"turn-1","prompt":"fix login","reply":"Done. I fixed login in src/auth.py and tests pass."}\n',
                encoding="utf-8",
            )
            stdout = StringIO()

            with patch("tokensquash.sidecar.urlopen", return_value=FakeResponse()):
                with redirect_stdout(stdout):
                    code = cli_main(
                        [
                            "sidecar",
                            "sweep",
                            str(corpus),
                            "--name",
                            "counter sweep",
                            "--run-id",
                            "sweep-001",
                            "--out-root",
                            str(out_root),
                            "--mode",
                            "reply",
                            "--limit",
                            "1",
                            "--model",
                            "tiny-a",
                            "--model",
                            "tiny-b",
                            "--counter",
                            "chars",
                            "--counter",
                            "char4",
                            "--json",
                        ]
                    )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema_version"], "tokensquash.sidecar.sweep.v1")
            self.assertEqual(payload["name"], "counter sweep")
            self.assertEqual(payload["run_id"], "sweep-001")
            self.assertEqual(payload["summary"]["run_count"], 4)
            self.assertEqual(payload["summary"]["comparison_count"], 3)
            self.assertEqual(payload["summary"]["skipped_comparison_count"], 2)
            self.assertEqual(len(payload["runs"]), 4)
            self.assertEqual(len(payload["comparisons"]), 3)
            self.assertTrue(any(comparison["status"] != "skipped" for comparison in payload["comparisons"]))
            self.assertTrue(any(comparison["status"] == "skipped" for comparison in payload["comparisons"]))
            self.assertTrue((sweep_dir / "sweep.json").exists())
            self.assertTrue((sweep_dir / "summary.md").exists())
            self.assertTrue((sweep_dir / "runs" / payload["runs"][0]["run_id"] / "evaluation.json").exists())
            self.assertTrue((sweep_dir / "comparisons").exists())
            self.assertIn("TokenSquash Sidecar Sweep", (sweep_dir / "summary.md").read_text(encoding="utf-8"))

    def test_sidecar_sweep_cli_markdown_output(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"response": '{"s":"d","m":"fixed login","f":["src/auth.py"]}'}).encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "turns.jsonl"
            out_root = Path(tmp) / "sweeps"
            corpus.write_text(
                '{"id":"turn-1","prompt":"fix login","reply":"Done. I fixed login in src/auth.py."}\n',
                encoding="utf-8",
            )
            stdout = StringIO()

            with patch("tokensquash.sidecar.urlopen", return_value=FakeResponse()):
                with redirect_stdout(stdout):
                    code = cli_main(
                        [
                            "sidecar",
                            "sweep",
                            str(corpus),
                            "--run-id",
                            "sweep-001",
                            "--out-root",
                            str(out_root),
                            "--mode",
                            "reply",
                            "--limit",
                            "1",
                            "--counter",
                            "chars",
                        ]
                    )

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("TokenSquash Sidecar Sweep", output)
            self.assertIn("## Runs", output)
            self.assertIn("Saved %", output)
            self.assertIn("sweep.json", output)

    def test_compare_sidecar_evaluations_reports_improvement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.json"
            target = Path(tmp) / "target.json"
            base.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.sidecar.evaluate.v1",
                        "status": "warn",
                        "source": "base-turns.jsonl",
                        "mode": "both",
                        "model": "tiny-local",
                        "counter": "chars",
                        "summary": {
                            "item_count": 2,
                            "success_count": 2,
                            "failure_count": 1,
                            "warning_count": 2,
                            "original_tokens": 100,
                            "semantic_tokens": 90,
                            "saved_tokens": 10,
                            "saved_pct": 10.0,
                            "win_items": 1,
                            "loss_items": 1,
                            "tie_items": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            target.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.sidecar.evaluate.v1",
                        "status": "pass",
                        "source": "target-turns.jsonl",
                        "mode": "both",
                        "model": "tiny-local",
                        "counter": "chars",
                        "summary": {
                            "item_count": 2,
                            "success_count": 2,
                            "failure_count": 0,
                            "warning_count": 1,
                            "original_tokens": 100,
                            "semantic_tokens": 84,
                            "saved_tokens": 16,
                            "saved_pct": 16.0,
                            "win_items": 2,
                            "loss_items": 0,
                            "tie_items": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = compare_sidecar_evaluations(base, target)

        self.assertEqual(report["schema_version"], "tokensquash.sidecar.evaluate.compare.v1")
        self.assertEqual(report["status"], "improved")
        self.assertEqual(report["delta"]["saved_tokens"], 6)
        self.assertEqual(report["delta"]["saved_pct"], 6.0)
        self.assertEqual(report["delta"]["failure_count"], -1)
        self.assertEqual(report["delta"]["warning_count"], -1)
        self.assertIn("Target saves more tokens than base.", report["notes"])

    def test_sidecar_compare_evaluations_cli_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.json"
            target = Path(tmp) / "target.json"
            out = Path(tmp) / "compare.md"
            base.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.sidecar.evaluate.v1",
                        "status": "pass",
                        "summary": {
                            "item_count": 1,
                            "success_count": 1,
                            "failure_count": 0,
                            "warning_count": 0,
                            "original_tokens": 50,
                            "semantic_tokens": 45,
                            "saved_tokens": 5,
                            "saved_pct": 10.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            target.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.sidecar.evaluate.v1",
                        "status": "pass",
                        "summary": {
                            "item_count": 1,
                            "success_count": 1,
                            "failure_count": 0,
                            "warning_count": 0,
                            "original_tokens": 50,
                            "semantic_tokens": 40,
                            "saved_tokens": 10,
                            "saved_pct": 20.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = cli_main(["sidecar", "compare-evaluations", str(base), str(target), "--out", str(out)])

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("TokenSquash Sidecar Evaluation Compare", output)
            self.assertIn("Status: `improved`", output)
            self.assertTrue(out.exists())
            self.assertIn("Saved percent delta: `10.0%`", out.read_text(encoding="utf-8"))

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

    def test_reply_supports_session_field_aliases(self) -> None:
        aliases = AliasTable({}, {"commands": {"npm test": "c0"}, "risks": {"staging database not seeded": "r0"}})
        reply = encode_reply(
            "checked checkout",
            commands=["npm test"],
            risks=["staging database not seeded"],
        )

        wire = reply.to_wire(aliases=aliases)
        parsed = parse_reply_wire(wire, aliases=aliases)

        self.assertIn("c=c0", wire)
        self.assertIn("r=r0", wire)
        self.assertEqual(parsed.commands, ("npm test",))
        self.assertEqual(parsed.risks, ("staging database not seeded",))

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

    def test_learn_reply_aliases_selects_repeated_field_values(self) -> None:
        records = [
            {
                "id": "a",
                "summary": "checked search",
                "commands": ["npm test"],
                "risks": ["staging database not seeded"],
                "text": "Done. I checked search and ran npm test.",
            },
            {
                "id": "b",
                "summary": "checked checkout",
                "commands": ["npm test"],
                "risks": ["staging database not seeded"],
                "text": "Done. I checked checkout and ran npm test.",
            },
        ]

        report = learn_reply_aliases(records, counter="chars", min_count=2, max_field_values=2, max_path_prefixes=0)
        aliases = AliasTable.from_dict(report)

        selected = {(item["field"], item["value"]): item for item in report["selected_field_values"]}
        self.assertIn(("commands", "npm test"), selected)
        self.assertIn(("risks", "staging database not seeded"), selected)
        self.assertEqual(aliases.field_code_for_value("commands", "npm test"), selected[("commands", "npm test")]["code"])
        self.assertEqual(aliases.field_value_for_code("risks", selected[("risks", "staging database not seeded")]["code"]), "staging database not seeded")

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

    def test_capture_turn_record_writes_raw_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"

            report = capture_turn_record(
                prompt="fix login for dev@example.com",
                reply="Done. api_key=secret123",
                raw_output_path=raw,
                redacted_output_path=redacted,
                verification=["unit tests pass"],
            )

            self.assertEqual(report["schema_version"], "tokensquash.turns.capture.v1")
            self.assertEqual(report["status"], "written")
            self.assertEqual(report["id"], "turn-0001")
            self.assertEqual(report["turns"], 1)
            self.assertGreaterEqual(report["redaction_count"], 2)
            self.assertIn("dev@example.com", raw.read_text(encoding="utf-8"))
            redacted_text = redacted.read_text(encoding="utf-8")
            self.assertIn("[REDACTED_EMAIL]", redacted_text)
            self.assertIn("[REDACTED_SECRET]", redacted_text)

    def test_capture_turn_record_can_evaluate_report_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prompt_file = Path(tmp) / "prompt.txt"
            reply_file = Path(tmp) / "reply.txt"
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            eval_dir = Path(tmp) / "private-turns" / "eval-real"
            prompt_file.write_text("review packages/mobile/src/screens/login.tsx and summarize files", encoding="utf-8")
            reply_file.write_text("Done.", encoding="utf-8")

            report = capture_turn_record(
                prompt=prompt_file.read_text(encoding="utf-8"),
                reply=reply_file.read_text(encoding="utf-8"),
                raw_output_path=raw,
                redacted_output_path=redacted,
                evaluate=True,
                evaluation_output_dir=eval_dir,
                counter="chars",
            )

            self.assertEqual(report["status"], "pass")
            self.assertTrue(report["evaluated"])
            self.assertIsNotNone(report["evaluation"])
            self.assertTrue((eval_dir / "evaluation.json").exists())
            self.assertTrue((eval_dir / "aliases.json").exists())

    def test_turns_capture_cli_accepts_prompt_and_reply_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prompt_file = Path(tmp) / "prompt.txt"
            reply_file = Path(tmp) / "reply.txt"
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            eval_dir = Path(tmp) / "private-turns" / "eval-real"
            prompt_file.write_text("review packages/mobile/src/screens/login.tsx and summarize files", encoding="utf-8")
            reply_file.write_text("Done.", encoding="utf-8")
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = cli_main(
                    [
                        "turns",
                        "capture",
                        "--prompt-file",
                        str(prompt_file),
                        "--reply-file",
                        str(reply_file),
                        "--raw-out",
                        str(raw),
                        "--redacted-out",
                        str(redacted),
                        "--evaluate",
                        "--eval-out-dir",
                        str(eval_dir),
                        "--counter",
                        "chars",
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema_version"], "tokensquash.turns.capture.v1")
            self.assertTrue(raw.exists())
            self.assertTrue(redacted.exists())
            self.assertTrue((eval_dir / "evaluation.json").exists())

    def test_turns_capture_cli_accepts_stdin_prompt_and_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            stdout = StringIO()
            stdin = StringIO("fix login for dev@example.com\n---reply---\nDone. api_key=secret123\n")

            with patch("sys.stdin", stdin), redirect_stdout(stdout):
                code = cli_main(
                    [
                        "turns",
                        "capture",
                        "--stdin",
                        "--raw-out",
                        str(raw),
                        "--redacted-out",
                        str(redacted),
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema_version"], "tokensquash.turns.capture.v1")
            self.assertEqual(payload["id"], "turn-0001")
            self.assertGreaterEqual(payload["redaction_count"], 2)
            self.assertIn("dev@example.com", raw.read_text(encoding="utf-8"))
            self.assertIn("[REDACTED_EMAIL]", redacted.read_text(encoding="utf-8"))

    def test_turns_capture_cli_stdin_evaluate_markdown_summarizes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            eval_dir = Path(tmp) / "private-turns" / "eval-real"
            stdout = StringIO()
            stdin = StringIO("review packages/mobile/src/screens/login.tsx and summarize files\n---reply---\nDone.\n")

            with patch("sys.stdin", stdin), redirect_stdout(stdout):
                code = cli_main(
                    [
                        "turns",
                        "capture",
                        "--stdin",
                        "--raw-out",
                        str(raw),
                        "--redacted-out",
                        str(redacted),
                        "--evaluate",
                        "--eval-out-dir",
                        str(eval_dir),
                        "--counter",
                        "chars",
                    ]
                )

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("# TokenSquash Turn Capture", output)
            self.assertIn("- Prompt saved percent:", output)
            self.assertIn("- Reply saved percent:", output)
            self.assertIn("- Selected path aliases:", output)
            self.assertIn("- Alias setup tokens:", output)
            self.assertIn("## Top Win", output)
            self.assertIn("## Top Raw Wire Loss", output)
            self.assertTrue((eval_dir / "evaluation.json").exists())

    def test_turns_report_cli_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                '{"id":"t1","prompt":"review packages/mobile/src/screens/login.tsx and summarize files","reply":"Done. I reviewed packages/mobile/src/screens/login.tsx and ran `npm test`."}\n'
                '{"id":"t2","prompt":"review packages/mobile/src/screens/checkout.tsx and summarize files","reply":"Done. I reviewed packages/mobile/src/screens/checkout.tsx and ran `npm test`."}\n',
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_main(
                    [
                        "turns",
                        "report",
                        str(path),
                        "--counter",
                        "chars",
                        "--out",
                        str(Path(tmp) / "report.md"),
                    ]
                )

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("# TokenSquash Turn Report", output)
            self.assertIn("- Saved percent:", output)
            self.assertIn("## Top Win", output)
            self.assertIn("## Top Raw Wire Loss", output)
            self.assertIn("## Top Repeated Path Candidates", output)
            self.assertIn("## Top Repeated Field Candidates", output)
            self.assertTrue((Path(tmp) / "report.md").exists())

    def test_turns_report_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                '{"id":"t1","prompt":"review packages/mobile/src/screens/login.tsx and summarize files","reply":"Done. I reviewed packages/mobile/src/screens/login.tsx and ran `npm test`."}\n'
                '{"id":"t2","prompt":"review packages/mobile/src/screens/checkout.tsx and summarize files","reply":"Done. I reviewed packages/mobile/src/screens/checkout.tsx and ran `npm test`."}\n',
                encoding="utf-8",
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = cli_main(
                    [
                        "turns",
                        "report",
                        str(path),
                        "--counter",
                        "chars",
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema_version"], "tokensquash.turns.report.v1")
            self.assertIn("path", payload)
            self.assertEqual(payload["path"], str(path))
            summary = payload["summary"]
            self.assertIn("turn_count", summary)
            self.assertIn("saved_pct", summary)
            self.assertGreater(summary["wire_tokens"], 0)
            self.assertEqual(summary["wire_tokens"], payload["measure"]["benchmark"]["summary"]["wire_tokens"])
            self.assertIn("top_wins", payload)
            self.assertIn("top_raw_wire_losses", payload)
            self.assertIn("top_path_candidates", payload)
            self.assertIn("top_field_candidates", payload)
            self.assertEqual(summary["turn_count"], 2)

    def test_turns_compare_reports_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "report-before.json"
            target = Path(tmp) / "report-after.json"
            base.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.turns.report.v1",
                        "status": "pass",
                        "path": "private-turns/real.redacted-turns.jsonl",
                        "counter": "chars",
                        "adaptive": True,
                        "summary": {
                            "turn_count": 2,
                            "original_tokens": 100,
                            "wire_tokens": 90,
                            "squashed_tokens": 95,
                            "saved_tokens": 5,
                            "saved_pct": 5.0,
                            "prompt_saved_pct": 3.0,
                            "reply_saved_pct": 7.0,
                            "privacy_finding_count": 0,
                            "selected_path_prefix_count": 1,
                            "selected_field_value_count": 0,
                            "alias_saved_tokens_delta": 2,
                            "alias_saved_pct_delta": 1.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            target.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.turns.report.v1",
                        "status": "pass",
                        "path": "private-turns/real.redacted-turns.jsonl",
                        "counter": "chars",
                        "adaptive": True,
                        "summary": {
                            "turn_count": 3,
                            "original_tokens": 120,
                            "wire_tokens": 100,
                            "squashed_tokens": 108,
                            "saved_tokens": 12,
                            "saved_pct": 10.0,
                            "prompt_saved_pct": 6.0,
                            "reply_saved_pct": 14.0,
                            "privacy_finding_count": 1,
                            "selected_path_prefix_count": 2,
                            "selected_field_value_count": 1,
                            "alias_saved_tokens_delta": 5,
                            "alias_saved_pct_delta": 2.5,
                        },
                    }
                ),
                encoding="utf-8",
            )
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = cli_main(["turns", "compare-reports", str(base), str(target), "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema_version"], "tokensquash.turns.report.compare.v1")
            self.assertEqual(payload["status"], "improved")
            self.assertEqual(payload["base"]["report_path"], str(base))
            self.assertEqual(payload["target"]["report_path"], str(target))
            self.assertEqual(payload["delta"]["saved_pct"], 5.0)
            self.assertEqual(payload["delta"]["saved_tokens"], 7)
            self.assertEqual(payload["delta"]["prompt_saved_pct"], 3.0)
            self.assertEqual(payload["delta"]["reply_saved_pct"], 7.0)
            self.assertEqual(payload["delta"]["alias_saved_tokens_delta"], 3)
            self.assertEqual(payload["delta"]["selected_path_prefix_count"], 1)
            self.assertEqual(payload["delta"]["selected_field_value_count"], 1)

    def test_turns_compare_reports_cli_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "report-before.json"
            target = Path(tmp) / "report-after.json"
            out = Path(tmp) / "report-compare.md"
            base.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.turns.report.v1",
                        "summary": {
                            "saved_pct": 4.0,
                            "saved_tokens": 8,
                            "prompt_saved_pct": 2.0,
                            "reply_saved_pct": 6.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            target.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.turns.report.v1",
                        "summary": {
                            "saved_pct": 3.5,
                            "saved_tokens": 7,
                            "prompt_saved_pct": 2.0,
                            "reply_saved_pct": 5.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = cli_main(["turns", "compare-reports", str(base), str(target), "--out", str(out)])

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("# TokenSquash Turn Report Compare", output)
            self.assertIn("- Status: `regressed`", output)
            self.assertIn("- Saved percent delta: `-0.5%`", output)
            self.assertIn("- Saved token delta: `-1`", output)
            self.assertTrue(out.exists())
            self.assertEqual(out.read_text(encoding="utf-8"), output)

    def test_turns_suggestions_cli_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.turns.report.v1",
                        "status": "pass",
                        "path": "private-turns/real.redacted-turns.jsonl",
                        "counter": "chars",
                        "adaptive": True,
                        "summary": {
                            "turn_count": 2,
                            "saved_tokens": 10,
                            "saved_pct": 5.0,
                            "privacy_finding_count": 1,
                            "selected_path_prefix_count": 1,
                            "selected_field_value_count": 0,
                            "alias_saved_tokens_delta": 6,
                            "alias_saved_pct_delta": 2.0,
                            "break_even_corpora": 2,
                        },
                        "top_path_candidates": [
                            {
                                "value": "packages/mobile/src/screens/",
                                "count": 2,
                                "estimated_new_saved_tokens": 30,
                            }
                        ],
                        "top_field_candidates": [
                            {
                                "field": "commands",
                                "value": "npm test",
                                "count": 2,
                                "estimated_new_saved_tokens": 12,
                            }
                        ],
                        "top_raw_wire_losses": [
                            {
                                "id": "short",
                                "wire_saved_tokens": -5,
                                "saved_tokens": 0,
                                "tags": ["raw_wire_loss"],
                                "prompt_preview": "ok",
                                "reply_preview": "Done.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = cli_main(["turns", "suggestions", str(report), "--limit", "4", "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema_version"], "tokensquash.turns.suggestions.v1")
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["summary"]["suggestion_count"], 4)
            self.assertEqual(payload["suggestions"][0]["type"], "path_alias_candidate")
            self.assertEqual(payload["suggestions"][0]["estimated_saved_tokens"], 30)
            self.assertEqual(
                [item["type"] for item in payload["suggestions"]],
                ["path_alias_candidate", "field_alias_candidate", "alias_impact", "raw_wire_loss"],
            )

    def test_turns_suggestions_cli_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            out = Path(tmp) / "suggestions.md"
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "tokensquash.turns.report.v1",
                        "path": "private-turns/real.redacted-turns.jsonl",
                        "summary": {
                            "saved_tokens": 0,
                            "saved_pct": 0.0,
                        },
                        "top_raw_wire_losses": [
                            {
                                "id": "short",
                                "wire_saved_tokens": -4,
                                "saved_tokens": 0,
                                "tags": ["raw_wire_loss"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = cli_main(["turns", "suggestions", str(report), "--out", str(out)])

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("# TokenSquash Turn Suggestions", output)
            self.assertIn("Inspect raw-wire loss", output)
            self.assertIn("- Type: `raw_wire_loss`", output)
            self.assertTrue(out.exists())
            self.assertEqual(out.read_text(encoding="utf-8"), output)

    def test_private_turn_storage_is_gitignored(self) -> None:
        ignore_text = Path(".gitignore").read_text(encoding="utf-8")

        self.assertIn("private-turns/", ignore_text.splitlines())

    def test_capture_turn_record_rejects_duplicate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"

            capture_turn_record(
                prompt="fix login",
                reply="Done.",
                raw_output_path=raw,
                redacted_output_path=redacted,
                item_id="same",
            )

            with self.assertRaisesRegex(ValueError, "turn id already exists"):
                capture_turn_record(
                    prompt="fix checkout",
                    reply="Done.",
                    raw_output_path=raw,
                    redacted_output_path=redacted,
                    item_id="same",
                )

    def test_import_turn_corpus_writes_raw_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            rows = [
                {
                    "id": "seed-1",
                    "prompt": "fix login for dev@example.com",
                    "reply": "Done. api_key=secret123",
                    "verification": ["unit tests pass"],
                },
                {
                    "prompt": "review src/checkout.py",
                    "assistant": {
                        "status": "done",
                        "summary": "Reviewed checkout.",
                        "files": ["src/checkout.py"],
                        "commands": ["python -m unittest discover -s tests"],
                    },
                },
            ]
            source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            report = import_turn_corpus(source, raw_output_path=raw, redacted_output_path=redacted)
            records = load_turn_records(raw)

            self.assertEqual(report["schema_version"], "tokensquash.turns.import.v1")
            self.assertEqual(report["status"], "written")
            self.assertEqual(report["imported_turns"], 2)
            self.assertEqual(report["imported_ids"], ["seed-1", "turn-0002"])
            self.assertEqual(report["turns"], 2)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[1]["reply_text"], "Reviewed checkout.")
            self.assertIn("dev@example.com", raw.read_text(encoding="utf-8"))
            redacted_text = redacted.read_text(encoding="utf-8")
            self.assertIn("[REDACTED_EMAIL]", redacted_text)
            self.assertIn("[REDACTED_SECRET]", redacted_text)

    def test_import_turn_corpus_allocates_ids_after_existing_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            append_turn_record(raw, prompt="existing turn", reply="Done.")
            rows = [
                {"prompt": "first imported turn", "reply": "Done."},
                {"prompt": "second imported turn", "reply": "Done."},
            ]
            source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            report = import_turn_corpus(source, raw_output_path=raw, redacted_output_path=redacted)

            self.assertEqual(report["imported_ids"], ["turn-0002", "turn-0003"])
            self.assertEqual(report["first_id"], "turn-0002")
            self.assertEqual(report["last_id"], "turn-0003")
            self.assertEqual(report["turns"], 3)

    def test_import_turn_corpus_rejects_duplicate_id_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            append_turn_record(raw, prompt="existing turn", reply="Done.", item_id="same")
            rows = [
                {"prompt": "would otherwise import", "reply": "Done."},
                {"id": "same", "prompt": "duplicate import", "reply": "Done."},
            ]
            source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "turn id already exists"):
                import_turn_corpus(source, raw_output_path=raw, redacted_output_path=redacted)

            self.assertEqual(len(load_turn_records(raw)), 1)
            self.assertFalse(redacted.exists())

    def test_turns_import_cli_evaluates_report_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            raw = Path(tmp) / "private-turns" / "real.jsonl"
            redacted = Path(tmp) / "private-turns" / "real.redacted-turns.jsonl"
            eval_dir = Path(tmp) / "private-turns" / "eval-real"
            rows = [
                {
                    "prompt": "review packages/mobile/src/screens/login.tsx and summarize files",
                    "reply": "Done. I reviewed packages/mobile/src/screens/login.tsx.",
                }
            ]
            source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = cli_main(
                    [
                        "turns",
                        "import",
                        str(source),
                        "--raw-out",
                        str(raw),
                        "--redacted-out",
                        str(redacted),
                        "--evaluate",
                        "--eval-out-dir",
                        str(eval_dir),
                        "--counter",
                        "chars",
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["schema_version"], "tokensquash.turns.import.v1")
            self.assertEqual(payload["imported_turns"], 1)
            self.assertTrue(payload["evaluated"])
            self.assertIn("saved_pct", payload["summary"])
            self.assertTrue(raw.exists())
            self.assertTrue(redacted.exists())
            self.assertTrue((eval_dir / "evaluation.json").exists())
            self.assertTrue((eval_dir / "aliases.json").exists())

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

    def test_mine_turn_patterns_includes_prompt_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"a","prompt":"review packages/mobile/src/screens/login.tsx and summarize files","reply":"Done."}\n'
                '{"id":"b","prompt":"review packages/mobile/src/screens/checkout.tsx and summarize files","reply":"Done."}\n',
                encoding="utf-8",
            )

            report = mine_turn_patterns(path, counter="chars", min_count=2)
            prompt_path = next(item for item in report["path_patterns"] if item["value"] == "packages/mobile/src/screens/")

            self.assertEqual(report["summary"]["prompt_path_record_count"], 2)
            self.assertEqual(prompt_path["pattern_type"], "path_prefix")
            self.assertGreater(prompt_path["estimated_new_saved_tokens"], 0)

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

    def test_learn_turn_aliases_uses_prompt_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"a","prompt":"review packages/mobile/src/screens/login.tsx and summarize files","reply":"Done."}\n'
                '{"id":"b","prompt":"review packages/mobile/src/screens/checkout.tsx and summarize files","reply":"Done."}\n',
                encoding="utf-8",
            )

            report = learn_turn_aliases(path, counter="chars", min_count=2, max_path_prefixes=1)
            aliases = AliasTable.from_dict(report)

            self.assertEqual(report["summary"]["prompt_path_record_count"], 2)
            self.assertEqual(report["summary"]["selected_path_prefix_count"], 1)
            self.assertTrue(aliases.encode_path("packages/mobile/src/screens/login.tsx").startswith("@0/"))

    def test_turn_alias_impact_reports_prompt_path_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"a","prompt":"review packages/mobile/src/screens/login.tsx and summarize files","reply":"Done."}\n'
                '{"id":"b","prompt":"review packages/mobile/src/screens/checkout.tsx and summarize files","reply":"Done."}\n',
                encoding="utf-8",
            )

            report = benchmark_turn_alias_impact(
                path,
                counter="chars",
                target_savings_pct=0.0,
                max_path_prefixes=1,
                max_field_values=0,
            )

            self.assertEqual(report["status"], "improved")
            self.assertEqual(report["summary"]["selected_path_prefix_count"], 1)
            self.assertGreater(report["summary"]["saved_tokens_delta"], 0)
            self.assertGreater(
                report["aliased"]["prompt_report"]["summary"]["wire_saved_tokens"],
                report["baseline"]["prompt_report"]["summary"]["wire_saved_tokens"],
            )

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

    def test_turn_alias_impact_reports_field_alias_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            path.write_text(
                '{"id":"a","prompt":"check search","reply":"Done. I ran `npm run integration -- --project customer-portal`. Risk: staging database not seeded."}\n'
                '{"id":"b","prompt":"check checkout","reply":"Done. I ran `npm run integration -- --project customer-portal`. Risk: staging database not seeded."}\n',
                encoding="utf-8",
            )

            report = benchmark_turn_alias_impact(
                path,
                counter="chars",
                target_savings_pct=0.0,
                max_path_prefixes=0,
                max_field_values=2,
            )

            self.assertEqual(report["status"], "improved")
            self.assertEqual(report["summary"]["selected_path_prefix_count"], 0)
            self.assertGreaterEqual(report["summary"]["selected_field_value_count"], 1)
            self.assertGreater(report["summary"]["saved_tokens_delta"], 0)

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

    def test_evaluate_turn_corpus_writes_report_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turns.jsonl"
            out_dir = Path(tmp) / "eval"
            path.write_text(
                '{"id":"a","prompt":"review packages/mobile/src/screens/login.tsx and summarize files","reply":"Done."}\n'
                '{"id":"b","prompt":"review packages/mobile/src/screens/checkout.tsx and summarize files","reply":"Done."}\n',
                encoding="utf-8",
            )

            report = evaluate_turn_corpus(
                path,
                counter="chars",
                target_savings_pct=0.0,
                max_path_prefixes=1,
                max_field_values=0,
                out_dir=out_dir,
            )

            self.assertEqual(report["schema_version"], "tokensquash.turns.evaluate.v1")
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["summary"]["turn_count"], 2)
            self.assertEqual(report["summary"]["selected_path_prefix_count"], 1)
            self.assertGreater(report["summary"]["alias_saved_tokens_delta"], 0)
            for key in ("evaluation", "validation", "measure", "mine", "alias_impact", "bench", "alias_table"):
                self.assertIn(key, report["outputs"])
                self.assertTrue(Path(report["outputs"][key]).exists())

    def test_evaluate_turn_corpus_reports_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-turns.jsonl"
            out_dir = Path(tmp) / "eval"
            path.write_text('{"id":"t1","prompt":"missing reply"}\n', encoding="utf-8")

            report = evaluate_turn_corpus(path, out_dir=out_dir)

            self.assertEqual(report["status"], "fail")
            self.assertIsNone(report["measure"])
            self.assertTrue((out_dir / "evaluation.json").exists())
            self.assertTrue((out_dir / "validation.json").exists())


if __name__ == "__main__":
    unittest.main()
