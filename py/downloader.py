# -*- coding: utf-8 -*-
"""Скачивание модели и python-библиотек в каталог данных приложения.

Одна логика на двух хозяев:

  * scripts/fetch-deps.py — ручной запуск из терминала;
  * py/backend.py — кнопка «Скачать» при первом запуске приложения.

Прогресс отдаётся колбэком progress(stage, pct): stage — человекочитаемое
имя этапа, pct — целые проценты либо -1, если размер неизвестен. Никаких
pyotherside и print — модуль чистый, его гоняют тесты на любой машине.
Сбой = исключение наружу; докачки нет, повтор качает файл заново.
"""

import io
import json
import os
import shutil
import tarfile
import urllib.request
import zipfile

APP = 'soundtype.n0madd3v0ps'
HOME = os.environ.get('HOME', os.path.expanduser('~'))
DATA = os.path.join(HOME, '.local', 'share', APP)

PARAKEET_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
                'asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2')
SILERO_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
              'asr-models/silero_vad.onnx')

# Колёса под Python 3.8 / aarch64 — ровно то, что стоит в Ubuntu Touch 20.04.
WHEELS = [
    ('numpy', '1.24.4', 'cp38-cp38-manylinux_2_17_aarch64'),
    ('sherpa-onnx', '1.13.6', 'cp38-cp38-manylinux2014_aarch64'),
]

UA = {'User-Agent': 'soundtype-downloader'}


def _models(data_dir):
    return os.path.join(data_dir, 'models')


def _pylibs(data_dir):
    return os.path.join(data_dir, 'runtime', 'pylibs')


def missing(data_dir=DATA):
    """Чего не хватает для работы. Пустой список — всё на месте."""
    out = []
    for pkg, _ver, _tag in WHEELS:
        if not os.path.exists(os.path.join(_pylibs(data_dir),
                                           pkg.replace('-', '_'))):
            out.append(pkg)
    if not os.path.exists(os.path.join(_models(data_dir), 'silero_vad.onnx')):
        out.append('silero-vad')
    if not os.path.exists(os.path.join(_models(data_dir), 'parakeet',
                                       'encoder.int8.onnx')):
        out.append('parakeet')
    return out


def download(url, dest=None, progress=None, stage=''):
    """Качаем файл; dest=None — в память. progress зовём на целых процентах."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get('Content-Length') or 0)
        buf = open(dest, 'wb') if dest else io.BytesIO()
        got = 0
        last = -2
        try:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                buf.write(chunk)
                got += len(chunk)
                if progress is not None:
                    pct = int(got * 100 / total) if total else -1
                    if pct != last:
                        last = pct
                        progress(stage, pct)
            if dest:
                return dest
            return buf.getvalue()
        finally:
            if dest:
                buf.close()


def fetch_wheels(progress=None, data_dir=DATA, force=False):
    pylibs = _pylibs(data_dir)
    os.makedirs(pylibs, exist_ok=True)
    for pkg, ver, tag in WHEELS:
        probe = os.path.join(pylibs, pkg.replace('-', '_'))
        if os.path.exists(probe) and not force:
            continue
        meta = json.loads(download(
            'https://pypi.org/pypi/%s/%s/json' % (pkg, ver)).decode('utf-8'))
        url = None
        for f in meta['urls']:
            if tag in f['filename']:
                url = f['url']
                break
        if not url:
            raise RuntimeError('не нашёл колесо %s %s (%s)' % (pkg, ver, tag))
        blob = download(url, progress=progress, stage=pkg)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(pylibs)


def fetch_silero(progress=None, data_dir=DATA, force=False):
    models = _models(data_dir)
    os.makedirs(models, exist_ok=True)
    dest = os.path.join(models, 'silero_vad.onnx')
    if os.path.exists(dest) and not force:
        return
    download(SILERO_URL, dest, progress=progress, stage='детектор тишины')


def fetch_parakeet(progress=None, data_dir=DATA, force=False):
    models = _models(data_dir)
    os.makedirs(models, exist_ok=True)
    target = os.path.join(models, 'parakeet')
    if os.path.exists(os.path.join(target, 'encoder.int8.onnx')) and not force:
        return
    tmp = os.path.join(models, '_parakeet.tar.bz2')
    download(PARAKEET_URL, tmp, progress=progress, stage='модель Parakeet')

    if progress is not None:
        progress('распаковка', -1)
    unpack = os.path.join(models, '_unpack')
    shutil.rmtree(unpack, ignore_errors=True)
    os.makedirs(unpack)
    with tarfile.open(tmp, 'r:bz2') as tf:
        tf.extractall(unpack)

    # Внутри архива один каталог — забираем из него нужные файлы.
    inner = [os.path.join(unpack, d) for d in os.listdir(unpack)]
    inner = [d for d in inner if os.path.isdir(d)]
    if not inner:
        raise RuntimeError('в архиве не нашлось каталога с моделью')
    src = inner[0]

    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    for fn in ('encoder.int8.onnx', 'decoder.int8.onnx',
               'joiner.int8.onnx', 'tokens.txt'):
        s = os.path.join(src, fn)
        if not os.path.exists(s):
            raise RuntimeError('в архиве нет файла %s' % fn)
        shutil.move(s, os.path.join(target, fn))

    shutil.rmtree(unpack, ignore_errors=True)
    os.remove(tmp)


def fetch_all(progress=None, data_dir=DATA, force=False):
    """Скачать всё недостающее. Сбой = исключение наружу."""
    fetch_wheels(progress, data_dir, force)
    fetch_silero(progress, data_dir, force)
    fetch_parakeet(progress, data_dir, force)
