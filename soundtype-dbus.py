#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

# Движок держит ~1ГБ RAM резидентно — выгружаем после простоя.
# Загрузка ленивая: первый toggle после старта/выгрузки сначала грузит движок
# (клавиатура показывает «занят»), а запись стартует сама по событию 'ready'.
IDLE_UNLOAD_SECONDS = int(os.environ.get('SOUNDTYPE_IDLE_UNLOAD', '300'))

class PyOtherSideMock:
    def __init__(self, dbus_obj):
        self.dbus_obj = dbus_obj

    def send(self, event, *args):
        print(f"Event: {event}, Args: {args}", flush=True)
        svc = self.dbus_obj
        if event == 'done':
            text = args[0] if args else ""
            svc.TranscriptionReady(text)
        elif event == 'partial':
            # partial(idx, text) — фраза распозналась по ходу записи
            if len(args) > 1 and args[1]:
                svc.PartialReady(str(args[1]))
        elif event == 'recording':
            if args[0]:
                svc.StatusChanged("recording")
        elif event == 'transcribing':
            if args[0]:
                svc.StatusChanged("processing")
            else:
                svc.StatusChanged("ready")
        elif event == 'level':
            svc.Level(float(args[0]))
        elif event == 'status':
            # 'loading' при (пере)загрузке движка — индикатору «занят»;
            # 'unloaded' после idle-выгрузки — индикатору «серый»
            if args and args[0] == 'loading':
                svc.StatusChanged("processing")
            elif args and args[0] == 'unloaded':
                svc.StatusChanged("unloaded")
        elif event == 'ready':
            svc.StatusChanged("ready")
            # движок догрузился после hold — запускаем отложенную запись
            if svc.pending_start:
                svc.pending_start = False
                backend.start()
        elif event == 'error':
            if svc.pending_start:
                # ошибка на загрузке: движка нет, следующий toggle попробует заново
                svc.pending_start = False
                svc.loaded = False
            svc.Error(str(args[0]))

class SoundTypeService(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.listening = False
        self.loaded = False
        self.pending_start = False
        self.idle_timer_id = None

    def start_idle_timer(self):
        self.stop_idle_timer()
        self.idle_timer_id = GLib.timeout_add_seconds(
            IDLE_UNLOAD_SECONDS, self.on_idle_timeout)

    def stop_idle_timer(self):
        if self.idle_timer_id is not None:
            GLib.source_remove(self.idle_timer_id)
            self.idle_timer_id = None

    def on_idle_timeout(self):
        self.idle_timer_id = None
        if self.loaded and not self.listening:
            print(f"Idle for {IDLE_UNLOAD_SECONDS}s, unloading model to save RAM...", flush=True)
            try:
                backend.unload()
                self.loaded = False
            except Exception as exc:
                print(f"Error unloading model: {exc}", flush=True)
        return False

    @dbus.service.method("com.n0madd3v0ps.soundtype", in_signature='', out_signature='')
    def ToggleDictation(self):
        self.stop_idle_timer()
        if not self.listening:
            self.listening = True
            if not self.loaded:
                self.loaded = True
                self.pending_start = True
                backend.init()  # асинхронно; start() дёрнет mock на 'ready'
            else:
                backend.start()
        else:
            self.listening = False
            self.pending_start = False
            backend.stop()
            self.start_idle_timer()

    @dbus.service.signal("com.n0madd3v0ps.soundtype", signature='s')
    def StatusChanged(self, status):
        pass

    @dbus.service.signal("com.n0madd3v0ps.soundtype", signature='d')
    def Level(self, value):
        pass

    @dbus.service.signal("com.n0madd3v0ps.soundtype", signature='s')
    def PartialReady(self, text):
        pass

    @dbus.service.signal("com.n0madd3v0ps.soundtype", signature='s')
    def TranscriptionReady(self, text):
        self.listening = False
        self.start_idle_timer()

    @dbus.service.signal("com.n0madd3v0ps.soundtype", signature='s')
    def Error(self, message):
        self.listening = False
        self.start_idle_timer()

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
name = dbus.service.BusName("com.n0madd3v0ps.soundtype", bus)
service = SoundTypeService(bus, "/com/n0madd3v0ps/soundtype")

# Заглушаем pyotherside
sys.modules['pyotherside'] = PyOtherSideMock(service)

# Добавляем путь к питонячим исходникам SoundType
sys.path.insert(0, '/home/phablet/soundtype/py')
import backend

print(f"SoundType D-Bus Daemon is running (lazy engine, idle unload {IDLE_UNLOAD_SECONDS}s)...", flush=True)
loop = GLib.MainLoop()
try:
    loop.run()
except KeyboardInterrupt:
    pass
