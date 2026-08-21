# Eval Harness Implementation Plan (issue #6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A repeatable evaluation harness that measures dictation quality (WER/CER/term recall) on Khan's real recordings, so model and pipeline changes (#12 GigaAM switch, #14 overlap+LCS, #13 denoise) are decided by numbers, not feel.

**Architecture:** A standalone `eval/` package inside the repo, run on the Mac (not the phone). It (1) collects a private corpus (audio + seed reference texts) from the phone history and the 2026-08-21 backup, (2) decodes the corpus with any sherpa-onnx offline model in two modes (whole-file / prod-like VAD segmentation), (3) computes normalized WER/CER + term recall, and (4) renders a markdown comparison report between two runs. Corpus, runs, and reports are private (gitignored) — only harness code is committed to the public repo.

**Tech Stack:** Python 3 (repo `.venv` on Mac), `sherpa-onnx` (pip, arm64 wheel), `jiwer` (WER/CER), stdlib `wave` (16 kHz mono s16 WAVs), `adb` for corpus pull.

## Global Constraints

- Public repo: **no audio, no dictation texts, no reports may be committed** — `eval/corpus/`, `eval/runs/`, `eval/reports/` must be gitignored before any data lands there.
- Phone keeps only the last 20 recordings (`AUDIO_KEEP = 20` in `py/backend.py`) — `collect.py` must be idempotent and additive, so repeated runs accumulate a growing corpus.
- All dev deps go into `.venv` only; nothing new ships to the phone.
- WAV format: 16000 Hz, mono, int16 (`RATE`/`CHANNELS` in `py/backend.py`).
- adb binary: `/Users/n0mads/Downloads/platform-tools/adb` (not in PATH); phone data dir: `/home/phablet/.local/share/soundtype.n0madd3v0ps/`.
- Backup corpus source: `/Users/n0mads/Downloads/platform-tools/ut-build/phone-backup-2026-08-21/` (history.jsonl, 51 records + `audio/`, 24 wavs).
- History line format: `{"ts": <float unix>, "text": "<str>"}`; matching audio file: `audio/<int(ts*1000)>.wav`.
- Commit messages in English, no Co-Authored-By.

## File Structure

```
eval/
  __init__.py          # empty, makes eval importable for tests
  collect.py           # corpus collection: adb pull + backup merge → corpus/ + manifest.jsonl
  normalize.py         # Russian text normalization for scoring
  metrics.py           # WER/CER via jiwer + term recall
  run_model.py         # decode corpus with a sherpa-onnx model (whole|vad modes) → runs/<name>.jsonl
  report.py            # compare two runs (or run vs refs) → markdown report
  terms.txt            # seed list of Khan's domain terms (committed; contains no private text)
  README.md            # how to collect, run, compare; model download commands
  corpus/              # PRIVATE (gitignored): <id>.wav + <id>.ref.txt + manifest.jsonl
  runs/                # PRIVATE (gitignored): decode outputs
  reports/             # PRIVATE (gitignored): markdown reports
tests/
  test_eval_collect.py
  test_eval_normalize.py
  test_eval_metrics.py
  test_eval_run_model.py
  test_eval_report.py
```

---

### Task 1: Privacy guard + package skeleton

**Files:**
- Modify: `.gitignore`
- Create: `eval/__init__.py`, `eval/README.md`, `eval/terms.txt`

**Interfaces:**
- Produces: importable `eval` package; gitignored data dirs.

- [ ] **Step 1: Add gitignore rules**

Append to `.gitignore`:

```
# eval harness private data (Khan's voice and texts — never commit)
eval/corpus/
eval/runs/
eval/reports/
```

- [ ] **Step 2: Create skeleton**

`eval/__init__.py` — empty file.

`eval/terms.txt` (one term per line, `#` comments allowed):

```
# domain terms checked by recall metric — extend freely
клод
убунту
терминал
демон
клавиатура
диктовка
коммит
```

`eval/README.md`:

```markdown
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
```

- [ ] **Step 3: Prove the guard**

Run: `mkdir -p eval/corpus && touch eval/corpus/probe.wav && git status --porcelain | grep -c probe.wav; rm eval/corpus/probe.wav`
Expected: `0` (file invisible to git)

- [ ] **Step 4: Commit**

```bash
git add .gitignore eval/__init__.py eval/README.md eval/terms.txt
git commit -m "eval: package skeleton with private-data gitignore (issue #6)"
```

---

### Task 2: Corpus collector

**Files:**
- Create: `eval/collect.py`
- Test: `tests/test_eval_collect.py`

