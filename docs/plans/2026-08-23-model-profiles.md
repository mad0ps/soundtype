# Model Profiles (GigaAM-v3 + Parakeet) Implementation Plan (issue #12)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** User-selectable ASR model profile — "Russian (GigaAM-v3 e2e)" or "Multilingual (Parakeet v3)" — persisted in `settings.json`, downloaded on demand, picked up by both the app and the keyboard daemon.

**Architecture:** A new pure module `py/models.py` owns the profile registry and the persisted choice; `py/downloader.py` learns to fetch the GigaAM files and becomes profile-aware in `missing()`/`fetch_all()`; `py/backend.py` builds the recognizer from the active profile and gains `set_model()` + `model_stale()`; the daemon unloads a stale engine before starting; the app gets a two-option selector in the settings column. Both engines lazy-load, so a profile switch takes effect on the next engine load.

**Tech Stack:** Python 3 (phone: 3.12/pyotherside, tests: repo `.venv`), sherpa-onnx `OfflineRecognizer.from_transducer(model_type='nemo_transducer')` for BOTH models, QML (Lomiri.Components), existing test fakes (`tests/conftest.py` stubs pyotherside).

## Global Constraints

- Both models load via `sherpa_onnx.OfflineRecognizer.from_transducer(..., num_threads=4, model_type='nemo_transducer')` — verified working for the GigaAM e2e_rnnt int8 export in the eval harness (issue #6).
- Profile names (exact strings, used in settings.json, registry, QML): `parakeet`, `gigaam`.
- Default profile: `parakeet` (installed base keeps working after OTA of this version; user opts into GigaAM).
- settings file: `<DATA>/settings.json`, written atomically (`.tmp` + `os.replace`), shape `{"model": "parakeet"}`. Unknown/corrupt values fall back to the default silently.
- GigaAM files (HF `Smirnov75/GigaAM-v3-sherpa-onnx`, base URL `https://huggingface.co/Smirnov75/GigaAM-v3-sherpa-onnx/resolve/main/`): `gigaam_v3_e2e_rnnt_encoder_int8.onnx` (~319 MB) → local `encoder.int8.onnx`; `gigaam_v3_e2e_rnnt_decoder.onnx` → `decoder.onnx`; `gigaam_v3_e2e_rnnt_joint.onnx` → `joiner.onnx`; `gigaam_v3_e2e_rnnt_tokens.txt` → `tokens.txt`. Local dir: `<DATA>/models/gigaam-e2e/`. Encoder downloads LAST (it is the presence probe — same retryability idiom as `fetch_parakeet`).
- `py/models.py` must import cleanly with no pyotherside and no sherpa (tests run on Mac).
- Commit messages in English, no Co-Authored-By. Python: `.venv/bin/python`. All existing 55 tests stay green.
- Comments in code follow the repo's existing style (Russian is fine — the file headers are Russian).

## File Structure

```
py/models.py            # NEW: profile registry, get_active/set_active, model_files, label
py/downloader.py        # MODIFY: GIGAAM_URLS, fetch_gigaam, model-aware missing()/fetch_all()
py/backend.py           # MODIFY: profile-aware Dictation.load, set_model(), model_stale()
soundtype-dbus.py       # MODIFY: unload stale engine on toggle
qml/Main.qml            # MODIFY: model selector in settings column
manifest.json           # MODIFY: version 0.9.0 (Task 6)
CHANGELOG.md            # MODIFY: 0.9.0 entry (Task 6)
tests/test_models.py    # NEW
tests/test_downloader.py# MODIFY: gigaam + model-aware cases
tests/test_backend_session.py or new tests/test_backend_model.py  # set_model/model_stale
```

---

### Task 1: `py/models.py` — registry + persisted choice

**Files:**
- Create: `py/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces (consumed by Tasks 2-5):
  - `DEFAULT = 'parakeet'`
  - `REGISTRY: dict` with keys `'parakeet'`, `'gigaam'`; each value has `'dir'` (str), `'files'` (dict with keys `encoder/decoder/joiner/tokens` → filenames), `'label'` (str).
  - `get_active(data_dir) -> str` — from `<data_dir>/settings.json`, default/fallback `DEFAULT`.
  - `set_active(name, data_dir) -> None` — atomic write; `ValueError` on unknown name; preserves unrelated keys already in settings.json.
  - `model_dir(name, data_dir) -> str` — `<data_dir>/models/<REGISTRY[name]['dir']>`.
  - `model_files(name, data_dir) -> dict` — absolute paths for encoder/decoder/joiner/tokens.
  - `probe_path(name, data_dir) -> str` — the encoder absolute path (presence probe).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models.py
# -*- coding: utf-8 -*-
import json, os
import models


def test_registry_shape():
    assert set(models.REGISTRY) == {'parakeet', 'gigaam'}
    for name, spec in models.REGISTRY.items():
        assert set(spec['files']) == {'encoder', 'decoder', 'joiner', 'tokens'}
        assert spec['dir'] and spec['label']


def test_get_active_default_when_no_file(tmp_path):
    assert models.get_active(str(tmp_path)) == 'parakeet'


def test_set_then_get_roundtrip(tmp_path):
    models.set_active('gigaam', str(tmp_path))
    assert models.get_active(str(tmp_path)) == 'gigaam'
    raw = json.load(open(tmp_path / 'settings.json'))
    assert raw['model'] == 'gigaam'


def test_set_preserves_other_keys(tmp_path):
    (tmp_path / 'settings.json').write_text(json.dumps({'other': 1, 'model': 'parakeet'}))
    models.set_active('gigaam', str(tmp_path))
    raw = json.load(open(tmp_path / 'settings.json'))
    assert raw == {'other': 1, 'model': 'gigaam'}


def test_get_active_falls_back_on_garbage(tmp_path):
    (tmp_path / 'settings.json').write_text('{broken')
    assert models.get_active(str(tmp_path)) == 'parakeet'
    (tmp_path / 'settings.json').write_text(json.dumps({'model': 'nosuch'}))
    assert models.get_active(str(tmp_path)) == 'parakeet'


def test_set_unknown_raises(tmp_path):
    try:
        models.set_active('nosuch', str(tmp_path))
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_set_leaves_no_tmp_file(tmp_path):
    models.set_active('gigaam', str(tmp_path))
    assert not (tmp_path / 'settings.json.tmp').exists()


def test_paths(tmp_path):
    d = str(tmp_path)
    files = models.model_files('gigaam', d)
    assert files['encoder'] == os.path.join(d, 'models', 'gigaam-e2e', 'encoder.int8.onnx')
    assert files['decoder'].endswith('gigaam-e2e/decoder.onnx')
    assert models.probe_path('parakeet', d).endswith('parakeet/encoder.int8.onnx')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'models'` (conftest already puts `py/` on sys.path — check `tests/conftest.py`; if the import error differs, adapt nothing else, just confirm conftest covers `py/`).

- [ ] **Step 3: Implement `py/models.py`**

```python
# -*- coding: utf-8 -*-
"""Профили ASR-моделей и персист выбора пользователя.

Чистый модуль: без pyotherside и sherpa — его гоняют тесты на Mac.
settings.json пишется атомарно; неизвестное/битое значение молча
откатывается к DEFAULT, чтобы кривой файл не окирпичил диктовку.
"""
import json
import os

DEFAULT = 'parakeet'

REGISTRY = {
    'parakeet': {
        'dir': 'parakeet',
        'files': {'encoder': 'encoder.int8.onnx', 'decoder': 'decoder.int8.onnx',
                  'joiner': 'joiner.int8.onnx', 'tokens': 'tokens.txt'},
        'label': 'Мультиязычная (Parakeet v3)',
    },
    'gigaam': {
        'dir': 'gigaam-e2e',
        'files': {'encoder': 'encoder.int8.onnx', 'decoder': 'decoder.onnx',
                  'joiner': 'joiner.onnx', 'tokens': 'tokens.txt'},
        'label': 'Русская (GigaAM-v3)',
    },
}


def _settings_path(data_dir):
    return os.path.join(data_dir, 'settings.json')


def _read_settings(data_dir):
    try:
        with open(_settings_path(data_dir), encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get_active(data_dir):
    name = _read_settings(data_dir).get('model')
    return name if name in REGISTRY else DEFAULT


def set_active(name, data_dir):
    if name not in REGISTRY:
        raise ValueError('unknown model profile: %r' % name)
    data = _read_settings(data_dir)
    data['model'] = name
    os.makedirs(data_dir, exist_ok=True)
    tmp = _settings_path(data_dir) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, _settings_path(data_dir))


def model_dir(name, data_dir):
    return os.path.join(data_dir, 'models', REGISTRY[name]['dir'])


def model_files(name, data_dir):
    base = model_dir(name, data_dir)
    return {k: os.path.join(base, fn)
            for k, fn in REGISTRY[name]['files'].items()}


def probe_path(name, data_dir):
    return model_files(name, data_dir)['encoder']
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: 8 PASS

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → all green.

```bash
git add py/models.py tests/test_models.py
git commit -m "feat: model profile registry with persisted choice (issue #12)"
```

---

### Task 2: downloader — GigaAM fetch + profile-aware missing/fetch_all

**Files:**
- Modify: `py/downloader.py`
- Test: `tests/test_downloader.py` (append tests; keep existing ones untouched)

**Interfaces:**
- Consumes: `models.get_active`, `models.model_dir`, `models.model_files`, `models.probe_path`, `models.REGISTRY`.
- Produces (consumed by backend Task 3):
  - `missing(data_dir=DATA, model=None) -> list` — wheels + silero as today; model check now against the given profile (None → active). The missing-model entry in the list is the PROFILE NAME (`'parakeet'` or `'gigaam'`), not the literal `'parakeet'` always.
  - `fetch_model(name, progress=None, data_dir=DATA, force=False)` — dispatches to `fetch_parakeet` or `fetch_gigaam`.
  - `fetch_gigaam(progress=None, data_dir=DATA, force=False)` — per-file download into `models/gigaam-e2e/`, `.part` + `os.replace` per file, encoder last.
  - `fetch_all(...)` — wheels + silero + ACTIVE profile's model (not always parakeet).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_downloader.py`; follow that file's existing monkeypatch style — read it first)

```python
def test_missing_is_profile_aware(tmp_path, monkeypatch):
    import downloader, models
    d = str(tmp_path)
    # wheels+silero present so only the model entry differs
    for pkg, _v, _t, probe in downloader.WHEELS:
        p = os.path.join(d, 'runtime', 'pylibs', probe)
        os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').close()
    os.makedirs(os.path.join(d, 'models'), exist_ok=True)
    open(os.path.join(d, 'models', 'silero_vad.onnx'), 'w').close()

    assert downloader.missing(d, model='gigaam') == ['gigaam']
    assert downloader.missing(d, model='parakeet') == ['parakeet']
    # active profile is used when model=None
    models.set_active('gigaam', d)
    assert downloader.missing(d) == ['gigaam']
    # place the gigaam probe -> clean
    ep = models.probe_path('gigaam', d)
    os.makedirs(os.path.dirname(ep), exist_ok=True); open(ep, 'w').close()
    assert downloader.missing(d) == []


def test_fetch_gigaam_downloads_encoder_last(tmp_path, monkeypatch):
    import downloader, models
    d = str(tmp_path)
    calls = []

    def fake_download(url, dest=None, progress=None, stage=''):
        calls.append(url)
        open(dest, 'wb').write(b'x')
        return dest

    monkeypatch.setattr(downloader, 'download', fake_download)
    downloader.fetch_gigaam(data_dir=d)
    files = models.model_files('gigaam', d)
    for path in files.values():
        assert os.path.exists(path)
    assert 'encoder_int8' in calls[-1]  # encoder queued last
    # idempotent: second run downloads nothing
    calls.clear()
    downloader.fetch_gigaam(data_dir=d)
    assert calls == []


def test_fetch_gigaam_force_redownloads(tmp_path, monkeypatch):
    import downloader, models
    d = str(tmp_path)
    calls = []

    def fake_download(url, dest=None, progress=None, stage=''):
        calls.append(url); open(dest, 'wb').write(b'x'); return dest

    monkeypatch.setattr(downloader, 'download', fake_download)
    downloader.fetch_gigaam(data_dir=d)
    n_first = len(calls)
    downloader.fetch_gigaam(data_dir=d, force=True)
    assert len(calls) == n_first * 2


def test_fetch_all_downloads_active_profile(tmp_path, monkeypatch):
    import downloader, models
    d = str(tmp_path)
    models.set_active('gigaam', d)
    got = []
    monkeypatch.setattr(downloader, 'fetch_wheels', lambda *a, **k: None)
    monkeypatch.setattr(downloader, 'fetch_silero', lambda *a, **k: None)
    monkeypatch.setattr(downloader, 'fetch_model',
                        lambda name, *a, **k: got.append(name))
    downloader.fetch_all(data_dir=d)
    assert got == ['gigaam']


def test_fetch_model_dispatch(monkeypatch, tmp_path):
    import downloader
    hit = []
    monkeypatch.setattr(downloader, 'fetch_parakeet', lambda **kw: hit.append('p'))
    monkeypatch.setattr(downloader, 'fetch_gigaam', lambda **kw: hit.append('g'))
    downloader.fetch_model('parakeet', data_dir=str(tmp_path))
    downloader.fetch_model('gigaam', data_dir=str(tmp_path))
    assert hit == ['p', 'g']
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_downloader.py -v`
Expected: new tests FAIL (`AttributeError: fetch_gigaam` / TypeError on `missing(model=)`), old ones PASS.

- [ ] **Step 3: Implement in `py/downloader.py`**

Add near the URL constants:

```python
import models  # noqa: E402  (py/ модули живут в одном каталоге)

GIGAAM_BASE = ('https://huggingface.co/Smirnov75/GigaAM-v3-sherpa-onnx/'
               'resolve/main/')
# локальное имя -> имя файла на HF; encoder последним (он же probe)
GIGAAM_FILES = [
    ('decoder.onnx', 'gigaam_v3_e2e_rnnt_decoder.onnx'),
    ('joiner.onnx', 'gigaam_v3_e2e_rnnt_joint.onnx'),
    ('tokens.txt', 'gigaam_v3_e2e_rnnt_tokens.txt'),
    ('encoder.int8.onnx', 'gigaam_v3_e2e_rnnt_encoder_int8.onnx'),
]
```

Replace the model check inside `missing()` (the `parakeet/encoder.int8.onnx` block) with:

```python
    name = model or models.get_active(data_dir)
    if not os.path.exists(models.probe_path(name, data_dir)):
        out.append(name)
```

and change the signature to `def missing(data_dir=DATA, model=None):`.

Add after `fetch_parakeet`:

```python
def fetch_gigaam(progress=None, data_dir=DATA, force=False):
    target = models.model_dir('gigaam', data_dir)
    if os.path.exists(models.probe_path('gigaam', data_dir)) and not force:
        return
    os.makedirs(target, exist_ok=True)
    for local, remote in GIGAAM_FILES:
        dest = os.path.join(target, local)
        if os.path.exists(dest) and not force and local != 'encoder.int8.onnx':
            continue
        part = dest + '.part'
        download(GIGAAM_BASE + remote, part, progress=progress,
                 stage='модель GigaAM (%s)' % local)
        os.replace(part, dest)


def fetch_model(name, progress=None, data_dir=DATA, force=False):
    if name == 'gigaam':
        fetch_gigaam(progress, data_dir, force)
    else:
        fetch_parakeet(progress, data_dir, force)
```

Change `fetch_all` to download the active profile:

```python
def fetch_all(progress=None, data_dir=DATA, force=False):
    """Скачать всё недостающее для АКТИВНОГО профиля. Сбой = исключение."""
    fetch_wheels(progress, data_dir, force)
    fetch_silero(progress, data_dir, force)
    fetch_model(models.get_active(data_dir), progress, data_dir, force)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_downloader.py tests/test_models.py -v`
Expected: all PASS

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → all green.

```bash
git add py/downloader.py tests/test_downloader.py
git commit -m "feat: downloader fetches the active model profile (GigaAM files added)"
```

---

### Task 3: backend — profile-aware engine + set_model/model_stale

**Files:**
- Modify: `py/backend.py`
- Test: `tests/test_backend_model.py` (new; reuse `tests/fakes.py`/conftest stubs the way `tests/test_backend_session.py` does — read both first)

**Interfaces:**
- Consumes: `models.get_active/set_active/model_files`, `downloader.missing`.
- Produces (consumed by QML Task 5 and daemon Task 4):
  - `backend.set_model(name)` (module-level): persists the choice, unloads the engine if loaded, then emits `('model', name)`; then if `downloader.missing()` non-empty emits `('deps-missing', miss)`, else calls `_engine.load()` (so the app reloads immediately).
  - `backend.model_stale() -> bool` (module-level): engine holds a loaded recognizer AND its profile ≠ active profile.
  - `backend.init` now emits `('model', <active>)` before the deps check (QML learns the current choice on startup).
  - `Dictation.load` builds the recognizer from `models.model_files(active)` and remembers `self.model_name = active`; `Dictation.unload` clears it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backend_model.py
# -*- coding: utf-8 -*-
"""set_model/model_stale — без sherpa: движок не грузим, только состояние."""
import backend
import models


def test_init_emits_active_model(tmp_path, monkeypatch, events):
    monkeypatch.setattr(backend.downloader, 'missing', lambda *a, **k: ['x'])
    monkeypatch.setattr(models, 'get_active', lambda d=None: 'parakeet')
    backend.init()
    kinds = [e[0] for e in events]
    assert ('model', 'parakeet') in events
    assert 'deps-missing' in kinds
    # model объявляется ДО deps-missing — QML должен знать выбор даже без модели
    assert kinds.index('model') < kinds.index('deps-missing')


def test_set_model_persists_and_emits(tmp_path, monkeypatch, events):
    monkeypatch.setattr(backend, 'DATA', str(tmp_path))
    monkeypatch.setattr(backend.downloader, 'missing', lambda *a, **k: ['gigaam'])
    saved = []
    monkeypatch.setattr(models, 'set_active', lambda n, d: saved.append((n, d)))
    backend.set_model('gigaam')
    assert saved and saved[0][0] == 'gigaam'
    kinds = [e[0] for e in events]
    assert 'model' in kinds and 'deps-missing' in kinds


def test_set_model_loads_engine_when_nothing_missing(tmp_path, monkeypatch, events):
    monkeypatch.setattr(backend, 'DATA', str(tmp_path))
    monkeypatch.setattr(backend.downloader, 'missing', lambda *a, **k: [])
    monkeypatch.setattr(models, 'set_active', lambda n, d: None)
    loads = []
    monkeypatch.setattr(backend._engine, 'load', lambda: loads.append(1))
    backend.set_model('gigaam')
    assert loads == [1]
    assert ('model', 'gigaam') in events


def test_set_model_unknown_name_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', str(tmp_path))
    try:
        backend.set_model('nosuch')
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_model_stale_logic(monkeypatch):
    monkeypatch.setattr(models, 'get_active', lambda d=None: 'gigaam')
    backend._engine.model_name = 'parakeet'
    backend._engine.recognizer = object()
    assert backend.model_stale() is True
    backend._engine.model_name = 'gigaam'
    assert backend.model_stale() is False
    backend._engine.recognizer = None
    assert backend.model_stale() is False
```

Note on the `events` fixture: `tests/conftest.py` stubs pyotherside with an event journal — read it and use its actual fixture name/shape (adapt the test's fixture name if it differs, e.g. collect events via the stub's recorded list). If no fixture exists, capture `backend.emit` with monkeypatch into a local list — the assertions stay the same.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backend_model.py -v`
Expected: FAIL (`AttributeError: set_model` / `model_stale`).

- [ ] **Step 3: Implement in `py/backend.py`**

1. Top: `import models  # noqa: E402` next to `import downloader`.
2. `Dictation.__init__`: add `self.model_name = None`.
3. In `Dictation.load` worker (the block at ~line 276 that hardcodes `pk = os.path.join(MODELS, 'parakeet')`), replace with:

```python
                active = models.get_active(DATA)
                mf = models.model_files(active, DATA)
                rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=mf['encoder'],
                    decoder=mf['decoder'],
                    joiner=mf['joiner'],
                    tokens=mf['tokens'],
                    num_threads=4,
                    model_type='nemo_transducer',
                    debug=False,
                )
```

and inside the same `with self.lock:` block that stores `self.recognizer = rec`, add `self.model_name = active`.
4. In `Dictation.unload` where `self.recognizer = None`, add `self.model_name = None`.
5. Module level, near `init()`:

```python
def model_stale():
    """Движок загружен, но профиль в настройках уже другой."""
    return (_engine.recognizer is not None
            and _engine.model_name != models.get_active(DATA))


def set_model(name):
    """Выбор профиля из настроек приложения."""
    models.set_active(name, DATA)
    if _engine.recognizer is not None:
        _engine.unload()
    emit('model', name)
    miss = downloader.missing()
    if miss:
        emit('deps-missing', miss)
    else:
        _engine.load()
```

6. `init()`: before the `miss = downloader.missing()` line add `emit('model', models.get_active(DATA))`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backend_model.py tests/test_backend_session.py -v`
Expected: all PASS

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest -q` → all green.

```bash
git add py/backend.py tests/test_backend_model.py
git commit -m "feat: engine loads the active model profile; set_model/model_stale API"
```

---

### Task 4: daemon — stale-profile pickup on toggle

**Files:**
- Modify: `soundtype-dbus.py` (ToggleDictation start branch)

**Interfaces:**
- Consumes: `backend.model_stale()`, `backend.unload()`.

- [ ] **Step 1: Handle deps-missing in the daemon mock**

In `PyOtherSideMock.send`, add a branch (next to the existing `elif event == 'error':`): a model switched in the app but not yet downloaded must NOT leave the keyboard stuck on «busy» — reset the pending state and show the grey indicator:

```python
        elif event == 'deps-missing':
            # выбранная модель ещё не скачана (переключили в приложении):
            # не зависаем в «занят», индикатор в серый
            svc.pending_start = False
            svc.loaded = False
            svc.StatusChanged("unloaded")
```

- [ ] **Step 2: Edit ToggleDictation**

In the start branch (currently `if not self.listening: self.listening = True; self.keep_display_on(); if not self.loaded: ...`), insert the staleness check BEFORE the `if not self.loaded` test:

```python
            # профиль сменили из приложения — выгружаем старый движок,
            # ленивый путь ниже загрузит актуальный
            if self.loaded and backend.model_stale():
                try:
                    backend.unload()
                except Exception as exc:
                    print(f"stale unload failed: {exc}", flush=True)
                self.loaded = False
```

- [ ] **Step 3: Compile check**

Run: `python3 -m py_compile soundtype-dbus.py`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add soundtype-dbus.py
git commit -m "feat: keyboard daemon reloads engine when model profile changed"
```

---

### Task 5: QML — model selector in settings

**Files:**
- Modify: `qml/Main.qml`

**Interfaces:**
- Consumes: pyotherside `py.call('backend.set_model', [name])`; event `setHandler('model', ...)` (emitted by init and set_model).

- [ ] **Step 1: Add state + handler**

Near the other root properties (after `property bool autoCopy: true`):

```qml
    property string activeModel: "parakeet"
    property bool modelSwitchBusy: false
```

In the `Component.onCompleted` / handler-registration block where other `setHandler` calls live (same block that has `setHandler("recording", ...)`), add:

```qml
            setHandler("model", function (name) {
                root.activeModel = name;
                root.modelSwitchBusy = false;
                // движок только что выгружен (смена профиля) либо ещё не
                // загружен (старт) — микрофон разблокирует событие 'ready'
                root.ready = false;
            });
```

- [ ] **Step 2: Add the selector UI**

In the settings column, right after the `autoCopySwitch` row block, add:

```qml
                    Label {
                        text: "Модель распознавания"
                        fontSize: "small"
                        color: theme.palette.normal.backgroundSecondaryText
                    }
                    OptionSelector {
                        id: modelSelector
                        model: ["Мультиязычная (Parakeet v3)",
                                "Русская (GigaAM-v3)"]
                        enabled: !root.modelSwitchBusy && !root.recording && !root.transcribing
                        selectedIndex: root.activeModel === "gigaam" ? 1 : 0
                        onDelegateClicked: function (index) {
                            var name = index === 1 ? "gigaam" : "parakeet";
                            if (name === root.activeModel)
                                return;
                            root.modelSwitchBusy = true;
                            py.call("backend.set_model", [name]);
                        }
                    }
                    Label {
                        visible: root.activeModel === "gigaam"
                        text: "Русский профиль: пунктуация и ё из коробки"
                        fontSize: "x-small"
                        color: theme.palette.normal.backgroundTertiaryText
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
```

Style note: Main.qml uses raw Russian UI strings (no i18n.tr) — keep that. The settings items sit in a ColumnLayout with RowLayout children using `Layout.fillWidth` — insert after the `// ---------- авто-копирование ----------` RowLayout block and use `Layout.fillWidth: true` on the OptionSelector.

Notes: `selectedIndex` binding covers startup (the `model` event arrives from `backend.init`). `onDelegateClicked` fires only on user taps, so no echo loop; the binding restores the selector if python rejects the switch. If `Layout.fillWidth` is not applicable in that column (it's a plain Column, not ColumnLayout), drop that line and set `width: parent.width` instead — match the neighboring elements' pattern.

- [ ] **Step 3: Syntax sanity**

Run: `grep -c "setHandler(\"model\"" qml/Main.qml` → 1; visually re-read the diff (qmllint is broken on noble per project notes — do not chase it).

- [ ] **Step 4: Commit**

```bash
git add qml/Main.qml
git commit -m "feat: model profile selector in app settings"
```

---

### Task 6: release prep + phone deployment + live acceptance

**Files:**
- Modify: `manifest.json` (`"version": "0.9.0"`), `CHANGELOG.md` (new 0.9.0 entry, English, style of existing entries: model profiles, selector, GigaAM download, daemon pickup)
- Phone: push py/*.py + soundtype-dbus.py to `/home/phablet/soundtype/`, restart daemon unit, rebuild + reinstall click (`scripts/build.sh` + `scripts/install.sh` on the phone), close the running app first (`ps -ef | grep qmlscene`, kill if running — lesson from 22.08).

**Steps:**

- [ ] Update manifest.json version to 0.9.0 + CHANGELOG entry; commit `chore: bump to 0.9.0 (model profiles)`.
- [ ] adb push changed files to phone repo; md5-verify each pushed file (phone copies must equal repo copies BEFORE pushing — abort and report if they differ).
- [ ] Restart daemon: `env XDG_RUNTIME_DIR=/run/user/32011 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/32011/bus systemctl --user restart soundtype-daemon.service`; verify `is-active` + journal line "running".
- [ ] Kill running app instance if any; build + install click on phone; verify `grep -c OptionSelector /opt/click.ubuntu.com/soundtype.n0madd3v0ps/current/qml/Main.qml` ≥ 1.
- [ ] Verification criteria (DoD, run each, show output):
  1. `.venv/bin/python -m pytest -q` on Mac — all green (≥70 tests).
  2. Phone journal shows daemon running; keyboard dictation works on Parakeet (D-Bus toggle test, `Event: done` in journal).
  3. `settings.json` does not exist yet → app starts on parakeet (default path verified by `adb shell cat .../settings.json` returning ENOENT, and app dictation still works).
  4. Switching in the app to GigaAM triggers the download UI (~330 MB) and after download dictation works from the app (Khan taps; controller watches journal + settings.json content `{"model": "gigaam"}`).
  5. Keyboard dictation after the switch: first toggle after daemon idle-unload (or forced `systemctl --user restart`) loads GigaAM — journal shows load, dictation types Russian with punctuation.
  6. Switch back to Parakeet in settings works (no re-download, model already on disk).
  7. Edge: switch to GigaAM in the app but do NOT download → keyboard hold-space shows the grey (unloaded) indicator and recovers on next toggle after the model IS downloaded — daemon journal shows deps-missing handled, no stuck «busy».
- [ ] Commit nothing from the phone; Mac-side commits only.

**Interfaces:** none downstream — final task.

## Self-Review

- Spec coverage: registry+persist (T1), download GigaAM (T2), engine per profile + API (T3), daemon pickup (T4), UI selector (T5), deploy+acceptance+version (T6). Selector persists across restarts via settings.json read in `init` → `emit('model')` → QML binding. ✓
- Placeholder scan: none; all code inline. The two "read the existing file first" notes (conftest fixture name, Column vs ColumnLayout) are adaptation instructions with concrete fallbacks, not TBDs.
- Type consistency: `set_model(name)`/`model_stale()` names match across T3 (definition), T4 (daemon), T5 (QML call). `models.get_active(data_dir)` called with `DATA` in backend, with explicit dirs in tests. `missing(data_dir=DATA, model=None)` — backend calls `downloader.missing()` (both defaults) — correct: active profile.
- Risk noted: QML OptionSelector `onDelegateClicked` signature varies across Lomiri versions — implementer should mirror whatever pattern compiles on 1.3 (`delegateClicked(index)` signal). If problematic, fall back to two `Switch`-less `ListItem`s with radio semantics; keep the py.call contract identical.
