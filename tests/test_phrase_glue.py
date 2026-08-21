# -*- coding: utf-8 -*-
from streaming import phrase_glue, capitalize_first


def test_first_phrase_capitalized_no_glue():
    assert phrase_glue(None, None, 1.5) == ('', True)


def test_after_sentence_end_space_and_cap():
    assert phrase_glue('Привет.', 0.2, 1.5) == (' ', True)
    assert phrase_glue('Как дела?', None, 1.5) == (' ', True)


def test_short_pause_keeps_model_case():
    assert phrase_glue('привет', 0.2, 1.5) == (' ', False)
    assert phrase_glue('привет', None, 1.5) == (' ', False)


def test_long_pause_adds_period_and_cap():
    assert phrase_glue('привет', 2.0, 1.5) == ('. ', True)


def test_capitalize_first():
    assert capitalize_first('привет мир') == 'Привет мир'
    assert capitalize_first('«привет»') == '«Привет»'
    assert capitalize_first('123 и точка') == '123 И точка'
    assert capitalize_first('') == ''
