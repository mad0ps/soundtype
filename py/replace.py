# -*- coding: utf-8 -*-
"""Пользовательский словарь пост-замен над финальным текстом диктовки.

Чистый модуль: без pyotherside и sherpa — гоняется тестами на любой машине.
Движок — одна combined-alternation регулярка (не цикл str.replace: тот цепляет
замены и не умеет whole-word). Правила: whole-word через lookaround, ключи
длинными-первыми (альтернация берёт первую, а не длиннейшую), ё↔е свёрнуты
только в паттерне, регистр совпадения переносится на замену, каждый литерал
экранируется. Один проход re.sub по исходному тексту.
"""
import json
import os
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


FILENAME = 'replacements.json'


def _path(data_dir):
    return os.path.join(data_dir, FILENAME)


def load(data_dir):
    """Список правил {id,heard,written,on}. Битый/отсутствующий файл -> []."""
    try:
        with open(_path(data_dir), encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    rules = data.get('rules') if isinstance(data, dict) else None
    if not isinstance(rules, list):
        return []
    out = []
    for r in rules:
        if isinstance(r, dict) and 'heard' in r and 'written' in r:
            out.append({'id': int(r.get('id', 0)),
                        'heard': str(r['heard']),
                        'written': str(r['written']),
                        'on': bool(r.get('on', True))})
    return out


def _save(rules, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    tmp = _path(data_dir) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump({'rules': rules}, fh, ensure_ascii=False)
    os.replace(tmp, _path(data_dir))


def add(heard, written, data_dir):
    rules = load(data_dir)
    new_id = (max((r['id'] for r in rules), default=0)) + 1
    rule = {'id': new_id, 'heard': heard, 'written': written, 'on': True}
    rules.append(rule)
    _save(rules, data_dir)
    return rule


def update(rule_id, heard, written, data_dir):
    rules = load(data_dir)
    for r in rules:
        if r['id'] == rule_id:
            r['heard'], r['written'] = heard, written
            _save(rules, data_dir)
            return True
    return False


def delete(rule_id, data_dir):
    rules = load(data_dir)
    kept = [r for r in rules if r['id'] != rule_id]
    if len(kept) == len(rules):
        return False
    _save(kept, data_dir)
    return True


def toggle(rule_id, on, data_dir):
    rules = load(data_dir)
    for r in rules:
        if r['id'] == rule_id:
            r['on'] = bool(on)
            _save(rules, data_dir)
            return True
    return False


def apply(text, data_dir):
    """Применяем включённые правила к тексту (позже добавленное heard побеждает)."""
    gloss = {}
    for r in load(data_dir):
        if r['on']:
            gloss[r['heard']] = r['written']
    return apply_text(text, gloss)


# Стартовый набор «разработка (RU)»: услышано(кириллица) -> записано.
# Алиасы уже развёрнуты в отдельные пары (движок работает по одиночным heard).
PACK_RU_TECH = [
    ('депло', 'deploy'), ('деплой', 'deploy'), ('задеплоить', 'deploy'),
    ('коммит', 'commit'), ('закоммитить', 'commit'),
    ('пуш', 'push'), ('запушить', 'push'),
    ('пул реквест', 'pull request'), ('пиар', 'pull request'),
    ('мёрдж', 'merge'), ('смёрджить', 'merge'),
    ('кубер', 'kubernetes'), ('кубернетес', 'kubernetes'),
    ('докер', 'docker'), ('редис', 'redis'),
    ('постгрес', 'postgres'), ('постгря', 'postgres'),
    ('кэш', 'cache'), ('эндпоинт', 'endpoint'),
    ('реквест', 'request'), ('респонс', 'response'),
    ('роллбэк', 'rollback'), ('откатить', 'rollback'),
    ('билд', 'build'), ('дебаг', 'debug'), ('дебажить', 'debug'),
    ('логи', 'logs'), ('таск', 'task'), ('ветка', 'branch'),
    ('код ревью', 'code review'),
]


def _norm(s):
    """Ключ для сравнения heard: регистр + ё->е."""
    return s.casefold().replace('ё', 'е')


def add_pack(data_dir):
    """Добавляем пары пака, чьих heard ещё нет (без учёта регистра/ё). -> сколько."""
    existing = {_norm(r['heard']) for r in load(data_dir)}
    added = 0
    for heard, written in PACK_RU_TECH:
        if _norm(heard) in existing:
            continue
        add(heard, written, data_dir)
        existing.add(_norm(heard))
        added += 1
    return added
