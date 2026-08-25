# Overlap + LCS at VAD segment boundaries — Implementation Plan (issue #14)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove word loss/garbling at VAD segment junctions by giving each
segment ~1 s of the previous segment's audio as left context and deduplicating
the re-decoded words with a token-level LCS merge, measured by the eval harness.

**Architecture:** Backward-only overlap (streaming cannot see future audio):
the Segmenter lets a phrase's window reach back into the previous segment's
speech; the joiner (`join_chunk`) decodes the enlarged phrase and drops tokens
duplicated with the tail of the already-emitted text via normalized LCS.
Pipeline constants move to `py/streaming.py` (importable without pyotherside)
so the eval harness reuses the exact prod chain (parity), and a formalized
boundary metric (`eval/boundary.py`) measures the effect on the private corpus.

**Tech Stack:** Python (phone: 3.12/noble; Mac: repo `.venv`), numpy,
sherpa-onnx (silero VAD + offline transducer), jiwer (eval only), pytest.

**Spec:** `docs/specs/2026-08-20-streaming-selfdownload-waveform.md` §5
(overlap+LCS recipe) + baseline: `eval/reports/boundary-baseline-gigaam.md`
(private, gitignored; summary: 66 junctions on GigaAM corpus, 44% damaged,
dominant error = edge-word degradation from missing context; gap size does
not predict damage — hence context restoration, not gap targeting).
Issue: https://github.com/mad0ps/soundtype/issues/14 (NVIDIA long-form recipe:
~1 s overlap + token-level LCS merge).

## Global Constraints

- Python code in `py/` must run on the phone: stdlib + numpy only, sherpa-onnx
  loaded lazily at runtime; no new dependencies.
- `py/streaming.py` must stay importable WITHOUT pyotherside (eval + tests rely
  on this); `py/backend.py` is the only module importing pyotherside.
- Code comments in Russian (existing style), repo docs/commits in English,
  no Co-Authored-By in commits.
- Corpus content (transcripts, clip audio) must NEVER appear in committed
  files: `eval/corpus/`, `eval/runs/`, `eval/reports/` are gitignored — verify
  with `git check-ignore` before every commit that touches eval outputs.
- Existing behavior with `overlap=0` must be bit-identical to today's pipeline
  (all current tests keep passing unmodified except where a task says so).
- Work on branch `feat/overlap-lcs`; PR to main at the end (no direct push).

## File Structure

- `py/streaming.py` — canonical home of pipeline constants (moved from
  backend) + new `merge_overlap()`, `join_chunk()`; `Segmenter` learns
  backward overlap; `Phrase` gains `overlap` field.
- `py/backend.py` — drops its copies of the constants, imports them from
  `streaming`; `_transcribe()` and `DecodeWorker` call sites switch to
  `join_chunk`.
- `eval/run_model.py` — vad mode rebuilt on the prod chain
  (Segmenter + join_chunk + prod VAD config incl. `max_speech=30`), new
  `--overlap` / `--max-speech` flags, writes `<name>-segments.jsonl`.
- `eval/boundary.py` (new) — junction-attribution metric + CLI (formalizes
  `eval/reports/boundary_attrib.py` scratch script).
- Tests: `tests/test_merge_overlap.py` (new), `tests/test_segmenter.py` (+3),
  `tests/test_join_chunk.py` (new), `tests/test_decode_worker.py` (+1),
  `tests/test_eval_run_model.py` (+2), `tests/test_eval_boundary.py` (new).

---

### Task 1: Constants move + `merge_overlap()` in py/streaming.py

**Files:**
- Modify: `py/streaming.py` (top of file + new function after `capitalize_first`)
- Modify: `py/backend.py:50-61` (constants block)
- Test: `tests/test_merge_overlap.py` (new)

**Interfaces:**
- Produces: `streaming.VAD_WINDOW=512`, `MIN_SILENCE=1.0`, `MIN_SPEECH=0.25`,
  `MAX_SPEECH=30.0`, `PAD_PRE=0.4`, `PAD_POST=0.25`, `CAP_PAUSE=1.5` (moved
  verbatim), new `OVERLAP=1.0`, `OVERLAP_GAP_MAX=2.0`, `LCS_WINDOW=8`,
  `LCS_MIN_MATCH=2`.
- Produces: `merge_overlap(prev_text, text, window=LCS_WINDOW,
  min_match=LCS_MIN_MATCH) -> (str, bool)` — new text with duplicated head
  dropped + whether a merge happened.

- [ ] **Step 1: branch**

```bash
git checkout -b feat/overlap-lcs
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_merge_overlap.py`:

