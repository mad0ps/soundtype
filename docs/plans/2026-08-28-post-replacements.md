# Post-processing replacements module (#8) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user glossary that rewrites final dictation text by whole-word rules
(«депло»→«deploy»), editable in Settings and one-tap-addable from history.

**Architecture:** A pure stdlib-`re` matching engine + JSON storage in
`py/replace.py` (host-testable, no pyotherside/sherpa). `apply()` runs once over
the final text in both `Dictation._transcribe` (retry) and `Dictation._session`
(live). Backend exposes `replacements_*` wrappers to QML; QML adds a Settings
glossary screen and a long-press "add replacement" from the history list.

**Tech Stack:** Python 3.12 stdlib (`re`, `json`, `os`), pyotherside, Lomiri
UITK QML.

**Spec:** `docs/research/2026-08-28-post-replacements.md`

## Global Constraints

- **stdlib `re` only — NO new bundled dependency.** Cyrillic `\b`/`IGNORECASE`
  are Unicode-aware for `str` on the target Python 3.12.3 (measured).
- `py/replace.py` is a **pure module** (no `import pyotherside`, no sherpa) so it
  runs under host pytest, exactly like `py/models.py`. Russian docstrings, English
  identifiers — match `py/models.py` / `py/backend.py` style.
- **Storage:** `replacements.json` in the app data dir, **atomic write**
  (`.tmp` + `os.replace`), **graceful fallback** to empty on a missing/corrupt
  file — same discipline as `models.py` settings.
- **Matching engine (locked):** one combined-alternation regex; keys sorted
  **longest-first**; whole-word via `(?<!\w)…(?!\w)`; `re.IGNORECASE` +
  `restore_case`; ё/е folded **only in the pattern** as `[еёЕЁ]`; `re.escape`
  every literal; phrase keys joined with `\s+`; **single `re.sub` pass** (no
  chaining).
- **Scope:** MVP applies replacements to text dictated **in the app** (final
  text + history). **Keyboard-streaming mode is OUT of scope** (separate later
  step — it lives in the daemon/keyboard patch).
- **No inflection tolerance in MVP** (exact whole-word match); it is a documented
  later opt-in per the spec.
- Rules are `{"id": int, "heard": str, "written": str, "on": bool}`. Dedup at
  apply-time by normalized `heard` (last enabled rule wins).

---

### Task 1: Matching engine (pure)

**Files:**
- Create: `py/replace.py`
- Test: `tests/test_replace_engine.py`

**Interfaces:**
- Produces: `build(glossary: dict[str, str]) -> Callable[[str], str]` — compiles a
  replacer from a `{heard: written}` dict; returns identity behavior for an empty
  dict. `apply_text(text: str, glossary: dict[str, str]) -> str` — convenience
  wrapper (`build(glossary)(text)`), returns `text` unchanged if glossary empty.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_replace_engine.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replace_engine.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'replace'` / attributes missing).

- [ ] **Step 3: Write the engine**

```python
# py/replace.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_replace_engine.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add py/replace.py tests/test_replace_engine.py
git commit -m "feat(replace): whole-word Cyrillic glossary matching engine (#8)"
```

---

### Task 2: Storage + CRUD + apply(data_dir)

**Files:**
- Modify: `py/replace.py`
- Test: `tests/test_replace_store.py`

**Interfaces:**
- Consumes: `build`, `apply_text` (Task 1).
- Produces:
  - `load(data_dir) -> list[dict]` — rules `{id,heard,written,on}`; `[]` on
    missing/corrupt file.
  - `add(heard, written, data_dir) -> dict` — new rule with fresh int `id`,
    `on=True`; persists; returns the rule.
  - `update(rule_id, heard, written, data_dir) -> bool`
  - `delete(rule_id, data_dir) -> bool`
  - `toggle(rule_id, on, data_dir) -> bool`
  - `apply(text, data_dir) -> str` — loads rules, builds `{heard: written}` from
    enabled ones (later rule wins on duplicate heard), applies; returns `text`
    unchanged when no enabled rules.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_replace_store.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replace_store.py -q`
Expected: FAIL (`AttributeError: module 'replace' has no attribute 'load'`).

- [ ] **Step 3: Implement storage + CRUD + apply**

```python
# append to py/replace.py
import json
import os

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_replace_store.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add py/replace.py tests/test_replace_store.py
git commit -m "feat(replace): JSON storage, CRUD and apply(data_dir) (#8)"
```

---

### Task 3: RU-tech seed pack

**Files:**
- Modify: `py/replace.py`
- Test: `tests/test_replace_pack.py`

