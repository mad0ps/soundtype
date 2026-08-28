# -*- coding: utf-8 -*-
import backend
import replace


def test_transcribe_applies_replacements(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', str(tmp_path))
    replace.add('депло', 'deploy', str(tmp_path))
    d = backend.Dictation()
    # обходим декод: подсовываем сегменты как готовый текст
    monkeypatch.setattr(d, '_split', lambda pcm: [
        type('P', (), {'samples': b'', 'speech_len': 99999, 'gap': None,
                       'overlap': 0.0})()])
    monkeypatch.setattr(d, '_decode', lambda samples: 'депло готов')
    d.np = __import__('numpy')
    out = d._transcribe(b'\x00\x00' * 16000)
    # первая фраза капитализируется join_chunk («Депло»), замена переносит
    # заглавную на результат → «Deploy готов»
    assert out == 'Deploy готов'


def test_replacements_wrappers_crud(tmp_path, monkeypatch, events):
    monkeypatch.setattr(backend, 'DATA', str(tmp_path))
    backend.replacements_add('депло', 'deploy')
    rules = backend.replacements_list()
    assert rules[0]['heard'] == 'депло'
    rid = rules[0]['id']
    backend.replacements_toggle(rid, False)
    assert backend.replacements_list()[0]['on'] is False
    backend.replacements_update(rid, 'депло', 'DEPLOY')
    assert backend.replacements_list()[0]['written'] == 'DEPLOY'
    backend.replacements_delete(rid)
    assert backend.replacements_list() == []
    # каждое изменение эмитит актуальный список
    assert any(e[0] == 'replacements' for e in events)


def test_replacements_add_pack(tmp_path, monkeypatch, events):
    monkeypatch.setattr(backend, 'DATA', str(tmp_path))
    backend.replacements_add_pack()
    assert len(backend.replacements_list()) == len(replace.PACK_RU_TECH)
