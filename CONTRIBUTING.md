# Contributing

## Run the tests

```
python3 -m unittest discover -s tests     # backend, no bridge needed
node --test tests/model.test.js           # pure view logic in qml/Model.js
python3 tests/qml_smoke.py                # every view, offscreen
```

The smoke test needs `quickshell` and Omarchy's shell modules; point
`OMARCHY_SHELL` at them if they are not in `/usr/share/omarchy/shell`.
`HUE_QML_REAL=1` uses your own bridge instead of the recorded fixture.
`tools/capture_fixture.py` records a fixture from your bridge with ids, names,
schedule and timestamps replaced by synthetic values; run it with `--check` and
read the result for personal data before committing:
`python3 tools/capture_fixture.py --check tests/fixtures/bridge_resource.json`
(`tests/test_fixture.py` enforces the same check).

## Architecture rules (see docs/ARCHITECTURE.md)

- The backend owns the bridge. The UI never makes network calls.
- The UI never edits bridge state; it shows pending changes over the last snapshot.
- Keep logic pure and testable (`qml/Model.js`, `colour.py`, `ops.py`, `state.py`);
  inject fakes into `bridge.py` and `server.py`.
- Python stays standard library only and works on 3.9+.
- Every id that reaches a URL is validated; names and enums are allow-listed.
- Never log keys, request bodies or payloads.
- No English in the QML: every user-visible string is an entry in
  `qml/i18n/en.json`, read with `Hue.Strings.t("key", args…)` or, for counts,
  `Hue.Strings.tn("key", n)`; `Model.js` text takes a `tr`. Use a literal key
  (the tests scan for them), whole sentences with `%N` holes, never fragments
  joined together. Brand names and glyphs stay as they are; logs stay English.

## Changing the protocol

`docs/PROTOCOL.md` is the contract. Change it in the same commit as the code on both
sides and the tests. Adding an optional field or a new command is
backwards compatible; renaming, removing or changing meaning is not, and needs
a bump of `PROTOCOL` in `server.py` and a CHANGELOG entry. Update
`CHANGELOG.md` for user-visible changes.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org): `type(scope): summary`,
for example `fix(backend): refuse an empty certificate pin` or `docs: add README
screenshots`. Common types are `feat`, `fix`, `docs`, `test`, `refactor`, `ci` and
`chore`; mark breaking changes with `!` (for example `feat!:`) and explain them in the body.
