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
