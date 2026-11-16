# Architecture

Two halves joined by a documented protocol ([`PROTOCOL.md`](PROTOCOL.md)):

```
 QML (Quickshell)                         Python backend (stdlib only)
 ┌─────────────────────────┐   NDJSON    ┌──────────────────────────────────┐
 │ Panel + tabs (views)    │  stdin ───▶ │ server.py  dispatch, worker,     │
 │ HueService (singleton)  │ ◀── stdout  │            connector, emitter    │
 │ Strings (i18n catalog)  │             │ ops.py     command → API request │
 │ Model.js (pure logic)   │             │ state.py   cache → snapshot      │
 └─────────────────────────┘             │ bridge.py  pinned TLS, limits    │
                                         │ wallpaper.py, pairing.py, ...    │
                                         └───────────────┬──────────────────┘
                                                         ▼ Hue CLIP v2 + event stream
```

## Rules

* **The backend owns the bridge.** One process, one connection, one rate limiter,
  one serialized command worker. The UI never makes a network call.
* **The UI never edits bridge state.** `HueService` holds the last snapshot.
  A user change is a *pending* entry shown over the snapshot until the command
  finishes and the bridge echoes it (`Model.js`: `remember`, `settle`, `expire`).
  A failed command drops only its own entries.
* **The event stream keeps the snapshot current.** Opening the panel sends
  nothing; `r`, a middle click on the bar button and the recovery card's Retry
  send `refresh`, an in-place resync that keeps the connection and stream (with
  no connection it reconnects at once). A dropped or idle stream reconnects
  silently.
  A new or forgotten bridge clears the snapshot at once, so no room from the
  old bridge is shown while the new one loads.
* **One service, many bars.** `HueService` is a QML singleton, so every
  monitor's bar shares one backend.
* **Pure logic is testable.** `Model.js` and `colour.py`/`ops.py`/`state.py`
  have no I/O; `bridge.py` and `server.py` take injected fakes. `Model.js`
  functions that return words take a translator (`tr`) instead of holding English.
* **Every word on screen comes from `qml/i18n/`.** See *Translations* below.
* **Security.** The bridge's private-CA certificate is pinned by SHA-256
  fingerprint (trust on first use), and a missing pin is treated as a changed
  certificate: only link-button pairing, the openhue import and `pair.trust`
  may contact an unpinned bridge. The key file is mode 0600; every id that
  reaches a URL is validated as a UUID; names and enums are allow-listed.

## Where wallpaper sync fits

It is a backend module, `backend/hue_backend/wallpaper.py`, run by the same
server: it watches Omarchy's current-background symlink, extracts a palette
(ImageMagick, ffmpeg for video), and submits ordinary `set` commands through
the shared worker, so it shares the connection and rate limits and cannot fight
the UI. Settings are `wallpaper.config` / `wallpaper.sync` commands plus a
`wallpaper` event; the QML side is only `WallpaperCard.qml`. Its settings live in
`settings.json` (migrated once from `~/.config/omarchy/hue-wallpaper.json`).

## Translations

The host's mechanism (`$OMARCHY_PATH/default/agents/skills/omarchy/plugins.md`,
"Translations"): flat catalogs `qml/i18n/<code>.json`, read through
`Commons.Translations`, following Setup > Language live. A missing string falls
back to the base language, then `en.json`, then the key.

* `Strings.qml` is a singleton holding the one `Commons.Translations` reader, so
  a repeated delegate does not open three catalog files each. Views call
  `Hue.Strings.t(key, args…)`, `tn(key, count, args…)` (plural; `%1` is the
  count, written with the language's digits) and `label(prefix, value, fallback)`
  for bridge enums such as effects (`effect.candle`), falling back to the
  prettified id.
* Holes are filled in one pass by `Model.fill`, so a `%2` inside a bridge name
  or error is left alone. Sentences are whole entries; fragments are never
  glued together.
* `Model.js` (`connectionMessage`, `errorMessage`, `pairFailure`,
  `discoveryFailure`, `ago`, `wallpaperStatus`, `wallpaperHint`) takes `tr`: `Hue.Strings` in QML, a translator built from
  `en.json` in the Node tests. Calls stay inside bindings, and the panel's
  notice keeps the result event, not its text, so a language switch rewords
  everything without a restart.
* Not translated: brand names ("Hue"), glyphs, and text the backend sends
  (device reading labels and values, control labels, `result.message`, bridge
  warnings), which arrive as English. Failure codes are worded from the
  catalog; for pairing and discovery failures `Model.js` also recognises the
  backend's usual messages (no answer, not a bridge, link button not pressed),
  and only an unrecognised one is shown as sent.
* `tests/model.test.js` checks every key the code uses is in `en.json` (and the
  reverse), plural shapes and `%N` numbering. `tests/qml_smoke.py` writes a
  pseudo-locale (`qps`, accented, bracketed, a third longer) into its temp copy
  only, switches to it mid-run and fails if any catalog string is still English.

## Layout

```
manifest.json       entry point: qml/Panel.qml
backend/            python package (`python3 backend serve`)
qml/                the Quickshell plugin (everything the shell loads)
  Model.js            pure view logic        tests/model.test.js
  HueService.qml      singleton: process, state, pending
  Strings.qml         singleton: the i18n catalog reader (Commons.Translations)
  i18n/en.json        the source catalog; add <code>.json per language
  Panel.qml           bar button + panel shell, row keyboard cursor
  *Tab.qml, GroupCard, LightRow, WallpaperCard, PairingView,
  RecoveryView        views (RecoveryView: paired, nothing loaded, bridge unreachable)
  CursorRing.qml      the keyboard cursor's ring, drawn by whichever row has it
  Card/Title/Field/LevelSlider/Chip/Link/Caption/...          small widgets
docs/               ARCHITECTURE, PROTOCOL, PRIVACY, screenshots
tools/              capture_fixture.py (records and sanitises the test fixture)
tests/              python (unittest) + node tests; fixtures/ is a recorded bridge
                    dump whose ids, names, schedule and timestamps are replaced
                    with synthetic values (tools/capture_fixture.py)
tests/qml/          the offscreen harness's shell (qml_smoke.py)
tools/              capture_fixture.py
```

Run tests: `python3 -m unittest discover -s tests`, `node --test tests/model.test.js`, `python3 tests/qml_smoke.py` (offscreen render of every view, English then the pseudo-locale; `HUE_QML_REAL=1` uses your own bridge, `HUE_QML_SHOTS=DIR` keeps the PNGs).

## Not done yet

* Translations beyond English: the mechanism and `en.json` are in place; no
  other language ships yet.
* Right-to-left mirroring (Arabic, Hebrew, Persian, Urdu): the panel is built on
  `KeyboardPanel`, but rows that place things by explicit anchors have not been
  checked mirrored.
* Backend-sent display text (device readings, control labels, errors) is
  English; translating it needs ids in the protocol, not labels.
* Packaging.

Decided: the row keyboard cursor is done (`Panel.qml`, `CursorRing.qml`, logic
in `Model.js`). Settings stay in the panel and `settings.json`, not in the
manifest: they are runtime state the backend owns, shared by every bar.

## Scripting

`python3 backend status | toggle | room IDS… | scene ID` are one-shot commands
for scripts (a custom bar module, a key binding, a cron job). Each opens its own
short connection with the same credentials and pinning.
