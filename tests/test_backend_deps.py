# -*- coding: utf-8 -*-
import threading
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


def test_fetch_deps_not_reentrant(events, monkeypatch):
    """I5: двойной тап по «Скачать» не должен запускать вторую загрузку,
    делящую временные пути с первой."""
    calls = []
    release = threading.Event()

    def blocking_fetch_all(cb):
        calls.append(1)
        release.wait(2)

    monkeypatch.setattr(backend.downloader, 'fetch_all', blocking_fetch_all)
    monkeypatch.setattr(backend._engine, 'load', lambda: None)

    backend.fetch_deps()
    for _ in range(100):
        if calls:
            break
        time.sleep(0.02)
    assert calls == [1]

    backend.fetch_deps()   # первая загрузка ещё держит лок — должно быть no-op
    time.sleep(0.05)
    assert calls == [1]    # fetch_all не вызвался второй раз

    release.set()
    _wait_event(events, 'download-done')
