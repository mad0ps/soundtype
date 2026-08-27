# Research — Post-processing replacements module (#8)

Gathered 2026-08-28 before planning. Sources: three focused web-research passes
(matching mechanics / Russian inflection libraries / community & product prior
art) plus local measurement on the target device. This document feeds the
implementation plan; it does not itself decide UX copy.

## 0. Local ground truth (measured on-device)

- Phone runtime: **Python 3.12.3**, aarch64. Available relevant modules: **stdlib
  `re` only**. `regex`, `pymorphy2`, `pymorphy3`, `snowballstemmer` are all
  **absent**. The app bundles only `numpy` + `sherpa-onnx` wheels — every new
  dependency must be shipped as a bundled wheel (download size + confined
  packaging cost).
- **Cyrillic `\b` works on the target Python 3.12.3**: `\bкот\b` matches «кот»,
  does **not** match inside «котёнок»; `ё` is in `\w`; phrase substitution and
  case-preserving `re.sub(..., flags=re.I)` verified live on the phone
  («Депло»→«Deploy», «депло»→«deploy»).

**Consequence:** the MVP can be **pure stdlib**, zero new dependencies.

## 1. Which layer — post-processing vs decoder hotwords

**Post-processing text replacement is the correct primary layer.** Decoder
biasing (sherpa-onnx hotwords) is not viable for us:

- Hotwords require `modified_beam_search`; our pipeline decodes per-phrase with
  **greedy_search**, which does **not** support hotwords at all.
- Hotwords also require a transducer model + BPE tokenization + `hotwords-file`
  and would need a pipeline change on every glossary edit — wrong cost profile
  for a user-editable list.
- Post-processing is model-agnostic, instant, editable by the user, and can emit
  spellings the tokenizer can never produce (кубер→k8s). This is exactly how
  nerd-dictation, Talon, and Dragon word-lists solve the same problem.

