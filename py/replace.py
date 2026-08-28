# -*- coding: utf-8 -*-
"""Пользовательский словарь пост-замен над финальным текстом диктовки.

Чистый модуль: без pyotherside и sherpa — гоняется тестами на любой машине.
Движок — одна combined-alternation регулярка (не цикл str.replace: тот цепляет
замены и не умеет whole-word). Правила: whole-word через lookaround, ключи
длинными-первыми (альтернация берёт первую, а не длиннейшую), ё↔е свёрнуты
только в паттерне, регистр совпадения переносится на замену, каждый литерал
экранируется. Один проход re.sub по исходному тексту.
"""
import re


def _yo(key):
    """Ключ -> паттерн: е/ё сворачиваем в [еёЕЁ], остальное экранируем."""
    return ''.join('[еёЕЁ]' if ch in 'еёЕЁ' else re.escape(ch) for ch in key)


def _phrase(key):
    """Многословный ключ: между словами — любой пробел (в т.ч. перенос)."""
    return r'\s+'.join(_yo(w) for w in key.split())


def _restore_case(matched, repl):
    """Переносим регистр совпадения на замену: ВЕСЬ верхний / Первая / как есть."""
    if len(matched) > 1 and matched.isupper():
        return repl.upper()
    if matched[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def build(glossary):
    """Из {heard: written} собираем функцию замены. Пустой словарь -> identity."""
    keys = [k for k in sorted(glossary, key=len, reverse=True) if k.strip()]
    if not keys:
        return lambda text: text
    alts = '|'.join('(?P<g%d>%s)' % (i, _phrase(k)) for i, k in enumerate(keys))
    rx = re.compile(r'(?<!\w)(?:%s)(?!\w)' % alts, re.IGNORECASE)
    repl = {'g%d' % i: glossary[k] for i, k in enumerate(keys)}

    def run(text):
        return rx.sub(lambda m: _restore_case(m.group(0), repl[m.lastgroup]), text)
    return run


def apply_text(text, glossary):
    """Разовое применение словаря к тексту."""
    if not glossary or not text:
        return text
    return build(glossary)(text)
