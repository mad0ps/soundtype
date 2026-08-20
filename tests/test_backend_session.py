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
