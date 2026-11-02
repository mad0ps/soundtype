# -*- coding: utf-8 -*-
"""Кому демон отдаёт итог: клавиатуре или приложению, запустившему запись.

dbus/gi на машине разработчика может не быть — подменяем их заглушками,
которые лишь записывают испущенные сигналы.
"""

import importlib.util
import os
import sys
import types

import pytest

DAEMON = os.path.join(os.path.dirname(__file__), '..', 'soundtype-dbus.py')


def _identity_decorator(*_args, **_kwargs):
    return lambda fn: fn


def _signal(*_args, **_kwargs):
    def decorate(fn):
        def emit(self, *args):
            fn(self, *args)
            self.emitted.append((fn.__name__,) + args)
        return emit
    return decorate


class _Object:
    def __init__(self, bus, path):
        self.emitted = []


class _Backend:
    def __init__(self):
        self.calls = []

    def model_stale(self):
        return False

    def __getattr__(self, name):
        return lambda *args: self.calls.append(name)


@pytest.fixture
def daemon(monkeypatch):
    dbus = types.ModuleType('dbus')
    dbus.service = types.SimpleNamespace(
        Object=_Object, method=_identity_decorator, signal=_signal)
    dbus.SystemBus = lambda: (_ for _ in ()).throw(RuntimeError('no bus'))
    glib_loop = types.SimpleNamespace(DBusGMainLoop=lambda **_kw: None)
    glib = types.SimpleNamespace(
        timeout_add_seconds=lambda *_a: 1, source_remove=lambda _id: None)
    for name, module in {
        'dbus': dbus,
        'dbus.service': dbus.service,
        'dbus.mainloop': types.SimpleNamespace(glib=glib_loop),
        'dbus.mainloop.glib': glib_loop,
        'gi': types.SimpleNamespace(),
        'gi.repository': types.SimpleNamespace(GLib=glib),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location('soundtype_dbus', DAEMON)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.backend = _Backend()
    service = module.SoundTypeService(None, '/com/n0madd3v0ps/soundtype')
    service.loaded = True
    return service, module.PyOtherSideMock(service)


def _dictate(service, mock, start, stop, text):
    start()
    stop()
    service.emitted.clear()
    mock.send('done', text)
    return service.emitted


def test_keyboard_session_goes_to_keyboard(daemon):
    service, mock = daemon
    emitted = _dictate(service, mock, service.ToggleDictation,
                       service.ToggleDictation, 'привет')
    assert emitted == [('TranscriptionReady', 'привет')]


def test_app_session_goes_to_app_only(daemon):
    service, mock = daemon
    emitted = _dictate(service, mock, service.ToggleAppDictation,
                       service.ToggleAppDictation, 'ls -la')
    # приложению текст, клавиатуре пустой итог, и именно в таком порядке
    assert emitted == [('AppTranscriptionReady', 'ls -la'),
                       ('TranscriptionReady', '')]


def test_the_one_who_stops_gets_the_text(daemon):
    service, mock = daemon
    assert _dictate(service, mock, service.ToggleDictation,
                    service.ToggleAppDictation, 'a')[0] == (
                        'AppTranscriptionReady', 'a')
    assert _dictate(service, mock, service.ToggleAppDictation,
                    service.ToggleDictation, 'b') == [
                        ('TranscriptionReady', 'b')]


def test_app_result_ends_the_session(daemon):
    service, mock = daemon
    service.ToggleAppDictation()
    assert service.listening
    service.ToggleAppDictation()
    mock.send('done', 'x')
    assert not service.listening
    # следующий тап клавиатуры начинает новую запись, а не останавливает
    service.ToggleDictation()
    assert service.listening and service.owner == 'keyboard'
