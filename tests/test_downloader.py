# -*- coding: utf-8 -*-
import io
import os
import tarfile

import pytest

import downloader


def test_missing_on_empty_dir(tmp_path):
    assert downloader.missing(str(tmp_path)) == [
        'numpy', 'sherpa-onnx', 'sherpa-onnx-core', 'silero-vad', 'parakeet']


def test_missing_when_all_present(tmp_path):
    d = tmp_path
    (d / 'runtime' / 'pylibs' / 'numpy').mkdir(parents=True)
    (d / 'runtime' / 'pylibs' / 'numpy' / 'version.py').write_bytes(b'x')
    lib = d / 'runtime' / 'pylibs' / 'sherpa_onnx' / 'lib'
    lib.mkdir(parents=True)
    (lib / '_sherpa_onnx.cpython-312-aarch64-linux-gnu.so').write_bytes(b'x')
    (lib / 'libonnxruntime.so').write_bytes(b'x')
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


def test_missing_includes_core_wheel(tmp_path):
    # sherpa-onnx-core кладёт libonnxruntime.so поверх дерева sherpa_onnx —
    # без него движок не стартует (ImportError на телефоне, 2026-08-21).
    d = tmp_path
    (d / 'runtime' / 'pylibs' / 'numpy').mkdir(parents=True)
    (d / 'runtime' / 'pylibs' / 'numpy' / 'version.py').write_bytes(b'x')
    lib = d / 'runtime' / 'pylibs' / 'sherpa_onnx' / 'lib'
    lib.mkdir(parents=True)
    (lib / '_sherpa_onnx.cpython-312-aarch64-linux-gnu.so').write_bytes(b'x')
    (d / 'models' / 'parakeet').mkdir(parents=True)
    (d / 'models' / 'silero_vad.onnx').write_bytes(b'x')
    (d / 'models' / 'parakeet' / 'encoder.int8.onnx').write_bytes(b'x')
    assert downloader.missing(str(d)) == ['sherpa-onnx-core']
    (lib / 'libonnxruntime.so').write_bytes(b'x')
    assert downloader.missing(str(d)) == []


def test_wheel_merge_does_not_replace_existing_tree(tmp_path, monkeypatch):
    # Второе колесо (core) распаковывается в тот же каталог sherpa_onnx,
    # что и первое — перенос обязан СЛИВАТЬ деревья, а не сносить старое.
    import io
    import json
    import zipfile as zf_mod

    def fake_wheel(files):
        buf = io.BytesIO()
        with zf_mod.ZipFile(buf, 'w') as z:
            for name, data in files:
                z.writestr(name, data)
        return buf.getvalue()

    wheels = {
        'sherpa-onnx': fake_wheel([
            ('sherpa_onnx/__init__.py', b'init'),
            ('sherpa_onnx/lib/_sherpa_onnx.cpython-312-aarch64-linux-gnu.so',
             b'so'),
        ]),
        'sherpa-onnx-core': fake_wheel([
            ('sherpa_onnx/lib/libonnxruntime.so', b'ort'),
        ]),
    }

    def fake_download(url, dest=None, progress=None, stage=''):
        if 'pypi.org' in url:
            for pkg in wheels:
                if '/%s/' % pkg in url:
                    tags = {w[0]: w[2] for w in downloader.WHEELS}
                    return json.dumps({'urls': [
                        {'filename': '%s-x-%s.whl' % (pkg, tags[pkg]),
                         'url': pkg}
                    ]}).encode('utf-8')
            raise AssertionError('unexpected meta url %s' % url)
        return wheels[url]

    monkeypatch.setattr(downloader, 'download', fake_download)
    monkeypatch.setattr(downloader, 'WHEELS', [
        w for w in downloader.WHEELS if w[0] != 'numpy'])

    downloader.fetch_wheels(None, str(tmp_path))

    lib = tmp_path / 'runtime' / 'pylibs' / 'sherpa_onnx' / 'lib'
    assert (lib / '_sherpa_onnx.cpython-312-aarch64-linux-gnu.so').exists()
    assert (lib / 'libonnxruntime.so').exists()
    assert (tmp_path / 'runtime' / 'pylibs' / 'sherpa_onnx'
            / '__init__.py').exists()


def test_missing_is_profile_aware(tmp_path, monkeypatch):
    import downloader, models
    d = str(tmp_path)
    # wheels+silero present so only the model entry differs
    for pkg, _v, _t, probe in downloader.WHEELS:
        p = os.path.join(d, 'runtime', 'pylibs', probe)
        os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'w').close()
    os.makedirs(os.path.join(d, 'models'), exist_ok=True)
    open(os.path.join(d, 'models', 'silero_vad.onnx'), 'w').close()

    assert downloader.missing(d, model='gigaam') == ['gigaam']
    assert downloader.missing(d, model='parakeet') == ['parakeet']
    # active profile is used when model=None
    models.set_active('gigaam', d)
    assert downloader.missing(d) == ['gigaam']
    # place the gigaam probe -> clean
    ep = models.probe_path('gigaam', d)
    os.makedirs(os.path.dirname(ep), exist_ok=True); open(ep, 'w').close()
    assert downloader.missing(d) == []


def test_fetch_gigaam_downloads_encoder_last(tmp_path, monkeypatch):
    import downloader, models
    d = str(tmp_path)
    calls = []

    def fake_download(url, dest=None, progress=None, stage=''):
        calls.append(url)
        open(dest, 'wb').write(b'x')
        return dest

    monkeypatch.setattr(downloader, 'download', fake_download)
    downloader.fetch_gigaam(data_dir=d)
    files = models.model_files('gigaam', d)
    for path in files.values():
        assert os.path.exists(path)
    assert 'encoder_int8' in calls[-1]  # encoder queued last
    # idempotent: second run downloads nothing
    calls.clear()
    downloader.fetch_gigaam(data_dir=d)
    assert calls == []


def test_fetch_gigaam_force_redownloads(tmp_path, monkeypatch):
    import downloader, models
    d = str(tmp_path)
    calls = []

    def fake_download(url, dest=None, progress=None, stage=''):
        calls.append(url); open(dest, 'wb').write(b'x'); return dest

    monkeypatch.setattr(downloader, 'download', fake_download)
    downloader.fetch_gigaam(data_dir=d)
    n_first = len(calls)
    downloader.fetch_gigaam(data_dir=d, force=True)
    assert len(calls) == n_first * 2


def test_fetch_all_downloads_active_profile(tmp_path, monkeypatch):
    import downloader, models
    d = str(tmp_path)
    models.set_active('gigaam', d)
    got = []
    monkeypatch.setattr(downloader, 'fetch_wheels', lambda *a, **k: None)
    monkeypatch.setattr(downloader, 'fetch_silero', lambda *a, **k: None)
    monkeypatch.setattr(downloader, 'fetch_model',
                        lambda name, *a, **k: got.append(name))
    downloader.fetch_all(data_dir=d)
    assert got == ['gigaam']


def test_fetch_model_dispatch(monkeypatch, tmp_path):
    import downloader
    hit = []
    monkeypatch.setattr(downloader, 'fetch_parakeet', lambda p, d, f: hit.append('p'))
    monkeypatch.setattr(downloader, 'fetch_gigaam', lambda p, d, f: hit.append('g'))
    downloader.fetch_model('parakeet', data_dir=str(tmp_path))
    downloader.fetch_model('gigaam', data_dir=str(tmp_path))
    assert hit == ['p', 'g']
