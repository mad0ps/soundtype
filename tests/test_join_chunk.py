# -*- coding: utf-8 -*-
from streaming import join_chunk


def test_dedupes_when_overlap_present():
    got = join_chunk('мы пошли в магазин', 'в магазин и купили',
                     gap=0.1, overlap=0.5, cap_pause=1.5)
    assert got == ' и купили'


def test_without_overlap_falls_back_to_glue():
    got = join_chunk('привет.', 'как дела', gap=0.2, overlap=0.0,
                     cap_pause=1.5)
    assert got == ' Как дела'


def test_overlap_without_match_uses_glue_rules():
    got = join_chunk('раз два', 'пять шесть', gap=2.0, overlap=0.5,
                     cap_pause=1.5)
    assert got == '. Пять шесть'


def test_all_duplicate_returns_empty():
    assert join_chunk('и вот мы решили', 'мы решили',
                      gap=0.1, overlap=0.5, cap_pause=1.5) == ''


def test_first_chunk_capitalized():
    assert join_chunk(None, 'привет', gap=None, overlap=0.0,
                      cap_pause=1.5) == 'Привет'
