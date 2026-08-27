# -*- coding: utf-8 -*-
"""SoundType backend.

Порядок работы (с 0.6 — потоковый):

  1. Нажали запись — пишем звук с микрофона в память. В том же цикле
     лёгкий VAD (silero) режет накопленный звук на фразы прямо по ходу
     записи; готовые фразы уходят в очередь отдельному потоку, который
     их распознаёт, пока запись продолжается. Цикл чтения микрофона
     сам по себе делает только это чтение — тяжёлый декод его не
     тормозит, sherpa-onnx отпускает GIL.
  2. Нажали стоп — доразбирается последняя ещё не закрытая фраза, и
     поток декода дожидается своей очереди.
  3. Готовый текст уходит в историю и сразу копируется в буфер обмена.

Звук последних записей сохраняется на диск, чтобы расшифровку можно
было переспросить, если модель ошиблась. Хранится ограниченное число
записей, старые удаляются автоматически.

Звук берём через libpulse-simple (ctypes), фразы режет silero VAD,
распознаёт Parakeet TDT 0.6b v3 через sherpa-onnx. Всё офлайн.
"""

import importlib
import json
import os
import sys
import time
import wave
import ctypes
import threading
import audioop

HOME = os.environ.get('HOME', '/home/phablet')
DATA = os.path.join(HOME, '.local', 'share', 'soundtype.n0madd3v0ps')
RUNTIME = os.path.join(DATA, 'runtime')
MODELS = os.path.join(DATA, 'models')
HISTORY = os.path.join(DATA, 'history.jsonl')
AUDIO = os.path.join(DATA, 'audio')

sys.path.insert(0, os.path.join(RUNTIME, 'pylibs'))

import pyotherside  # noqa: E402
import streaming  # noqa: E402
import downloader  # noqa: E402
import models  # noqa: E402

RATE = 16000
CHANNELS = 1
VAD_WINDOW = streaming.VAD_WINDOW
CHUNK_BYTES = VAD_WINDOW * 2 * 4  # 4 окна = 0.128 с: level для волны ~8 раз/с

# Параметры нарезки и стыков фраз живут в py/streaming.py (канон): их
# использует и eval-харнесс, чтобы мерить ровно продовый пайплайн.
MAX_SPEECH = streaming.MAX_SPEECH
MIN_SILENCE = streaming.MIN_SILENCE
MIN_SPEECH = streaming.MIN_SPEECH
PAD_PRE = streaming.PAD_PRE
PAD_POST = streaming.PAD_POST
CAP_PAUSE = streaming.CAP_PAUSE
VAD_BUFFER_SECONDS = 120
MAX_RECORD_SECONDS = 600

HISTORY_LIMIT = 500
# Сколько последних записей держим со звуком. Минута речи — около 2 МБ,
# так что двадцать записей это десятки мегабайт, не больше.
AUDIO_KEEP = 20

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


# ---------------------------------------------------------------- звук


def _audio_path(ts):
    return os.path.join(AUDIO, '%d.wav' % int(ts * 1000))


def _audio_save(ts, pcm_bytes):
    """Кладём запись рядом с историей, чтобы её можно было переспросить."""
    try:
        os.makedirs(AUDIO, exist_ok=True)
        path = _audio_path(ts)
        with wave.open(path, 'wb') as w:
            w.setnchannels(CHANNELS)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm_bytes)
        _audio_prune()
        return os.path.basename(path)
    except Exception as exc:
        emit('error', 'Не удалось сохранить запись: %s' % exc)
        return None


def _audio_prune():
    """Оставляем только последние AUDIO_KEEP записей."""
    try:
        files = [os.path.join(AUDIO, f) for f in os.listdir(AUDIO)
                 if f.endswith('.wav')]
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for path in files[AUDIO_KEEP:]:
            try:
                os.remove(path)
            except OSError:
                pass
    except Exception:
        pass


def _audio_load(ts):
    path = _audio_path(ts)
    if not os.path.exists(path):
        return None
    with wave.open(path, 'rb') as w:
        return w.readframes(w.getnframes())


