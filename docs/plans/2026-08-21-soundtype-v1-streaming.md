# SoundType v1: Streaming + Self-Download + Waveform — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Мгновенный текст на «стоп» (декод по ходу записи), самозагрузка модели кнопкой при первом запуске, waveform-лента во время записи.

**Architecture:** Три чистых модуля: `py/streaming.py` (Segmenter — VAD-нарезка в цикле записи; DecodeWorker — фоновый поток декода через `queue.Queue`), `py/downloader.py` (логика fetch-deps как импортируемый модуль с колбэком прогресса), QML-слой (partial-текст, экран загрузки, waveform). `backend.py` только связывает их. Спека: `docs/specs/2026-08-20-streaming-selfdownload-waveform.md`.

**Tech Stack:** Python 3.8 (телефон), sherpa-onnx 1.13.6 + numpy 1.24.4 (pylibs), silero VAD, pyotherside, QML (Qt 5.12, Lomiri.Components 1.3). Тесты: pytest на Mac в `.venv`.

## Global Constraints

- Целевая платформа: Ubuntu Touch 20.04 = Python 3.8, Qt 5.12. Никаких конструкций новее Python 3.8 (нет `match`, нет `X | Y` в типах).
- На телефоне доступны ТОЛЬКО stdlib + `numpy 1.24.4` + `sherpa-onnx 1.13.6` из `runtime/pylibs`. Никакого pip/torch.
- Ловушка sherpa-onnx issue #2918: декодировать ТОЛЬКО текущий сегмент, НИКОГДА не пере-декодировать растущий буфер.
- Параметры VAD не менять: `threshold 0.5`, `min_silence_duration 0.35`, `min_speech_duration 0.20`, `max_speech_duration 30.0` (MAX_SPEECH).
- Стиль backend: %-форматирование строк, русские докстринги и комментарии — как в существующем коде.
- Каждое НОВОЕ pyotherside-событие обязано получить `setHandler` в `Main.qml` (иначе теряется молча). Новые события v1: `partial`, `deps-missing`, `download-progress`, `download-done`, `download-error`.
- `py/streaming.py` и `py/downloader.py` НЕ импортируют pyotherside — чистая логика, общение через колбэки. Только `backend.py` эмитит события.
- Тесты гоняются на Mac: `.venv/bin/python -m pytest tests/ -v`. Один раз создать: `python3 -m venv .venv && .venv/bin/pip install pytest numpy`.
- Коммиты: английские, короткие, БЕЗ Co-Authored-By. Рабочий каталог git — корень репо soundtype.
- Версия релиза этих фич: 0.6.0 (бамп в задаче 9, не раньше).

## File Structure

- Create: `py/streaming.py` — `Segmenter` (окна 512 → VAD → готовые сегменты) + `DecodeWorker` (поток: очередь → декод → колбэк текста).
- Create: `py/downloader.py` — `missing()`, `download()`, `fetch_wheels/silero/parakeet()`, `fetch_all()`. Без pyotherside и без print.
- Modify: `py/backend.py` — `_session` со стримингом, `_split` через Segmenter (DRY), `init` → проверка deps, `fetch_deps()`, guard retry-во-время-записи, CHUNK_BYTES 4 окна.
- Modify: `qml/Main.qml` — обработчики новых событий, partial-текст, оверлей загрузки, waveform.
- Modify: `soundtype.apparmor` — + `networking`.
- Modify: `scripts/fetch-deps.py` — тонкая CLI-обёртка над downloader.
- Create: `tests/conftest.py`, `tests/fakes.py`, `tests/test_segmenter.py`, `tests/test_decode_worker.py`, `tests/test_backend_session.py`, `tests/test_downloader.py`, `tests/test_backend_deps.py`.
- Modify: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `CHANGELOG.md`, `README.md`, `manifest.json`, `.gitignore`.

---

### Task 1: Тестовый каркас + Segmenter

**Files:**
- Create: `tests/conftest.py`, `tests/fakes.py`, `tests/test_segmenter.py`
- Create: `py/streaming.py` (пока только Segmenter)
- Modify: `.gitignore` (добавить `.venv/`)

**Interfaces:**
- Consumes: интерфейс sherpa-onnx VAD: `accept_waveform(samples)`, `empty()`, `front.samples`, `pop()`, `flush()`.
- Produces: `Segmenter(vad, np, window=512)`; `feed(samples: np.float32 1-D array) -> list` (список samples готовых сегментов); `flush() -> list` (дожимает хвост < окна + остатки VAD). Остаток, не кратный окну, хранится между feed'ами.

- [ ] **Step 1: Создать venv для тестов (один раз)**

```bash
cd /Users/n0mads/Downloads/platform-tools/ut-build/soundtype
python3 -m venv .venv && .venv/bin/pip install pytest numpy
printf '\n.venv/\n' >> .gitignore
```

- [ ] **Step 2: Написать conftest и фейки**

`tests/conftest.py`:

```python
# -*- coding: utf-8 -*-
"""Общая обвязка: py/ в пути импорта, заглушка pyotherside с журналом событий."""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'py'))
sys.path.insert(0, os.path.dirname(__file__))

EVENTS = []


def _send(event, *args):
    EVENTS.append((event,) + args)


sys.modules.setdefault('pyotherside', types.SimpleNamespace(send=_send))


@pytest.fixture
def events():
    EVENTS.clear()
    return EVENTS
```

`tests/fakes.py`:

```python
# -*- coding: utf-8 -*-
"""Фейковый VAD: ровно тот кусочек интерфейса sherpa-onnx, что нужен Segmenter."""

import types


def make_segment(samples):
    return types.SimpleNamespace(samples=samples)


class FakeVad(object):
    def __init__(self):
        self.windows = []    # всё, что скормили через accept_waveform
        self.pending = []    # «созревшие» сегменты; тест кладёт их сам
        self.flushed = False
        self.resets = 0

    def accept_waveform(self, w):
        self.windows.append(list(w))

    def empty(self):
        return not self.pending

    @property
    def front(self):
        return self.pending[0]

    def pop(self):
        self.pending.pop(0)

    def flush(self):
        self.flushed = True

    def reset(self):
        self.resets += 1
```

