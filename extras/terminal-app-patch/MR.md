# Fix use-after-free crash when leaving selection mode

## Problem

Tapping the "exit selection mode" bar aborts the app with `SIGABRT`
(`munmap_chunk(): invalid pointer`), taking any running shell session with it.
Reproduced on 2.0.5 and 2.0.6; the code is unchanged in `main`.

## Cause

In `app/qml/TerminalPage.qml`, `bottomMessage.active` is turned on by
`PropertyChanges` in the `SELECTION` state. The bar's `MouseArea.onClicked`
sets `terminalPage.state = "DEFAULT"` as its first statement, which reverts
that `PropertyChanges` and makes the `Loader` destroy its item tree
synchronously — including the `MouseArea` currently executing. The following
`PopupUtils.open(...)` then runs against freed objects.

That also explains the four `UCLabel was created without a valid QML Engine`
warnings emitted immediately before the abort.

This is a regression from 8dcfc136 ("redesign close element action and close
selection mode"). The same two statements previously lived in
`closeSelectionButton` / `closeSelectionButtonTab`, `AbstractButton`s toggled
through `visible`. Leaving the state hid them rather than destroying them, so
the handler finished safely. Moving the code into the `bottomMessage` `Loader`
changed the container from one that hides to one that destroys; the statements
themselves were carried over unchanged.

Additionally this was the only one of three `PopupUtils.open()` call sites
passing no caller; lines 103 and 219 both pass `dummyForOtherActions`.

## Change

* Move the handler body into `terminalPage.exitSelectionMode()`, so it runs on
  an object that survives the state change.
* Open the popover while the bar is still alive, passing `dummyForOtherActions`
  as the caller, consistent with the other two call sites.
* Defer `state = "DEFAULT"` via `Qt.callLater` so the teardown happens after the
  `MouseArea` handler has returned.

No user-visible strings, no UI change, no new dependencies.

## Testing

Manual, on Ubuntu Touch 20.04 arm64 (Focal), terminal 2.0.6:

* Before: entering selection mode and tapping "exit selection mode" aborted the
  app every time — six aborts recorded in one session, each with the same
  `munmap_chunk(): invalid pointer` signature.
* After: the popover opens, selection mode exits normally, and no further
  aborts were recorded over continued use.
* The other two popover entry points — the header "other-actions" button and
  the long-press action — behave as before.

No autopilot test added: the crash needs a real touch interaction with the
selection-mode bar, which the existing suite does not cover. Happy to add one
if you can point at the right place to hook it.

## Related

Not a duplicate of #64 (different trigger, predates this bar) or #117
(different signal and code path).