**Interfaces:**
- Produces: `merge_source(history_path, audio_dir, corpus_dir, source) -> int` (returns number of NEW clips added), CLI `python -m eval.collect [--corpus-dir eval/corpus]`.
- Manifest: `eval/corpus/manifest.jsonl`, one line per clip: `{"id": "<ms-ts>", "wav": "<id>.wav", "ref": "<id>.ref.txt", "source": "phone"|"backup", "verified": false}`.
- Later tasks rely on: manifest schema above; ref files are plain UTF-8 text.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval_collect.py
import json, wave, os
from eval.collect import merge_source, load_manifest

def _mk_wav(path, seconds=0.1):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b'\x00\x00' * int(16000 * seconds))

def _mk_source(tmp_path, ts, text):
    hist = tmp_path / 'history.jsonl'
    with open(hist, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': ts, 'text': text}, ensure_ascii=False) + '\n')
    audio = tmp_path / 'audio'; audio.mkdir(exist_ok=True)
    _mk_wav(audio / ('%d.wav' % int(ts * 1000)))
    return hist, audio

def test_merge_creates_clip_and_manifest(tmp_path):
    hist, audio = _mk_source(tmp_path / 'src', 1000.5, 'привет мир')
    corpus = tmp_path / 'corpus'
    added = merge_source(hist, audio, corpus, source='phone')
    assert added == 1
    assert (corpus / '1000500.wav').exists()
    assert (corpus / '1000500.ref.txt').read_text(encoding='utf-8') == 'привет мир'
    m = load_manifest(corpus)
    assert m == [{'id': '1000500', 'wav': '1000500.wav', 'ref': '1000500.ref.txt',
                  'source': 'phone', 'verified': False}]

def test_merge_is_idempotent_and_keeps_edited_refs(tmp_path):
    hist, audio = _mk_source(tmp_path / 'src', 1000.5, 'привет мир')
    corpus = tmp_path / 'corpus'
    merge_source(hist, audio, corpus, source='phone')
    (corpus / '1000500.ref.txt').write_text('привет, мир!', encoding='utf-8')  # Khan corrected it
    added = merge_source(hist, audio, corpus, source='phone')
    assert added == 0
    assert (corpus / '1000500.ref.txt').read_text(encoding='utf-8') == 'привет, мир!'
    assert len(load_manifest(corpus)) == 1

def test_merge_skips_records_without_audio(tmp_path):
    src = tmp_path / 'src'; src.mkdir()
    hist = src / 'history.jsonl'
    hist.write_text(json.dumps({'ts': 2000.0, 'text': 'без аудио'}) + '\n')
    (src / 'audio').mkdir()
    added = merge_source(hist, src / 'audio', tmp_path / 'corpus', source='backup')
    assert added == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_eval_collect.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.collect'`

- [ ] **Step 3: Implement `eval/collect.py`**

```python
"""Corpus collection: history+audio from the phone and the Aug-21 backup.

Idempotent and additive: existing clips (and hand-corrected .ref.txt files)
are never overwritten. Phone keeps only the last 20 recordings, so run this
often — the corpus only grows.
"""
import argparse, json, os, shutil, subprocess, tempfile

ADB = '/Users/n0mads/Downloads/platform-tools/adb'
PHONE_DATA = '/home/phablet/.local/share/soundtype.n0madd3v0ps'
BACKUP_DIR = '/Users/n0mads/Downloads/platform-tools/ut-build/phone-backup-2026-08-21'
DEFAULT_CORPUS = os.path.join(os.path.dirname(__file__), 'corpus')


def load_manifest(corpus_dir):
    path = os.path.join(corpus_dir, 'manifest.jsonl')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def _append_manifest(corpus_dir, entry):
    with open(os.path.join(corpus_dir, 'manifest.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def merge_source(history_path, audio_dir, corpus_dir, source):
    os.makedirs(corpus_dir, exist_ok=True)
    known = {e['id'] for e in load_manifest(corpus_dir)}
    added = 0
    with open(history_path, encoding='utf-8') as f:
        records = [json.loads(line) for line in f if line.strip()]
    for rec in records:
        clip_id = '%d' % int(rec['ts'] * 1000)
        wav_src = os.path.join(str(audio_dir), clip_id + '.wav')
        if clip_id in known or not os.path.exists(wav_src):
            continue
        text = (rec.get('text') or '').strip()
        if not text:
            continue
        shutil.copy2(wav_src, os.path.join(str(corpus_dir), clip_id + '.wav'))
        with open(os.path.join(str(corpus_dir), clip_id + '.ref.txt'), 'w',
                  encoding='utf-8') as rf:
            rf.write(text)
        _append_manifest(str(corpus_dir), {
            'id': clip_id, 'wav': clip_id + '.wav', 'ref': clip_id + '.ref.txt',
            'source': source, 'verified': False})
        known.add(clip_id)
        added += 1
    return added


def collect_phone(corpus_dir):
    """adb pull history+audio into a temp dir, then merge."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([ADB, 'pull', PHONE_DATA + '/history.jsonl', tmp], check=True)
        subprocess.run([ADB, 'pull', PHONE_DATA + '/audio', tmp], check=True)
        return merge_source(os.path.join(tmp, 'history.jsonl'),
                            os.path.join(tmp, 'audio'), corpus_dir, source='phone')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus-dir', default=DEFAULT_CORPUS)
    ap.add_argument('--no-phone', action='store_true', help='backup only')
    args = ap.parse_args()
    total = 0
    if os.path.isdir(BACKUP_DIR):
        n = merge_source(os.path.join(BACKUP_DIR, 'history.jsonl'),
                         os.path.join(BACKUP_DIR, 'audio'),
                         args.corpus_dir, source='backup')
        print('backup: +%d clips' % n); total += n
    if not args.no_phone:
        n = collect_phone(args.corpus_dir)
        print('phone: +%d clips' % n); total += n
    print('corpus now: %d clips' % len(load_manifest(args.corpus_dir)))


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_eval_collect.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add eval/collect.py tests/test_eval_collect.py
git commit -m "eval: idempotent corpus collector from phone history and backup"
```

---

### Task 3: Russian normalization for scoring

**Files:**
- Create: `eval/normalize.py`
- Test: `tests/test_eval_normalize.py`

**Interfaces:**
- Produces: `normalize(text: str, fold_yo: bool = True) -> str` — lowercase, strip punctuation to spaces, collapse whitespace, ё→е when `fold_yo`. Used by metrics and report.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval_normalize.py
from eval.normalize import normalize

def test_lowercase_and_punct():
    assert normalize('Привет, мир! Как дела?') == 'привет мир как дела'

def test_yo_folding_default():
    assert normalize('Всё ещё') == 'все еще'

def test_yo_kept_when_disabled():
    assert normalize('Всё ещё', fold_yo=False) == 'всё ещё'

def test_dash_and_ellipsis_and_numbers():
    assert normalize('Так — вот… 25 штук') == 'так вот 25 штук'

def test_collapse_whitespace_and_newlines():
    assert normalize('раз\nдва   три ') == 'раз два три'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_eval_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `eval/normalize.py`**

```python
"""Text normalization for fair WER: strips exactly the formatting layers
that differ between models (case, punctuation, ё) so WER measures words."""
import re

# keep letters/digits (any script), everything else becomes a space
_NON_WORD = re.compile(r'[^\w]+', re.UNICODE)


def normalize(text, fold_yo=True):
    text = text.lower()
    if fold_yo:
        text = text.replace('ё', 'е')
    text = _NON_WORD.sub(' ', text)
    return ' '.join(text.split())
```

Note: `\w` includes `_`; underscores don't occur in dictation output, no special-casing needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_eval_normalize.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add eval/normalize.py tests/test_eval_normalize.py
git commit -m "eval: russian text normalization for scoring"
```

---

### Task 4: Metrics — WER/CER + term recall

**Files:**
- Create: `eval/metrics.py`
- Test: `tests/test_eval_metrics.py`
- Modify: `.venv` (install `jiwer`)

**Interfaces:**
- Consumes: `normalize()` from Task 3.
- Produces:
  - `score_pair(ref: str, hyp: str, fold_yo=True) -> dict` → `{'wer': float, 'cer': float, 'ref_words': int}` (computed on normalized text).
  - `term_recall(refs: list[str], hyps: list[str], terms: list[str]) -> dict` → `{term: {'ref': int, 'hit': int}}` — occurrences in normalized refs vs how many of those survive in the paired hyp (capped per pair).
  - `load_terms(path) -> list[str]` — reads terms.txt, skips blanks/comments.

- [ ] **Step 1: Install jiwer**

Run: `.venv/bin/pip install jiwer`
Expected: success; `.venv/bin/python -c "import jiwer; print(jiwer.wer('a b', 'a c'))"` prints `0.5`

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_eval_metrics.py
from eval.metrics import score_pair, term_recall, load_terms

def test_score_pair_perfect_after_normalization():
    s = score_pair('Привет, мир!', 'привет мир')
    assert s['wer'] == 0.0 and s['cer'] == 0.0 and s['ref_words'] == 2

def test_score_pair_one_sub():
    s = score_pair('привет большой мир', 'привет странный мир')
    assert abs(s['wer'] - 1/3) < 1e-9

def test_term_recall_counts_hits_per_pair():
    refs = ['запусти демон и демон второй', 'без терминов']
    hyps = ['запусти демон и деман второй', 'без терминов']
    r = term_recall(refs, hyps, ['демон'])
    assert r['демон'] == {'ref': 2, 'hit': 1}

def test_load_terms_skips_comments(tmp_path):
    p = tmp_path / 'terms.txt'
    p.write_text('# comment\n\nклод\nдемон\n', encoding='utf-8')
    assert load_terms(p) == ['клод', 'демон']
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_eval_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement `eval/metrics.py`**

```python
"""WER/CER (jiwer) and domain-term recall, all on normalized text."""
import jiwer

from eval.normalize import normalize


def score_pair(ref, hyp, fold_yo=True):
    nref, nhyp = normalize(ref, fold_yo), normalize(hyp, fold_yo)
    if not nref:
        return {'wer': 0.0 if not nhyp else 1.0, 'cer': 0.0 if not nhyp else 1.0,
                'ref_words': 0}
    return {'wer': jiwer.wer(nref, nhyp),
            'cer': jiwer.cer(nref, nhyp),
            'ref_words': len(nref.split())}


def term_recall(refs, hyps, terms):
    out = {}
    for term in terms:
        nterm = normalize(term)
        ref_n = hit_n = 0
        for ref, hyp in zip(refs, hyps):
            in_ref = normalize(ref).split().count(nterm)
            in_hyp = normalize(hyp).split().count(nterm)
            ref_n += in_ref
            hit_n += min(in_ref, in_hyp)
        out[term] = {'ref': ref_n, 'hit': hit_n}
    return out


def load_terms(path):
    terms = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                terms.append(line)
    return terms
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_eval_metrics.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add eval/metrics.py tests/test_eval_metrics.py
git commit -m "eval: WER/CER and term-recall metrics"
```

---

### Task 5: Model runner (whole-file and VAD modes)

**Files:**
- Create: `eval/run_model.py`
- Test: `tests/test_eval_run_model.py`
- Modify: `.venv` (install `sherpa-onnx`)

**Interfaces:**
- Consumes: manifest schema from Task 2.
- Produces:
  - `decode_corpus(decode_fn, corpus_dir, out_path, mode_label, model_label) -> int` — iterates manifest, calls `decode_fn(samples: np.float32 array 16 kHz) -> str`, writes `runs/<name>.jsonl` lines `{"id", "hyp", "model", "mode"}`; returns clip count.
  - `read_wav(path) -> np.ndarray` — float32 in [-1,1] from 16 kHz mono s16 WAV.
  - CLI: `python -m eval.run_model --model-dir <dir> --name <run-name> [--mode whole|vad] [--corpus-dir ...]`.
  - Real decoding builds a `sherpa_onnx.OfflineRecognizer.from_transducer(encoder, decoder, joiner, tokens, num_threads=4, model_type='nemo_transducer')` — same family as `py/backend.py:283` uses; works for both Parakeet int8 and GigaAM-v3 e2e_rnnt int8 exports.
  - VAD mode mirrors prod segmentation params from `py/backend.py` (silero VAD, `min_silence_duration = 1.0`); segments are decoded independently and joined with a single space.

- [ ] **Step 1: Install sherpa-onnx**

Run: `.venv/bin/pip install sherpa-onnx`
Expected: success on macOS arm64; `.venv/bin/python -c "import sherpa_onnx; print(sherpa_onnx.__version__)"` prints a version. Record the version in the commit message of Step 6.

- [ ] **Step 2: Write the failing tests** (decode_fn injected — no model download in tests)

```python
# tests/test_eval_run_model.py
import json, wave
import numpy as np
from eval.run_model import decode_corpus, read_wav

def _mk_corpus(tmp_path, n=2):
    corpus = tmp_path / 'corpus'; corpus.mkdir()
    entries = []
    for i in range(n):
        cid = 'clip%d' % i
        with wave.open(str(corpus / (cid + '.wav')), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(np.full(1600, 1000, dtype=np.int16).tobytes())
        (corpus / (cid + '.ref.txt')).write_text('текст %d' % i, encoding='utf-8')
        entries.append({'id': cid, 'wav': cid + '.wav', 'ref': cid + '.ref.txt',
                        'source': 'phone', 'verified': False})
    with open(corpus / 'manifest.jsonl', 'w', encoding='utf-8') as f:
        for e in entries:
            f.write(json.dumps(e) + '\n')
    return corpus

def test_read_wav_scales_to_unit_float(tmp_path):
    corpus = _mk_corpus(tmp_path, n=1)
    samples = read_wav(corpus / 'clip0.wav')
    assert samples.dtype == np.float32
    assert abs(float(samples[0]) - 1000 / 32768.0) < 1e-6

def test_decode_corpus_writes_run_file(tmp_path):
    corpus = _mk_corpus(tmp_path)
    out = tmp_path / 'run.jsonl'
    n = decode_corpus(lambda s: 'решённый текст', corpus, out,
                      mode_label='whole', model_label='fake')
    assert n == 2
    lines = [json.loads(l) for l in open(out, encoding='utf-8')]
    assert lines[0] == {'id': 'clip0', 'hyp': 'решённый текст',
                        'model': 'fake', 'mode': 'whole'}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_eval_run_model.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement `eval/run_model.py`**

```python
"""Decode the corpus with a sherpa-onnx offline model.

Modes:
  whole — one decode per file (isolates model quality),
  vad   — prod-like silero-VAD segmentation (min_silence 1.0s), segments
          decoded independently and space-joined (approximation of the
          app pipeline; #14 will reuse this mode for boundary tuning).
"""
import argparse, glob, json, os, wave

import numpy as np

from eval.collect import load_manifest, DEFAULT_CORPUS

RUNS_DIR = os.path.join(os.path.dirname(__file__), 'runs')
VAD_MODEL = os.path.join(os.path.dirname(__file__), 'models', 'silero_vad.onnx')
MIN_SILENCE = 1.0  # mirrors py/backend.py prod segmentation


def read_wav(path):
    with wave.open(str(path), 'rb') as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def decode_corpus(decode_fn, corpus_dir, out_path, mode_label, model_label):
    entries = load_manifest(str(corpus_dir))
    os.makedirs(os.path.dirname(str(out_path)) or '.', exist_ok=True)
    n = 0
    with open(out_path, 'w', encoding='utf-8') as f:
        for e in entries:
            samples = read_wav(os.path.join(str(corpus_dir), e['wav']))
            hyp = decode_fn(samples)
            f.write(json.dumps({'id': e['id'], 'hyp': hyp, 'model': model_label,
                                'mode': mode_label}, ensure_ascii=False) + '\n')
            n += 1
            print('[%d/%d] %s' % (n, len(entries), e['id']), flush=True)
    return n


def _find_one(model_dir, pattern):
    hits = sorted(glob.glob(os.path.join(model_dir, pattern)))
    if not hits:
        raise SystemExit('no %s in %s' % (pattern, model_dir))
    return hits[0]


def build_recognizer(model_dir):
    import sherpa_onnx
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=_find_one(model_dir, 'encoder*.onnx'),
        decoder=_find_one(model_dir, 'decoder*.onnx'),
        joiner=_find_one(model_dir, 'joiner*.onnx'),
        tokens=_find_one(model_dir, 'tokens.txt'),
        num_threads=4, model_type='nemo_transducer')


def whole_decode_fn(recognizer):
    def fn(samples):
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        return stream.result.text.strip()
    return fn


def vad_decode_fn(recognizer):
    import sherpa_onnx
    base = whole_decode_fn(recognizer)

    def fn(samples):
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = VAD_MODEL
        cfg.silero_vad.min_silence_duration = MIN_SILENCE
        cfg.sample_rate = 16000
        vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=300)
        window = cfg.silero_vad.window_size
        parts = []
        for off in range(0, len(samples), window):
            vad.accept_waveform(samples[off:off + window])
        vad.flush()
        while not vad.empty():
            parts.append(base(np.asarray(vad.front.samples, dtype=np.float32)))
            vad.pop()
        return ' '.join(p for p in parts if p)
    return fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model-dir', required=True)
    ap.add_argument('--name', required=True, help='run name → runs/<name>.jsonl')
    ap.add_argument('--mode', choices=['whole', 'vad'], default='whole')
    ap.add_argument('--corpus-dir', default=DEFAULT_CORPUS)
    args = ap.parse_args()
    rec = build_recognizer(args.model_dir)
    fn = whole_decode_fn(rec) if args.mode == 'whole' else vad_decode_fn(rec)
    out = os.path.join(RUNS_DIR, args.name + '.jsonl')
    n = decode_corpus(fn, args.corpus_dir, out, args.mode,
                      os.path.basename(os.path.normpath(args.model_dir)))
    print('wrote %s (%d clips)' % (out, n))


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_eval_run_model.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add eval/run_model.py tests/test_eval_run_model.py
git commit -m "eval: corpus decode runner, whole-file and VAD modes (sherpa-onnx <version>)"
```

---

### Task 6: Comparison report

**Files:**
- Create: `eval/report.py`
- Test: `tests/test_eval_report.py`

**Interfaces:**
- Consumes: `score_pair`, `term_recall`, `load_terms` (Task 4); manifest (Task 2); run files (Task 5).
- Produces: `build_report(corpus_dir, run_paths: list, terms_path) -> str` (markdown); CLI `python -m eval.report runs/a.jsonl [runs/b.jsonl] [--out reports/<auto>.md]`. Aggregate = word-weighted corpus WER (total errors / total ref words via per-clip `wer * ref_words`), plus per-clip table sorted by delta when two runs given.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval_report.py
import json
from eval.report import build_report

def _corpus(tmp_path):
    corpus = tmp_path / 'corpus'; corpus.mkdir()
    clips = {'a': 'привет мир', 'b': 'запусти демон'}
    with open(corpus / 'manifest.jsonl', 'w', encoding='utf-8') as f:
        for cid, text in clips.items():
            (corpus / (cid + '.ref.txt')).write_text(text, encoding='utf-8')
            (corpus / (cid + '.wav')).write_bytes(b'')
            f.write(json.dumps({'id': cid, 'wav': cid + '.wav',
                                'ref': cid + '.ref.txt', 'source': 'phone',
                                'verified': False}) + '\n')
    return corpus

def _run(tmp_path, name, hyps):
    p = tmp_path / (name + '.jsonl')
    with open(p, 'w', encoding='utf-8') as f:
        for cid, hyp in hyps.items():
            f.write(json.dumps({'id': cid, 'hyp': hyp, 'model': name,
                                'mode': 'whole'}, ensure_ascii=False) + '\n')
    return p

def test_single_run_report_has_aggregate(tmp_path):
    corpus = _corpus(tmp_path)
    terms = tmp_path / 'terms.txt'; terms.write_text('демон\n', encoding='utf-8')
    run = _run(tmp_path, 'm1', {'a': 'привет мир', 'b': 'запусти демона'})
    md = build_report(corpus, [run], terms)
    assert 'WER' in md and 'm1' in md and 'демон' in md

def test_two_run_report_has_delta_table(tmp_path):
    corpus = _corpus(tmp_path)
    terms = tmp_path / 'terms.txt'; terms.write_text('', encoding='utf-8')
    r1 = _run(tmp_path, 'm1', {'a': 'привет мир', 'b': 'пусти демон'})
    r2 = _run(tmp_path, 'm2', {'a': 'привет мир', 'b': 'запусти демон'})
    md = build_report(corpus, [r1, r2], terms)
    assert 'Δ' in md and 'm2' in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_eval_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `eval/report.py`**

```python
"""Markdown report: one run vs refs, or two runs side by side."""
import argparse, datetime, json, os

from eval.collect import load_manifest, DEFAULT_CORPUS
from eval.metrics import score_pair, term_recall, load_terms

REPORTS_DIR = os.path.join(os.path.dirname(__file__), 'reports')
TERMS = os.path.join(os.path.dirname(__file__), 'terms.txt')


def _load_run(path):
    with open(path, encoding='utf-8') as f:
        rows = [json.loads(line) for line in f if line.strip()]
    label = '%s/%s' % (rows[0]['model'], rows[0]['mode']) if rows else str(path)
    return label, {r['id']: r['hyp'] for r in rows}


def _aggregate(refs, hyps):
    tot_err_w = tot_w = 0.0
    tot_cer = 0.0
    for ref, hyp in zip(refs, hyps):
        s = score_pair(ref, hyp)
        tot_err_w += s['wer'] * s['ref_words']
        tot_w += s['ref_words']
        tot_cer += s['cer']
    n = max(len(refs), 1)
    return (tot_err_w / tot_w if tot_w else 0.0), tot_cer / n


def build_report(corpus_dir, run_paths, terms_path):
    entries = load_manifest(str(corpus_dir))
    refs = {}
    for e in entries:
        with open(os.path.join(str(corpus_dir), e['ref']), encoding='utf-8') as f:
            refs[e['id']] = f.read().strip()
    runs = [_load_run(p) for p in run_paths]
    ids = [e['id'] for e in entries if all(e['id'] in h for _, h in runs)]
    terms = load_terms(terms_path)

    lines = ['# Eval report — %s' % datetime.date.today().isoformat(),
             '', 'Corpus: %d clips scored (%d in manifest), verified refs: %d' % (
                 len(ids), len(entries),
                 sum(1 for e in entries if e.get('verified'))), '']
    lines.append('| run | WER | mean CER |')
    lines.append('|---|---|---|')
    for label, hyps in runs:
        wer, cer = _aggregate([refs[i] for i in ids], [hyps[i] for i in ids])
        lines.append('| %s | %.2f%% | %.2f%% |' % (label, wer * 100, cer * 100))
    lines.append('')

    for label, hyps in runs:
        tr = term_recall([refs[i] for i in ids], [hyps[i] for i in ids], terms)
        hits = {t: v for t, v in tr.items() if v['ref']}
        if hits:
            lines.append('## Terms — %s' % label)
            for t, v in sorted(hits.items()):
                lines.append('- %s: %d/%d' % (t, v['hit'], v['ref']))
            lines.append('')

    if len(runs) == 2:
        (la, ha), (lb, hb) = runs
        rows = []
        for i in ids:
            wa = score_pair(refs[i], ha[i])['wer']
            wb = score_pair(refs[i], hb[i])['wer']
            rows.append((wb - wa, i, wa, wb))
        rows.sort(reverse=True)
        lines.append('## Per-clip Δ WER (%s → %s, worst regressions first)' % (la, lb))
        lines.append('| clip | %s | %s | Δ |' % (la, lb))
        lines.append('|---|---|---|---|')
        for d, i, wa, wb in rows:
            lines.append('| %s | %.1f%% | %.1f%% | %+.1f%% |' % (i, wa * 100, wb * 100, d * 100))
        lines.append('')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--corpus-dir', default=DEFAULT_CORPUS)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    md = build_report(args.corpus_dir, args.runs, TERMS)
    out = args.out or os.path.join(
        REPORTS_DIR, datetime.datetime.now().strftime('%Y%m%d-%H%M') + '.md')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(md)
    print(md)
    print('\nsaved: %s' % out)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_eval_report.py -v`
Expected: 2 PASS

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green (35 old + ~16 new)

- [ ] **Step 6: Commit**

```bash
git add eval/report.py tests/test_eval_report.py
git commit -m "eval: markdown comparison report"
```

---

### Task 7: Models on the Mac + real baseline run (Parakeet)

**Files:**
- Modify: `eval/README.md` (Models section), `.gitignore` (`eval/models/`)
- Create (local only, not committed): `eval/models/parakeet-int8/`, `eval/models/silero_vad.onnx`, corpus, `runs/parakeet-whole.jsonl`, `runs/parakeet-vad.jsonl`

**Interfaces:**
- Consumes: CLI from Tasks 2, 5, 6.
- Produces: populated corpus (~40 clips) and the Parakeet baseline run files used by #12/#14 comparisons.

- [ ] **Step 1: gitignore models dir**

Append `eval/models/` to `.gitignore` (same block as Task 1).

- [ ] **Step 2: Download models (same URLs the app uses, from `py/downloader.py`)**

```bash
cd eval/models
curl -LO https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2
tar xjf sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2 && mv sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 parakeet-int8 && rm *.tar.bz2
curl -L -o silero_vad.onnx $(python3 -c "import re,sys;print(re.search(r\"SILERO_URL = \('(.+)'\s*\n\s*'(.+)'\)\", open('../../py/downloader.py').read()).group(1)+re.search(r\"SILERO_URL = \('(.+)'\s*\n\s*'(.+)'\)\", open('../../py/downloader.py').read()).group(2))")
```

(If the SILERO_URL extraction one-liner is awkward in practice, just open `py/downloader.py`, copy the two URL halves by hand — it is a fixed GitHub release URL.)

- [ ] **Step 3: Collect the corpus**

Run: `.venv/bin/python -m eval.collect`
Expected: `backup: +N`, `phone: +M`, `corpus now: ~40+ clips` (24 backup + 20 phone minus empty-text clips and overlaps)

- [ ] **Step 4: Baseline runs**

Run: `.venv/bin/python -m eval.run_model --model-dir eval/models/parakeet-int8 --name parakeet-whole --mode whole`
Then: `.venv/bin/python -m eval.run_model --model-dir eval/models/parakeet-int8 --name parakeet-vad --mode vad`
Expected: both complete over the full corpus without exceptions; run files in `eval/runs/`.

- [ ] **Step 5: Baseline report**

Run: `.venv/bin/python -m eval.report eval/runs/parakeet-whole.jsonl eval/runs/parakeet-vad.jsonl`
Expected: markdown with two aggregate rows + Δ table. Sanity: whole-mode WER is LOW (refs came from this very model — near-0 is expected and fine; the harness's job here is relative comparison), vad-mode shows boundary-induced delta.

- [ ] **Step 6: Update README Models section + commit code changes**

Add to `eval/README.md`:

```markdown
## Models

    # Parakeet TDT 0.6B v3 int8 (current prod model) + silero VAD:
    #   see Task-7 commands in docs/plans/2026-08-22-eval-harness.md
    # GigaAM-v3 e2e_rnnt int8 (candidate, issue #12):
    #   https://huggingface.co/Smirnov75/GigaAM-v3-sherpa-onnx — download
    #   encoder/decoder/joiner int8 + tokens.txt into eval/models/gigaam-e2e-int8/
```

```bash
git add .gitignore eval/README.md
git commit -m "eval: models dir gitignore and download docs"
```

---

### Task 8: Candidate run (GigaAM-v3 e2e_rnnt) — first real comparison for issue #12

**Files:**
- Create (local only): `eval/models/gigaam-e2e-int8/`, `runs/gigaam-whole.jsonl`, `runs/gigaam-vad.jsonl`, report

**Interfaces:**
- Consumes: everything above.
- Produces: the Parakeet-vs-GigaAM report Khan reviews to green-light #12.

- [ ] **Step 1: Download GigaAM-v3 e2e_rnnt int8 from HF**

List files: `curl -s https://huggingface.co/api/models/Smirnov75/GigaAM-v3-sherpa-onnx | python3 -c "import json,sys; [print(s['rfilename']) for s in json.load(sys.stdin)['siblings']]"`
Then download the `e2e_rnnt` int8 encoder/decoder/joiner + tokens into `eval/models/gigaam-e2e-int8/` via `curl -LO https://huggingface.co/Smirnov75/GigaAM-v3-sherpa-onnx/resolve/main/<file>` (exact names from the listing; fallback repo: `csukuangfj/sherpa-onnx-nemo-transducer-giga-am-v3-russian-2025-12-16`).

- [ ] **Step 2: Decode**

Run: `.venv/bin/python -m eval.run_model --model-dir eval/models/gigaam-e2e-int8 --name gigaam-whole --mode whole`
Then: `.venv/bin/python -m eval.run_model --model-dir eval/models/gigaam-e2e-int8 --name gigaam-vad --mode vad`
Expected: completes; if `from_transducer` rejects the export, retry with `model_type=''` (auto-detect) — note what worked in the run-file commit… (no commit — note it in `eval/README.md` instead if non-default).

- [ ] **Step 3: The money report**

Run: `.venv/bin/python -m eval.report eval/runs/parakeet-whole.jsonl eval/runs/gigaam-whole.jsonl`
Expected: aggregate WER both models + per-clip Δ + term recall. IMPORTANT caveat for reading it: refs are seed texts produced BY Parakeet, so absolute WER favors Parakeet; the value is in the Δ table — eyeball the biggest diffs, and hand-verify refs for the ~10 clips with the largest |Δ| (edit `.ref.txt`, set `"verified": true` in manifest) before drawing conclusions.

- [ ] **Step 4: Hand review with Khan**

Show Khan the report + 5-10 worst/best diff pairs (ref / parakeet / gigaam side by side). His read decides #12 go/no-go.

---

## Verification criteria (issue #6 DoD)

1. `.venv/bin/python -m pytest -q` — green, ≥50 tests total.
2. `.venv/bin/python -m eval.collect` — corpus ≥35 clips, second run adds 0 (idempotent).
3. `git status --porcelain | grep -E 'corpus|runs|reports|models'` inside eval/ — empty (privacy guard holds).
4. Both models decode the full corpus in both modes without exceptions.
5. Comparison report renders with aggregate WER, per-clip Δ, term recall.

## Self-Review

- Spec coverage: corpus from real history ✓ (T2, T7), WER/CER ✓ (T4), term metrics ✓ (T4), model comparison Parakeet vs GigaAM ✓ (T5, T7, T8), Mac + sherpa-onnx ✓ (T5), privacy ✓ (T1, T7).
- Placeholder scan: none — all code inline.
- Type consistency: `merge_source`/`load_manifest` (T2) used in T5/T6 with same signatures; `score_pair`/`term_recall`/`load_terms` (T4) used in T6; manifest keys consistent (`id/wav/ref/source/verified`).
- Known seed-ref bias documented in T8 Step 3 (refs generated by Parakeet) — mitigated by Δ-review + hand-verification of top-diff clips.