```python
# -*- coding: utf-8 -*-
from streaming import merge_overlap


def test_drops_duplicated_prefix():
    got, m = merge_overlap('мы пошли в магазин', 'в магазин и купили хлеб')
    assert m and got == 'и купили хлеб'


def test_normalized_match_keeps_original_tokens():
    got, m = merge_overlap('Смотри, программа работает',
                           'Программа работает! отлично')
    assert m and got == 'отлично'


def test_single_token_match_not_merged():
    got, m = merge_overlap('раз два три', 'три четыре пять')
    assert not m and got == 'три четыре пять'


def test_match_must_touch_prev_tail():
    # «в магазин» встречается в prev, но далеко от хвоста — это не дубль
    got, m = merge_overlap('в магазин мы не пошли а поехали',
                           'в магазин на машине')
    assert not m and got == 'в магазин на машине'


def test_full_duplicate_drops_everything():
    got, m = merge_overlap('и вот тогда мы решили', 'мы решили')
    assert m and got == ''


def test_empty_inputs_untouched():
    assert merge_overlap('', 'текст') == ('текст', False)
    assert merge_overlap('текст', '') == ('', False)
    assert merge_overlap(None, 'текст') == ('текст', False)
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_merge_overlap.py -v`
Expected: FAIL — `ImportError: cannot import name 'merge_overlap'`

- [ ] **Step 4: Implement**

In `py/streaming.py`, add `import re` to the imports and, right after the
docstring/imports, the constants block (moved from backend.py plus new knobs):

```python
# --- Параметры прод-пайплайна (канон здесь: backend и eval импортируют) ---
VAD_WINDOW = 512          # silero работает окнами по 512 отсчётов
MIN_SILENCE = 1.0         # было 0.35 — резало речь на подфразовые обрывки
MIN_SPEECH = 0.25
MAX_SPEECH = 30.0
PAD_PRE = 0.4             # сек контекста перед сегментом (sherpa-onnx#3035)
PAD_POST = 0.25           # сек хвоста после сегмента
CAP_PAUSE = 1.5           # пауза, после которой стык считаем новым предложением
# Overlap+LCS на стыках (issue #14): сегмент захватывает хвост предыдущего,
# задвоенные слова убирает merge_overlap. Streaming не видит будущего звука,
# поэтому перекрытие только назад.
OVERLAP = 1.0             # сек речи предыдущего сегмента в качестве контекста
OVERLAP_GAP_MAX = 2.0     # при паузе длиннее контекст соседа не берём
LCS_WINDOW = 8            # окно токенов для поиска дубля на стыке
LCS_MIN_MATCH = 2         # минимум совпавших токенов, чтобы счесть дублем
```

After `capitalize_first`, add:

```python
_TOKEN_JUNK = re.compile(r'[^\w]+', re.UNICODE)


def _norm_token(tok):
    return _TOKEN_JUNK.sub('', tok.lower().replace('ё', 'е'))


def merge_overlap(prev_text, text, window=LCS_WINDOW, min_match=LCS_MIN_MATCH):
    """Убирает из начала text слова, задвоенные с хвостом prev_text.

    Сегмент с overlap-аудио начинается с повторного декода хвоста предыдущего;
    ищем самое длинное непрерывное совпадение нормализованных токенов
    (регистр/ё/пунктуация не в счёт) между последними `window` токенами prev
    и первыми `window` токенами text. Совпадение обязано доставать до хвоста
    prev (допуск 1 токен — последний мог быть обрезан срезом). Возвращает
    (text без дубля, был ли дубль); выбрасываются исходные токены text.
    """
    if not prev_text or not text:
        return text, False
    prev_norm = [_norm_token(t) for t in prev_text.split()][-window:]
    toks = text.split()
    head_norm = [_norm_token(t) for t in toks[:window]]
    best_len = best_end = 0
    for i in range(len(prev_norm)):
        for j in range(len(head_norm)):
            k = 0
            while (i + k < len(prev_norm) and j + k < len(head_norm)
                   and prev_norm[i + k] and prev_norm[i + k] == head_norm[j + k]):
                k += 1
            if k > best_len and i + k >= len(prev_norm) - 1:
                best_len, best_end = k, j + k
    if best_len < min_match:
        return text, False
    return ' '.join(toks[best_end:]), True
```

In `py/backend.py` replace the constants block at lines 48–62 with (the
research comment about pause sizes moves to streaming.py next to the
constants; `RATE`, `CHANNELS`, `CHUNK_BYTES`, `VAD_BUFFER_SECONDS` stay):

```python
RATE = 16000
CHANNELS = 1
VAD_WINDOW = streaming.VAD_WINDOW
CHUNK_BYTES = VAD_WINDOW * 2 * 4  # 4 окна = 0.128 с: level для волны ~8 раз/с

# Параметры нарезки и стыков фраз живут в py/streaming.py (канон): их
# использует и eval-харнесс, чтобы мерить ровно продовый пайплайн.
MAX_SPEECH = streaming.MAX_SPEECH
MIN_SILENCE = streaming.MIN_SILENCE
MIN_SPEECH = streaming.MIN_SPEECH
PAD_PRE = streaming.PAD_PRE
PAD_POST = streaming.PAD_POST
CAP_PAUSE = streaming.CAP_PAUSE
VAD_BUFFER_SECONDS = 120
```

