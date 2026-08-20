# -*- coding: utf-8 -*-
"""Общая обвязка: py/ в пути импорта, заглушка pyotherside с журналом событий."""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'py'))
sys.path.insert(0, os.path.dirname(__file__))

EVENTS = []


def _send(event, *args):
    EVENTS.append((event,) + args)


sys.modules.setdefault('pyotherside', types.SimpleNamespace(send=_send))


@pytest.fixture
def events():
    EVENTS.clear()
    return EVENTS
