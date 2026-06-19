# Command Map

Use this page when you know what you want to do, but not which TokenSquash
command to run first.

For the interactive-style overview:

```powershell
python -m tokensquash guide
```

## I Want To Try TokenSquash Quickly

```powershell
python -m tokensquash demo
```

This uses the packaged public sample corpus. It does not need private data,
Ollama, API keys, or a hosted service.

## I Want To Set Up Private Local Storage

```powershell
python -m tokensquash init
```

This creates ignored private folders, updates `.gitignore`, and writes starter
prompt/reply files under `private-turns/`.

## I Have One Real Prompt And Reply

```powershell
python -m tokensquash turns first-run --prompt-file private-turns\prompt.example.txt --reply-file private-turns\reply.example.txt
```

This captures one raw turn, regenerates the redacted corpus, evaluates it,
writes a scorecard, and prints the next commands to run.

## I Have A Redacted Turn Corpus

```powershell
python -m tokensquash turns scorecard private-turns\real.redacted-turns.jsonl
python -m tokensquash turns certify private-turns\real.redacted-turns.jsonl
```

Use this when you want evidence that can be inspected, gated, and compared over
time.

## I Need A Public Claim Review

```powershell
python -m tokensquash turns claim-pack private-turns\certification --out-dir private-turns\claim-pack
```

Claim packs are intentionally cautious. They should say what the evidence
supports and list the limits beside it.

## I Want To Try The Experimental Sidecar

```powershell
python -m tokensquash sidecar roundtrip prompt "fix the login bug, run tests, and summarize risks"
```

Sidecar output is not canonical. Use `sidecar review`, `sidecar gate`, and
`sidecar certify` before treating sidecar savings as meaningful.

## I Need Release Evidence

```powershell
python -m tokensquash release-candidate --require-clean
python -m tokensquash verify-release-candidate private-turns\release-candidate --require-release-candidate-pass
python -m tokensquash release-assets private-turns\release-candidate --tag vX.Y.Z
python -m tokensquash verify-release-assets private-turns\release-assets\release-assets.json
```

Use the release flow only after local tests, strict doctor, readiness, and
release-candidate evidence are clean.