When moving the constants into streaming.py, carry over the original
research comment («Нарезка и стыки фраз (ресёрч 21.08: faster-whisper
2.0s+pad400, … arxiv 2409.05601)…») verbatim above MIN_SILENCE.
`import streaming` is already at backend.py line 44, above this block.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS (new + existing 78)

- [ ] **Step 6: Commit**

```bash
git add py/streaming.py py/backend.py tests/test_merge_overlap.py
git commit -m "feat(streaming): centralize pipeline constants, add token-LCS merge_overlap (#14)"
```

---

### Task 2: Backward overlap in Segmenter

**Files:**
- Modify: `py/streaming.py` — `Phrase` (slots/ctor), `Segmenter.__init__`,
  `Segmenter._drain`
- Test: `tests/test_segmenter.py` (append 3 tests)

**Interfaces:**
- Consumes: constants from Task 1.
- Produces: `Phrase(samples, speech_len, gap, overlap=0.0)` — `overlap` =
  seconds of the previous segment's window included at the head (0.0 when
  none); `Segmenter(..., overlap=0.0, overlap_gap_max=OVERLAP_GAP_MAX)`.
  Default `overlap=0.0` keeps today's behavior bit-identical.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_segmenter.py` (reuses `_mk` helper already in the file):

```python
def test_overlap_reaches_into_previous_segment():
    vad = FakeVad()
    s = Segmenter(vad, np, window=100, rate=1000, pad_pre=0.1, pad_post=0.0,
                  overlap=0.2, overlap_gap_max=2.0)
    stream = np.arange(2000, dtype=np.float32)
    s.feed(stream[:600])
    vad.pending.append(_mk(stream[200:300], 200))
    s.feed(stream[600:700])                        # prev_end = 300
    vad.pending.append(_mk(stream[500:600], 500))
    got = s.feed(stream[700:800])
    p = got[0]
    # lo = min(500-100, 300-200) = 100: захватили хвост предыдущего сегмента
    assert p.samples[0] == 100.0
    assert abs(p.overlap - 0.2) < 1e-9
    assert p.gap == 0.2


def test_no_overlap_when_gap_exceeds_max():
    vad = FakeVad()
    s = Segmenter(vad, np, window=100, rate=1000, pad_pre=0.1, pad_post=0.0,
                  overlap=0.2, overlap_gap_max=0.1)
    stream = np.arange(2000, dtype=np.float32)
    s.feed(stream[:600])
    vad.pending.append(_mk(stream[200:300], 200))
    s.feed(stream[600:700])
    vad.pending.append(_mk(stream[500:600], 500))
    got = s.feed(stream[700:800])
    p = got[0]
    # пауза 0.2с > overlap_gap_max: старое поведение, pre-pad упирается в prev_end
    assert p.samples[0] == 400.0
    assert p.overlap == 0.0


def test_first_segment_never_overlaps():
    vad = FakeVad()
    s = Segmenter(vad, np, window=100, rate=1000, pad_pre=0.1, pad_post=0.0,
                  overlap=0.5)
    stream = np.arange(1000, dtype=np.float32)
    s.feed(stream[:500])
    vad.pending.append(_mk(stream[200:300], 200))
    got = s.feed(stream[500:600])
    assert got[0].overlap == 0.0
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_segmenter.py -v`
Expected: new tests FAIL (`TypeError: unexpected keyword 'overlap'`), old PASS

- [ ] **Step 3: Implement**

`Phrase`: add the field —

```python
class Phrase(object):
    """Готовая фраза из VAD: samples (с паддингом), длина чистой речи
    в отсчётках, пауза в секундах перед началом (None = первая/неизвестно)
    и overlap — сколько секунд окна предыдущего сегмента захвачено в начале
    (0.0 = перекрытия нет)."""

    __slots__ = ('samples', 'speech_len', 'gap', 'overlap')

    def __init__(self, samples, speech_len, gap, overlap=0.0):
        self.samples = samples
        self.speech_len = speech_len
        self.gap = gap
        self.overlap = overlap
```

`Segmenter.__init__`: add params `overlap=0.0, overlap_gap_max=OVERLAP_GAP_MAX`
and store `self._overlap = int(rate * overlap)`,
`self._overlap_gap_max = overlap_gap_max`.

`Segmenter._drain`: replace the `lo = max(...)` line with:

```python
            prev_hi = self._prev_hi if self._prev_end is not None else 0
            if (self._overlap and self._prev_end is not None
                    and gap is not None and gap <= self._overlap_gap_max):
                # Стык близкий: даём сегменту хвост предыдущего ОКНА как
                # левый контекст; задвоенные слова уберёт merge_overlap.
                lo = max(min(start - self._pad_pre, prev_hi - self._overlap),
                         self._buf_base)
                overlap = max(0, prev_hi - lo) / float(self.rate)
            else:
                lo = max(start - self._pad_pre, self._buf_base,
                         self._prev_end if self._prev_end is not None else 0)
                overlap = 0.0
```

