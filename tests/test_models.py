# -*- coding: utf-8 -*-
import json, os
import models


def test_registry_shape():
    assert set(models.REGISTRY) == {'parakeet', 'gigaam'}
    for name, spec in models.REGISTRY.items():
        assert set(spec['files']) == {'encoder', 'decoder', 'joiner', 'tokens'}
        assert spec['dir'] and spec['label']


def test_get_active_default_when_no_file(tmp_path):
    assert models.get_active(str(tmp_path)) == 'parakeet'


def test_set_then_get_roundtrip(tmp_path):
    models.set_active('gigaam', str(tmp_path))
    assert models.get_active(str(tmp_path)) == 'gigaam'
    raw = json.load(open(tmp_path / 'settings.json'))
    assert raw['model'] == 'gigaam'


def test_set_preserves_other_keys(tmp_path):
    (tmp_path / 'settings.json').write_text(json.dumps({'other': 1, 'model': 'parakeet'}))
    models.set_active('gigaam', str(tmp_path))
    raw = json.load(open(tmp_path / 'settings.json'))
    assert raw == {'other': 1, 'model': 'gigaam'}


def test_get_active_falls_back_on_garbage(tmp_path):
    (tmp_path / 'settings.json').write_text('{broken')
    assert models.get_active(str(tmp_path)) == 'parakeet'
    (tmp_path / 'settings.json').write_text(json.dumps({'model': 'nosuch'}))
    assert models.get_active(str(tmp_path)) == 'parakeet'


def test_set_unknown_raises(tmp_path):
    try:
        models.set_active('nosuch', str(tmp_path))
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_set_leaves_no_tmp_file(tmp_path):
    models.set_active('gigaam', str(tmp_path))
    assert not (tmp_path / 'settings.json.tmp').exists()


def test_paths(tmp_path):
    d = str(tmp_path)
    files = models.model_files('gigaam', d)
    assert files['encoder'] == os.path.join(d, 'models', 'gigaam-e2e', 'encoder.int8.onnx')
    assert files['decoder'].endswith('gigaam-e2e/decoder.onnx')
    assert models.probe_path('parakeet', d).endswith('parakeet/encoder.int8.onnx')