- [ ] **Step 3: Написать падающие тесты Segmenter**

`tests/test_segmenter.py`:

```python
# -*- coding: utf-8 -*-
import numpy as np

from fakes import FakeVad, make_segment
from streaming import Segmenter


def test_feeds_vad_by_windows():
    vad = FakeVad()
    s = Segmenter(vad, np, window=512)
    s.feed(np.zeros(1024, dtype=np.float32))
    assert len(vad.windows) == 2
    assert all(len(w) == 512 for w in vad.windows)


def test_carries_tail_between_feeds():
    vad = FakeVad()
    s = Segmenter(vad, np, window=512)
    s.feed(np.zeros(700, dtype=np.float32))
    assert len(vad.windows) == 1
    s.feed(np.zeros(400, dtype=np.float32))   # 188 хвост + 400 = 588 → ещё окно
    assert len(vad.windows) == 2


def test_returns_ready_segments():
    vad = FakeVad()
    s = Segmenter(vad, np, window=512)
    vad.pending.append(make_segment([0.1] * 800))
    got = s.feed(np.zeros(512, dtype=np.float32))
    assert got == [[0.1] * 800]


def test_flush_feeds_tail_and_drains():
    vad = FakeVad()
    s = Segmenter(vad, np, window=512)
    s.feed(np.zeros(300, dtype=np.float32))
    assert vad.windows == []                  # хвост меньше окна ещё не ушёл
    vad.pending.append(make_segment([0.2] * 640))
    got = s.flush()
    assert vad.flushed
    assert len(vad.windows) == 1 and len(vad.windows[0]) == 300
    assert got == [[0.2] * 640]
```

- [ ] **Step 4: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_segmenter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'streaming'`

- [ ] **Step 5: Написать Segmenter**

`py/streaming.py`:

```python
# -*- coding: utf-8 -*-
"""Потоковая нарезка и фоновое распознавание.

Segmenter гонит звук через VAD окнами по 512 отсчётков прямо из цикла
записи; готовые фразы уходят вызывающему. DecodeWorker (задача 2) разбирает
их в отдельном потоке. Ловушка sherpa-onnx #2918: декодируем только сегмент,
никогда весь накопленный буфер.

Модуль не знает про pyotherside — только колбэки. Так его можно гонять
тестами на любой машине.
"""

import queue
import threading

_SENTINEL = object()