and the tail of `_drain` becomes:

```python
            hi = min(end + self._pad_post, self._fed)
            self._prev_end = end
            self._prev_hi = hi
            out.append(Phrase(self._buf[lo - self._buf_base:hi - self._buf_base],
                              len(raw), gap, overlap))
```

Add `self._prev_hi = 0` next to `self._prev_end = None` in `__init__`.
(`prev_hi` = конец окна предыдущей фразы с pad_post: overlap меряем от того,
что реально ушло в декод соседа — дубль ищем ровно в этой зоне.)

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS (old `test_padding_and_gap` etc. must not change —
default `overlap=0.0` short-circuits the new branch)

- [ ] **Step 5: Commit**

```bash
git add py/streaming.py tests/test_segmenter.py
git commit -m "feat(streaming): Segmenter backward overlap into previous segment (#14)"
```

---

### Task 3: `join_chunk()` + wiring into DecodeWorker and backend

**Files:**
- Modify: `py/streaming.py` (new function after `merge_overlap`;
  `DecodeWorker._run` tail), `py/backend.py` (`_transcribe` join block,
  `_split`/`_session` Segmenter calls get `overlap=OVERLAP` — via
  `streaming.OVERLAP`)
- Test: `tests/test_join_chunk.py` (new), `tests/test_decode_worker.py` (+1)

**Interfaces:**
- Consumes: `merge_overlap` (Task 1), `Phrase.overlap` (Task 2),
  existing `phrase_glue`, `capitalize_first`.
- Produces: `join_chunk(prev_text, text, gap, overlap, cap_pause,
  window=LCS_WINDOW, min_match=LCS_MIN_MATCH) -> str` — the chunk to append
  (`''` = nothing). Both prod paths (streaming worker + whole-record retry)
  emit through it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_join_chunk.py`:

```python
# -*- coding: utf-8 -*-
from streaming import join_chunk


def test_dedupes_when_overlap_present():
    got = join_chunk('мы пошли в магазин', 'в магазин и купили',
                     gap=0.1, overlap=0.5, cap_pause=1.5)
    assert got == ' и купили'


def test_without_overlap_falls_back_to_glue():
    got = join_chunk('привет.', 'как дела', gap=0.2, overlap=0.0,
                     cap_pause=1.5)
    assert got == ' Как дела'


def test_overlap_without_match_uses_glue_rules():
    got = join_chunk('раз два', 'пять шесть', gap=2.0, overlap=0.5,
                     cap_pause=1.5)
    assert got == '. Пять шесть'


def test_all_duplicate_returns_empty():
    assert join_chunk('и вот мы решили', 'мы решили',
                      gap=0.1, overlap=0.5, cap_pause=1.5) == ''


def test_first_chunk_capitalized():
    assert join_chunk(None, 'привет', gap=None, overlap=0.0,
                      cap_pause=1.5) == 'Привет'
```

Append to `tests/test_decode_worker.py` (mirror the file's existing style for
building segments/worker — it already fakes `decode_fn`):

```python
def test_worker_dedupes_overlapped_segments():
    import types
    texts = iter(['мы пошли в магазин', 'в магазин и купили хлеб'])
    got = []
    w = DecodeWorker(lambda s: next(texts), on_text=lambda i, t: got.append(t),
                     min_samples=0, cap_pause=1.5)
    w.put(types.SimpleNamespace(samples=[0.0] * 10, speech_len=10, gap=None,
                                overlap=0.0))
    w.put(types.SimpleNamespace(samples=[0.0] * 10, speech_len=10, gap=0.2,
                                overlap=1.0))
    full = w.close(timeout=5)
    assert full == 'мы пошли в магазин и купили хлеб'
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_join_chunk.py tests/test_decode_worker.py -v`
Expected: FAIL — `ImportError: cannot import name 'join_chunk'` /
duplicated «в магазин» in worker output

- [ ] **Step 3: Implement**

`py/streaming.py`, after `merge_overlap`:

```python
def join_chunk(prev_text, text, gap, overlap, cap_pause,
               window=LCS_WINDOW, min_match=LCS_MIN_MATCH):
    """Единая точка склейки нового текста фразы с уже набранным.

    При overlap-аудио сначала пробуем LCS-дедуп; удался — стык внутри
    предложения (пробел, без капитализации). Иначе обычные правила
    phrase_glue. Возвращает строку для append ('' — добавлять нечего).
    """
    if not text:
        return ''
    if overlap and prev_text:
        merged, matched = merge_overlap(prev_text, text, window, min_match)
        if matched:
            return (' ' + merged) if merged else ''
    glue, cap = phrase_glue(prev_text, gap, cap_pause)
    return glue + (capitalize_first(text) if cap else text)
```

`DecodeWorker._run` — replace the final `if text:` block with:

```python
            if text:
                prev = self.texts[-1] if self.texts else None
                chunk = join_chunk(prev, text, gap,
                                   getattr(seg, 'overlap', 0.0),
                                   self.cap_pause)
                if chunk:
                    self.texts.append(chunk)
                    self.on_text(idx, chunk)