# ---------------------------------------------------------------- история


_history_lock = threading.Lock()


def _history_append(text, ts):
    rec = {'ts': ts, 'text': text}
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


def _history_rewrite(items):
    tmp = HISTORY + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        for r in items:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, HISTORY)


def _history_update(ts, text):
    """Заменяем текст записи после повторного распознавания."""
    with _history_lock:
        items = _history_read()
        for r in items:
            if abs(r.get('ts', 0) - ts) < 0.001:
                r['text'] = text
                break
        else:
            return False
        _history_rewrite(items)
    return True


def history_list():
    """Отдаём историю в QML, новые записи сверху."""
    with _history_lock:
        items = _history_read()[-HISTORY_LIMIT:]
    items.reverse()
    for it in items:
        ts = it.get('ts', 0)
        it['when'] = time.strftime('%d.%m %H:%M', time.localtime(ts))
        it['has_audio'] = os.path.exists(_audio_path(ts))
    return items


def history_clear():
    try:
        with _history_lock:
            if os.path.exists(HISTORY):
                os.remove(HISTORY)
        for f in os.listdir(AUDIO) if os.path.isdir(AUDIO) else []:
            try:
                os.remove(os.path.join(AUDIO, f))
            except OSError:
                pass
        return True
    except Exception as exc:
        emit('error', 'Не удалось очистить историю: %s' % exc)
        return False


# ---------------------------------------------------------------- движок


