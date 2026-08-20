# Text selection is impossible while the running program uses mouse reporting

## Summary

Selection mode produces no selection whenever the running program has mouse
reporting enabled. The selection overlay behaves normally, but the terminal
never creates a selection of its own, so **Copy is permanently greyed out**.

This affects every full-screen program that tracks the mouse — `vim` with
`set mouse=a`, `htop`, `tmux`, `less -X`, and TUI tools generally. Given that
those are the programs whose output one most often wants to copy, text
copying is effectively unavailable on touch in a large part of daily use.

## Steps to reproduce

1. In a fresh tab (plain shell, nothing running), print some text.
2. Long-press → **Select** → drag over the text → tap the bottom bar.
   Copying works.
3. In the same tab start any program that enables mouse reporting, e.g.
   `htop`, or `vim` with `set mouse=a`.
4. Repeat the same selection steps.
   Nothing gets selected, and `Copy` in the popover stays disabled.

Reproduced on Ubuntu Touch 20.04 (arm64, Focal), terminal 2.0.6.

## Cause

When a program enables mouse tracking, `QMLTermWidget` forwards pointer
events to that program instead of performing its own text selection. Entering
`SELECTION` state does not change this: `TerminalPage.qml` disables
`TerminalInputArea` for the duration, but nothing tells the widget to stop
handing the mouse to the program.

As a result `terminal.isSelectionEmpty()` is still true when the popover
opens, so this binding keeps `Copy` disabled:

```qml
Action {
    text: i18n.tr("Copy")
    enabled: !terminal.isSelectionEmpty()
    onTriggered: terminal.copyClipboard();
}
```

The natural fix — release the mouse for the duration of selection mode —
cannot be done from QML. `QMLTermWidget` exposes the flag read-only
(`lib/TerminalDisplay.h`, at the submodule commit this app pins):

```cpp
Q_PROPERTY(bool terminalUsesMouse  READ getUsesMouse  NOTIFY usesMouseChanged)
```

There is no `WRITE`, so any assignment from QML fails:

```
TerminalPage.qml: TypeError: Cannot assign to read-only property
```

The setter already exists in C++ — `void setUsesMouse(bool)` in the same
header — it is simply not wired into the property.

## Suggested fix

Two small changes:

1. In the `libs/qmltermwidget` submodule
   (`https://github.com/gber/qmltermwidget`), wire the existing setter into
   the property — a one-line change in `lib/TerminalDisplay.h`:

   ```cpp
   Q_PROPERTY(bool terminalUsesMouse  READ getUsesMouse  WRITE setUsesMouse
                                      NOTIFY usesMouseChanged)
   ```

2. In `app/qml/TerminalPage.qml`, release the mouse while in `SELECTION`
   state and restore the previous value on exit, e.g.

   ```qml
   property var savedUsesMouse

   onStateChanged: {
       if (!terminal)
           return;
       if (state === "SELECTION") {
           savedUsesMouse = terminal.terminalUsesMouse;
           terminal.terminalUsesMouse = false;
       } else if (savedUsesMouse !== undefined) {
           terminal.terminalUsesMouse = savedUsesMouse;
           savedUsesMouse = undefined;
       }
   }
   ```

Step 2 alone is not enough; it throws the TypeError above until step 1 lands.

## Possibly the same root cause as #94

#94 "keyboard selection mode does not work" describes selection not working
without stating a condition. If that report was made while a mouse-reporting
program was running, this is the same defect, and the two can be merged.

## Related, but a separate defect

`QMLTermWidget` does not implement **OSC 52**, so a program's own "copy to
clipboard" request is silently discarded. Applications that copy this way
report success while the clipboard stays untouched. That is independent of
the selection problem above and would need its own change in the same
submodule; happy to open a separate issue for it if useful.