```

`py/backend.py` `_transcribe` — replace the glue block with:

```python
            if text:
                prev = texts[-1] if texts else None
                chunk = streaming.join_chunk(prev, text, phrase.gap,
                                             phrase.overlap, CAP_PAUSE)
                if chunk:
                    texts.append(chunk)
```

`py/backend.py` — both `Segmenter(...)` constructions (`_split` and
`_session`) get the extra argument `overlap=streaming.OVERLAP` (gap_max
default). This is the switch that turns the feature ON in prod.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS. If an existing `test_backend_session`/`test_decode_worker`
case asserts old glue text, inspect: with `overlap` present but no token
match, output is unchanged — failures here mean a real bug, not a test to
edit.

- [ ] **Step 5: Commit**

```bash
git add py/streaming.py py/backend.py tests/test_join_chunk.py tests/test_decode_worker.py
git commit -m "feat: dedupe overlapped segment joins via join_chunk, enable overlap in prod paths (#14)"
```

---

### Task 4: Eval parity — vad mode on the prod chain

**Files:**
- Modify: `eval/run_model.py` (vad path rewritten; new flags)
- Test: `tests/test_eval_run_model.py` (+2)

**Interfaces:**
- Consumes: `streaming.Segmenter`, `streaming.join_chunk`, constants
  (Tasks 1–3).
- Produces: `vad_pipeline(samples, vad, decode_fn, np_mod, overlap) ->
  (text, metas)` where `metas` is a list of
  `{'text','gap','overlap','dur'}` per decoded phrase; CLI flags
  `--overlap SECONDS` (default `streaming.OVERLAP`, `0` = off) and
  `--max-speech SECONDS` (default `streaming.MAX_SPEECH`); vad runs write
  `runs/<name>.jsonl` + `runs/<name>-segments.jsonl`
  (`{'id':…, 'segments': metas}` per line). Task 5 reads that file.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_eval_run_model.py`:

```python
def test_vad_pipeline_joins_via_prod_chain():
    import types
    from eval.run_model import vad_pipeline
    from fakes import FakeVad

    vad = FakeVad()
    # speech_len должен пройти прод-порог 0.2с (3200 отсчётков при 16кГц)
    seg = types.SimpleNamespace(samples=[0.5] * 4000, start=100)
    vad.pending.append(seg)
    texts = iter(['привет мир'])
    text, metas = vad_pipeline(np.arange(1600, dtype=np.float32), vad,
                               lambda s: next(texts), np, overlap=1.0)
    assert text == 'Привет мир'          # прод-склейка: капитализация первой
    assert len(metas) == 1
    assert set(metas[0]) == {'text', 'gap', 'overlap', 'dur'}


def test_vad_mode_writes_segments_file(tmp_path, monkeypatch):
    import eval.run_model as rm
    corpus = _mk_corpus(tmp_path, n=1)
    out = tmp_path / 'run.jsonl'
    monkeypatch.setattr(rm, 'build_vad', lambda max_speech: __import__('fakes').FakeVad())
    n = rm.decode_corpus_vad(lambda s: 'текст', corpus, out,
                             model_label='fake', overlap=1.0, max_speech=30.0)
    assert n == 1
    segs = [json.loads(l) for l in open(tmp_path / 'run-segments.jsonl',
                                        encoding='utf-8')]
    assert segs[0]['id'] == 'clip0' and 'segments' in segs[0]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_eval_run_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'vad_pipeline'`

- [ ] **Step 3: Implement**

In `eval/run_model.py`:

1. Top of file, make prod modules importable and drop local `MIN_SILENCE`:

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'py'))
import streaming  # noqa: E402  (канон параметров пайплайна — py/streaming.py)
```

(add `import sys` to the import line; delete the `MIN_SILENCE = 1.0` constant —
use `streaming.MIN_SILENCE`.)

2. Replace `vad_decode_fn` with the prod-parity pipeline:

```python
def build_vad(max_speech=streaming.MAX_SPEECH):
    """VAD с ПРОДОВЫМ конфигом (backend.load), включая max_speech форс-нарезку."""
    import sherpa_onnx
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = VAD_MODEL
    cfg.silero_vad.threshold = 0.5
    cfg.silero_vad.min_silence_duration = streaming.MIN_SILENCE
    cfg.silero_vad.min_speech_duration = streaming.MIN_SPEECH
    cfg.silero_vad.max_speech_duration = max_speech
    cfg.sample_rate = 16000
    return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=300)


