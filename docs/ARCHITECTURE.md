# Architecture

The system has two halves. A documented protocol ([`PROTOCOL.md`](PROTOCOL.md)) joins them.

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

* **The backend owns the bridge.** The backend is one process.
  It has one connection, one rate limiter and one serialized command worker.
  The UI never makes a network call.
* **The UI never edits bridge state.** `HueService` holds the last snapshot.
  A user change is a *pending* entry.
  The UI shows the pending entry over the snapshot until the command finishes and the bridge echoes it
  (`Model.js`: `remember`, `settle`, `expire`).
  A failed command drops only its own entries.
* **The event stream keeps the snapshot current.** When the panel opens, it sends nothing.
  These actions send `refresh`: `r`, a middle click on the bar button and the Retry button on the recovery card.
  `refresh` is an in-place resync. It keeps the connection and the stream.
  If no connection exists, `refresh` reconnects at once.
  A dropped or idle stream reconnects silently.
  A new or forgotten bridge clears the snapshot at once.
  Thus the panel does not show a room from the old bridge while the new bridge loads.
* **One service, many bars.** `HueService` is a QML singleton.
  Every monitor bar shares one backend.
* **Pure logic is testable.** `Model.js`, `colour.py`, `ops.py` and `state.py` have no I/O.
  `bridge.py` and `server.py` take injected fakes.
  `Model.js` functions that return words take a translator (`tr`).
  They do not hold English text.
* **Every word on screen comes from `qml/i18n/`.** See *Translations* below.
* **Security.** The backend pins the private-CA certificate of the bridge by SHA-256 fingerprint (trust on first use).
  A missing pin counts as a changed certificate.
  Only link-button pairing, the openhue import and `pair.trust` can contact an unpinned bridge.
  The key file is mode 0600.
  The backend validates every id that reaches a URL as a UUID.
  The backend allow-lists names and enums.

## Where wallpaper sync fits

Wallpaper sync is a backend module: `backend/hue_backend/wallpaper.py`.
The same server runs it. The module does these steps:

* It watches the current-background symlink of Omarchy.
* It extracts a palette (ImageMagick, ffmpeg for video).
* It submits ordinary `set` commands through the shared worker.

Thus wallpaper sync shares the connection and the rate limits. It cannot conflict with the UI.
The settings are the `wallpaper.config` and `wallpaper.sync` commands and a `wallpaper` event.
The QML side is only `WallpaperCard.qml`.
The settings are in `settings.json`.
The backend migrates them once from `~/.config/omarchy/hue-wallpaper.json`.

## Translations

The host defines the mechanism (`$OMARCHY_PATH/default/agents/skills/omarchy/plugins.md`, "Translations").
The mechanism uses flat catalogs: `qml/i18n/<code>.json`.
`Commons.Translations` reads the catalogs.
The catalogs change at once when the user changes Setup > Language.
If a string is missing, the system uses the base language.
If the string is missing there, the system uses `en.json`, then the key.

* `Strings.qml` is a singleton. It holds the one `Commons.Translations` reader.
  Thus a repeated delegate does not open three catalog files each.
  Views call `Hue.Strings.t(key, args…)`.
  For plurals, views call `tn(key, count, args…)`: `%1` is the count, written with the digits of the language.
  For bridge enums, such as effects (`effect.candle`), views call `label(prefix, value, fallback)`.
  If no catalog entry exists, `label` uses the prettified id.
* `Model.fill` fills all placeholders in one pass.
  Thus a `%2` inside a bridge name or error stays unchanged.
  Sentences are whole entries. The code never joins fragments.
* These `Model.js` functions take `tr`: `connectionMessage`, `errorMessage`, `pairFailure`,
  `discoveryFailure`, `ago`, `wallpaperStatus`, `wallpaperHint`.
  In QML, `tr` is `Hue.Strings`. In the Node tests, `tr` is a translator built from `en.json`.
  Calls stay inside bindings.
  The notice of the panel keeps the result event, not its text.
  Thus a language switch rewords everything without a restart.
* These items are not translated: brand names ("Hue"), glyphs, and text that the backend sends
  (device reading labels and values, control labels, `result.message`, bridge warnings).
  This text arrives in English.
  The catalog supplies the words for failure codes.
  For pairing and discovery failures, `Model.js` also recognises the usual messages of the backend
  (no answer, not a bridge, link button not pressed).
  The panel shows an unrecognised message as sent.
* `tests/model.test.js` checks that every key the code uses is in `en.json`, and the reverse.
  It also checks plural shapes and `%N` numbering.
  `tests/qml_smoke.py` writes a pseudo-locale (`qps`) into its temporary copy only.
  The pseudo-locale has accented text in brackets, one third longer than the original.
  The test switches to the pseudo-locale during the run.
  The test fails if any catalog string is still English.

## Layout

<!-- STE-REVIEW: the code block below lists `tools/` two times. The block is kept exactly as it was. -->
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

Run the tests with these commands:

* `python3 -m unittest discover -s tests`
* `node --test tests/model.test.js`
* `python3 tests/qml_smoke.py`: an offscreen render of every view, in English and then in the pseudo-locale.

Set `HUE_QML_REAL=1` to use your own bridge. Set `HUE_QML_SHOTS=DIR` to keep the PNGs.

## Not done yet

* Translations beyond English: the mechanism and `en.json` exist. No other language is available yet.
* Right-to-left mirroring (Arabic, Hebrew, Persian, Urdu): the panel is built on `KeyboardPanel`.
  Rows that place items with explicit anchors are not checked in a mirrored layout.
* The backend sends display text (device readings, control labels, errors) in English.
  To translate this text, the protocol needs ids, not labels.
* Packaging.

Decided: the row keyboard cursor is done (`Panel.qml`, `CursorRing.qml`, logic in `Model.js`).
Settings stay in the panel and `settings.json`. They do not go in the manifest.
Settings are runtime state. The backend owns this state, and every bar shares it.

## Scripting

These commands run once for scripts (a custom bar module, a key binding, a cron job):
`python3 backend status | toggle | room IDS… | scene ID`.
Each command opens its own short connection.
The connection uses the same credentials and pinning.
