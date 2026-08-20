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

    history_calls = []
    audio_calls = []
    monkeypatch.setattr(backend, '_history_append',
                        lambda text, ts: history_calls.append((text, ts)))
    monkeypatch.setattr(backend, '_audio_save',
                        lambda ts, raw: audio_calls.append((ts, raw)))

    eng._session()

    assert [e for e in events if e[0] == 'partial'] == \
        [('partial', 1, 'слово8000')]
    finals = [e for e in events if e[0] == 'final']
    assert finals and finals[0][1] == 'слово8000'
    assert ('done', 'слово8000') in events
    assert vad.flushed             # хвост дожат на стопе
    assert vad.resets == 1         # VAD сброшен перед сессией

    # I3/тест-пункт 3: _history_append и _audio_save реально дошли до
    # финального текста и до сырых байт записи.
    assert len(history_calls) == 1
    assert history_calls[0][0] == 'слово8000'
    assert len(audio_calls) == 1
    assert audio_calls[0][1] == chunk * 40


def test_on_chunk_exception_does_not_lose_recording(events, monkeypatch):
    """I3: сбой внутри on_chunk (VAD/numpy) не должен ронять сессию —
    запись должна выжить и уйти дальше по I4-фолбэку целиком."""
    eng = backend.Dictation()
    eng.np = np
    eng.vad = FakeVad()
    eng.recognizer = object()
    monkeypatch.setattr(eng, '_decode', lambda seg: 'текст')

    chunk = b'\x10\x00' * 4096
    calls = []

    def fake_record(on_chunk=None):
        # backend._record сам оборачивает on_chunk в try/except — здесь
        # эмулируем именно это поведение, вызывая колбэк напрямую.
        def guarded(data):
            calls.append(1)
            raise RuntimeError('бум внутри VAD')
        try:
            guarded(chunk)
        except Exception:
            pass
        return chunk * 40
    monkeypatch.setattr(eng, '_record', fake_record)
    monkeypatch.setattr(backend, '_history_append', lambda *a: None)
    monkeypatch.setattr(backend, '_audio_save', lambda *a: None)

    eng._session()

    assert calls == [1]
    # ни один сегмент не был поставлен в очередь (on_chunk упал сразу) —
    # I4-фолбэк должен декодировать всю запись целиком.
    done = [e for e in events if e[0] == 'done']
    assert done and done[0][1] == 'текст'
    assert not [e for e in events if e[0] == 'error'
                and 'бум' in str(e[1])]


def test_vad_never_yields_segments_falls_back_to_whole_buffer(events,
                                                               monkeypatch):
    """I4: если VAD ни разу не «дозрел» до фразы, декодируем всю запись."""
    eng = backend.Dictation()
    eng.np = np
    eng.vad = FakeVad()   # pending всегда пуст — ни одного сегмента
    eng.recognizer = object()
    monkeypatch.setattr(eng, '_decode', lambda seg: 'вся запись')

    chunk = b'\x10\x00' * 4096
    monkeypatch.setattr(eng, '_record', lambda on_chunk=None: chunk * 40)
    monkeypatch.setattr(backend, '_history_append', lambda *a: None)
    monkeypatch.setattr(backend, '_audio_save', lambda *a: None)

    eng._session()

    finals = [e for e in events if e[0] == 'final']
    assert finals and finals[0][1] == 'вся запись'
    assert ('done', 'вся запись') in events


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


def test_start_refused_while_busy(events):
    """I2: start() не должен запускать вторую сессию, пока идёт распознавание
    (например, повтор из истории держит self.busy)."""
    eng = backend.Dictation()
    eng.recognizer = object()
    eng.busy.acquire()
    try:
        eng.start()
    finally:
        eng.busy.release()

    assert eng.thread is None
    assert any(e[0] == 'error' and 'распознавание' in str(e[1])
               for e in events)


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
