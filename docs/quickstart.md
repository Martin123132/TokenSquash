# Quickstart

This guide gets TokenSquash running from a fresh checkout and shows the shape of
the reports without using private data, API keys, or a local model.

## Install

```powershell
python -m pip install -e .
```

For exact tokenizer checks, install the optional tokenizer extra:

```powershell
python -m pip install -e ".[tokenizer]"
```

## Run The Public Demo

```powershell
python -m tokensquash demo
```

The demo uses the packaged public sample corpus at
`examples\sample-turns.jsonl`. It reports:

- status
- turn count
- saved tokens and saved percent
- privacy finding count
- commands for deeper evaluation

Write the demo evidence to ignored local storage:

```powershell
python -m tokensquash demo --counter chars --out-dir private-turns\demo-output --json
python -m tokensquash turns scorecard examples\sample-turns.jsonl --counter chars --json --out private-turns\scorecards\sample.json
python -m tokensquash turns scorecard-pack examples\sample-turns.jsonl --counter chars --out-dir private-turns\scorecard-pack --json
```

`private-turns/` is ignored local storage and should not be committed.

## Ask For The Right Path

```powershell
python -m tokensquash guide
python -m tokensquash guide --path first-turn
```

The guide maps common jobs to the next command: public demo, first real turn,
corpus evidence, sidecar experiments, or release verification.

## Prepare Private Storage

```powershell
python -m tokensquash init
```

This creates ignored private folders, updates `.gitignore`, and writes starter
files under `private-turns/` for the first real turn workflow.

## Capture A First Real Turn

```powershell
python -m tokensquash turns first-run --prompt-file private-turns\prompt.example.txt --reply-file private-turns\reply.example.txt
```

`turns first-run` captures the raw turn locally, regenerates the redacted
corpus, evaluates it, writes a scorecard, and prints next commands.

## Encode And Decode A Prompt

```powershell
python -m tokensquash encode "fix the login bug, keep the diff small, run tests"
python -m tokensquash decode 'ts1 f "login bug" c=sd v=t'
```

`ts1` is deterministic. It is the canonical compact prompt format.

## Encode And Decode A Reply

```powershell
python -m tokensquash reply encode --summary "fixed login bug" --file src/auth.py --verify "unit tests pass" --command "python -m unittest discover -s tests" --risk none
python -m tokensquash reply decode 'tr1 "fixed login bug" f=src/auth.py v=t c=pyunit r=0'
```

`tr1` is deterministic. It is the canonical compact reply format.

## Inspect The Product Manifest

```powershell
python -m tokensquash about --json
```

The manifest lists command groups, schema versions, readiness commands,
governance documents, license metadata, and packaged demo data.

## Run Health Checks

```powershell
python -m tokensquash doctor
python -m tokensquash doctor --strict
```

`doctor --strict` checks the deterministic demo, packaged sample corpus,
workspace init, governance docs, product manifest, and certification workflow.

## Run A Readiness Pack

```powershell
python -m tokensquash readiness --out-dir private-turns\readiness
python -m tokensquash verify-readiness private-turns\readiness --require-readiness-pass
```

The readiness pack is the first full local evidence bundle. It includes nested
doctor, demo, certification, release-check, and verification artifacts.

## Next Steps

- Use [real-turn-workflow.md](real-turn-workflow.md) for private prompt/reply
  corpora.
- Use [evidence-packs.md](evidence-packs.md) when a result needs to be gated or
  certified.
- Use [sidecar-ollama.md](sidecar-ollama.md) only after the deterministic core
  workflow is clear.