**Interfaces:**
- Consumes: `load`, `add` (Task 2).
- Produces: `PACK_RU_TECH: list[tuple[str, str]]` (aliases pre-expanded to single
  pairs); `add_pack(data_dir) -> int` — appends pack pairs whose `heard` is not
  already present (case/ё-insensitive), returns count added; idempotent.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_replace_pack.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_replace_pack.py -q`
Expected: FAIL (`AttributeError: ... 'PACK_RU_TECH'`).

- [ ] **Step 3: Implement the pack**

```python
# append to py/replace.py

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_replace_pack.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add py/replace.py tests/test_replace_pack.py
git commit -m "feat(replace): toggleable RU-tech starter pack (#8)"
```

---

### Task 4: Backend integration (apply on final text + QML wrappers)

**Files:**
- Modify: `py/backend.py` (import `replace`; wrap final text in `_transcribe` and
  `_session`; add module-level `replacements_*` functions near `history_list`).
- Test: `tests/test_backend_replace.py`

**Interfaces:**
- Consumes: `replace.apply`, `replace.load/add/update/delete/toggle/add_pack`.
- Produces (module-level, called from QML via `py.call`):
  - `replacements_list()` -> `emit('replacements', rules)` and returns `rules`
  - `replacements_add(heard, written)`, `replacements_update(id, heard, written)`,
    `replacements_delete(id)`, `replacements_toggle(id, on)`,
    `replacements_add_pack()` — each persists then `emit('replacements', rules)`.
- Final dictation text passes through `replace.apply(text, DATA)` in both paths.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backend_replace.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backend_replace.py -q`
Expected: FAIL (`AttributeError: module 'backend' has no attribute 'replacements_add'`).

- [ ] **Step 3: Wire the backend**

Add the import near the other `py/` imports at the top of `py/backend.py`:

```python
import replace
```

In `Dictation._transcribe`, change the final return:

```python
        return replace.apply(''.join(texts).strip(), DATA)
```

In `Dictation._session`, right after `full = worker.close(timeout=180)`:

```python
            full = worker.close(timeout=180)
            full = replace.apply(full, DATA)
            emit('transcribing', False)
```

Add module-level wrappers next to `history_list` / `history_clear`:

```python
def _emit_replacements():
    rules = replace.load(DATA)
    emit('replacements', rules)
    return rules


def replacements_list():
    return _emit_replacements()


def replacements_add(heard, written):
    replace.add(heard, written, DATA)
    return _emit_replacements()


def replacements_update(rule_id, heard, written):
    replace.update(int(rule_id), heard, written, DATA)
    return _emit_replacements()


def replacements_delete(rule_id):
    replace.delete(int(rule_id), DATA)
    return _emit_replacements()


def replacements_toggle(rule_id, on):
    replace.toggle(int(rule_id), bool(on), DATA)
    return _emit_replacements()


def replacements_add_pack():
    replace.add_pack(DATA)
    return _emit_replacements()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backend_replace.py tests/ -q`
Expected: PASS (all — new + existing 110 regression stays green).

- [ ] **Step 5: Commit**

```bash
git add py/backend.py tests/test_backend_replace.py
git commit -m "feat(backend): apply replacements on final text + QML wrappers (#8)"
```

---

### Task 5: Settings glossary screen (QML)

**Files:**
- Modify: `qml/Main.qml` (a `replacementsPage` Page pushed from a Settings row;
  a `ListModel` fed by the `replacements` handler; an add/edit Dialog).

**Interfaces:**
- Consumes: `backend.replacements_list/add/update/delete/toggle/add_pack`; the
  `replacements` pyotherside signal → fills the model.

- [ ] **Step 1: Add the `replacements` handler + model**

In the `Python { Component.onCompleted: { … } }` block, alongside the other
`setHandler(...)` calls:

```qml
setHandler("replacements", function (rules) {
    replacementsModel.clear();
    for (var i = 0; i < rules.length; i++)
        replacementsModel.append({
            rid: rules[i].id, heard: rules[i].heard,
            written: rules[i].written, on: rules[i].on
        });
});
```

Near `ListModel { id: historyModel }` add:

```qml
ListModel { id: replacementsModel }
```

- [ ] **Step 2: Add the Settings entry point**

In the settings column, below the model selector block, add a row that opens the
page and loads data:

```qml
Button {
    text: "Замены текста"
    Layout.fillWidth: true
    onClicked: {
        stack.push(replacementsPage);
        py.call("backend.replacements_list", []);
    }
}
```

- [ ] **Step 3: Add the `replacementsPage` with list + add/edit dialog**

Add near `historyPage`:

```qml
Page {
    id: replacementsPage
    visible: false
    header: PageHeader {
        title: "Замены текста"
        trailingActionBar.actions: [
            Action {
                iconName: "add"
                text: "Добавить"
                onTriggered: PopupUtils.open(ruleDialog, null, {rid: -1, heard: "", written: ""})
            },
            Action {
                iconName: "compose"
                text: "Набор RU"
                onTriggered: py.call("backend.replacements_add_pack", [])
            }
        ]
    }
    ListView {
        anchors.fill: parent
        anchors.topMargin: units.gu(6)
        model: replacementsModel
        delegate: ListItem {
            height: units.gu(7)
            ListItemLayout {
                title.text: heard + "  →  " + written
                title.color: on ? theme.palette.normal.baseText
                                 : theme.palette.normal.backgroundTertiaryText
                Switch {
                    SlotsLayout.position: SlotsLayout.Trailing
                    checked: on
                    onClicked: py.call("backend.replacements_toggle", [rid, checked])
                }
            }
            onClicked: PopupUtils.open(ruleDialog, null,
                {rid: rid, heard: heard, written: written})
            leadingActions: ListItemActions {
                actions: [ Action {
                    iconName: "delete"
                    onTriggered: py.call("backend.replacements_delete", [rid])
                } ]
            }
        }
    }
}

Component {
    id: ruleDialog
    Dialog {
        id: dlg
        property int rid: -1
        property alias heard: heardField.text
        property alias written: writtenField.text
        title: rid < 0 ? "Новая замена" : "Правка замены"
        TextField { id: heardField; placeholderText: "услышано (напр. депло)" }
        TextField { id: writtenField; placeholderText: "записать как (напр. deploy)" }
        Button {
            text: "Сохранить"
            color: LomiriColors.green
            enabled: heardField.text.length > 0 && writtenField.text.length > 0
            onClicked: {
                if (dlg.rid < 0)
                    py.call("backend.replacements_add", [heardField.text, writtenField.text]);
                else
                    py.call("backend.replacements_update", [dlg.rid, heardField.text, writtenField.text]);
                PopupUtils.close(dlg);
            }
        }
        Button { text: "Отмена"; onClicked: PopupUtils.close(dlg) }
    }
}
```

Ensure `import Lomiri.Components.Popups 1.3` is present at the top of `Main.qml`
(add it if missing).

- [ ] **Step 4: Deploy and verify on-device**

```bash
A=/Users/n0mads/Downloads/platform-tools/adb
$A push qml/Main.qml /home/phablet/soundtype/qml/
$A shell "cd soundtype && ./scripts/build.sh >/dev/null 2>&1 && ubuntu-app-stop soundtype.n0madd3v0ps_soundtype 2>/dev/null; ./scripts/install.sh 2>&1 | tail -1"
$A shell "XDG_RUNTIME_DIR=/run/user/32011 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/32011/bus lomiri-app-launch soundtype.n0madd3v0ps_soundtype" &
```
Drive via the `phonectl` channel (`echo 'click X Y' > /tmp/phonefifo`) + `mirscreencast`:
open Settings → "Замены текста" → "Набор RU" → verify the list fills; add a rule
via the dialog; toggle one off; delete one. Screenshot each state.
Expected: rules render `heard → written`, toggle greys the row, delete removes it.

- [ ] **Step 5: Commit**

```bash
git add qml/Main.qml
git commit -m "feat(ui): replacements glossary screen in settings (#8)"
```

---

### Task 6: One-tap "add replacement" from history