class Dictation(object):
    def __init__(self):
        self.recognizer = None
        self.model_name = None
        self.vad = None
        self.np = None
        self.thread = None
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.busy = threading.Lock()
        self.loading = False

    # ---------- загрузка движка ----------

    def load(self):
        with self.lock:
            if self.loading:
                # загрузка уже идёт; если выбор успел смениться, хвост
                # work() сам перегрузит движок на актуальный профиль (#27)
                return
            self.loading = True

        def work():
            active = None
            try:
                emit('status', 'loading')
                # Каталог pylibs мог появиться уже ПОСЛЕ старта процесса
                # (первый запуск: скачали и сразу грузим). Python 3.8 кэширует
                # отсутствовавший путь как None в sys.path_importer_cache и
                # молча пропускает его — без сброса кэша import numpy падает.
                importlib.invalidate_caches()
                import numpy as np
                import sherpa_onnx

                active = models.get_active(DATA)
                mf = models.model_files(active, DATA)
                rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=mf['encoder'],
                    decoder=mf['decoder'],
                    joiner=mf['joiner'],
                    tokens=mf['tokens'],
                    num_threads=4,
                    model_type='nemo_transducer',
                    debug=False,
                )

                cfg = sherpa_onnx.VadModelConfig()
                cfg.silero_vad.model = os.path.join(MODELS, 'silero_vad.onnx')
                cfg.silero_vad.threshold = 0.5
                cfg.silero_vad.min_silence_duration = MIN_SILENCE
                cfg.silero_vad.min_speech_duration = MIN_SPEECH
                cfg.silero_vad.max_speech_duration = MAX_SPEECH
                cfg.sample_rate = RATE
                vad = sherpa_onnx.VoiceActivityDetector(
                    cfg, buffer_size_in_seconds=VAD_BUFFER_SECONDS)

                with self.lock:
                    self.np = np
                    self.recognizer = rec
                    self.model_name = active
                    self.vad = vad
                # выбор могли сменить, пока грузились: ready об устаревшем
                # движке не объявляем — ниже перегрузимся на актуальный
                if models.get_active(DATA) == active:
                    emit('ready', active)
            except Exception as exc:
                emit('error', 'Не удалось загрузить движок: %s' % exc)
            finally:
                with self.lock:
                    self.loading = False
            self._reload_if_switched(active)
        threading.Thread(target=work, daemon=True).start()

    def _reload_if_switched(self, loaded):
        """Схлопывает гонку #27: профиль сменили во время загрузки.

        Вызывается из потока загрузки после сброса loading. Каким бы ни был
        порядок потоков, последним всегда выполняется этот хвост — и он
        приводит движок к профилю из настроек.
        """
        if loaded is None or models.get_active(DATA) == loaded:
            return False
        self.unload()
        _ensure_loaded()
        return True

    def unload(self):
        import gc
        with self.lock:
            self.recognizer = None
            self.model_name = None
            self.vad = None
        gc.collect()
        # glibc не отдаёт освобождённую кучу ОС сам — без trim RSS остаётся
        # сотни МБ после выгрузки модели
        try:
            import ctypes
            ctypes.CDLL('libc.so.6').malloc_trim(0)
        except Exception:
            pass
        emit('status', 'unloaded')

    # ---------- управление ----------

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return
        with self.lock:
            if self.recognizer is None:
                emit('error', 'Движок ещё не загружен')
                return
        if not self.busy.acquire(False):
            emit('error', 'Идёт распознавание — подожди')
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

    def _record(self, on_chunk=None):
        """Пишем звук в память до нажатия стоп; каждый кусок отдаём колбэку."""
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

                parts.append(data)
                total += len(data) // 2
                emit('elapsed', total / float(RATE))

                if on_chunk is not None:
                    try:
                        on_chunk(data)
                    except Exception:
                        pass

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

        return b''.join(parts)

    # ---------- расшифровка ----------

    def _split(self, pcm):
        """Режем запись на фразы. Общий механизм с потоковым режимом."""
        self.vad.reset()
        seg = streaming.Segmenter(self.vad, self.np, VAD_WINDOW, rate=RATE,
                                  pad_pre=PAD_PRE, pad_post=PAD_POST,
                                  overlap=streaming.OVERLAP)
        segments = seg.feed(pcm)
        segments += seg.flush()
        if not segments and len(pcm):
            segments = [streaming.Phrase(pcm, len(pcm), None)]
        return segments

    def _decode(self, samples):
        stream = self.recognizer.create_stream()
        stream.accept_waveform(RATE, samples)
        self.recognizer.decode_stream(stream)
        return (stream.result.text or '').strip()

    def _transcribe(self, raw):
        """Из сырых байтов PCM получаем текст. Общий путь для записи и повтора."""
        np = self.np
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        segments = self._split(pcm)
        texts = []
        for idx, phrase in enumerate(segments, 1):
            if phrase.speech_len < RATE * 0.2:
                continue
            emit('progress', idx, len(segments))
            try:
                text = self._decode(phrase.samples)
            except Exception as exc:
                emit('error', 'Сбой распознавания: %s' % exc)
                continue
            if text:
                prev = texts[-1] if texts else None
                chunk = streaming.join_chunk(prev, text, phrase.gap,
                                             phrase.overlap, CAP_PAUSE)
                if chunk:
                    texts.append(chunk)
        return ''.join(texts).strip()

    def _session(self):
        worker = None
        try:
            np = self.np
            self.vad.reset()
            seg = streaming.Segmenter(self.vad, np, VAD_WINDOW, rate=RATE,
                                      pad_pre=PAD_PRE, pad_post=PAD_POST,
                                      overlap=streaming.OVERLAP)
            worker = streaming.DecodeWorker(
                self._decode,
                on_text=lambda idx, text: emit('partial', idx, text),
                on_error=lambda exc: emit('error',
                                          'Сбой распознавания: %s' % exc),
                min_samples=int(RATE * 0.2), cap_pause=CAP_PAUSE)

            queued = [False]  # хоть один сегмент дошёл до воркера

            def on_chunk(data):
                samples = (np.frombuffer(data, dtype=np.int16)
                           .astype(np.float32) / 32768.0)
                for s in seg.feed(samples):
                    queued[0] = True
                    worker.put(s)

            raw = self._record(on_chunk)
            ts = time.time()
            short = len(raw) < RATE * 2 * 0.3

            # На стопе осталась только последняя открытая фраза.
            emit('transcribing', True)
            for s in seg.flush():
                queued[0] = True
                worker.put(s)

            if not short and not queued[0]:
                # VAD ни разу не «дозрел» до фразы за всю запись — например,
                # порог не сработал на тихой речи. Не оставляем пользователя
                # без единого слова текста: декодируем всю запись целиком,
                # но только один раз (не нарушает грабли #2918 — это разовый
                # decode всего буфера, а не повторный decode растущего).
                whole = (np.frombuffer(raw, dtype=np.int16)
                         .astype(np.float32) / 32768.0)
                worker.put(whole)

            full = worker.close(timeout=180)
            emit('transcribing', False)

            if short:
                emit('done', '')
                return

            if full:
                _history_append(full, ts)
                _audio_save(ts, raw)
                emit('final', full, ts)
            emit('done', full)
        except Exception as exc:
            if worker is not None:
                worker.close(timeout=5)
            emit('transcribing', False)
            emit('error', str(exc))
            emit('done', '')
        finally:
            if self.busy.locked():
                try:
                    self.busy.release()
                except RuntimeError:
                    pass

    # ---------- повторное распознавание ----------

    def retry(self, ts):
        def work():
            if self.thread is not None and self.thread.is_alive():
                emit('error', 'Идёт запись — сначала останови её')
                return
            if not self.busy.acquire(False):
                emit('error', 'Уже идёт распознавание')
                return
            try:
                with self.lock:
                    if self.recognizer is None:
                        emit('error', 'Движок ещё не загружен')
                        return
                raw = _audio_load(ts)
                if raw is None:
                    emit('error', 'Запись не сохранилась, переспросить нечего')
                    emit('retried', ts, '')
                    return
                emit('transcribing', True)
                text = self._transcribe(raw)
                emit('transcribing', False)
                if text:
                    _history_update(ts, text)
                emit('retried', ts, text)
            except Exception as exc:
                emit('transcribing', False)
                emit('error', str(exc))
                emit('retried', ts, '')
            finally:
                self.busy.release()
        threading.Thread(target=work, daemon=True).start()


