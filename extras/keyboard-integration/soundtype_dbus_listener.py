import os
import dbus
import pyotherside
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import threading

def run_dbus_loop():
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    def status_handler(status):
        pyotherside.send('statusChanged', str(status))
    def ready_handler(text):
        pyotherside.send('transcriptionReady', str(text))
    def partial_handler(text):
        pyotherside.send('partialReady', str(text))
    
    bus.add_signal_receiver(status_handler, dbus_interface='com.n0madd3v0ps.soundtype', signal_name='StatusChanged')
    bus.add_signal_receiver(ready_handler, dbus_interface='com.n0madd3v0ps.soundtype', signal_name='TranscriptionReady')
    bus.add_signal_receiver(partial_handler, dbus_interface='com.n0madd3v0ps.soundtype', signal_name='PartialReady')
    
    loop = GLib.MainLoop()
    loop.run()

def init():
    t = threading.Thread(target=run_dbus_loop, daemon=True)
    t.start()

def toggle_dictation():
    os.system("dbus-send --session --dest=com.n0madd3v0ps.soundtype --type=method_call /com/n0madd3v0ps/soundtype com.n0madd3v0ps.soundtype.ToggleDictation")
