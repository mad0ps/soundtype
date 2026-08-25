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
    assert len(got) == 1
    assert got[0].samples == [0.1] * 800
    assert got[0].speech_len == 800
    assert got[0].gap is None


def test_flush_feeds_tail_and_drains():
    vad = FakeVad()
    s = Segmenter(vad, np, window=512)
    s.feed(np.zeros(300, dtype=np.float32))
    assert vad.windows == []                  # хвост меньше окна ещё не ушёл
    vad.pending.append(make_segment([0.2] * 640))
    got = s.flush()
    assert vad.flushed
    assert len(vad.windows) == 1 and len(vad.windows[0]) == 300
    assert len(got) == 1 and got[0].samples == [0.2] * 640


def _mk(samples, start):
    seg = make_segment(samples)
    seg.start = start
    return seg


def test_padding_and_gap():
    vad = FakeVad()
    s = Segmenter(vad, np, window=100, rate=1000, pad_pre=0.1, pad_post=0.05)
    stream = np.arange(2000, dtype=np.float32)

    s.feed(stream[:500])
    vad.pending.append(_mk(stream[200:300], 200))
    got = s.feed(stream[500:600])
    assert len(got) == 1
    p = got[0]
    # паддинг: 100 отсчётов до + 50 после, ограничен скормленным (600)
    assert p.samples[0] == 100.0 and p.samples[-1] == 349.0
    assert p.speech_len == 100
    assert p.gap is None

    vad.pending.append(_mk(stream[500:600], 500))
    got = s.feed(stream[600:700])
    p = got[0]
    assert p.gap == (500 - 300) / 1000.0
    # pre-pad не залезает в предыдущий сегмент (его конец = 300)
    assert p.samples[0] == 400.0 and p.samples[-1] == 649.0


def test_pre_pad_capped_by_previous_segment():
    vad = FakeVad()
    s = Segmenter(vad, np, window=100, rate=1000, pad_pre=0.5, pad_post=0.0)
    stream = np.arange(1000, dtype=np.float32)
    s.feed(stream[:400])
    vad.pending.append(_mk(stream[100:200], 100))
    s.feed(stream[400:500])
    vad.pending.append(_mk(stream[300:400], 300))
    got = s.feed(stream[500:600])
    # pad_pre=500 хочет с 0, но конец предыдущего сегмента = 200
    assert got[0].samples[0] == 200.0


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
