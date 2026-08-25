# -*- coding: utf-8 -*-
from eval.boundary import attribute, collapse_ratio


def test_clean_junction_not_flagged():
    r = attribute('раз два три четыре пять шесть',
                  ['раз два три', 'четыре пять шесть'])
    assert r['junctions'] == 1 and r['damaged'] == 0 and r['ops'] == 0


def test_substitution_at_junction_flagged():
    r = attribute('раз два три четыре пять шесть',
                  ['раз два три', 'читыре пять шесть'])
    assert r['junctions'] == 1 and r['damaged'] == 1
    assert r['ops'] == 1 and r['ops_junction'] == 1


def test_mid_segment_error_not_attributed_to_junction():
    # ошибка на 2-м слове, стык после 5-го: вне окна ±2 от стыка
    r = attribute('раз два три четыре пять шесть семь восемь девять',
                  ['раз двас три четыре пять', 'шесть семь восемь девять'])
    assert r['damaged'] == 0 and r['ops'] == 1 and r['ops_junction'] == 0


def test_collapse_ratio():
    assert collapse_ratio('раз два', ['раз два три четыре']) == 0.5
