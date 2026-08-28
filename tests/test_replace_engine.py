# -*- coding: utf-8 -*-
import replace


def ap(text, gloss):
    return replace.apply_text(text, gloss)


def test_whole_word_only_not_substring():
    assert ap('котёнок и кот', {'кот': 'cat'}) == 'котёнок и cat'


def test_case_insensitive_match():
    assert ap('депло готов', {'депло': 'deploy'}) == 'deploy готов'


def test_restore_leading_capital():
    assert ap('Депло готов', {'депло': 'deploy'}) == 'Deploy готов'


def test_restore_all_caps():
    assert ap('ДЕПЛО готов', {'депло': 'deploy'}) == 'DEPLOY готов'


def test_yo_folding_key_matches_both():
    assert ap('еще раз', {'ещё': 'again'}) == 'again раз'
    assert ap('ещё раз', {'ещё': 'again'}) == 'again раз'


def test_phrase_key_tolerates_whitespace():
    assert ap('моя облачная   функция', {'облачная функция': 'lambda'}) \
        == 'моя lambda'


def test_longest_match_first():
    g = {'функция': 'fn', 'облачная функция': 'lambda'}
    assert ap('облачная функция', g) == 'lambda'


def test_literal_key_with_regex_chars():
    assert ap('это c++ код', {'c++': 'cpp'}) == 'это cpp код'


def test_no_chaining_single_pass():
    # 'a'->'b' then 'b'->'c' must NOT cascade in one apply
    assert ap('a', {'a': 'b', 'b': 'c'}) == 'b'


def test_empty_glossary_noop():
    assert ap('текст без замен', {}) == 'текст без замен'


def test_digit_underscore_neighbor_not_matched():
    assert ap('кот3 кот_ кот', {'кот': 'cat'}) == 'кот3 кот_ cat'
