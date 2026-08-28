# -*- coding: utf-8 -*-
import replace


def test_add_pack_populates(tmp_path):
    d = str(tmp_path)
    n = replace.add_pack(d)
    assert n == len(replace.PACK_RU_TECH)
    heards = {r['heard'] for r in replace.load(d)}
    assert 'депло' in heards and 'коммит' in heards


def test_add_pack_idempotent(tmp_path):
    d = str(tmp_path)
    replace.add_pack(d)
    added_second = replace.add_pack(d)
    assert added_second == 0
    # длина не удвоилась
    assert len(replace.load(d)) == len(replace.PACK_RU_TECH)


def test_add_pack_skips_existing_case_yo_insensitive(tmp_path):
    d = str(tmp_path)
    replace.add('Депло', 'deploy', d)          # уже есть, иным регистром
    n = replace.add_pack(d)
    assert n == len(replace.PACK_RU_TECH) - 1   # 'депло' из пака пропущен
