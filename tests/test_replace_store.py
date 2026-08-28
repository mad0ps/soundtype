# -*- coding: utf-8 -*-
import json
import os

import replace


def test_load_missing_file_returns_empty(tmp_path):
    assert replace.load(str(tmp_path)) == []


def test_load_corrupt_file_returns_empty(tmp_path):
    open(os.path.join(str(tmp_path), 'replacements.json'), 'w').write('{bad')
    assert replace.load(str(tmp_path)) == []


def test_add_persists_and_assigns_ids(tmp_path):
    d = str(tmp_path)
    r1 = replace.add('депло', 'deploy', d)
    r2 = replace.add('кубер', 'k8s', d)
    assert r1['id'] != r2['id']
    assert r1['heard'] == 'депло' and r1['on'] is True
    rules = replace.load(d)
    assert [r['heard'] for r in rules] == ['депло', 'кубер']
    # атомарная запись оставила валидный JSON
    json.load(open(os.path.join(d, 'replacements.json')))


def test_update_delete_toggle(tmp_path):
    d = str(tmp_path)
    r = replace.add('депло', 'deploy', d)
    assert replace.update(r['id'], 'депло', 'DEPLOY', d) is True
    assert replace.load(d)[0]['written'] == 'DEPLOY'
    assert replace.toggle(r['id'], False, d) is True
    assert replace.load(d)[0]['on'] is False
    assert replace.delete(r['id'], d) is True
    assert replace.load(d) == []
    assert replace.update(999, 'x', 'y', d) is False


def test_apply_uses_only_enabled(tmp_path):
    d = str(tmp_path)
    r = replace.add('депло', 'deploy', d)
    assert replace.apply('депло готов', d) == 'deploy готов'
    replace.toggle(r['id'], False, d)
    assert replace.apply('депло готов', d) == 'депло готов'


def test_apply_no_rules_noop(tmp_path):
    assert replace.apply('просто текст', str(tmp_path)) == 'просто текст'
