# -*- coding: utf-8 -*-
"""SoundType backend.

Порядок работы простой и предсказуемый:

  1. Нажали запись — пишем звук с микрофона в память, и только пишем.
     Никакого распознавания в это время не происходит, поэтому терять
     на паузах нечего: цикл чтения не может ничем застопориться.
  2. Нажали стоп — весь накопленный звук режем детектором тишины на
     фразы и прогоняем через Parakeet по очереди.
  3. Готовый текст уходит в историю и сразу копируется в буфер обмена.

Звук берём через libpulse-simple (ctypes), фразы режет silero VAD,
распознаёт Parakeet TDT 0.6b v3 через sherpa-onnx. Всё офлайн.
"""

import json
import os
import sys
import time
import ctypes
import threading
import audioop

HOME = os.environ.get('HOME', '/home/phablet')
DATA = os.path.join(HOME, '.local', 'share', 'soundtype.n0madd3v0ps')
RUNTIME = os.path.join(DATA, 'runtime')
MODELS = os.path.join(DATA, 'models')
HISTORY = os.path.join(DATA, 'history.jsonl')

sys.path.insert(0, os.path.join(RUNTIME, 'pylibs'))

import pyotherside  # noqa: E402

RATE = 16000
CHANNELS = 1
VAD_WINDOW = 512                  # silero работает окнами по 512 отсчётов
CHUNK_BYTES = VAD_WINDOW * 2 * 8  # читаем по 8 окон за раз

# Режем запись на фразы уже после остановки, поэтому длина одной фразы
# ограничена только удобством: слишком длинный кусок модель считает долго.
MAX_SPEECH = 30.0
VAD_BUFFER_SECONDS = 120

# Потолок одной записи. 16 кГц float32 — это 64 КБ в секунду,
# десять минут занимают около 38 МБ, что для телефона приемлемо.
MAX_RECORD_SECONDS = 600

HISTORY_LIMIT = 500

PA_SAMPLE_S16LE = 3
PA_STREAM_RECORD = 2


def emit(event, *args):
    try:
        pyotherside.send(event, *args)
    except Exception:
        pass


class PaSampleSpec(ctypes.Structure):
    _fields_ = [('format', ctypes.c_int),
                ('rate', ctypes.c_uint32),
                ('channels', ctypes.c_uint8)]


_pa = None


def _pulse():
    global _pa
    if _pa is not None:
        return _pa
    lib = ctypes.CDLL('libpulse-simple.so.0')
    lib.pa_simple_new.restype = ctypes.c_void_p
    lib.pa_simple_new.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
        ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(PaSampleSpec),
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.pa_simple_read.restype = ctypes.c_int
    lib.pa_simple_read.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.pa_simple_free.restype = None
    lib.pa_simple_free.argtypes = [ctypes.c_void_p]
    lib.pa_strerror.restype = ctypes.c_char_p
    lib.pa_strerror.argtypes = [ctypes.c_int]
    _pa = lib
    return lib


# ---------------------------------------------------------------- история


_history_lock = threading.Lock()


