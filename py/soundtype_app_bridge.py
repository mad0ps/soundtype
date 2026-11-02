# -*- coding: utf-8 -*-
"""Мост к демону SoundType для приложений, которые вставляют текст сами
(кнопка микрофона в Терминале), в отличие от клавиатуры.

Запись запускается методом ToggleAppDictation, итог приходит сигналом
AppTranscriptionReady и клавиатурой не вставляется.

Почему не soundtype_dbus_listener: тот вешает dbus-python на общий
GMainContext процесса и крутит его во втором потоке. В клавиатуре это
работает, а в Терминале событие доходило через 16–37 с (замер 02.11.2026).
Здесь у потока свой GMainContext: GDBus вызывает обработчики сигналов
только в нём, с циклом событий Qt общего ничего нет.
"""

import threading

import pyotherside
from gi.repository import Gio, GLib

BUS_NAME = 'com.n0madd3v0ps.soundtype'
OBJECT_PATH = '/com/n0madd3v0ps/soundtype'
INTERFACE = 'com.n0madd3v0ps.soundtype'

# сигнал демона -> событие для QML
EVENTS = {
    'StatusChanged': 'statusChanged',
    'AppTranscriptionReady': 'transcriptionReady',
    # итог записи, которую остановила клавиатура: текст вставит она,
    # приложению это лишь знак, что запись кончилась
    'TranscriptionReady': 'sessionEnded',
    'Error': 'dictationError',
}

_bus = None


def _on_signal(connection, sender, path, interface, signal, parameters,
               *user_data):
    pyotherside.send(EVENTS[signal], *parameters.unpack())


def _run(ready, failure):
    global _bus
    context = GLib.MainContext.new()
    context.push_thread_default()
    try:
        _bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        for signal in EVENTS:
            _bus.signal_subscribe(None, INTERFACE, signal, OBJECT_PATH, None,
                                  Gio.DBusSignalFlags.NONE, _on_signal)
    except Exception as exc:
        failure.append(exc)
        ready.set()
        return
    ready.set()
    GLib.MainLoop.new(context, False).run()


def init():
    ready, failure = threading.Event(), []
    threading.Thread(target=_run, args=(ready, failure), daemon=True).start()
    if not ready.wait(5):
        raise RuntimeError('SoundType: session bus not reachable')
    if failure:
        raise failure[0]


def toggle_dictation():
    _bus.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, 'ToggleAppDictation',
                   None, None, Gio.DBusCallFlags.NO_AUTO_START, 3000, None)
