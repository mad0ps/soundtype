# -*- coding: utf-8 -*-
import pytest

import downloader


def test_missing_on_empty_dir(tmp_path):
    assert downloader.missing(str(tmp_path)) == [
        'numpy', 'sherpa-onnx', 'silero-vad', 'parakeet']


def test_missing_when_all_present(tmp_path):
    d = tmp_path
    (d / 'runtime' / 'pylibs' / 'numpy').mkdir(parents=True)
    (d / 'runtime' / 'pylibs' / 'sherpa_onnx').mkdir()
    (d / 'models' / 'parakeet').mkdir(parents=True)
    (d / 'models' / 'silero_vad.onnx').write_bytes(b'x')
    (d / 'models' / 'parakeet' / 'encoder.int8.onnx').write_bytes(b'x')
    assert downloader.missing(str(d)) == []


def test_fetch_all_runs_stages_in_order(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(downloader, 'fetch_wheels',
                        lambda p, d, f: calls.append('wheels'))
    monkeypatch.setattr(downloader, 'fetch_silero',
                        lambda p, d, f: calls.append('silero'))
    monkeypatch.setattr(downloader, 'fetch_parakeet',
                        lambda p, d, f: calls.append('parakeet'))
    downloader.fetch_all(None, str(tmp_path))
    assert calls == ['wheels', 'silero', 'parakeet']


def test_fetch_error_bubbles_up(tmp_path, monkeypatch):
    def boom(url, dest=None, progress=None, stage=''):
        raise OSError('нет сети')
    monkeypatch.setattr(downloader, 'download', boom)
    with pytest.raises(OSError):
        downloader.fetch_all(None, str(tmp_path))
