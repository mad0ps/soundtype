#!/usr/bin/env python3
"""On-device integration acceptance for issues #27/#28.

Runs the REAL app backend against the REAL on-device filesystem (settings.json
and downloaded model probes), with a fake pyotherside capturing emitted events
and the engine load mocked out. Complements the host unit tests (which fake the
filesystem) by exercising downloader.missing() / models.fallback_profile() and
the deps-missing payload against actual disk state.

Usage on the phone (UT):
    # temporarily hide the fallback-target's probe to simulate "not downloaded"
    ST_DATA=~/.local/share/soundtype.n0madd3v0ps \
    ST_PY=/home/phablet/soundtype/py python3 scripts/on-device-acceptance.py

Preconditions the script asserts (set them up before running):
  * settings.json active model = gigaam
  * parakeet probe (encoder) absent  -> simulates "not downloaded"
  * gigaam probe present
Exit code 0 = all green.
"""
import json
import os
import sys
import types

DATA = os.environ.get('ST_DATA',
                      os.path.expanduser('~/.local/share/soundtype.n0madd3v0ps'))
PY = os.environ.get('ST_PY', '/home/phablet/soundtype/py')

EVENTS = []
sys.modules['pyotherside'] = types.SimpleNamespace(
    send=lambda ev, *a: EVENTS.append((ev,) + a))
sys.path.insert(0, PY)
import backend  # noqa: E402
import downloader  # noqa: E402,F401
import models  # noqa: E402

backend.DATA = DATA
loads = []
backend._engine.load = lambda: loads.append(1)
backend._engine.recognizer = None

ok = True
def check(name, cond):
    global ok
    print(('PASS ' if cond else 'FAIL ') + name)
    ok = ok and cond

# preconditions
models.set_active('gigaam', DATA)
check('precondition: gigaam active', models.get_active(DATA) == 'gigaam')
check('precondition: parakeet NOT downloaded',
      not os.path.exists(models.probe_path('parakeet', DATA)))
check('precondition: gigaam downloaded',
      os.path.exists(models.probe_path('gigaam', DATA)))
check('precondition: fallback_profile(parakeet)==gigaam',
      models.fallback_profile('parakeet', DATA) == 'gigaam')

# #28: switching to a not-downloaded profile raises deps-missing with a fallback
EVENTS.clear(); loads.clear()
backend.set_model('parakeet')
check('#28 emits model=parakeet', ('model', 'parakeet') in EVENTS)
dm = [e for e in EVENTS if e[0] == 'deps-missing']
check('#28 deps-missing raised', bool(dm))
check('#28 engine NOT loaded (model missing)', loads == [])
if dm:
    payload = dm[0]
    check('#28 payload carries info dict (3 args)', len(payload) == 3)
    info = payload[2] if len(payload) == 3 else {}
    check('#28 fallback == gigaam', info.get('fallback') == 'gigaam')
    check('#28 fallback_label correct',
          info.get('fallback_label') == models.REGISTRY['gigaam']['label'])
    check('#28 selected-model (parakeet) size shown',
          info.get('size') == models.REGISTRY['parakeet'].get('size'))
    check('#28 missing includes parakeet', 'parakeet' in payload[1])

# #28 return: the "return" button -> set_model(gigaam) -> loads, no overlay
EVENTS.clear(); loads.clear()
backend.set_model('gigaam')
check('#28 return: emits model=gigaam', ('model', 'gigaam') in EVENTS)
check('#28 return: no deps-missing (gigaam downloaded)',
      not any(e[0] == 'deps-missing' for e in EVENTS))
check('#28 return: engine loads', loads == [1])
check('#28 return: settings.json restored to gigaam',
      json.load(open(os.path.join(DATA, 'settings.json')))['model'] == 'gigaam')

# #27: double-load guard
d = backend.Dictation()
created = []
class _FakeThread:
    def __init__(self, target=None, daemon=None): created.append(target)
    def start(self): pass
backend.threading.Thread = _FakeThread
d.load(); d.load()
check('#27 second load during in-flight load spawns no 2nd thread',
      len(created) == 1)

print('\n=== ' + ('ALL GREEN' if ok else 'HAS RED') + ' ===')
sys.exit(0 if ok else 1)