def vad_pipeline(samples, vad, decode_fn, np_mod, overlap):
    """Прод-цепочка: Segmenter (pad+overlap) → decode → join_chunk."""
    seg = streaming.Segmenter(vad, np_mod, streaming.VAD_WINDOW, rate=16000,
                              pad_pre=streaming.PAD_PRE,
                              pad_post=streaming.PAD_POST, overlap=overlap)
    phrases = seg.feed(samples) + seg.flush()
    texts, metas = [], []
    for ph in phrases:
        if ph.speech_len < 16000 * 0.2:
            continue
        text = decode_fn(np_mod.asarray(ph.samples, dtype=np_mod.float32))
        metas.append({'text': text, 'gap': ph.gap, 'overlap': ph.overlap,
                      'dur': len(ph.samples) / 16000.0})
        chunk = streaming.join_chunk(texts[-1] if texts else None, text,
                                     ph.gap, ph.overlap, streaming.CAP_PAUSE)
        if chunk:
            texts.append(chunk)
    return ''.join(texts).strip(), metas


def decode_corpus_vad(decode_fn, corpus_dir, out_path, model_label,
                      overlap, max_speech):
    """Как decode_corpus, но через прод-цепочку + пишет <name>-segments.jsonl."""
    entries = load_manifest(str(corpus_dir))
    seg_path = str(out_path)[:-len('.jsonl')] + '-segments.jsonl'
    n = 0
    with open(out_path, 'w', encoding='utf-8') as f, \
         open(seg_path, 'w', encoding='utf-8') as fs:
        for e in entries:
            samples = read_wav(os.path.join(str(corpus_dir), e['wav']))
            text, metas = vad_pipeline(samples, build_vad(max_speech),
                                       decode_fn, np, overlap)
            f.write(json.dumps({'id': e['id'], 'hyp': text,
                                'model': model_label, 'mode': 'vad'},
                               ensure_ascii=False) + '\n')
            fs.write(json.dumps({'id': e['id'], 'segments': metas},
                                ensure_ascii=False) + '\n')
            n += 1
            print('[%d/%d] %s' % (n, len(entries), e['id']), flush=True)
    return n
```

3. `main()`: add
`ap.add_argument('--overlap', type=float, default=streaming.OVERLAP)` and
`ap.add_argument('--max-speech', type=float, default=streaming.MAX_SPEECH)`;
route `--mode vad` to
`decode_corpus_vad(whole_decode_fn(rec), args.corpus_dir, out,
os.path.basename(os.path.normpath(args.model_dir)), args.overlap,
args.max_speech)`. `--mode whole` path unchanged. Update the module
docstring: vad mode is now the prod pipeline (pads + overlap+LCS +
max_speech forced cuts); old raw-VAD runs from 2026-08-22 are not comparable.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add eval/run_model.py tests/test_eval_run_model.py
git commit -m "feat(eval): vad mode mirrors prod pipeline (pads, overlap+LCS, max_speech) (#14)"
```

---

### Task 5: Boundary metric — eval/boundary.py

**Files:**
- Create: `eval/boundary.py`
- Test: `tests/test_eval_boundary.py` (new)

**Interfaces:**
- Consumes: `runs/<name>-segments.jsonl` (Task 4 format),
  `runs/<whole>.jsonl`, `eval.normalize.normalize`, jiwer.
- Produces: `attribute(whole_text, seg_texts, win=2) -> dict` with keys
  `junctions` (int), `damaged` (int), `ops` (int), `ops_junction` (int),
  `details` (list of per-op tuples `(is_junction, type, ref, hyp)`);
  `collapse_ratio(whole_text, seg_texts) -> float` (len(whole)/len(vad),
  clips with ratio < 0.7 are excluded as untrustworthy-whole);
  CLI `python -m eval.boundary --segments runs/X-segments.jsonl --whole
  runs/Y.jsonl [--win 2]` printing an aggregate block + per-clip damage list.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_boundary.py`:

```python
# -*- coding: utf-8 -*-
from eval.boundary import attribute, collapse_ratio


def test_clean_junction_not_flagged():
    r = attribute('раз два три четыре пять шесть',
                  ['раз два три', 'четыре пять шесть'])
    assert r['junctions'] == 1 and r['damaged'] == 0 and r['ops'] == 0


def test_substitution_at_junction_flagged():
    r = attribute('раз два три четыре пять шесть',
                  ['раз два три', 'читыре пять шесть'])
    assert r['junctions'] == 1 and r['damaged'] == 1
    assert r['ops'] == 1 and r['ops_junction'] == 1


def test_mid_segment_error_not_attributed_to_junction():
    # ошибка на 2-м слове, стык после 5-го: вне окна ±2 от стыка
    r = attribute('раз два три четыре пять шесть семь восемь девять',
                  ['раз двас три четыре пять', 'шесть семь восемь девять'])
    assert r['damaged'] == 0 and r['ops'] == 1 and r['ops_junction'] == 0


def test_collapse_ratio():
    assert collapse_ratio('раз два', ['раз два три четыре']) == 0.5
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_eval_boundary.py -v`
Expected: FAIL — `ModuleNotFoundError: eval.boundary`

- [ ] **Step 3: Implement**

Create `eval/boundary.py` (formalizes the scratch script from the baseline —
`eval/reports/boundary_attrib.py`; same algorithm, importable + tested):

```python
"""Junction-attribution metric for #14: which vad-vs-whole diffs sit at
VAD segment junctions. whole-decode of the SAME model is the reference —
the diff isolates segmentation damage from model quality."""
import argparse, json

