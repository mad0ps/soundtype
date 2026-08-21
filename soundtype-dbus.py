#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

class PyOtherSideMock:
    def __init__(self, dbus_obj):
        self.dbus_obj = dbus_obj

    def send(self, event, *args):
        print(f"Event: {event}, Args: {args}", flush=True)
        if event == 'done':
            text = args[0] if args else ""
            self.dbus_obj.TranscriptionReady(text)
        elif event == 'partial':
            # partial(idx, text) — фраза распозналась по ходу записи
            if len(args) > 1 and args[1]:
                self.dbus_obj.PartialReady(str(args[1]))
        elif event == 'recording':
            if args[0]:
                self.dbus_obj.StatusChanged("recording")
        elif event == 'transcribing':
            if args[0]:
                self.dbus_obj.StatusChanged("processing")
            else:
                self.dbus_obj.StatusChanged("ready")
        elif event == 'ready':
            self.dbus_obj.StatusChanged("ready")
        elif event == 'error':
            self.dbus_obj.Error(str(args[0]))

class SoundTypeService(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.listening = False

    @dbus.service.method("com.n0madd3v0ps.soundtype", in_signature='', out_signature='')
    def ToggleDictation(self):
        if not self.listening:
            self.listening = True
            backend.start()
        else:
            self.listening = False
            backend.stop()

    @dbus.service.signal("com.n0madd3v0ps.soundtype", signature='s')
    def StatusChanged(self, status):
        pass

    @dbus.service.signal("com.n0madd3v0ps.soundtype", signature='s')
    def PartialReady(self, text):
        pass

    @dbus.service.signal("com.n0madd3v0ps.soundtype", signature='s')
    def TranscriptionReady(self, text):
        self.listening = False

    @dbus.service.signal("com.n0madd3v0ps.soundtype", signature='s')
    def Error(self, message):
        self.listening = False

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
name = dbus.service.BusName("com.n0madd3v0ps.soundtype", bus)
service = SoundTypeService(bus, "/com/n0madd3v0ps/soundtype")

# Заглушаем pyotherside
sys.modules['pyotherside'] = PyOtherSideMock(service)

# Добавляем путь к питонячим исходникам SoundType
sys.path.insert(0, '/home/phablet/soundtype/py')
import backend

# Инициализируем бэкенд (подгружаем нейросеть)
backend.init()

print("SoundType D-Bus Daemon is running...", flush=True)
loop = GLib.MainLoop()
try:
    loop.run()
except KeyboardInterrupt:
    pass
