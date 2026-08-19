# Fix use-after-free crash when leaving selection mode

## Problem

Tapping the "exit selection mode" bar aborts the app with `SIGABRT`
(`munmap_chunk(): invalid pointer`), taking any running shell session with it.
Reproduced on 2.0.5 and 2.0.6; the code is unchanged in `main`.

## Cause

In `app/qml/TerminalPage.qml`, `bottomMessage.active` is turned on by
`PropertyChanges` in the `SELECTION` state. The bar's `MouseArea.onClicked`
sets `terminalPage.state = "DEFAULT"` as its first statement, which reverts
that `PropertyChanges` and makes the Loader destroy its item tree
synchronously — including the `MouseArea` currently executing. The following
`PopupUtils.open(...)` then runs against freed objects.

That also explains the four `UCLabel was created without a valid QML Engine`
warnings emitted immediately before the abort.

Additionally this call site was the only one of three passing no caller to
`PopupUtils.open()`; lines 103 and 219 both pass `dummyForOtherActions`.

## Change

- Move the handler body into `terminalPage.exitSelectionMode()`, so it runs on
  an object that survives the state change.
- Open the popover while the bar is still alive, passing
  `dummyForOtherActions` as the caller, consistent with the other two sites.
- Defer `state = "DEFAULT"` via `Qt.callLater` so the teardown happens after
  the `MouseArea` handler has returned.

Two-line behavioural change, no user-visible strings, no UI change.

## Testing

Manual, on Ubuntu Touch 20.04 arm64 (Focal), terminal 2.0.6:

- Enter selection mode, tap "exit selection mode" — before: app aborts every
  time; after: popover opens and selection mode exits normally.
- The other two popover entry points (header "other-actions" button and the
  long-press action) behave as before.

No autopilot test added — the crash needs a real touch interaction with the
selection-mode bar, which the existing suite does not cover.
