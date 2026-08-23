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
