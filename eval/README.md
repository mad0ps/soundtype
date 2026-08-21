# Eval harness (issue #6)

Private-corpus evaluation for SoundType. Corpus/runs/reports are gitignored —
only code is public. All commands run from repo root on the Mac.

    # 1. collect/refresh corpus (phone via adb + 2026-08-21 backup)
    .venv/bin/python -m eval.collect

    # 2. decode with a model
    .venv/bin/python -m eval.run_model --model-dir models/parakeet-int8 --name parakeet-whole --mode whole

    # 3. compare two runs
    .venv/bin/python -m eval.report runs/parakeet-whole.jsonl runs/gigaam-whole.jsonl

Model downloads: see "Models" section at the bottom.