import jiwer

from eval.normalize import normalize


def collapse_ratio(whole_text, seg_texts):
    """len(whole)/len(vad) по нормализованным словам; < 0.7 = whole-decode
    рухнул (длинное/тихое аудио), эталоном служить не может."""
    ww = normalize(whole_text).split()
    vw = normalize(' '.join(seg_texts)).split()
    if not vw:
        return 1.0
    return float(len(ww)) / len(vw)


def attribute(whole_text, seg_texts, win=2):
    seg_words = [normalize(t).split() for t in seg_texts]
    vad_words = [w for sw in seg_words for w in sw]
    whole_words = normalize(whole_text).split()
    juncts, pos = [], 0
    for sw in seg_words[:-1]:
        pos += len(sw)
        juncts.append(pos)
    res = {'junctions': len(juncts), 'damaged': 0, 'ops': 0,
           'ops_junction': 0, 'details': []}
    if not whole_words or not vad_words:
        return res
    out = jiwer.process_words(' '.join(whole_words), ' '.join(vad_words))
    bad = set()
    for c in out.alignments[0]:
        if c.type == 'equal':
            continue
        near = [jp for jp in juncts
                if c.hyp_start_idx - win <= jp <= c.hyp_end_idx + win]
        res['ops'] += 1
        if near:
            res['ops_junction'] += 1
            bad.update(near)
        res['details'].append(
            (bool(near), c.type,
             ' '.join(whole_words[c.ref_start_idx:c.ref_end_idx]),
             ' '.join(vad_words[c.hyp_start_idx:c.hyp_end_idx])))
    res['damaged'] = len(bad)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--segments', required=True,
                    help='runs/<name>-segments.jsonl (Task-4 format)')
    ap.add_argument('--whole', required=True, help='runs/<whole>.jsonl')
    ap.add_argument('--win', type=int, default=2)
    args = ap.parse_args()
    whole = {r['id']: r['hyp'] for r in
             map(json.loads, open(args.whole, encoding='utf-8'))}
    tot = {'junctions': 0, 'damaged': 0, 'ops': 0, 'ops_junction': 0}
    excluded = []
    for row in map(json.loads, open(args.segments, encoding='utf-8')):
        cid, texts = row['id'], [s['text'] for s in row['segments']]
        if cid not in whole or len(texts) < 2:
            continue
        if collapse_ratio(whole[cid], texts) < 0.7:
            excluded.append(cid)
            continue
        r = attribute(whole[cid], texts, args.win)
        for k in tot:
            tot[k] += r[k]
        if r['damaged']:
            print('== %s: %d/%d junctions damaged' %
                  (cid, r['damaged'], r['junctions']))
            for near, typ, ref, hyp in r['details']:
                print('   [%s] %-10s whole=%r vad=%r' %
                      ('JUNCT' if near else 'mid  ', typ, ref, hyp))
    print()
    print('junctions: %d damaged: %d (%.0f%%)  ops: %d junction-ops: %d (%.0f%%)'
          % (tot['junctions'], tot['damaged'],
             100.0 * tot['damaged'] / max(tot['junctions'], 1),
             tot['ops'], tot['ops_junction'],
             100.0 * tot['ops_junction'] / max(tot['ops'], 1)))
    if excluded:
        print('excluded (whole collapsed, ratio<0.7): %s' % ', '.join(excluded))


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add eval/boundary.py tests/test_eval_boundary.py
git commit -m "feat(eval): junction-attribution boundary metric CLI (#14)"
```

---

### Task 6: Measure, tune, document

**Files:**
- Create: `eval/reports/boundary-overlap-tuning.md` (gitignored — stays local)
- Modify: `py/streaming.py` (only if tuning changes OVERLAP/LCS defaults),
  `docs/ARCHITECTURE.md` (pipeline section: overlap+LCS paragraph),
  `docs/DECISIONS.md` (backward-only overlap decision + rationale),
  `CHANGELOG.md` (Unreleased: overlap+LCS at segment boundaries)

**Interfaces:**
- Consumes: everything above; corpus + models already in `eval/`.

- [ ] **Step 1: Parity baseline run (overlap OFF — today's prod pipeline,
  first true measurement of it)**

```bash
.venv/bin/python -m eval.run_model --model-dir eval/models/gigaam-e2e-int8 \
  --name gigaam-vad-par0 --mode vad --overlap 0
.venv/bin/python -m eval.boundary --segments eval/runs/gigaam-vad-par0-segments.jsonl \
  --whole eval/runs/gigaam-whole.jsonl | tail -3
