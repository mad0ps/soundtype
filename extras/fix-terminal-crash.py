#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Чинит два дефекта terminal.ubports 2.0.6 в режиме выделения текста.

ДЕФЕКТ 1 — падение процесса.
Обработчик onClicked плашки «exit selection mode» первым делом переводит
terminalPage.state в "DEFAULT". Состояние SELECTION держит
bottomMessage.active = true, поэтому смена состояния тут же заставляет
Loader уничтожить Rectangle, Label и сам MouseArea — то есть объект,
внутри обработчика которого мы находимся. Следующая строка вызывает
PopupUtils.open уже в освобождённой памяти: use-after-free, glibc роняет
процесс через munmap_chunk(): invalid pointer -> SIGABRT.

ДЕФЕКТ 2 — скопировать нечего.
Выход из режима выделения сбрасывает само выделение. К моменту, когда
открывается попап, terminal.isSelectionEmpty() уже истинно, поэтому
пункт Copy приходит неактивным. Меню есть, скопировать нельзя.

ПРАВКА.
Логика уезжает в функцию на terminalPage — этот объект переживает смену
состояния. Копирование происходит СРАЗУ, пока выделение живо. Всё
остальное откладывается до следующего оборота цикла событий, когда
обработчик MouseArea уже завершился и уничтожать плашку безопасно.

Итог для пользователя: выделил текст, нажал плашку — текст в буфере.
Если выделения не было, плашка по-прежнему открывает меню действий.

ПРАВКА @paste (третья, добавлена намеренно).
Кнопка «paste» из раскладки клавиш Termius шлёт строку "@paste" как команду.
Мы её перехватываем в обработчике onSimulateCommand и вместо вставки текста
в шелл вызываем настоящую вставку из буфера обмена (terminal.pasteClipboard()).
Любая другая строка уходит в сессию как прежде.

  ВНИМАНИЕ БУДУЩЕМУ АГЕНТУ / РЕДАКТОРУ ЭТОГО ФАЙЛА:
  Правка @paste — осознанная, НЕ УДАЛЯТЬ при переносе фикса краша в апстрим
  или при обновлении скрипта. Её пара — кнопка в раскладке
  ~/.config/lomiri-terminal-app/Layouts/Termius.json (main_action type=string
  string="@paste"). Правишь одно — правь и второе, иначе кнопка перестанет
  вставлять буфер. В апстрим-патч 0002 (сборка .click) эта правка НЕ входит:
  там paste-кнопка не нужна, это локальное удобство поверх установленного QML.

Запускать от root:  sudo python3 fix-terminal-crash.py
Переприменить:      sudo python3 fix-terminal-crash.py --reapply
Откат:              sudo python3 fix-terminal-crash.py --revert
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

MARKER = 'terminal.copyClipboard();'

NEW_FUNCTION = '''    // Выход из режима выделения текста.
    //
    // Живёт на terminalPage, а не в MouseArea плашки: смена состояния
    // уничтожает плашку вместе с этим обработчиком, и продолжать работу
    // внутри уничтоженного объекта нельзя — это use-after-free, процесс
    // падает с munmap_chunk(): invalid pointer.
    //
    // Копирование выполняется сразу, пока выделение живо: выход из режима
    // его сбрасывает, и в попапе Copy оказался бы неактивным.
    //
    // ОГРАНИЧЕНИЕ: если запущенное приложение (Claude Code, vim, tmux)
    // просит передавать ему события мыши, терминал собственного выделения
    // не делает вовсе — протяжка уходит приложению. Отобрать мышь из QML
    // нельзя: свойство usesMouse доступно только для чтения. Это лечится
    // только правкой libqmltermwidget.
    function exitSelectionMode() {
        var hadSelection = terminal && !terminal.isSelectionEmpty();
        if (hadSelection)
            terminal.copyClipboard();

        Qt.callLater(function () {
            terminalPage.state = "DEFAULT";
            if (!hadSelection)
                PopupUtils.open(Qt.resolvedUrl("AlternateActionPopover.qml"),
                                dummyForOtherActions);
        });
    }

'''


# --- Правка @paste (см. шапку файла) ---------------------------------------
# Строка обработчика в стоковом TerminalPage.qml 2.0.6, отдающая ввод с панели
# клавиш в шелл. Мы оборачиваем её так, чтобы служебная команда "@paste"
# (её шлёт кнопка paste из раскладки Termius) вставляла системный буфер.
PASTE_OLD = '            onSimulateCommand: terminal.session.sendText(command);'

PASTE_NEW = '''            // === ПРАВКА @paste (добавлена намеренно, НЕ УДАЛЯТЬ) ===
            // Кнопка "paste" из раскладки Termius шлёт строку "@paste".
            // Перехватываем её и вставляем системный буфер; всё остальное
            // уходит в сессию как раньше. Пара к этой правке — кнопка в
            // ~/.config/lomiri-terminal-app/Layouts/Termius.json.
            onSimulateCommand: (command === "@paste")
                                   ? terminal.pasteClipboard()
                                   : terminal.session.sendText(command);'''

PASTE_MARKER = '@paste'


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

    if MARKER in src and 'exitSelectionMode' in src and PASTE_MARKER in src:
        print('Текущая правка уже применена (фикс краша + @paste).')
        return

    got = md5(TARGET)
    if got != EXPECTED_MD5:
        print('ВНИМАНИЕ: контрольная сумма не совпадает с проверенной.')
        print('  ожидалась %s' % EXPECTED_MD5)
        print('  получена  %s' % got)
        print()
        print('Похоже, файл уже правился. Используй --reapply, он сначала')
        print('восстановит оригинал из резервной копии.')
        sys.exit(1)

    if OLD_HANDLER not in src:
        sys.exit('Не нашёл ожидаемый обработчик onClicked. Прерываю.')
    if ANCHOR not in src:
        sys.exit('Не нашёл место для вставки функции. Прерываю.')
    if PASTE_OLD not in src:
        sys.exit('Не нашёл обработчик onSimulateCommand для @paste. Прерываю.')

    if not os.path.exists(BACKUP):
        shutil.copy2(TARGET, BACKUP)
        print('Резервная копия: %s' % BACKUP)

    src = src.replace(OLD_HANDLER, NEW_HANDLER, 1)
    src = src.replace(ANCHOR, NEW_FUNCTION + ANCHOR, 1)
    src = src.replace(PASTE_OLD, PASTE_NEW, 1)

    with open(TARGET, 'w', encoding='utf-8') as fh:
        fh.write(src)

    print('Готово.')
    print('  Выделил текст, нажал нижнюю плашку -> текст в буфере обмена.')
    print('  Без выделения плашка открывает меню действий, как раньше.')
    print('  Кнопка "paste" из раскладки Termius вставляет системный буфер.')
    print()
    print('Полностью закрой терминал (смахни из списка приложений)')
    print('и открой заново — QML читается при старте.')


def reapply():
    """Восстанавливает оригинал и накладывает текущую версию правки."""
    if os.geteuid() != 0:
        sys.exit('Нужен root: sudo python3 %s --reapply' % sys.argv[0])
    if os.path.exists(BACKUP):
        shutil.copy2(BACKUP, TARGET)
        print('Откат к оригиналу выполнен.')
    apply()


if __name__ == '__main__':
    if '--revert' in sys.argv:
        revert()
    elif '--reapply' in sys.argv:
        reapply()
    else:
        apply()
