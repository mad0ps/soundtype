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
# «депло» есть и в паке — убираем его, чтобы пак применился целиком
replace.delete(r['id'], d)
n = replace.add_pack(d)
check('pack added', n == len(replace.PACK_RU_TECH))
check('pack idempotent', replace.add_pack(d) == 0)
check('pack applies', replace.apply('сделал коммит и пуш', d)
      == 'сделал commit и push')

import shutil  # noqa: E402
shutil.rmtree(d, ignore_errors=True)
print('\n=== ' + ('ALL GREEN' if ok else 'HAS RED') + ' ===')
sys.exit(0 if ok else 1)
