# -*- coding: utf-8 -*-
"""Потоковая нарезка и фоновое распознавание.

Segmenter гонит звук через VAD окнами по 512 отсчётков прямо из цикла
записи; готовые фразы уходят вызывающему. DecodeWorker (задача 2) разбирает
их в отдельном потоке. Ловушка sherpa-onnx #2918: декодируем только сегмент,
никогда весь накопленный буфер.

Модуль не знает про pyotherside — только колбэки. Так его можно гонять
тестами на любой машине.
"""

import queue
import threading

_SENTINEL = object()


class Segmenter(object):
    """Кормит VAD окнами по `window` отсчётков, отдаёт готовые сегменты.

    feed() принимает float32-массив произвольной длины; остаток, не кратный
    окну, хранится до следующего feed() или flush().
    """

    def __init__(self, vad, np, window=512):
        self.vad = vad
        self.np = np
        self.window = window
        self._tail = np.zeros(0, dtype=np.float32)

    def _drain(self, out):
        while not self.vad.empty():
            out.append(self.vad.front.samples)
            self.vad.pop()

    def feed(self, samples):
        np = self.np
        buf = np.concatenate([self._tail, samples]) if len(self._tail) else samples
        n = (len(buf) // self.window) * self.window
        self._tail = buf[n:]
        out = []
        for i in range(0, n, self.window):
            self.vad.accept_waveform(buf[i:i + self.window])
            self._drain(out)
        return out

    def flush(self):
        """Дожимаем хвост меньше окна и всё, что осталось внутри VAD."""
        if len(self._tail):
            self.vad.accept_waveform(self._tail)
            self._tail = self._tail[:0]
        self.vad.flush()
        out = []
        self._drain(out)
        return out


class DecodeWorker(object):
    """Отдельный поток: берёт сегменты из очереди, декодирует, копит текст.

    Декод в C++ (sherpa-onnx) отпускает GIL, поэтому поток реально
    работает параллельно записи. Ошибка на одном сегменте не убивает
    поток — сегмент пропускается, остальные декодируются.
    """

    def __init__(self, decode_fn, on_text, on_error=None, min_samples=0):
        self.decode_fn = decode_fn
        self.on_text = on_text
        self.on_error = on_error
        self.min_samples = min_samples
        self.texts = []
        self.q = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def put(self, segment):
        self.q.put(segment)

    def close(self, timeout=None):
        """Сигнал конца: дожидаемся очереди, отдаём склеенный текст."""
        self.q.put(_SENTINEL)
        self._thread.join(timeout)
        return ' '.join(self.texts).strip()

    def _run(self):
        idx = 0
        while True:
            seg = self.q.get()
            if seg is _SENTINEL:
                return
            if self.min_samples and len(seg) < self.min_samples:
                continue
            idx += 1
            try:
                text = (self.decode_fn(seg) or '').strip()
            except Exception as exc:
                if self.on_error is not None:
                    self.on_error(exc)
                continue
            if text:
                self.texts.append(text)
                self.on_text(idx, text)
