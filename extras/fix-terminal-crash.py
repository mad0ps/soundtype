#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Чинит падение terminal.ubports 2.0.6 при выходе из режима выделения текста.

Причина: обработчик onClicked плашки «exit selection mode» первым делом
переводит terminalPage.state в "DEFAULT". Состояние SELECTION держит
bottomMessage.active = true, поэтому смена состояния тут же заставляет
Loader уничтожить Rectangle, Label и сам MouseArea — то есть объект,
внутри обработчика которого мы находимся. Следующая строка вызывает
PopupUtils.open уже в освобождённой памяти: use-after-free, glibc
роняет процесс через munmap_chunk(): invalid pointer -> SIGABRT.

Правка: выносим логику в функцию на terminalPage (этот объект переживает
смену состояния), попап открываем пока плашка ещё жива и с якорем, а
смену состояния откладываем до следующего оборота цикла событий —
когда обработчик MouseArea уже полностью завершится.

Запускать от root: sudo python3 fix-terminal-crash.py
Откат:             sudo python3 fix-terminal-crash.py --revert
"""

import hashlib
import os
import shutil
import sys

TARGET = '/opt/click.ubuntu.com/terminal.ubports/2.0.6/qml/TerminalPage.qml'
BACKUP = TARGET + '.orig'
EXPECTED_MD5 = '860b3c7338aebfbced90da2cc588302f'

OLD_HANDLER = '''                onClicked: {
                  terminalPage.state = "DEFAULT";
                  PopupUtils.open(Qt.resolvedUrl("AlternateActionPopover.qml"));
                }'''

NEW_HANDLER = '''                onClicked: terminalPage.exitSelectionMode()'''

ANCHOR = '    function changeColor(color) {'

NEW_FUNCTION = '''    // Выход из режима выделения текста.
    // Живёт на terminalPage, а не в MouseArea плашки: смена состояния
    // уничтожает саму плашку, и выполняться внутри неё в этот момент
    // нельзя — иначе use-after-free и падение процесса.
    function exitSelectionMode() {
        PopupUtils.open(Qt.resolvedUrl("AlternateActionPopover.qml"),
                        dummyForOtherActions);
        Qt.callLater(function () { terminalPage.state = "DEFAULT"; });
    }

'''


def md5(path):
    with open(path, 'rb') as fh:
        return hashlib.md5(fh.read()).hexdigest()


def revert():
    if not os.path.exists(BACKUP):
        sys.exit('Резервной копии нет: %s' % BACKUP)
    shutil.copy2(BACKUP, TARGET)
    print('Откат выполнен, файл восстановлен из %s' % BACKUP)
    print('Перезапусти терминал, чтобы вернулось исходное поведение.')


def apply():
    if os.geteuid() != 0:
        sys.exit('Нужен root: sudo python3 %s' % sys.argv[0])
    if not os.path.exists(TARGET):
        sys.exit('Файл не найден: %s' % TARGET)

    with open(TARGET, encoding='utf-8') as fh:
        src = fh.read()

    if 'function exitSelectionMode' in src:
        print('Правка уже применена, ничего не меняю.')
        return

    got = md5(TARGET)
    if got != EXPECTED_MD5:
        print('ВНИМАНИЕ: контрольная сумма другая.')
        print('  ожидалась %s' % EXPECTED_MD5)
        print('  получена  %s' % got)
        print('Версия терминала отличается от проверенной. Прерываю,')
        print('чтобы не сломать файл вслепую.')
        sys.exit(1)

    if OLD_HANDLER not in src:
        sys.exit('Не нашёл ожидаемый обработчик onClicked. Прерываю.')
    if ANCHOR not in src:
        sys.exit('Не нашёл место для вставки функции. Прерываю.')

    if not os.path.exists(BACKUP):
        shutil.copy2(TARGET, BACKUP)
        print('Резервная копия: %s' % BACKUP)

    src = src.replace(OLD_HANDLER, NEW_HANDLER, 1)
    src = src.replace(ANCHOR, NEW_FUNCTION + ANCHOR, 1)

    with open(TARGET, 'w', encoding='utf-8') as fh:
        fh.write(src)

    print('Готово. Изменено:')
    print('  1. обработчик плашки «exit selection mode» -> вызов функции')
    print('  2. добавлена terminalPage.exitSelectionMode()')
    print()
    print('Теперь полностью закрой терминал (смахни из списка приложений)')
    print('и открой заново — QML читается при старте.')


if __name__ == '__main__':
    if '--revert' in sys.argv:
        revert()
    else:
        apply()
