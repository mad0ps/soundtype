# Contributing to SoundType

Thanks for your interest! A few ground rules keep this project friendly to
the international Ubuntu Touch community:

## Language

- **Issues and pull requests:** English preferred, Russian accepted.
- **Code comments, commit messages, docs:** English only for new code.
  Existing Russian comments are translated opportunistically — when you
  touch a file anyway, feel free to translate its comments in the same PR
  (but keep pure-translation changes in separate commits to preserve
  `git blame` usability).
- **UI strings:** will move to gettext/`.po` (UBports Weblate) — see the
  [roadmap](docs/ROADMAP.md).

## Workflow

- Small fixes: just open a PR.
- Features: check [issues](https://github.com/mad0ps/soundtype/issues) and
  [milestones](https://github.com/mad0ps/soundtype/milestones) first — the
  roadmap lives there. Comment on an issue to claim it.
- The app builds on the phone itself (`scripts/build.sh`) — no
  cross-compilation needed. See "Development" in [README](README.md).
- Tests run on any machine: `python3 -m pytest tests/` (no phone required —
  pyotherside and the VAD are faked).

## Testing on a device

The keyboard integration patches system files — always test with
`extras/keyboard-integration/install.sh` / `uninstall.sh`, never by editing
`/usr` manually. The scripts keep stock backups and restart the right
services.
