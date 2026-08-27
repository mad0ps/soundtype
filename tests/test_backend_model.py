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


def test_ready_payload_not_hardcoded():
    import inspect
    src = inspect.getsource(backend.Dictation.load)
    assert 'parakeet-tdt-0.6b-v3' not in src
    assert "emit('ready', active)" in src


# ---------- гонка двойной загрузки (#27) ----------

def test_load_guard_spawns_single_thread(monkeypatch):
    d = backend.Dictation()
    created = []

    class FakeThread(object):
        def __init__(self, target=None, daemon=None):
            created.append(target)

        def start(self):
            pass

    monkeypatch.setattr(backend.threading, 'Thread', FakeThread)
    d.load()
    d.load()  # во время незавершённой загрузки — второй поток не создаётся
    assert len(created) == 1


def test_load_allowed_again_after_finish(monkeypatch):
    d = backend.Dictation()
    created = []

    class FakeThread(object):
        def __init__(self, target=None, daemon=None):
            created.append(target)

        def start(self):
            pass

    monkeypatch.setattr(backend.threading, 'Thread', FakeThread)
    d.load()
    with d.lock:
        d.loading = False  # work() отработал
    d.load()
    assert len(created) == 2


def test_reload_if_switched_reloads_current_profile(monkeypatch, events):
    d = backend.Dictation()
    monkeypatch.setattr(models, 'get_active', lambda dd=None: 'gigaam')
    calls = []
    monkeypatch.setattr(d, 'unload', lambda: calls.append('unload'))
    monkeypatch.setattr(backend, '_ensure_loaded', lambda: calls.append('ensure'))
    assert d._reload_if_switched('parakeet') is True
    assert calls == ['unload', 'ensure']


def test_reload_if_switched_noop_when_profile_kept(monkeypatch):
    d = backend.Dictation()
    monkeypatch.setattr(models, 'get_active', lambda dd=None: 'gigaam')
    monkeypatch.setattr(backend, '_ensure_loaded',
                        lambda: (_ for _ in ()).throw(AssertionError('reload')))
    assert d._reload_if_switched('gigaam') is False
    assert d._reload_if_switched(None) is False  # загрузка упала до выбора


def test_load_skips_stale_ready_emit():
    import inspect
    src = inspect.getsource(backend.Dictation.load)
    # ready не объявляется, если выбор сменился за время загрузки
    assert "if models.get_active(DATA) == active:" in src
    assert "self._reload_if_switched(active)" in src


# ---------- payload deps-missing для оверлея (#28) ----------

def test_deps_missing_carries_fallback(tmp_path, monkeypatch, events):
    import os
    monkeypatch.setattr(backend, 'DATA', str(tmp_path))
    monkeypatch.setattr(backend.downloader, 'missing', lambda *a, **k: ['gigaam'])
    backend._engine.recognizer = None
    probe = models.probe_path('parakeet', str(tmp_path))
    os.makedirs(os.path.dirname(probe), exist_ok=True)
    open(probe, 'w').close()
    backend.set_model('gigaam')
    ev = [e for e in events if e[0] == 'deps-missing']
    assert ev and len(ev[0]) == 3
    info = ev[0][2]
    assert info['fallback'] == 'parakeet'
    assert info['fallback_label'] == models.REGISTRY['parakeet']['label']
    assert info['size'] == models.REGISTRY['gigaam']['size']


def test_deps_missing_no_fallback_on_first_run(tmp_path, monkeypatch, events):
    monkeypatch.setattr(backend, 'DATA', str(tmp_path))
    monkeypatch.setattr(backend.downloader, 'missing', lambda *a, **k: ['x'])
    backend._engine.recognizer = None
    backend.init()
    info = [e for e in events if e[0] == 'deps-missing'][0][2]
    assert info['fallback'] == '' and info['fallback_label'] == ''
