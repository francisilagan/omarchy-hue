# Changelog

This file lists all notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-16

First release.

### Features
- Rooms and zones:
  - Control power, brightness, colour, white temperature and effects for a whole group
    or for each light.
  - Set power-up behaviour, flash and rename.
  - Create and delete zones.
- Scenes:
  - Static or dynamic scenes, speed, auto-dynamic, re-save and delete.
  - Routines (smart scenes).
  - Save the current look as a scene.
- Automations, entertainment areas and devices (bridge, sensors, switches,
  battery, connectivity, firmware, enable and disable of sensors).
- Wallpaper sync: paints colour lights with the vivid colours of the wallpaper.
  It follows changes of the wallpaper.
  It shows what the plugin applied and how many lights are eligible.
- Live updates through the event stream of the bridge. Changes made elsewhere appear
  within a short time. The panel shows your change immediately while the bridge
  confirms it.
- Pairing: reuse an openhue login, find the bridge, or enter its address and
  press the link button.
- Keyboard: tab switching, a row cursor with `Space`/`Enter`, scrolling, and the
  global keys `r`, `a`, `1`-`4`.
- Translations through `Commons.Translations` of Omarchy (English catalog).
- Theming that matches the own panels of Omarchy.

### Design
- A Python backend (standard library only) and a QML frontend. A documented
  newline-delimited JSON protocol joins them (`docs/PROTOCOL.md`).
  The bar of every monitor shares one connection.
- Certificate pinning (trust on first use, SHA-256 fingerprint) with a
  "certificate changed" flow.
- The application key is kept in a 0600 file.
- The log rotates, has mode 0600 and never holds keys.
- The backend validates every id, name and enum before it reaches a URL.
- Python unit tests, Node tests for view logic, and an offscreen QML smoke test.

[1.0.0]: https://github.com/francisilagan/omarchy-hue/releases/tag/v1.0.0
