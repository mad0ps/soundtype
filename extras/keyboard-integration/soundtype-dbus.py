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
            if len(args) > 1 and args[1]:
                self.dbus_obj.PartialReady(str(args[1]))
        elif event == 'recording':
            if args[0]:
                self.dbus_obj.StatusChanged("recording")
            else:
                self.dbus_obj.StatusChanged("processing")
        elif event == 'transcribing':
            if args[0]:
                self.dbus_obj.StatusChanged("processing")
            else:
                self.dbus_obj.StatusChanged("ready")
        elif event == 'ready':
            self.dbus_obj.StatusChanged("ready")
            if self.dbus_obj.pending_start:
                self.dbus_obj.pending_start = False
                backend.start()
        elif event == 'deps-missing':
            print("Error: Missing dependencies or model.", flush=True)
            self.dbus_obj.Error("deps-missing")
            self.dbus_obj.listening = False
            self.dbus_obj.initialized = False
        elif event == 'error':
            self.dbus_obj.Error(str(args[0]))
            self.dbus_obj.listening = False
            self.dbus_obj.pending_start = False

class SoundTypeService(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.listening = False
        self.initialized = False
        self.pending_start = False

    @dbus.service.method("com.n0madd3v0ps.soundtype", in_signature='', out_signature='')
    def ToggleDictation(self):
        if not self.initialized:
            self.initialized = True
            self.pending_start = True
            self.StatusChanged("processing")
            backend.init()
            return

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

# Динамический путь к исходникам SoundType (на две папки выше, затем /py)
script_dir = os.path.dirname(os.path.abspath(__file__))
soundtype_py_dir = os.path.abspath(os.path.join(script_dir, '..', '..', 'py'))
sys.path.insert(0, soundtype_py_dir)
import backend

print("SoundType D-Bus Daemon is running (lazy load mode)...", flush=True)
loop = GLib.MainLoop()
try:
    loop.run()
except KeyboardInterrupt:
    pass