class Segmenter(object):
    """Кормит VAD окнами по `window` отсчётков, отдаёт готовые сегменты.

    feed() принимает float32-массив произвольной длины; остаток, не кратный
    окну, хранится до следующего feed() или flush().
    """

    def __init__(self, vad, np, window=512):
        self.vad = vad
        self.np = np
        self.window = window
        self._tail = np.zeros(0, dtype=np.float32)

    def _drain(self, out):
        while not self.vad.empty():
            out.append(self.vad.front.samples)
            self.vad.pop()

    def feed(self, samples):
        np = self.np
        buf = np.concatenate([self._tail, samples]) if len(self._tail) else samples
        n = (len(buf) // self.window) * self.window
        self._tail = buf[n:]
        out = []
        for i in range(0, n, self.window):
            self.vad.accept_waveform(buf[i:i + self.window])
            self._drain(out)
        return out

    def flush(self):
        """Дожимаем хвост меньше окна и всё, что осталось внутри VAD."""
        if len(self._tail):
            self.vad.accept_waveform(self._tail)
            self._tail = self._tail[:0]
        self.vad.flush()
        out = []
        self._drain(out)
        return out
```

- [ ] **Step 6: Убедиться, что тесты зелёные**

Run: `.venv/bin/python -m pytest tests/test_segmenter.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add tests/ py/streaming.py .gitignore
git commit -m "test: harness; feat: Segmenter for streaming VAD windowing"
```

---

### Task 2: DecodeWorker — фоновый поток декода

**Files:**
- Modify: `py/streaming.py` (добавить DecodeWorker)
- Test: `tests/test_decode_worker.py`

**Interfaces:**
- Consumes: ничего из задачи 1 (независимый класс в том же файле).
- Produces: `DecodeWorker(decode_fn, on_text, on_error=None, min_samples=0)` — поток стартует в конструкторе; `put(segment)`; `close(timeout=None) -> str` (кладёт сентинел, ждёт поток, возвращает весь текст через пробел). `on_text(idx, text)` зовётся из потока worker'а для каждого непустого текста, idx с 1.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_decode_worker.py`:

```python
# -*- coding: utf-8 -*-
from streaming import DecodeWorker


def test_decodes_in_order_and_reports():
    calls = []
    w = DecodeWorker(lambda seg: 'txt-%d' % len(seg),
                     on_text=lambda idx, t: calls.append((idx, t)))
    w.put([0.0] * 10)
    w.put([0.0] * 20)
    assert w.close(timeout=5) == 'txt-10 txt-20'
    assert calls == [(1, 'txt-10'), (2, 'txt-20')]


def test_skips_short_segments():
    w = DecodeWorker(lambda seg: 'x', on_text=lambda i, t: None,
                     min_samples=100)
    w.put([0.0] * 10)
    assert w.close(timeout=5) == ''


def test_error_does_not_kill_worker():
    errors = []

    def decode(seg):
        if len(seg) == 1:
            raise RuntimeError('boom')
        return 'ok'

    w = DecodeWorker(decode, on_text=lambda i, t: None,
                     on_error=lambda exc: errors.append(str(exc)))
    w.put([0.0])
    w.put([0.0, 0.0])
    assert w.close(timeout=5) == 'ok'
    assert errors == ['boom']


def test_empty_text_ignored():
    calls = []
    w = DecodeWorker(lambda seg: '  ', on_text=lambda i, t: calls.append(t))
    w.put([0.0])
    assert w.close(timeout=5) == ''
    assert calls == []
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_decode_worker.py -v`
Expected: FAIL — `ImportError: cannot import name 'DecodeWorker'`

- [ ] **Step 3: Написать DecodeWorker (добавить в конец py/streaming.py)**

```python
class DecodeWorker(object):
    """Отдельный поток: берёт сегменты из очереди, декодирует, копит текст.

    Декод в C++ (sherpa-onnx) отпускает GIL, поэтому поток реально
    работает параллельно записи. Ошибка на одном сегменте не убивает
    поток — сегмент пропускается, остальные декодируются.
    """

    def __init__(self, decode_fn, on_text, on_error=None, min_samples=0):
        self.decode_fn = decode_fn
        self.on_text = on_text
        self.on_error = on_error
        self.min_samples = min_samples
        self.texts = []
        self.q = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def put(self, segment):
        self.q.put(segment)

    def close(self, timeout=None):
        """Сигнал конца: дожидаемся очереди, отдаём склеенный текст."""
        self.q.put(_SENTINEL)
        self._thread.join(timeout)
        return ' '.join(self.texts).strip()

    def _run(self):
        idx = 0
        while True:
            seg = self.q.get()
            if seg is _SENTINEL:
                return
            if self.min_samples and len(seg) < self.min_samples:
                continue
            idx += 1
            try:
                text = (self.decode_fn(seg) or '').strip()
            except Exception as exc:
                if self.on_error is not None:
                    self.on_error(exc)
                continue
            if text:
                self.texts.append(text)
                self.on_text(idx, text)
```

- [ ] **Step 4: Убедиться, что все тесты зелёные**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add py/streaming.py tests/test_decode_worker.py
git commit -m "feat: DecodeWorker background decode thread"
```

---

### Task 3: Streaming-сессия в backend

**Files:**
- Modify: `py/backend.py`
- Test: `tests/test_backend_session.py`

**Interfaces:**
- Consumes: `streaming.Segmenter(vad, np, VAD_WINDOW)`, `streaming.DecodeWorker(decode_fn, on_text, on_error, min_samples)` из задач 1–2.
- Produces: новое pyotherside-событие `partial(idx, text)` (живой текст по ходу); `_record(self, on_chunk=None)` — зовёт `on_chunk(data: bytes)` на каждый прочитанный кусок; события `final/done/transcribing/recording/level/elapsed` сохраняют прежнюю семантику.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_backend_session.py`:

```python
# -*- coding: utf-8 -*-
import threading
import time

import numpy as np

import backend
from fakes import FakeVad, make_segment


def test_session_streams_segments(events, monkeypatch):
    eng = backend.Dictation()
    eng.np = np
    vad = FakeVad()
    eng.vad = vad
    eng.recognizer = object()
    monkeypatch.setattr(eng, '_decode', lambda seg: 'слово%d' % len(seg))

    chunk = b'\x10\x00' * 4096

    def fake_record(on_chunk=None):
        on_chunk(chunk)
        # после первой порции VAD «дозрел» до сегмента
        vad.pending.append(make_segment([0.1] * 8000))
        on_chunk(chunk)
        return chunk * 40          # достаточно длинно для сохранения
    monkeypatch.setattr(eng, '_record', fake_record)
    monkeypatch.setattr(backend, '_history_append', lambda *a: None)
    monkeypatch.setattr(backend, '_audio_save', lambda *a: None)

    eng._session()

    assert [e for e in events if e[0] == 'partial'] == \
        [('partial', 1, 'слово8000')]
    finals = [e for e in events if e[0] == 'final']
    assert finals and finals[0][1] == 'слово8000'
    assert ('done', 'слово8000') in events
    assert vad.flushed             # хвост дожат на стопе
    assert vad.resets == 1         # VAD сброшен перед сессией


def test_short_recording_gives_empty_done(events, monkeypatch):
    eng = backend.Dictation()
    eng.np = np
    eng.vad = FakeVad()
    eng.recognizer = object()
    monkeypatch.setattr(eng, '_decode', lambda seg: 'x')
    monkeypatch.setattr(eng, '_record', lambda on_chunk=None: b'\x00\x00' * 100)

    eng._session()

    assert ('done', '') in events
    assert not [e for e in events if e[0] == 'final']


def test_retry_refused_while_recording(events):
    eng = backend.Dictation()
    eng.recognizer = object()
    eng.thread = threading.Thread(target=time.sleep, args=(0.6,))
    eng.thread.start()
    eng.retry(123.0)
    for _ in range(100):
        if any(e[0] == 'error' for e in events):
            break
        time.sleep(0.02)
    assert any(e[0] == 'error' and 'запис' in str(e[1]) for e in events)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_backend_session.py -v`
Expected: FAIL — `_record() got an unexpected keyword argument 'on_chunk'` / нет события `partial` / нет guard'а в retry

- [ ] **Step 3: Внести изменения в backend.py**

3a. Импорт после `import pyotherside`:

```python
import streaming  # noqa: E402
```

3b. Чанк чтения — 4 окна вместо 8 (уровень для волны ~8 раз/с, окна VAD не задеты):

```python
CHUNK_BYTES = VAD_WINDOW * 2 * 4  # 4 окна = 0.128 с: level для волны ~8 раз/с
```

3c. `_record` получает колбэк — единственная правка цикла (после `emit('level', ...)` и learn-блока, рядом с `parts.append(data)`):

```python
    def _record(self, on_chunk=None):
        """Пишем звук в память до нажатия стоп; каждый кусок отдаём колбэку."""
```

и внутри цикла сразу после `data = buf.raw[:CHUNK_BYTES]` + блока level:

```python
                if on_chunk is not None:
                    on_chunk(data)
```

(остальное тело `_record` не трогать.)

3d. `_split` переиспользует Segmenter (убрать ручной цикл окон):

```python
    def _split(self, pcm):
        """Режем запись на фразы. Общий механизм с потоковым режимом."""
        self.vad.reset()
        seg = streaming.Segmenter(self.vad, self.np, VAD_WINDOW)
        segments = seg.feed(pcm)
        segments += seg.flush()
        if not segments and len(pcm):
            segments = [pcm]
        return segments
```

3e. `_session` — декод по ходу записи:

```python
    def _session(self):
        worker = None
        try:
            np = self.np
            self.vad.reset()
            seg = streaming.Segmenter(self.vad, np, VAD_WINDOW)
            worker = streaming.DecodeWorker(
                self._decode,
                on_text=lambda idx, text: emit('partial', idx, text),
                on_error=lambda exc: emit('error',
                                          'Сбой распознавания: %s' % exc),
                min_samples=int(RATE * 0.2))

            def on_chunk(data):
                samples = (np.frombuffer(data, dtype=np.int16)
                           .astype(np.float32) / 32768.0)
                for s in seg.feed(samples):
                    worker.put(s)

            raw = self._record(on_chunk)
            ts = time.time()

            # На стопе осталась только последняя открытая фраза.
            emit('transcribing', True)
            for s in seg.flush():
                worker.put(s)
            full = worker.close(timeout=180)
            emit('transcribing', False)

            if len(raw) < RATE * 2 * 0.3:
                emit('done', '')
                return

            if full:
                _history_append(full, ts)
                _audio_save(ts, raw)
                emit('final', full, ts)
            emit('done', full)
        except Exception as exc:
            if worker is not None:
                worker.close(timeout=5)
            emit('transcribing', False)
            emit('error', str(exc))
            emit('done', '')
```

3f. Guard в `retry` — самое начало `work()` (запись и retry делят один VAD):

```python
            if self.thread is not None and self.thread.is_alive():
                emit('error', 'Идёт запись — сначала останови её')
                return
```

- [ ] **Step 4: Убедиться, что все тесты зелёные**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add py/backend.py tests/test_backend_session.py
git commit -m "feat: decode during recording (simulated streaming)"
```

---

### Task 4: QML — живой текст (partial)

**Files:**
- Modify: `qml/Main.qml`

**Interfaces:**
- Consumes: событие `partial(idx, text)` из задачи 3.
- Produces: `root.partialText` (string) — накопленный живой текст; используется только внутри Main.qml.

QML-тестов в проекте нет — проверка глазами на устройстве в задаче 10 (критерий 1 спеки).

- [ ] **Step 1: Добавить свойство** (рядом с `property string progressText`):

```qml
    property string partialText: ""
```

- [ ] **Step 2: Обработчик partial** (в `Component.onCompleted` рядом с `setHandler("progress", ...)`):

```qml
            setHandler("partial", function (idx, t) {
                root.partialText += (root.partialText.length ? " " : "") + t;
            });
```

- [ ] **Step 3: Очистка на старте и финише.** В обработчике `recording` в ветку `if (on)` добавить `root.partialText = "";` В обработчике `done` первой строкой добавить `root.partialText = "";`

- [ ] **Step 4: Показ живого текста.** Заменить биндинг `text` у `partialLabel`:

```qml
                                text: {
                                    if (root.partialText.length)
                                        return root.partialText;
                                    return root.transcribing
                                          ? ("расшифровываю… " + root.progressText)
                                          : "";
                                }
```

- [ ] **Step 5: Прогнать python-тесты (регрессия) и закоммитить**

Run: `.venv/bin/python -m pytest tests/ -v` → 11 passed

```bash
git add qml/Main.qml
git commit -m "feat: live partial text while recording"
```

---

### Task 5: Модуль downloader + тонкий fetch-deps.py

**Files:**
- Create: `py/downloader.py`
- Modify: `scripts/fetch-deps.py` (стал обёрткой)
- Test: `tests/test_downloader.py`

**Interfaces:**
- Consumes: ничего из прошлых задач.
- Produces: `downloader.DATA` (str); `missing(data_dir=DATA) -> list[str]` (пусто = всё на месте, имена: `'numpy'`, `'sherpa-onnx'`, `'silero-vad'`, `'parakeet'`); `fetch_all(progress=None, data_dir=DATA, force=False)` — качает недостающее, `progress(stage: str, pct: int)` (pct −1 = размер неизвестен), при сбое БРОСАЕТ исключение (вызывающий решает, как показать).

- [ ] **Step 1: Написать падающие тесты**

`tests/test_downloader.py`:

```python
# -*- coding: utf-8 -*-
import pytest

import downloader


def test_missing_on_empty_dir(tmp_path):
    assert downloader.missing(str(tmp_path)) == [
        'numpy', 'sherpa-onnx', 'silero-vad', 'parakeet']


def test_missing_when_all_present(tmp_path):
    d = tmp_path
    (d / 'runtime' / 'pylibs' / 'numpy').mkdir(parents=True)
    (d / 'runtime' / 'pylibs' / 'sherpa_onnx').mkdir()
    (d / 'models' / 'parakeet').mkdir(parents=True)
    (d / 'models' / 'silero_vad.onnx').write_bytes(b'x')
    (d / 'models' / 'parakeet' / 'encoder.int8.onnx').write_bytes(b'x')
    assert downloader.missing(str(d)) == []


def test_fetch_all_runs_stages_in_order(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(downloader, 'fetch_wheels',
                        lambda p, d, f: calls.append('wheels'))
    monkeypatch.setattr(downloader, 'fetch_silero',
                        lambda p, d, f: calls.append('silero'))
    monkeypatch.setattr(downloader, 'fetch_parakeet',
                        lambda p, d, f: calls.append('parakeet'))
    downloader.fetch_all(None, str(tmp_path))
    assert calls == ['wheels', 'silero', 'parakeet']


def test_fetch_error_bubbles_up(tmp_path, monkeypatch):
    def boom(url, dest=None, progress=None, stage=''):
        raise OSError('нет сети')
    monkeypatch.setattr(downloader, 'download', boom)
    with pytest.raises(OSError):
        downloader.fetch_all(None, str(tmp_path))
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_downloader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'downloader'`

- [ ] **Step 3: Написать py/downloader.py**

```python
# -*- coding: utf-8 -*-
"""Скачивание модели и python-библиотек в каталог данных приложения.

Одна логика на двух хозяев:

  * scripts/fetch-deps.py — ручной запуск из терминала;
  * py/backend.py — кнопка «Скачать» при первом запуске приложения.

Прогресс отдаётся колбэком progress(stage, pct): stage — человекочитаемое
имя этапа, pct — целые проценты либо -1, если размер неизвестен. Никаких
pyotherside и print — модуль чистый, его гоняют тесты на любой машине.
Сбой = исключение наружу; докачки нет, повтор качает файл заново.
"""

import io
import json
import os
import shutil
import tarfile
import urllib.request
import zipfile

APP = 'soundtype.n0madd3v0ps'
HOME = os.environ.get('HOME', os.path.expanduser('~'))
DATA = os.path.join(HOME, '.local', 'share', APP)

PARAKEET_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
                'asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2')
SILERO_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
              'asr-models/silero_vad.onnx')

