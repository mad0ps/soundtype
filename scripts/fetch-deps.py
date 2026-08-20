#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ручной запуск загрузчика:  python3 scripts/fetch-deps.py [--force]

Вся логика — в py/downloader.py; тот же код зовёт кнопка «Скачать»
в самом приложении. Качается около 500 МБ, распаковано примерно 700 МБ.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'py'))

import downloader  # noqa: E402


def show(stage, pct):
    if pct < 0:
        sys.stdout.write('\r  %s…            ' % stage)
    else:
        sys.stdout.write('\r  %s  %3d%%' % (stage, pct))
    sys.stdout.flush()


def main():
    print('Каталог данных:', downloader.DATA)
    force = '--force' in sys.argv
    if not downloader.missing() and not force:
        print('Всё уже на месте.')
        return
    downloader.fetch_all(show, force=force)
    print('\nГотово. Теперь можно собирать:  ./scripts/build.sh')


if __name__ == '__main__':
    main()
