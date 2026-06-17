# Sidecar Meaning Rubric

The local-AI sidecar is experimental. Treat its semantic JSON as a proposal to
inspect, not as the canonical TokenSquash protocol.

In short, deterministic `ts1` and `tr1` codecs remain the source of truth.

Use this rubric when reviewing `sidecar roundtrip`, `sidecar evaluate`,
`sidecar review`, `sidecar gate`, or `sidecar certify` evidence.

## Review Loop

Start with one turn:

```powershell
python -m tokensquash sidecar roundtrip prompt "fix the login bug, keep the diff small, run tests" --model llama3.2:3b --counter chars --json
python -m tokensquash sidecar roundtrip reply "Done. I fixed login in src/auth.py and tests pass." --model llama3.2:3b --counter chars --json
```

Then review a small redacted corpus:

```powershell
python -m tokensquash sidecar evaluate private-turns\real.redacted-turns.jsonl --mode both --limit 10 --model llama3.2:3b --counter chars --out-dir private-turns\sidecar-eval --json
python -m tokensquash sidecar review private-turns\sidecar-eval\evaluation.json
python -m tokensquash sidecar gate private-turns\sidecar-eval\review.json --min-saved-pct 0.5 --max-review-count 0 --json
```

Use `sidecar certify` when the run needs a durable review, gate, suggestions,
and certification folder:

```powershell
python -m tokensquash sidecar certify private-turns\sidecar-eval\evaluation.json --out-dir private-turns\sidecar-certification --json
```

## Pass

A sidecar row can be treated as a pass when all of these hold:

- the decoded text preserves the original intent or reply result
- paths, commands, verification requirements, risks, and next steps are not
  invented
- important constraints such as "keep the diff small", "do not change public
  API", or "run tests" survive the round trip
- the row has no missing-field or placeholder warnings
- the semantic JSON is actually shorter under the chosen counter

## Watch

Mark the row as watch when the decoded text is usable but needs human judgment:

- the gist is right but less specific
- a low-risk field is omitted
- the decoded text becomes generic, such as "complete the task"
- the row saves tokens only because details were compressed aggressively
- the model used a different but equivalent wording for a command or file

Watch rows can still be useful for research, but they should not be counted as
clean wins without review notes.

## Fail

Treat the row as a fail when any of these occur:

- the decoded text changes the task or result
- a required file, command, verification step, risk, or next step disappears
- the model invents files, commands, tests, or success claims
- schema placeholders such as `<=5 words`, `constraint1`, or `returns:` appear
  in the semantic payload
- the row has warnings that would mislead an automated consumer
- token savings depend on dropping meaning rather than representing it compactly

## Corpus-Level Bar

For a corpus-level sidecar experiment, review these together:

- saved percent and saved token count
- failure count
- warning count
- review finding count
- missing-field count
- generic decoded text count
- worst examples, not just averages

Prefer a boring, slightly smaller saving with clean meaning preservation over a
larger saving that produces more review findings. Token savings alone are not
success. Token savings alone are not success unless decoded meaning, warnings,
and failure counts support the result.

## Public Claims

Public notes should describe sidecar results as experimental unless the saved
evaluation, review, gate, and certification evidence all support the claim. Do
not claim production-scale savings from synthetic data or from a corpus whose
decoded meaning has not been reviewed. Use the [claims policy](claims-policy.md)
for the required evidence before making public sidecar claims.
