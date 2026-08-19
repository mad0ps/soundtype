# Terminal aborts (SIGABRT, heap corruption) when leaving selection mode

## Summary

Tapping the "exit selection mode" bar kills the app with `SIGABRT`. The
handler destroys the very item it is running inside, then keeps using it.

## Steps to reproduce

1. Long-press the terminal area and choose **Select** to enter selection mode.
2. The black "exit selection mode" bar appears at the bottom.
3. Tap that bar.
4. The app dies. Any running shell session is lost with it.

Reproduced on Ubuntu Touch 20.04 (arm64, Focal), terminal app **2.0.5 and
2.0.6** — same signature on both.

## Log

```
The item UCLabel was created without a valid QML Engine. Styling will not be possible.
The item UCLabel was created without a valid QML Engine. Styling will not be possible.
The item UCLabel was created without a valid QML Engine. Styling will not be possible.
The item UCLabel was created without a valid QML Engine. Styling will not be possible.
munmap_chunk(): invalid pointer
systemd[2559]: lomiri-app-launch--application-click--terminal.ubports_terminal_2.0.6--.service:
    Main process exited, code=killed, status=6/ABRT
```

`munmap_chunk(): invalid pointer` is glibc aborting on a corrupted heap, not
an out-of-memory kill — there are no OOM/LMK records at all, and an OOM kill
would be `SIGKILL` (9), not `SIGABRT` (6).

## Cause

`app/qml/TerminalPage.qml`, the `bottomMessage` Loader.

The `SELECTION` state is what keeps the bar alive:

```qml
State {
    name: "SELECTION"
    ...
    PropertyChanges { target: bottomMessage; active: true }
}
```

And the bar's own click handler resets that state first:

```qml
MouseArea {
    anchors.fill: parent
    onClicked: {
      terminalPage.state = "DEFAULT";   // bottomMessage.active -> false
                                        // Loader destroys Rectangle, Label
                                        // and this MouseArea, right here
      PopupUtils.open(Qt.resolvedUrl("AlternateActionPopover.qml"));
                                        // runs in freed memory
    }
}
```

Setting the state back to `DEFAULT` reverts the `PropertyChanges`, so the
Loader tears down its item tree synchronously — including the `MouseArea`
whose handler is still on the stack. The next statement then opens a popover
from a destroyed context. That is the use-after-free; the freed QML objects
are what makes `UCLabel` report "created without a valid QML Engine" just
before glibc aborts.

The missing second argument makes it worse: the two other call sites
(lines 103 and 219) pass `dummyForOtherActions` as the caller, this one
passes nothing, so the popover has no valid anchor to attach to either.

## Fix

Move the logic onto `terminalPage`, which survives the state change; open the
popover while the bar is still alive and with the same anchor the other call
sites use; defer the state change with `Qt.callLater` so it happens after the
`MouseArea` handler has fully returned.

Patch attached / see merge request.

## Notes

Not the same as #117 ("SIGSEGV if closed too quickly") — different signal,
different trigger, different code path.