_engine = Dictation()


def model_stale():
    """Движок загружен, но профиль в настройках уже другой."""
    return (_engine.recognizer is not None
            and _engine.model_name != models.get_active(DATA))


def _deps_missing_info():
    """Довесок к deps-missing для оверлея закачки (#28): размер выбранной
    модели и профиль, на который можно откатиться без сети."""
    active = models.get_active(DATA)
    fb = models.fallback_profile(active, DATA)
    return {
        'size': models.REGISTRY[active].get('size', ''),
        'fallback': fb or '',
        'fallback_label': models.REGISTRY[fb]['label'] if fb else '',
    }


def _ensure_loaded():
    """Грузим движок, если для активного профиля всё скачано."""
    miss = downloader.missing()
    if miss:
        emit('deps-missing', miss, _deps_missing_info())
    else:
        _engine.load()


def set_model(name):
    """Выбор профиля из настроек приложения."""
    models.set_active(name, DATA)
    if _engine.recognizer is not None:
        _engine.unload()
    emit('model', name)
    _ensure_loaded()


def init(_ignored=None):
    emit('model', models.get_active(DATA))
    _ensure_loaded()


def start():
    _engine.start()


def stop():
    _engine.stop()


def unload():
    _engine.unload()


def retry(ts):
    _engine.retry(float(ts))


_fetch_lock = threading.Lock()


def fetch_deps():
    """Скачиваем модель и библиотеки по кнопке из UI, с прогрессом.

    Кнопка «Скачать» в QML не блокируется на время загрузки, поэтому
    двойной тап должен быть безвредным: второй вызов не запускает
    параллельную загрузку в те же временные пути, а просто выходит.
    """
    if not _fetch_lock.acquire(False):
        return

    def work():
        try:
            emit('download-progress', 'подготовка', -1)
            downloader.fetch_all(
                lambda stage, pct: emit('download-progress', stage, pct))
            emit('download-done')
            _engine.load()
        except Exception as exc:
            emit('download-error', str(exc))
        finally:
            _fetch_lock.release()
    threading.Thread(target=work, daemon=True).start()
