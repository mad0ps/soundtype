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

# Конец предложения: после этих знаков следующая фраза начинается с заглавной.
SENTENCE_END = ('.', '!', '?', '…')


class Phrase(object):
    """Готовая фраза из VAD: samples (с паддингом), длина чистой речи
    в отсчётах и пауза в секундах перед началом (None = первая/неизвестно)."""

    __slots__ = ('samples', 'speech_len', 'gap')

    def __init__(self, samples, speech_len, gap):
        self.samples = samples
        self.speech_len = speech_len
        self.gap = gap


def phrase_glue(prev_text, gap, cap_pause):
    """Чем склеить предыдущий текст с новой фразой и капитализировать ли её.

    Модель пунктуирует каждый сегмент независимо; правило стыка:
    - предыдущая фраза закончилась знаком конца предложения -> пробел + заглавная;
    - пауза перед фразой длинная (>= cap_pause) -> точка недоставленная моделью
      + заглавная;
    - иначе обычный пробел, регистр модели не трогаем.
    """
    if prev_text is None:
        return '', True
    if prev_text.rstrip().endswith(SENTENCE_END):
        return ' ', True
    if gap is not None and gap >= cap_pause:
        return '. ', True
    return ' ', False


def capitalize_first(text):
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
    return text


class Segmenter(object):
    """Кормит VAD окнами по `window` отсчётков, отдаёт готовые сегменты.

    feed() принимает float32-массив произвольной длины; остаток, не кратный
    окну, хранится до следующего feed() или flush().
    """

    def __init__(self, vad, np, window=512, rate=0, pad_pre=0.0, pad_post=0.0,
                 keep_seconds=40.0):
        self.vad = vad
        self.np = np
        self.window = window
        self.rate = rate
        # Паддинг: sherpa-onnx не захватывает контекст вокруг сегмента
        # (k2-fsa/sherpa-onnx#3035), первые/последние слова подрезаются.
        # Держим кольцевой буфер сырого потока и приклеиваем края сами.
        self._pad_pre = int(rate * pad_pre)
        self._pad_post = int(rate * pad_post)
        self._keep = int(rate * keep_seconds) if rate else 0
        self._tail = np.zeros(0, dtype=np.float32)
        self._buf = np.zeros(0, dtype=np.float32)
        self._buf_base = 0     # абсолютный индекс первого отсчёта в _buf
        self._fed = 0          # сколько отсчётов скормлено VAD всего
        self._prev_end = None  # абсолютный конец предыдущего сегмента

    def _remember(self, chunk):
        if not self._keep:
            return
        np = self.np
        self._buf = np.concatenate([self._buf, chunk]) if len(self._buf) else chunk
        extra = len(self._buf) - self._keep
        if extra > 0:
            self._buf = self._buf[extra:]
            self._buf_base += extra

    def _drain(self, out):
        while not self.vad.empty():
            front = self.vad.front
            raw = front.samples
            start = getattr(front, 'start', None)
            self.vad.pop()
            if start is None or not self._keep:
                out.append(Phrase(raw, len(raw), None))
                continue
            end = start + len(raw)
            gap = (None if self._prev_end is None
                   else (start - self._prev_end) / float(self.rate))
            lo = max(start - self._pad_pre, self._buf_base,
                     self._prev_end if self._prev_end is not None else 0)
            hi = min(end + self._pad_post, self._fed)
            self._prev_end = end
            out.append(Phrase(self._buf[lo - self._buf_base:hi - self._buf_base],
                              len(raw), gap))

    def feed(self, samples):
        np = self.np
        buf = np.concatenate([self._tail, samples]) if len(self._tail) else samples
        n = (len(buf) // self.window) * self.window
        self._tail = buf[n:]
        out = []
        if n:
            self._remember(buf[:n])
        for i in range(0, n, self.window):
            self.vad.accept_waveform(buf[i:i + self.window])
            self._fed += self.window
            self._drain(out)
        return out

    def flush(self):
        """Дожимаем хвост меньше окна и всё, что осталось внутри VAD."""
        if len(self._tail):
            self._remember(self._tail)
            self.vad.accept_waveform(self._tail)
            self._fed += len(self._tail)
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

    def __init__(self, decode_fn, on_text, on_error=None, min_samples=0,
                 cap_pause=1.5):
        self.decode_fn = decode_fn
        self.on_text = on_text
        self.on_error = on_error
        self.min_samples = min_samples
        self.cap_pause = cap_pause
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
        return ''.join(self.texts).strip()

    def _run(self):
        idx = 0
        while True:
            seg = self.q.get()
            if seg is _SENTINEL:
                return
            samples = getattr(seg, 'samples', seg)
            speech_len = getattr(seg, 'speech_len', len(samples))
            gap = getattr(seg, 'gap', None)
            if self.min_samples and speech_len < self.min_samples:
                continue
            idx += 1
            try:
                text = (self.decode_fn(samples) or '').strip()
            except Exception as exc:
                if self.on_error is not None:
                    self.on_error(exc)
                continue
            if text:
                prev = self.texts[-1] if self.texts else None
                glue, cap = phrase_glue(prev, gap, self.cap_pause)
                chunk = glue + (capitalize_first(text) if cap else text)
                self.texts.append(chunk)
                self.on_text(idx, chunk)
