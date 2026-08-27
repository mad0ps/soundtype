# -*- coding: utf-8 -*-
"""Профили ASR-моделей и персист выбора пользователя.

Чистый модуль: без pyotherside и sherpa — его гоняют тесты на Mac.
settings.json пишется атомарно; неизвестное/битое значение молча
откатывается к DEFAULT, чтобы кривой файл не окирпичил диктовку.
"""
import json
import os

DEFAULT = 'parakeet'

REGISTRY = {
    'parakeet': {
        'dir': 'parakeet',
        'files': {'encoder': 'encoder.int8.onnx', 'decoder': 'decoder.int8.onnx',
                  'joiner': 'joiner.int8.onnx', 'tokens': 'tokens.txt'},
        'label': 'Мультиязычная (Parakeet v3)',
        'size': '≈0,5 ГБ',
    },
    'gigaam': {
        'dir': 'gigaam-e2e',
        'files': {'encoder': 'encoder.int8.onnx', 'decoder': 'decoder.onnx',
                  'joiner': 'joiner.onnx', 'tokens': 'tokens.txt'},
        'label': 'Русская (GigaAM-v3)',
        'size': '≈0,33 ГБ',
    },
}


def _settings_path(data_dir):
    return os.path.join(data_dir, 'settings.json')


def _read_settings(data_dir):
    try:
        with open(_settings_path(data_dir), encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get_active(data_dir):
    name = _read_settings(data_dir).get('model')
    return name if name in REGISTRY else DEFAULT


def set_active(name, data_dir):
    if name not in REGISTRY:
        raise ValueError('unknown model profile: %r' % name)
    data = _read_settings(data_dir)
    data['model'] = name
    os.makedirs(data_dir, exist_ok=True)
    tmp = _settings_path(data_dir) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, _settings_path(data_dir))


def model_dir(name, data_dir):
    return os.path.join(data_dir, 'models', REGISTRY[name]['dir'])


def model_files(name, data_dir):
    base = model_dir(name, data_dir)
    return {k: os.path.join(base, fn)
            for k, fn in REGISTRY[name]['files'].items()}


def probe_path(name, data_dir):
    return model_files(name, data_dir)['encoder']


def fallback_profile(active, data_dir):
    """Другой профиль, чья модель уже лежит на диске.

    Спасательный выход с оверлея закачки (#28): если выбранный профиль не
    скачан, а сети нет, пользователь возвращается сюда без трафика.
    """
    for name in REGISTRY:
        if name != active and os.path.exists(probe_path(name, data_dir)):
            return name
    return None
