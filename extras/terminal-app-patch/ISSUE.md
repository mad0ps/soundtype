# Terminal aborts (SIGABRT) when leaving selection mode

## Summary

Tapping the "exit selection mode" bar kills the app with `SIGABRT`. The click
handler destroys the very item it is running inside, then keeps using it.

Any running shell session dies with the app, which is what makes this painful
in practice — long-running work is lost.

## Steps to reproduce

1. Long-press the terminal area and choose **Select** to enter selection mode.
2. The black "exit selection mode" bar appears at the bottom.
3. Tap that bar.
4. The app aborts.

Reproduced on Ubuntu Touch 20.04 (arm64, Focal) with terminal **2.0.5 and
2.0.6**, six times in one session before patching. The relevant code is
unchanged in `main`.

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

`munmap_chunk(): invalid pointer` is glibc aborting on a corrupted heap, not an
out-of-memory kill: there are no OOM or lowmemorykiller records at all, and an
OOM kill would deliver `SIGKILL` (9), not `SIGABRT` (6).

## Cause

`app/qml/TerminalPage.qml`. The `SELECTION` state is what brings the bar into
existence:

```qml
State {
    name: "SELECTION"
    ...
    PropertyChanges { target: bottomMessage; active: true }
}
```

`bottomMessage` is a `Loader`. Its click handler resets that state as its first
statement:

```qml
MouseArea {
    anchors.fill: parent
    onClicked: {
      terminalPage.state = "DEFAULT";   // bottomMessage.active -> false
                                        // the Loader tears down Rectangle,
                                        // Label and this MouseArea, right here
      PopupUtils.open(Qt.resolvedUrl("AlternateActionPopover.qml"));
                                        // now running against freed objects
    }
}
```

Resetting the state reverts the `PropertyChanges`, so the `Loader` destroys its
item tree synchronously — including the `MouseArea` whose handler is still on
the stack. The next statement opens a popover from a destroyed context. The
freed QML objects are why `UCLabel` reports "created without a valid QML
Engine" immediately before glibc aborts.

The missing second argument compounds it: the two other call sites (lines 103
and 219) pass `dummyForOtherActions` as the caller, this one passes nothing, so
the popover has no valid anchor either.

## When it regressed

This used to be safe. Before 8dcfc136 ("redesign close element action and close
selection mode", 2020-12-14) the same two statements lived in
`closeSelectionButton` / `closeSelectionButtonTab`, which were `AbstractButton`s
toggled through `visible`:

```qml
AbstractButton {
    id: closeSelectionButton
    visible: false
    onClicked: {
      terminalPage.state = "DEFAULT";
      PopupUtils.open(Qt.resolvedUrl("AlternateActionPopover.qml"));
    }
}
```

Leaving the state merely **hid** those buttons — hiding is not destroying, so
the handler could safely finish. That commit moved the identical code into the
`sourceComponent` of the `bottomMessage` `Loader`, where the same state change
now **destroys** the item. `bottomMessage` already existed at the time, but only
as a non-interactive banner reading "Selection Mode"; the commit added the
`MouseArea` into it.

So the statements did not change — their container did, from one that hides to
one that destroys.

## Fix

Move the logic onto `terminalPage`, which survives the state change; open the
popover while the bar is still alive and with the anchor the other call sites
use; defer the state change with `Qt.callLater` so it runs after the `MouseArea`
handler has returned. Patch attached / see merge request.

## Not a duplicate

* #64 "App crashes in selection mode with press & hold" (2019, closed 2021) is
  a different trigger — press and hold **on the selection area**, crash on
  release — and predates the bottom bar this bug lives in.
* #117 "SIGSEGV if closed too quickly" is a different signal and a different
  code path.
