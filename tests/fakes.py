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
