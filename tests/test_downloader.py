# -*- coding: utf-8 -*-
import io
import tarfile

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


def test_parakeet_partial_failure_stays_retryable(tmp_path, monkeypatch):
    """Incomplete extraction must not mark parakeet as present."""
    # Create fake tar.bz2 with only encoder.int8.onnx (missing decoder, etc)
    fake_tar_buf = io.BytesIO()
    with tarfile.open(fileobj=fake_tar_buf, mode='w:bz2') as tf:
        inner_dir = tmp_path / '_fake_model'
        inner_dir.mkdir()
        encoder_file = inner_dir / 'encoder.int8.onnx'
        encoder_file.write_bytes(b'fake_encoder')
        tf.add(str(inner_dir), arcname='fake-model-dir')
    fake_tar_content = fake_tar_buf.getvalue()

    # Monkeypatch download to write the fake tar instead of fetching real one
    def fake_download(url, dest=None, progress=None, stage=''):
        if dest:
            with open(dest, 'wb') as f:
                f.write(fake_tar_content)
            return dest
        return fake_tar_content

    monkeypatch.setattr(downloader, 'download', fake_download)

    # fetch_parakeet should fail (decoder is first in new order, missing)
    with pytest.raises(RuntimeError, match='в архиве нет файла decoder'):
        downloader.fetch_parakeet(None, str(tmp_path))

    # Verify parakeet still marked as missing (encoder was not moved)
    assert 'parakeet' in downloader.missing(str(tmp_path))


def test_silero_partial_download_stays_retryable(tmp_path, monkeypatch):
    """C1: обрыв связи посреди скачивания не должен оставлять готовый файл."""
    def flaky_download(url, dest=None, progress=None, stage=''):
        # Пишем только .part (как это делает настоящий download при обрыве
        # соединения на середине), а затем падаем — до os.replace дело не
        # доходит.
        with open(dest, 'wb') as f:
            f.write(b'oops-not-the-whole-model')
        raise OSError('соединение оборвалось')

    monkeypatch.setattr(downloader, 'download', flaky_download)

    with pytest.raises(OSError):
        downloader.fetch_silero(None, str(tmp_path))

    final = tmp_path / 'models' / 'silero_vad.onnx'
    assert not final.exists()
    assert 'silero-vad' in downloader.missing(str(tmp_path))
