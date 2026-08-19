#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Докачивает всё, что не помещается в git: модель и python-библиотеки.

Кладёт их в каталог данных приложения:

    ~/.local/share/soundtype.n0madd3v0ps/
        models/parakeet/{encoder,decoder,joiner}.int8.onnx, tokens.txt
        models/silero_vad.onnx
        runtime/pylibs/{numpy,sherpa_onnx,...}

Качается около 500 МБ, в распакованном виде примерно 700 МБ.
pip не нужен: колёса — это обычные zip-архивы, распаковываем сами.

    python3 scripts/fetch-deps.py
    python3 scripts/fetch-deps.py --force   # перекачать заново
"""

import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile

APP = 'soundtype.n0madd3v0ps'
HOME = os.environ.get('HOME', os.path.expanduser('~'))
DATA = os.path.join(HOME, '.local', 'share', APP)
MODELS = os.path.join(DATA, 'models')
PYLIBS = os.path.join(DATA, 'runtime', 'pylibs')

PARAKEET_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
                'asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2')
SILERO_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
              'asr-models/silero_vad.onnx')

# Колёса под Python 3.8 / aarch64 — ровно то, что стоит в Ubuntu Touch 20.04.
WHEELS = [
    ('numpy', '1.24.4', 'cp38-cp38-manylinux_2_17_aarch64'),
    ('sherpa-onnx', '1.13.6', 'cp38-cp38-manylinux2014_aarch64'),
]

FORCE = '--force' in sys.argv
UA = {'User-Agent': 'soundtype-fetch-deps'}


def human(n):
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if n < 1024:
            return '%.0f %s' % (n, unit)
        n /= 1024.0
    return '%.1f ТБ' % n


def download(url, dest=None):
    """Качаем с показом прогресса. Возвращаем путь либо содержимое."""
    name = url.split('/')[-1]
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get('Content-Length') or 0)
        buf = open(dest, 'wb') if dest else io.BytesIO()
        got = 0
        try:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                buf.write(chunk)
                got += len(chunk)
                if total:
                    sys.stdout.write('\r  %s  %5.1f%%  (%s)'
                                     % (name, got * 100.0 / total, human(got)))
                else:
                    sys.stdout.write('\r  %s  %s' % (name, human(got)))
                sys.stdout.flush()
            sys.stdout.write('\n')
            if dest:
                return dest
            return buf.getvalue()
        finally:
            if dest:
                buf.close()


def fetch_parakeet():
    target = os.path.join(MODELS, 'parakeet')
    if os.path.exists(os.path.join(target, 'encoder.int8.onnx')) and not FORCE:
        print('Модель Parakeet уже на месте, пропускаю.')
        return
    print('Качаю модель Parakeet (около 490 МБ)…')
    tmp = os.path.join(MODELS, '_parakeet.tar.bz2')
    download(PARAKEET_URL, tmp)

    print('Распаковываю…')
    unpack = os.path.join(MODELS, '_unpack')
    shutil.rmtree(unpack, ignore_errors=True)
    os.makedirs(unpack)
    with tarfile.open(tmp, 'r:bz2') as tf:
        tf.extractall(unpack)

    # Внутри архива один каталог — забираем из него нужные файлы.
    inner = [os.path.join(unpack, d) for d in os.listdir(unpack)]
    inner = [d for d in inner if os.path.isdir(d)]
    if not inner:
        raise SystemExit('В архиве не нашлось каталога с моделью')
    src = inner[0]

    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    need = ['encoder.int8.onnx', 'decoder.int8.onnx',
            'joiner.int8.onnx', 'tokens.txt']
    for fn in need:
        s = os.path.join(src, fn)
        if not os.path.exists(s):
            raise SystemExit('В архиве нет файла %s' % fn)
        shutil.move(s, os.path.join(target, fn))

    shutil.rmtree(unpack, ignore_errors=True)
    os.remove(tmp)
    print('Модель готова:', target)


def fetch_silero():
    dest = os.path.join(MODELS, 'silero_vad.onnx')
    if os.path.exists(dest) and not FORCE:
        print('Детектор тишины уже на месте, пропускаю.')
        return
    print('Качаю детектор тишины silero…')
    download(SILERO_URL, dest)


def fetch_wheels():
    os.makedirs(PYLIBS, exist_ok=True)
    for pkg, ver, tag in WHEELS:
        probe = os.path.join(PYLIBS, pkg.replace('-', '_'))
        if os.path.exists(probe) and not FORCE:
            print('%s уже распакован, пропускаю.' % pkg)
            continue
        meta = json.loads(download(
            'https://pypi.org/pypi/%s/%s/json' % (pkg, ver)).decode('utf-8'))
        url = None
        for f in meta['urls']:
            if tag in f['filename']:
                url = f['url']
                break
        if not url:
            raise SystemExit('Не нашёл колесо %s %s (%s)' % (pkg, ver, tag))
        print('Качаю %s %s…' % (pkg, ver))
        blob = download(url)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(PYLIBS)
        print('  распакован в', PYLIBS)


def main():
    os.makedirs(MODELS, exist_ok=True)
    os.makedirs(PYLIBS, exist_ok=True)
    print('Каталог данных:', DATA)
    print()
    fetch_wheels()
    fetch_silero()
    fetch_parakeet()
    print()
    print('Готово. Теперь можно собирать:  ./scripts/build.sh')


if __name__ == '__main__':
    main()
