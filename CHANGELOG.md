# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-16

First release.

### Features
- Rooms and zones: power, brightness, colour, white temperature and effects for
  a whole group or each light, power-up behaviour, flash, rename, and creating
  and deleting zones.
- Scenes (static or dynamic, speed, auto-dynamic, re-save, delete), routines
  (smart scenes), saving the current look as a scene.
- Automations, entertainment areas, and devices (bridge, sensors, switches,
  battery, connectivity, firmware, enabling and disabling sensors).
- Wallpaper sync: paints colour lights with the wallpaper's vivid colours and
  follows wallpaper changes; shows what was applied and how many lights are
  eligible.
- Live updates through the bridge's event stream; changes made elsewhere appear
  within a moment, and the panel shows your change immediately while the bridge
  confirms it.
- Pairing: reuse an openhue login, find the bridge, or enter its address and
  press the link button.
- Keyboard: tab switching, a row cursor with `Space`/`Enter`, scrolling, and the
  global keys `r`, `a`, `1`-`4`.
- Translations through Omarchy's `Commons.Translations` (English catalog).
- Theming that matches Omarchy's own panels.

### Design
- Python backend (standard library only) and QML frontend joined by a documented
  newline-delimited JSON protocol (`docs/PROTOCOL.md`); one connection shared by every
  monitor's bar.
- Certificate pinning (trust on first use, SHA-256 fingerprint) with a
  "certificate changed" flow; application key kept in a 0600 file; rotating
  0600 log that never holds keys; every id, name and enum validated before it
  reaches a URL.
- Python unit tests, Node tests for view logic, and an offscreen QML smoke test.

[1.0.0]: https://github.com/francisilagan/omarchy-hue/releases/tag/v1.0.0