```

Record the aggregate line (junctions / damaged% / ops). NOTE: numbers will
differ from the 2026-08-25 baseline report (44%) — that one measured the old
UNPADDED eval vad; this parity run includes prod pads and max_speech=30.

- [ ] **Step 2: Overlap run (defaults: 1.0 s, min_match 2)**

```bash
.venv/bin/python -m eval.run_model --model-dir eval/models/gigaam-e2e-int8 \
  --name gigaam-vad-ovl10 --mode vad
.venv/bin/python -m eval.boundary --segments eval/runs/gigaam-vad-ovl10-segments.jsonl \
  --whole eval/runs/gigaam-whole.jsonl | tail -3
```

- [ ] **Step 3: Small grid if defaults underperform**

Only if damaged% did not drop ≥2× vs par0: try `--overlap 0.5` and
`--overlap 1.5`; if false merges appear (dedupe of genuine repeats —
inspect JUNCT deletes in the per-clip listing), raise `LCS_MIN_MATCH` to 3
and rerun. Pick the best (damaged% primary, ops_junction secondary);
if the winner differs from the defaults, change `OVERLAP`/`LCS_MIN_MATCH`
in `py/streaming.py` accordingly (single source — prod and eval both move).

- [ ] **Step 4: Whole-corpus sanity — overall WER must not regress**

```bash
.venv/bin/python -m eval.report eval/runs/gigaam-vad-par0.jsonl eval/runs/gigaam-vad-ovl10.jsonl
```

Expected: aggregate WER (vs refs) for ovl10 ≤ par0 + 0.5 pp. Refs are noisy
(Parakeet-authored, see baseline report) — this is a regression guard, not
the target metric.

- [ ] **Step 5: Write the tuning report**

`eval/reports/boundary-overlap-tuning.md`: table of runs (name, overlap,
min_match, junctions, damaged%, ops_junction, aggregate WER), the chosen
defaults, 2–3 sample junction fixes (from the CLI listing — file is
gitignored, transcripts allowed), and the parity-vs-old-baseline note.
Verify privacy: `git check-ignore eval/reports/boundary-overlap-tuning.md
eval/runs/gigaam-vad-par0.jsonl` must list both.

- [ ] **Step 6: Docs**

- `docs/ARCHITECTURE.md`: in the recognition-pipeline section describe
  backward overlap + LCS dedupe (constants, why backward-only: streaming
  cannot wait for future audio).
- `docs/DECISIONS.md`: new entry «Backward-only overlap + token-LCS dedupe at
  VAD junctions» — alternatives considered (symmetric NVIDIA chunking:
  offline-only; bigger static pads: no dedupe → duplicates), measured effect
  (numbers from Step 2).
- `CHANGELOG.md` Unreleased: «Overlap+LCS merge at segment boundaries —
  words at VAD junctions no longer lost/garbled (issue #14)».

- [ ] **Step 7: Full suite + commit**

```bash
.venv/bin/python -m pytest tests/ -q
git add docs/ARCHITECTURE.md docs/DECISIONS.md CHANGELOG.md py/streaming.py
git commit -m "docs: overlap+LCS decision, architecture and changelog (#14)"
git status --short   # must show NO eval/ paths staged or untracked-red
```

- [ ] **Step 8: PR**

```bash
git push -u origin feat/overlap-lcs
gh pr create --title "Overlap+LCS at VAD segment boundaries (#14)" \
  --body "Closes #14. Backward overlap (streaming-compatible) + token-LCS dedupe; eval vad mode now mirrors prod; boundary metric CLI. Numbers in PR comment."
```

PR body/comment: aggregates ONLY (junctions, damaged% before/after, ops) —
no corpus transcripts. Merge after review + Khan's acceptance below.

---

## Acceptance (after merge — Khan, on device)

Manual, Khan-gated: install the build on the phone, dictate long speech with
short pauses (and one 40 s+ no-pause monologue for a forced cut), confirm no
lost/duplicated words at junctions and normal capitalization. Then release
(v0.10.0) per the usual flow. Issue #14 gets a closing comment with the
aggregate numbers from the tuning report.

## Self-review notes

- Spec §5 coverage: forced cuts (max_speech) — covered by overlap branch (gap
  is 0 at forced cuts → ≤ OVERLAP_GAP_MAX → overlap applies) and measured via
  eval `--max-speech 30`; natural-pause edge degradation (baseline's dominant
  class) — same mechanism. Pre-speech padding from the issue note (#3035) —
  already in prod (PAD_PRE), untouched.
- `overlap=0` default keeps Segmenter/DecodeWorker byte-compatible: verified
  by leaving all pre-existing tests unmodified.
- Type consistency: `Phrase.overlap` (float, seconds) produced in Task 2,
  consumed via `getattr(seg, 'overlap', 0.0)` in Task 3 and `ph.overlap` in
  Task 4; `join_chunk` signature identical at all three call sites.
- Names `vad_pipeline`/`decode_corpus_vad`/`build_vad` (Task 4) match the
  monkeypatch and imports in the Task-4 tests; `attribute`/`collapse_ratio`
  (Task 5) match the Task-5 tests.