# Колёса под Python 3.8 / aarch64 — ровно то, что стоит в Ubuntu Touch 20.04.
WHEELS = [
    ('numpy', '1.24.4', 'cp38-cp38-manylinux_2_17_aarch64'),
    ('sherpa-onnx', '1.13.6', 'cp38-cp38-manylinux2014_aarch64'),
]

UA = {'User-Agent': 'soundtype-downloader'}


def _models(data_dir):
    return os.path.join(data_dir, 'models')


def _pylibs(data_dir):
    return os.path.join(data_dir, 'runtime', 'pylibs')


def missing(data_dir=DATA):
    """Чего не хватает для работы. Пустой список — всё на месте."""
    out = []
    for pkg, _ver, _tag in WHEELS:
        if not os.path.exists(os.path.join(_pylibs(data_dir),
                                           pkg.replace('-', '_'))):
            out.append(pkg)
    if not os.path.exists(os.path.join(_models(data_dir), 'silero_vad.onnx')):
        out.append('silero-vad')
    if not os.path.exists(os.path.join(_models(data_dir), 'parakeet',
                                       'encoder.int8.onnx')):
        out.append('parakeet')
    return out


def download(url, dest=None, progress=None, stage=''):
    """Качаем файл; dest=None — в память. progress зовём на целых процентах."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get('Content-Length') or 0)
        buf = open(dest, 'wb') if dest else io.BytesIO()
        got = 0
        last = -2
        try:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                buf.write(chunk)
                got += len(chunk)
                if progress is not None:
                    pct = int(got * 100 / total) if total else -1
                    if pct != last:
                        last = pct
                        progress(stage, pct)
            if dest:
                return dest
            return buf.getvalue()
        finally:
            if dest:
                buf.close()


def fetch_wheels(progress=None, data_dir=DATA, force=False):
    pylibs = _pylibs(data_dir)
    os.makedirs(pylibs, exist_ok=True)
    for pkg, ver, tag in WHEELS:
        probe = os.path.join(pylibs, pkg.replace('-', '_'))
        if os.path.exists(probe) and not force:
            continue
        meta = json.loads(download(
            'https://pypi.org/pypi/%s/%s/json' % (pkg, ver)).decode('utf-8'))
        url = None
        for f in meta['urls']:
            if tag in f['filename']:
                url = f['url']
                break
        if not url:
            raise RuntimeError('не нашёл колесо %s %s (%s)' % (pkg, ver, tag))
        blob = download(url, progress=progress, stage=pkg)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(pylibs)


def fetch_silero(progress=None, data_dir=DATA, force=False):
    models = _models(data_dir)
    os.makedirs(models, exist_ok=True)
    dest = os.path.join(models, 'silero_vad.onnx')
    if os.path.exists(dest) and not force:
        return
    download(SILERO_URL, dest, progress=progress, stage='детектор тишины')


def fetch_parakeet(progress=None, data_dir=DATA, force=False):
    models = _models(data_dir)
    os.makedirs(models, exist_ok=True)
    target = os.path.join(models, 'parakeet')
    if os.path.exists(os.path.join(target, 'encoder.int8.onnx')) and not force:
        return
    tmp = os.path.join(models, '_parakeet.tar.bz2')
    download(PARAKEET_URL, tmp, progress=progress, stage='модель Parakeet')

    if progress is not None:
        progress('распаковка', -1)
    unpack = os.path.join(models, '_unpack')
    shutil.rmtree(unpack, ignore_errors=True)
    os.makedirs(unpack)
    with tarfile.open(tmp, 'r:bz2') as tf:
        tf.extractall(unpack)

    # Внутри архива один каталог — забираем из него нужные файлы.
    inner = [os.path.join(unpack, d) for d in os.listdir(unpack)]
    inner = [d for d in inner if os.path.isdir(d)]
    if not inner:
        raise RuntimeError('в архиве не нашлось каталога с моделью')
    src = inner[0]

    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    for fn in ('encoder.int8.onnx', 'decoder.int8.onnx',
               'joiner.int8.onnx', 'tokens.txt'):
        s = os.path.join(src, fn)
        if not os.path.exists(s):
            raise RuntimeError('в архиве нет файла %s' % fn)
        shutil.move(s, os.path.join(target, fn))

    shutil.rmtree(unpack, ignore_errors=True)
    os.remove(tmp)


def fetch_all(progress=None, data_dir=DATA, force=False):
    """Скачать всё недостающее. Сбой = исключение наружу."""
    fetch_wheels(progress, data_dir, force)
    fetch_silero(progress, data_dir, force)
    fetch_parakeet(progress, data_dir, force)
```

- [ ] **Step 4: Переписать scripts/fetch-deps.py как обёртку** (полная замена содержимого):

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ручной запуск загрузчика:  python3 scripts/fetch-deps.py [--force]

Вся логика — в py/downloader.py; тот же код зовёт кнопка «Скачать»
в самом приложении. Качается около 500 МБ, распаковано примерно 700 МБ.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'py'))

import downloader  # noqa: E402


def show(stage, pct):
    if pct < 0:
        sys.stdout.write('\r  %s…            ' % stage)
    else:
        sys.stdout.write('\r  %s  %3d%%' % (stage, pct))
    sys.stdout.flush()


def main():
    print('Каталог данных:', downloader.DATA)
    force = '--force' in sys.argv
    if not downloader.missing() and not force:
        print('Всё уже на месте.')
        return
    downloader.fetch_all(show, force=force)
    print('\nГотово. Теперь можно собирать:  ./scripts/build.sh')


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Убедиться, что тесты зелёные + обёртка запускается**

Run: `.venv/bin/python -m pytest tests/ -v` → 15 passed
Run: `.venv/bin/python scripts/fetch-deps.py --помощь 2>/dev/null; echo $?` — не должен упасть на импорте (выведет «Каталог данных…» и полезет в сеть только если файлов нет; на Mac каталога нет — прервать Ctrl-C можно, важно отсутствие ImportError). Безопасная проверка импорта:
`.venv/bin/python -c "import sys; sys.path.insert(0, 'py'); import downloader; print(downloader.missing('/nonexistent'))"`
Expected: `['numpy', 'sherpa-onnx', 'silero-vad', 'parakeet']`

- [ ] **Step 6: Commit**

```bash
git add py/downloader.py scripts/fetch-deps.py tests/test_downloader.py
git commit -m "refactor: extract downloader module from fetch-deps script"
```

---

### Task 6: Backend — deps-события + networking в apparmor

**Files:**
- Modify: `py/backend.py`, `soundtype.apparmor`
- Test: `tests/test_backend_deps.py`

**Interfaces:**
- Consumes: `downloader.missing()`, `downloader.fetch_all(progress)` из задачи 5.
- Produces: события `deps-missing(list)`, `download-progress(stage, pct)`, `download-done()`, `download-error(msg)`; функция `backend.fetch_deps()` (зовётся из QML).

- [ ] **Step 1: Написать падающие тесты**

`tests/test_backend_deps.py`:

```python
# -*- coding: utf-8 -*-
import time

import backend


def test_init_reports_missing_deps(events, monkeypatch):
    monkeypatch.setattr(backend.downloader, 'missing', lambda: ['parakeet'])
    backend.init()
    assert ('deps-missing', ['parakeet']) in events


def test_init_loads_engine_when_deps_ok(events, monkeypatch):
    monkeypatch.setattr(backend.downloader, 'missing', lambda: [])
    called = []
    monkeypatch.setattr(backend._engine, 'load', lambda: called.append(1))
    backend.init()
    assert called == [1]


def _wait_event(events, name, tries=150):
    for _ in range(tries):
        if any(e[0] == name for e in events):
            return
        time.sleep(0.02)


def test_fetch_deps_reports_error(events, monkeypatch):
    def boom(cb):
        raise OSError('нет сети')
    monkeypatch.setattr(backend.downloader, 'fetch_all', boom)
    backend.fetch_deps()
    _wait_event(events, 'download-error')
    assert any(e[0] == 'download-error' and 'нет сети' in e[1]
               for e in events)


def test_fetch_deps_success_loads_engine(events, monkeypatch):
    monkeypatch.setattr(backend.downloader, 'fetch_all',
                        lambda cb: cb('модель Parakeet', 50))
    called = []
    monkeypatch.setattr(backend._engine, 'load', lambda: called.append(1))
    backend.fetch_deps()
    _wait_event(events, 'download-done')
    assert ('download-progress', 'модель Parakeet', 50) in events
    assert ('download-done',) in events
    assert called == [1]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_backend_deps.py -v`
Expected: FAIL — `AttributeError: module 'backend' has no attribute 'downloader'` / `'fetch_deps'`

- [ ] **Step 3: Изменить backend.py.** Импорт (рядом с `import streaming`):

```python
import downloader  # noqa: E402
```

Заменить существующую функцию `init` и добавить `fetch_deps` (в самом низу, рядом с `def start()`):

```python
def init(_ignored=None):
    miss = downloader.missing()
    if miss:
        emit('deps-missing', miss)
        return
    _engine.load()


def fetch_deps():
    """Скачиваем модель и библиотеки по кнопке из UI, с прогрессом."""
    def work():
        try:
            emit('download-progress', 'подготовка', -1)
            downloader.fetch_all(
                lambda stage, pct: emit('download-progress', stage, pct))
            emit('download-done')
            _engine.load()
        except Exception as exc:
            emit('download-error', str(exc))
    threading.Thread(target=work, daemon=True).start()
```

- [ ] **Step 4: apparmor — добавить сеть** (`soundtype.apparmor`, полное новое содержимое):

```json
{
    "policy_groups": [
        "microphone",
        "audio",
        "keep-display-on",
        "networking"
    ],
    "policy_version": 20.04
}
```

- [ ] **Step 5: Убедиться, что все тесты зелёные**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 19 passed

- [ ] **Step 6: Commit**

```bash
git add py/backend.py soundtype.apparmor tests/test_backend_deps.py
git commit -m "feat: self-download API in backend, networking apparmor group"
```

---

### Task 7: QML — экран первичной загрузки

**Files:**
- Modify: `qml/Main.qml`

**Interfaces:**
- Consumes: события `deps-missing`, `download-progress`, `download-done`, `download-error` и функция `backend.fetch_deps` из задачи 6.
- Produces: свойства `root.depsMissing`, `root.downloading`, `root.downloadStage`, `root.downloadPct`, `root.downloadError` — только внутри Main.qml.

Проверка на устройстве в задаче 10 (критерии 3–4 спеки).

- [ ] **Step 1: Свойства** (рядом с `property string partialText`):

```qml
    property bool depsMissing: false
    property bool downloading: false
    property string downloadStage: ""
    property int downloadPct: -1
    property string downloadError: ""
```

- [ ] **Step 2: Обработчики** (в `Component.onCompleted`, рядом с `setHandler("status", ...)`):

```qml
            setHandler("deps-missing", function (what) {
                root.depsMissing = true;
                root.statusText = "Нужно скачать модель";
            });
            setHandler("download-progress", function (stage, pct) {
                root.downloading = true;
                root.downloadError = "";
                root.downloadStage = stage;
                root.downloadPct = pct;
            });
            setHandler("download-done", function () {
                root.downloading = false;
                root.depsMissing = false;
                root.statusText = "Загрузка движка…";
            });
            setHandler("download-error", function (msg) {
                root.downloading = false;
                root.downloadError = msg;
                root.statusText = "Ошибка загрузки";
            });
```

- [ ] **Step 3: Оверлей.** Внутрь `Page { id: mainPage ... }`, ПОСЛЕ закрывающей скобки ColumnLayout (сосед по дереву, перекрывает контент):

```qml
            // Первый запуск: модели ещё нет — предлагаем скачать.
            Rectangle {
                anchors {
                    top: pageHeader.bottom
                    left: parent.left
                    right: parent.right
                    bottom: parent.bottom
                }
                color: theme.palette.normal.background
                visible: root.depsMissing
                z: 50

                Column {
                    anchors.centerIn: parent
                    width: parent.width - units.gu(6)
                    spacing: units.gu(2)

                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: units.gu(6)
                        height: width
                        name: "save-to"
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        text: "Для работы нужно скачать модель распознавания "
                              + "(около 500 МБ). Лучше делать это по Wi-Fi.\n"
                              + "После загрузки приложение работает полностью офлайн."
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        color: LomiriColors.red
                        visible: root.downloadError.length > 0
                        text: root.downloadError
                    }
                    ProgressBar {
                        width: parent.width
                        visible: root.downloading
                        indeterminate: root.downloadPct < 0
                        minimumValue: 0
                        maximumValue: 100
                        value: root.downloadPct
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        visible: root.downloading
                        textSize: Label.Small
                        opacity: 0.7
                        text: root.downloadStage
                              + (root.downloadPct >= 0
                                 ? "  " + root.downloadPct + "%" : "")
                    }
                    Button {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: !root.downloading
                        color: LomiriColors.green
                        text: root.downloadError.length ? "Повторить" : "Скачать"
                        onClicked: py.call("backend.fetch_deps", [])
                    }
                }
            }
```

- [ ] **Step 4: Регрессия python-тестов + commit**

Run: `.venv/bin/python -m pytest tests/ -v` → 19 passed

```bash
git add qml/Main.qml
git commit -m "feat: first-run model download screen"
```

---

### Task 8: QML — waveform-лента

**Files:**
- Modify: `qml/Main.qml`

**Interfaces:**
- Consumes: событие `level(v: 0..1)` (уже существует, с задачи 3 приходит ~8 раз/с).
- Produces: элемент `waveform` — только внутри Main.qml.

Сглаживание — вариант (б) спеки: интерполяция в QML (`Behavior on height`), частота ~8/с из задачи 3 (чанк 0.128 с).

- [ ] **Step 1: Пополнять ленту в обработчике level.** Заменить обработчик:

```qml
            setHandler("level", function (v) {
                root.level = v;
                if (root.recording)
                    waveform.push(v);
            });
```

- [ ] **Step 2: Сброс ленты на старте записи.** В обработчике `recording`, в ветку `if (on)` добавить:

```qml
                    waveform.bars = new Array(waveform.count).fill(0);
```

- [ ] **Step 3: Сам элемент.** В `ColumnLayout` главного экрана, МЕЖДУ Rectangle с расшифровкой и RowLayout автокопирования:

```qml
                // ---------- голосовые волны ----------
                Item {
                    id: waveform
                    Layout.fillWidth: true
                    Layout.preferredHeight: units.gu(6)
                    visible: root.recording

                    property int count: 40
                    property var bars: []

                    function push(v) {
                        var a = bars.slice(1);
                        a.push(v);
                        bars = a;
                    }

                    Row {
                        anchors.centerIn: parent
                        spacing: units.dp(3)
                        Repeater {
                            model: waveform.count
                            Rectangle {
                                property real v: index < waveform.bars.length
                                                 ? waveform.bars[index] : 0
                                width: units.dp(4)
                                height: units.dp(3)
                                       + v * (waveform.height - units.dp(3))
                                radius: width / 2
                                color: LomiriColors.orange
                                anchors.verticalCenter: parent.verticalCenter
                                Behavior on height {
                                    NumberAnimation { duration: 110 }
                                }
                            }
                        }
                    }
                }
```

- [ ] **Step 4: Регрессия + commit**

Run: `.venv/bin/python -m pytest tests/ -v` → 19 passed

```bash
git add qml/Main.qml
git commit -m "feat: waveform bars while recording"
```

---

### Task 9: Документация + версия 0.6.0

**Files:**
- Modify: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `CHANGELOG.md`, `README.md`, `manifest.json`

- [ ] **Step 1: manifest.json** — `"version": "0.5.0"` → `"version": "0.6.0"`.

- [ ] **Step 2: CHANGELOG.md** — новый раздел сверху:

```markdown
## 0.6.0 — потоковая расшифровка

* **Текст появляется по ходу записи.** VAD режет речь на фразы прямо в цикле
  записи; отдельный поток декодирует каждую фразу сразу, пока идёт следующая.
  После «стоп» доделывается только последняя фраза — финал за секунды вместо
  15–21 с на длинной записи.
* **Приложение само качает модель.** На первом запуске — экран с кнопкой
  «Скачать» (~500 МБ, лучше по Wi-Fi) и прогрессом. Ручной
  `scripts/fetch-deps.py` остался как обёртка той же логики.
* **Голосовые волны** во время записи: лента баров, высота = громкость.
* В apparmor добавлен `networking` — только ради загрузки модели; после неё
  приложение полностью офлайн, звук никуда не уходит.
* «Повторить» из истории больше нельзя запустить во время записи — они делят
  один детектор тишины.
```

- [ ] **Step 3: docs/DECISIONS.md** — добавить раздел (в конец):

```markdown
---

## Возврат к декоду во время записи — но не тем путём, что в 0.2

В 0.2 распознавание звалось прямо из цикла чтения микрофона и роняло звук;
в 0.4 ушли на пакетный режим. В 0.6 декод снова идёт по ходу записи, но
архитектура другая, и грабли 0.2 сюда не переносятся:

* В цикле записи — только лёгкий VAD (silero, окно 512 отсчётов, ~мс на окно).
  Тяжёлый декод — в отдельном потоке через `queue.Queue`; sherpa-onnx на
  декоде отпускает GIL, так что потоки реально параллельны.
* Замер на N10 (int8, 4 потока): 84 с аудио → 14.8 с декода с VAD (~5.7x).
  Декод успевает за записью с запасом.
* Ловушка sherpa-onnx #2918 учтена: декодируется только текущий сегмент,
  растущий буфер не пере-декодируется никогда.
* Референс архитектуры — FluidAudio/Spokenly (декод VAD-сегментов в фоне,
  на стопе только последняя фраза). Копируем идею, не код: их streaming-модель
  и Apple Neural Engine нам недоступны.

Спека с измерениями: `docs/specs/2026-08-20-streaming-selfdownload-waveform.md`.

## Silero VAD остаётся

Раньше обсуждали убрать VAD ради качества на стыках. Отменено: VAD — это и
есть механизм потоковой нарезки. Режем по паузам, слова не рвём.
```

- [ ] **Step 4: docs/ARCHITECTURE.md** — правки:
  - В таблицу «QML зовёт Python» добавить строку: `| fetch_deps() | Качает модель и библиотеки, шлёт прогресс |`
  - В таблицу событий добавить строки:

```markdown
| `partial` | номер, текст | Фраза распознана по ходу записи |
| `deps-missing` | список | Нет модели/библиотек — нужен экран загрузки |
| `download-progress` | этап, % | Ход загрузки (−1 — размер неизвестен) |
| `download-done` | — | Всё скачано, дальше грузится движок |
| `download-error` | сообщение | Сбой загрузки, можно повторить |
```

  - Фразу «Все одиннадцать событий…» заменить на «Все шестнадцать событий…».
  - В раздел «Запись» добавить абзац: «С 0.6 в цикле записи дополнительно работает VAD (окна по 512 отсчётов): готовые фразы уходят через очередь в поток декода (`py/streaming.py`). Цикл по-прежнему не делает тяжёлой работы — декод в другом потоке, sherpa-onnx отпускает GIL. Чтение по 4096 байт = 2048 отсчётов = 0.128 с.»
  - В раздел «Расшифровка» добавить: «Пакетный путь (`_split` → `_decode` по очереди) остался для «повторить» из истории; нарезка та же — `streaming.Segmenter`.»

- [ ] **Step 5: README.md** — в разделе установки заменить упоминание обязательного `fetch-deps.py` на: «При первом запуске приложение само предложит скачать модель (~500 МБ, лучше по Wi-Fi). Вручную то же самое делает `python3 scripts/fetch-deps.py`. Разрешение `networking` в apparmor нужно только для этой загрузки — распознавание полностью офлайн, звук никуда не уходит.»

- [ ] **Step 6: Регрессия + commit**

Run: `.venv/bin/python -m pytest tests/ -v` → 19 passed

```bash
git add manifest.json CHANGELOG.md README.md docs/
git commit -m "docs: architecture, decisions, changelog for 0.6.0"
```

---

### Task 10: Сборка и приёмка на телефоне

**Files:** без изменений кода (фиксы — отдельными коммитами по ходу).

Телефон: OnePlus N10, adb serial `20db81c3`, проект на телефоне собирается его же `scripts/build.sh` (click build) и ставится `scripts/install.sh`.

- [ ] **Step 1: Доставить код на телефон**

```bash
cd /Users/n0mads/Downloads/platform-tools/ut-build/soundtype
adb -s 20db81c3 shell mkdir -p /home/phablet/soundtype
for d in qml py assets scripts manifest.json soundtype.apparmor soundtype.desktop LICENSE; do
  adb -s 20db81c3 push "$d" /home/phablet/soundtype/
done
```

- [ ] **Step 2: Собрать и установить на телефоне**

```bash
adb -s 20db81c3 shell "cd /home/phablet/soundtype && sh scripts/build.sh && sh scripts/install.sh"
```

Expected: `click list` показывает `soundtype ... 0.6.0`.

- [ ] **Step 3: Критерий 3 спеки — свежая установка.** На телефоне убрать данные и проверить экран загрузки (Wi-Fi включён):

```bash
adb -s 20db81c3 shell "mv /home/phablet/.local/share/soundtype.n0madd3v0ps /home/phablet/st-data-backup"
```

Открыть приложение → должен появиться экран «скачать ~500 МБ» → [Скачать] → прогресс → после загрузки обычный экран, кнопка оживает. PASS/FAIL записать.

- [ ] **Step 4: Критерий 4 — нет сети.** Снова убрать данные (`mv` обратно и ещё раз, либо `rm -rf` свежескачанного и повтор), включить авиарежим → [Скачать] → внятная ошибка, приложение живо → выключить авиарежим → «Повторить» работает. После проверки вернуть полный набор данных (либо доскачать, либо `mv /home/phablet/st-data-backup` назад).

- [ ] **Step 5: Критерий 1 — длинная запись (~60–90 с с паузами).** Говорить с паузами: текст появляется по ходу (partial), после «стоп» финал ≤ ~2 с (сейчас было 15–21 с). Замер: секундомер от нажатия «стоп» до текста.

- [ ] **Step 6: Критерий 2 — короткая запись (~8 с).** Результат ≤ ~2 с, качество не хуже прежнего.

- [ ] **Step 7: Критерий 5 — waveform.** Во время записи лента реагирует на голос, UI не тормозит (кнопка и таймер живые).

- [ ] **Step 8: Критерий 6 — форс-нарезка.** Наговорить > 30 с БЕЗ пауз (читать текст) → процесс не падает, текст приходит (допустима потеря слова на стыке — v2 закроет overlap+LCS).

- [ ] **Step 9: Регрессии.** История: запись сохранилась, «повторить» работает (и отбивается с ошибкой во время записи), автокопирование в буфер после стопа, очистка истории.

- [ ] **Step 10: Итог.** Все критерии PASS → готово к релизному решению Khan (release v1 отложен до рабочей версии — его команда). Любой FAIL → фикс отдельным коммитом, повторная проверка этого критерия.

---

## Self-Review (выполнено при написании плана)

- Спека §1 (streaming) → задачи 1–3; §2 (VAD остаётся) → нигде не убирается, `_split` тоже на Segmenter; §3 (self-download, вариант B с подтверждением, apparmor networking, края «нет сети/повтор») → задачи 5–7; §4 (waveform, выбран вариант (б) сглаживания + чанк 0.128 с) → задачи 3 и 8; §5 — v2, вне плана (отмечено в задаче 10 шаг 8). Критерии готовности 1–6 → задача 10.
- Ловушка #2918: worker декодирует только сегмент из очереди — конструктивно исключено.
- Типы согласованы: `Segmenter.feed/flush -> list`, `DecodeWorker.close -> str`, имена событий совпадают между backend и QML во всех задачах.
