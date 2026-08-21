# Eval harness (issue #6)

Private-corpus evaluation for SoundType. Corpus/runs/reports are gitignored —
only code is public. All commands run from repo root on the Mac.

    # 1. collect/refresh corpus (phone via adb + 2026-08-21 backup)
    .venv/bin/python -m eval.collect

    # 2. decode with a model
    .venv/bin/python -m eval.run_model --model-dir eval/models/parakeet-int8 --name parakeet-whole --mode whole

    # 3. compare two runs
    .venv/bin/python -m eval.report eval/runs/parakeet-whole.jsonl eval/runs/gigaam-whole.jsonl

Model downloads: see "Models" section at the bottom.

## Models

    # Parakeet TDT 0.6B v3 int8 (current prod model) + silero VAD:
    #   see Task-7 commands in docs/plans/2026-08-22-eval-harness.md
    # GigaAM-v3 e2e_rnnt int8 (candidate, issue #12):
    #   https://huggingface.co/Smirnov75/GigaAM-v3-sherpa-onnx — download
    #   encoder/decoder/joiner int8 + tokens.txt into eval/models/gigaam-e2e-int8/
