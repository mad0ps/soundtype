# -*- coding: utf-8 -*-
from streaming import merge_overlap


def test_drops_duplicated_prefix():
    got, m = merge_overlap('мы пошли в магазин', 'в магазин и купили хлеб')
    assert m and got == 'и купили хлеб'


def test_normalized_match_keeps_original_tokens():
    got, m = merge_overlap('Смотри, программа работает',
                           'Программа работает! отлично')
    assert m and got == 'отлично'


def test_single_token_match_not_merged():
    got, m = merge_overlap('раз два три', 'три четыре пять')
    assert not m and got == 'три четыре пять'


def test_match_must_touch_prev_tail():
    # «в магазин» встречается в prev, но далеко от хвоста — это не дубль
    got, m = merge_overlap('в магазин мы не пошли а поехали',
                           'в магазин на машине')
    assert not m and got == 'в магазин на машине'


def test_full_duplicate_drops_everything():
    got, m = merge_overlap('и вот тогда мы решили', 'мы решили')
    assert m and got == ''


def test_empty_inputs_untouched():
    assert merge_overlap('', 'текст') == ('текст', False)
    assert merge_overlap('текст', '') == ('', False)
    assert merge_overlap(None, 'текст') == ('текст', False)
