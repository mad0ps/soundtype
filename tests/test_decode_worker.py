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