Reserve decoder hotwords (#7) only for terms the model *reliably mangles at the
phonetic level* — post-replace can't distinguish those from legitimate uses of
the rival word. That keeps #7 as a narrow later escape hatch, not MVP.

Refs: [sherpa-onnx hotwords](https://k2-fsa.github.io/sherpa/onnx/hotwords/index.html).

## 2. Matching mechanics — stdlib `re` only (verified)

No third-party `regex` needed. The engine:

- **One combined alternation regex**, not a `str.replace` loop (a loop chains —
  an earlier replacement's output gets re-matched — and can't do whole-word or
  case-insensitive matching). A single `re.sub` pass matches the original text
  only.
- **Sort keys longest-first** — alternation is leftmost/first-alternative, not
  longest, so «облачная функция» must precede a hypothetical «функция».
- **Whole-word via lookarounds `(?<!\w)…(?!\w)`** (more robust than `\b…\b`
  around a group). `\w` includes digits + `_`, so «кот3»/«кот_» do **not** match
  — correct for a glossary. Guards against the substring / Scunthorpe trap.
- **`re.IGNORECASE`** for matching (Unicode-aware for `str`) + a `restore_case()`
  function to carry the match's casing onto the replacement (ДЕПЛО→DEPLOY,
  Депло→Deploy, депло→deploy).
- **ё/е folding only in the pattern**: replace each е/ё in the key with the class
  `[еёЕЁ]` so key «ещё» matches «еще» and «ещё»; the replacement text is emitted
  verbatim.
- **Phrase keys** via `\s+` between sub-words (tolerate multiple spaces; use
  `[ \t]+` if newlines must not be crossed).
- **`re.escape()` every literal char** so keys like `c++` / `.net` stay literal.
- Compile once, reuse; O(1) dispatch to the winning replacement via
  `m.lastgroup`.

Skeleton (from research, verified live):

```python
import re

def _yo(key):                       # ё-fold only in the pattern
    return ''.join('[еёЕЁ]' if ch in 'еёЕЁ' else re.escape(ch) for ch in key)

def _phrase(key):                   # multi-word key, tolerate whitespace
    return r'\s+'.join(_yo(w) for w in key.split())

def _restore_case(matched, repl):
    if len(matched) > 1 and matched.isupper():
        return repl.upper()
    if matched[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl

def build(glossary):                # dict {heard: written}
    keys = sorted(glossary, key=len, reverse=True)          # longest-first
    alts = '|'.join('(?P<g%d>%s)' % (i, _phrase(k)) for i, k in enumerate(keys))
    rx = re.compile(r'(?<!\w)(?:%s)(?!\w)' % alts, re.IGNORECASE)
    repl = {'g%d' % i: glossary[k] for i, k in enumerate(keys)}
    return lambda text: rx.sub(lambda m: _restore_case(m.group(0), repl[m.lastgroup]), text)
```

Refs: [Python `re`](https://docs.python.org/3/library/re.html),
[casefold](https://docs.python.org/3/library/stdtypes.html#str.casefold),
[single-pass multi-replace](https://code.activestate.com/recipes/81330-single-pass-multiple-replace/),
[Scunthorpe problem](https://en.wikipedia.org/wiki/Scunthorpe_problem).

## 3. Inflection tolerance — defer, and when needed do it hand-rolled

**MVP: exact, case-insensitive, ё-normalized matching — no inflection.** For a
user-curated glossary, mis-replacing the wrong word mid-sentence is worse than
missing an inflected form; the user can add the forms they actually dictate.

**Later (opt-in): a hand-rolled suffix stripper (~20 lines), not a library.**
Strip common Russian endings before matching, store `norm(key)` alongside the
raw key, warn on stem collisions at add-time, and guard (residual stem ≥ 3–4
chars, stem must be a prefix of the key) to kill cross-word false matches.

Library options if the heuristic proves too crude, cheapest first:

| Option | Pure-Py | Added size | License | Verdict |
|---|---|---|---|---|
| Hand-rolled suffix stripper | yes | ~0 | ours | **best fit for a small curated glossary** |
| snowballstemmer (ru) / inline Russian Porter | yes | ~0.1 MB / 0 | BSD | cheap; stems not lemmas → over-stem risk |
| **pymorphy3** + dicts-ru | yes (default) | **~8.5 MB** + 15–30 MB RAM | MIT (dicts CC-BY-SA) | most correct (true lemmas), escape hatch only; works on 3.12/aarch64 |
| pymorphy2 | — | — | — | **dead** — crashes on Python 3.11+ (`inspect.getargspec`) |

Refs: [pymorphy3](https://pypi.org/project/pymorphy3/),
[pymorphy3-dicts-ru](https://pypi.org/project/pymorphy3-dicts-ru/),
[snowballstemmer](https://pypi.org/project/snowballstemmer/).

## 4. Data model & UX — community/product prior art

**Data model = `heard → written` pairs** (Dragon Spoken→Written, Talon
Original→Replacement, nerd-dictation `WORD_REPLACE`). Two fields per rule. Store
**phrases and single words in one list**, apply **phrases/longest first** (our
longest-first alternation already does this in a single pass).

**Storage**: a human-readable JSON file in the data dir (like `settings.json`),
atomic write, graceful fallback on a corrupt/empty file. Human-readable format
makes export/import essentially free (nerd-dictation/Talon model).

**UX worth copying (MVP):**
- A managed glossary screen in settings: searchable list, each row `heard →
  written`, tap to edit, swipe/delete, **per-rule enable/disable toggle**.
- **One-tap-from-history rule creation** as the headline interaction: from a past
  transcript, long-press the wrong word → it **prefills the "heard" side** → user
  types/dictates the correct "written" side → Save. Turns a real mis-recognition
  into a rule without retyping what was heard. (Diction/dictop/Wispr pattern.)
- **Immediate effect** — applies to the next dictation, no rebuild (post-proc is
  free here).
- **Seed a toggleable RU-tech starter pack** so the feature shows value on first
  run.
- Sensible fixed defaults (whole-word, case-insensitive match, case-preserving
  output); expose case/boundary/regex only behind an "advanced" expander.

**Skip for MVP** (over-engineered): decoder-hotword integration; auto-learning
rules from corrections (even Wispr/FUTO deliberately don't — risks silently
learning wrong rules); a user-facing regex authoring UI; cloud/team sync;
priority caps.

**Pitfalls to design against:** substring/Scunthorpe (→ whole-word), ASR
token-splitting one term into two words «пул реквест» (→ phrase rules),
replacement chaining (→ single pass), cross-phrase context (we decode per-phrase
→ keep rules local/self-contained). Note: unlike Vosk (all-lowercase), **GigaAM
already emits proper case and punctuation**, so the "fix casing" use-case is
narrower for us — the main value is transliteration/tech-term canonicalization
and fixed miswrites.

**Gap found:** no packaged ru→en tech-term dictation glossary exists (FUTO even
has an open request for a voice personal dictionary) — this feature fills a real
hole.

Refs: [nerd-dictation default config](https://github.com/ideasman42/nerd-dictation/blob/main/examples/default/nerd-dictation.py),
[talonhub/community](https://github.com/talonhub/community/blob/main/README.md),
[Dragon Vocabulary Editor](https://www.nuance.com/products/help/dragon/dragon-for-pc/enx/dps/main/Content/DialogBoxes/vocs/voc_editor_dlg.htm),
[FUTO #1839](https://github.com/futo-org/android-keyboard/issues/1839),
[Wispr dictionary](https://docs.wisprflow.ai/articles/6901148133-transcription-suddenly-got-worse-or-feels-less-accurate).

### Starter RU-tech pack (seed, toggleable) — heard → written

```
депло, деплой, задеплоить → deploy
коммит, закоммитить       → commit
пуш, запушить             → push
пул реквест, пиар         → pull request
мёрдж, смёрджить          → merge
кубер, кубернетес         → kubernetes
докер → docker · редис → redis · постгрес, постгря → postgres
кэш → cache · эндпоинт → endpoint · реквест / респонс → request / response
роллбэк, откатить → rollback · билд → build · дебаг, дебажить → debug
логи → logs · таск → task · ветка → branch · код ревью → code review
```
(канонические цели — редактируемы пользователем; кубер→kubernetes vs k8s
оставить на выбор.)

## 5. Where it hooks in our pipeline

Final text is assembled as `full` in both `Dictation._session` (live) and
`Dictation._transcribe` (retry) before it's saved to history / emitted. A single
`apply_replacements(full)` at those two points covers app dictation. Keyboard
streaming (per-phrase commit) is a **second step** — phrases are word-complete at
commit, so the same function applies per committed phrase, but it touches the
patched keyboard and is out of MVP scope.

## 6. Decisions this research settles (for the plan)

1. **Layer**: post-processing (decoder hotwords ruled out by greedy decode). ✅
2. **Deps**: stdlib `re` only for MVP — no wheel, no size. ✅
3. **Matching**: combined-alternation engine from §2 (whole-word, longest-first,
   IGNORECASE + restore_case, ё-fold in pattern, phrases, re.escape, single pass).
4. **Inflection**: **out of MVP**; later opt-in hand-rolled stripper; pymorphy3
   only as a documented escape hatch.
5. **Data model**: `heard → written` pairs, one list, phrases-first; JSON storage
   with graceful fallback; module `py/replace.py` (host-testable like models.py).
6. **Pipeline hook**: `apply_replacements` on `full` in `_session` + `_transcribe`;
   keyboard per-phrase = later.
7. **UX MVP**: settings glossary screen (list/add/edit/delete/enable-toggle) +
   one-tap-from-history creation + toggleable RU-tech seed pack. Regex/case/
   boundary options behind "advanced"; no auto-learning.