def _history_append(text):
    rec = {'ts': time.time(), 'text': text}
    try:
        with _history_lock:
            with open(HISTORY, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception as exc:
        emit('error', 'Не удалось сохранить в историю: %s' % exc)
    return rec


def _history_read():
    if not os.path.exists(HISTORY):
        return []
    out = []
    try:
        with _history_lock:
            with open(HISTORY, encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except Exception as exc:
        emit('error', 'Не удалось прочитать историю: %s' % exc)
        return []
    return out


def history_list():
    """Отдаём историю в QML, новые записи сверху."""
    items = _history_read()[-HISTORY_LIMIT:]
    items.reverse()
    for it in items:
        it['when'] = time.strftime('%d.%m %H:%M', time.localtime(it.get('ts', 0)))
    return items


def history_clear():
    try:
        with _history_lock:
            if os.path.exists(HISTORY):
                os.remove(HISTORY)
        return True
    except Exception as exc:
        emit('error', 'Не удалось очистить историю: %s' % exc)
        return False


# ---------------------------------------------------------------- движок


class Dictation(object):
    def __init__(self):
        self.recognizer = None
        self.vad = None
        self.np = None
        self.thread = None
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()

    # ---------- загрузка движка ----------

    def load(self):
        def work():
            try:
                emit('status', 'loading')
                import numpy as np
                import sherpa_onnx

                pk = os.path.join(MODELS, 'parakeet')
                rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=os.path.join(pk, 'encoder.int8.onnx'),
                    decoder=os.path.join(pk, 'decoder.int8.onnx'),
                    joiner=os.path.join(pk, 'joiner.int8.onnx'),
                    tokens=os.path.join(pk, 'tokens.txt'),
                    num_threads=4,
                    model_type='nemo_transducer',
                    debug=False,
                )

                cfg = sherpa_onnx.VadModelConfig()
                cfg.silero_vad.model = os.path.join(MODELS, 'silero_vad.onnx')
                cfg.silero_vad.threshold = 0.5
                cfg.silero_vad.min_silence_duration = 0.35
                cfg.silero_vad.min_speech_duration = 0.20
                cfg.silero_vad.max_speech_duration = MAX_SPEECH
                cfg.sample_rate = RATE
                vad = sherpa_onnx.VoiceActivityDetector(
                    cfg, buffer_size_in_seconds=VAD_BUFFER_SECONDS)

                with self.lock:
                    self.np = np
                    self.recognizer = rec
                    self.vad = vad
                emit('ready', 'parakeet-tdt-0.6b-v3')
            except Exception as exc:
                emit('error', 'Не удалось загрузить движок: %s' % exc)
        threading.Thread(target=work, daemon=True).start()

    # ---------- управление ----------

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return
        with self.lock:
            if self.recognizer is None:
                emit('error', 'Движок ещё не загружен')
                return
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._session, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()

    def _open_stream(self):
        pa = _pulse()
        spec = PaSampleSpec(PA_SAMPLE_S16LE, RATE, CHANNELS)
        err = ctypes.c_int(0)
        handle = pa.pa_simple_new(
            None, b'SoundType', PA_STREAM_RECORD, None, b'dictation',
            ctypes.byref(spec), None, None, ctypes.byref(err))
        if not handle:
            msg = pa.pa_strerror(err.value)
            msg = msg.decode('utf-8', 'replace') if msg else 'код %d' % err.value
            raise RuntimeError('микрофон недоступен (%s)' % msg)
        return pa, handle

    # ---------- запись ----------

    def _record(self):
        """Пишем звук в память до нажатия стоп. Больше ничего не делаем."""
        np = self.np
        pa = handle = None
        parts = []
        total = 0
        max_samples = int(RATE * MAX_RECORD_SECONDS)
        try:
            pa, handle = self._open_stream()
            emit('recording', True)

            buf = ctypes.create_string_buffer(CHUNK_BYTES)
            err = ctypes.c_int(0)

            while not self.stop_flag.is_set():
                if pa.pa_simple_read(handle, buf, CHUNK_BYTES,
                                     ctypes.byref(err)) < 0:
                    raise RuntimeError('обрыв чтения с микрофона')
                data = buf.raw[:CHUNK_BYTES]

                try:
                    emit('level', min(1.0, audioop.rms(data, 2) / 12000.0))
                except Exception:
                    pass

                parts.append(np.frombuffer(data, dtype=np.int16).copy())
                total += len(parts[-1])
                emit('elapsed', total / float(RATE))

                if total >= max_samples:
                    emit('error', 'Достигнут предел записи в %d минут'
                         % (MAX_RECORD_SECONDS // 60))
                    break
        finally:
            if pa is not None and handle:
                try:
                    pa.pa_simple_free(handle)
                except Exception:
                    pass
            emit('level', 0.0)
            emit('recording', False)

        if not parts:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(parts).astype(np.float32) / 32768.0

    # ---------- расшифровка ----------

    def _split(self, pcm):
        """Режем запись на фразы. Звук уже весь в памяти, ничего не теряется."""
        segments = []
        self.vad.reset()
        i = 0
        n = len(pcm)
        while i + VAD_WINDOW <= n:
            self.vad.accept_waveform(pcm[i:i + VAD_WINDOW])
            i += VAD_WINDOW
            while not self.vad.empty():
                segments.append(self.vad.front.samples)
                self.vad.pop()
        self.vad.flush()
        while not self.vad.empty():
            segments.append(self.vad.front.samples)
            self.vad.pop()
        # Если детектор не нашёл границ — отдаём модели всё целиком,
        # лучше так, чем молча вернуть пустой результат.
        if not segments and n:
            segments = [pcm]
        return segments

    def _decode(self, samples):
        stream = self.recognizer.create_stream()
        stream.accept_waveform(RATE, samples)
        self.recognizer.decode_stream(stream)
        return (stream.result.text or '').strip()

    def _session(self):
        try:
            pcm = self._record()

            if len(pcm) < RATE * 0.3:
                emit('done', '')
                return

            emit('transcribing', True)
            segments = self._split(pcm)

            texts = []
            for idx, seg in enumerate(segments, 1):
                if len(seg) < RATE * 0.2:
                    continue
                emit('progress', idx, len(segments))
                try:
                    text = self._decode(seg)
                except Exception as exc:
                    emit('error', 'Сбой распознавания: %s' % exc)
                    continue
                if text:
                    texts.append(text)

            full = ' '.join(texts).strip()
            emit('transcribing', False)

            if full:
                rec = _history_append(full)
                emit('final', full, rec.get('ts', 0))
            emit('done', full)
        except Exception as exc:
            emit('transcribing', False)
            emit('error', str(exc))
            emit('done', '')


_engine = Dictation()


def init(_ignored=None):
    _engine.load()


def start():
    _engine.start()


def stop():
    _engine.stop()