**Files:**
- Modify: `qml/Main.qml` (a history-row action / long-press that opens `ruleDialog`
  prefilling `heard` from the tapped word; reuse Task 5's dialog).

**Interfaces:**
- Consumes: `ruleDialog` (Task 5), `backend.replacements_add`.

- [ ] **Step 1: Add a history-row action to seed a replacement**

In the history delegate (`historyPage` ListView delegate, near the existing
"Копировать"/retry actions), add:

```qml
Action {
    iconName: "edit"
    text: "Замена"
    onTriggered: PopupUtils.open(ruleDialog, null,
        {rid: -1, heard: model.body.trim().split(/\s+/)[0] || "", written: ""})
}
```

(MVP: prefill the "heard" side with the first word of the entry; the user edits
`heard` to the exact mis-heard word and types the `written` side. A full
tap-the-wrong-word selection is a later refinement.)

- [ ] **Step 2: Deploy and verify on-device**

```bash
A=/Users/n0mads/Downloads/platform-tools/adb
$A push qml/Main.qml /home/phablet/soundtype/qml/
$A shell "cd soundtype && ./scripts/build.sh >/dev/null 2>&1 && ubuntu-app-stop soundtype.n0madd3v0ps_soundtype 2>/dev/null; ./scripts/install.sh 2>&1 | tail -1"
```
Drive via `phonectl`: open history → on an entry trigger "Замена" → dialog opens
with `heard` prefilled → set `written` → Save → open Settings → "Замены текста"
→ confirm the new rule is present. Screenshot the dialog + the resulting list.
Expected: the rule appears and applies on the next dictation.

- [ ] **Step 3: Commit**

```bash
git add qml/Main.qml
git commit -m "feat(ui): add a replacement from a history entry (#8)"
```

---

### Task 7: On-device end-to-end acceptance

**Files:**
- Create: `scripts/replace-acceptance.py`

**Interfaces:**
- Consumes: real `replace` + `backend` against the on-device data dir, fake
  pyotherside (same pattern as `scripts/on-device-acceptance.py`).

- [ ] **Step 1: Write the acceptance script**

```python
#!/usr/bin/env python3
"""On-device acceptance for #8 against the real data dir.
ST_DATA=~/.local/share/soundtype.n0madd3v0ps ST_PY=/home/phablet/soundtype/py \
python3 scripts/replace-acceptance.py"""
import os
import sys
import types

DATA = os.environ.get('ST_DATA',
                      os.path.expanduser('~/.local/share/soundtype.n0madd3v0ps'))
sys.path.insert(0, os.environ.get('ST_PY', '/home/phablet/soundtype/py'))
sys.modules['pyotherside'] = types.SimpleNamespace(send=lambda *a: None)
import replace  # noqa: E402

ok = True
def check(name, cond):
    global ok
    print(('PASS ' if cond else 'FAIL ') + name)
    ok = ok and cond

# используем изолированный под-каталог, чтобы не трогать боевой словарь
d = os.path.join(DATA, '_acc_replace')
os.makedirs(d, exist_ok=True)
for f in ('replacements.json',):
    p = os.path.join(d, f)
    if os.path.exists(p):
        os.remove(p)

r = replace.add('депло', 'deploy', d)
check('add + apply whole-word', replace.apply('Депло готов, депло опять', d)
      == 'Deploy готов, deploy опять')
check('substring untouched', replace.apply('котёнок', d) == 'котёнок')
replace.toggle(r['id'], False, d)
check('disabled rule is inert', replace.apply('депло', d) == 'депло')
n = replace.add_pack(d)
check('pack added', n == len(replace.PACK_RU_TECH))
check('pack idempotent', replace.add_pack(d) == 0)
check('pack applies', replace.apply('сделал коммит и пуш', d)
      == 'сделал commit и push')

import shutil  # noqa: E402
shutil.rmtree(d, ignore_errors=True)
print('\n=== ' + ('ALL GREEN' if ok else 'HAS RED') + ' ===')
sys.exit(0 if ok else 1)
```

- [ ] **Step 2: Run it on-device**

```bash
A=/Users/n0mads/Downloads/platform-tools/adb
$A push py/replace.py /home/phablet/soundtype/py/replace.py
$A push scripts/replace-acceptance.py /tmp/replace-acceptance.py
$A shell "cd /home/phablet/soundtype && python3 /tmp/replace-acceptance.py"
```
Expected: `=== ALL GREEN ===` (6 checks).

- [ ] **Step 3: Commit**

```bash
git add scripts/replace-acceptance.py
git commit -m "test: on-device acceptance for the replacements module (#8)"
```

---

## Self-Review

**Spec coverage** (`docs/research/2026-08-28-post-replacements.md` §6 decisions):
1. Post-processing layer → Task 4 hooks `_transcribe`/`_session`. ✅
2. stdlib `re` only → Task 1 (no imports beyond `re`). ✅
3. Matching engine (whole-word/longest-first/IGNORECASE+restore_case/ё-fold/
   escape/single-pass) → Task 1 + tests. ✅
4. Inflection out of MVP → not implemented; documented in Global Constraints. ✅
5. `heard→written` data model, JSON storage, host-testable module → Task 2. ✅
6. Pipeline hook on final text (`_transcribe` + `_session`); keyboard = later →
   Task 4 + Global Constraints scope. ✅
7. UX: settings glossary (list/add/edit/delete/toggle) → Task 5; one-tap from
   history → Task 6; toggleable RU-tech pack → Task 3 + Task 5 action. ✅

**Placeholder scan:** every code/test step carries real content; no TODO/TBD;
QML tasks carry concrete QML + explicit on-device verification (they can't run
under host pytest, so they use the established phonectl+mirscreencast channel).

**Type consistency:** rule shape `{id:int, heard:str, written:str, on:bool}` is
consistent across `load/add/update/delete/toggle/apply` (Task 2), the pack
(Task 3), the backend wrappers (Task 4), and the QML model fields `rid/heard/
written/on` (Task 5, mapped from `id`). `apply(text, data_dir)` signature matches
its call in Task 4. `add_pack(data_dir)->int` matches Task 3 tests and Task 4
wrapper.
