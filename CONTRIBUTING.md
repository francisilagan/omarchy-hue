# Contributing

## Run the tests

```
python3 -m unittest discover -s tests     # backend, no bridge needed
node --test tests/model.test.js           # pure view logic in qml/Model.js
python3 tests/qml_smoke.py                # every view, offscreen
```

The smoke test needs `quickshell` and the shell modules of Omarchy.
If they are not in `/usr/share/omarchy/shell`, set `OMARCHY_SHELL` to their path.
Set `HUE_QML_REAL=1` to use your own bridge instead of the recorded fixture.

`tools/capture_fixture.py` records a fixture from your bridge.
It replaces ids, names, schedule and timestamps with synthetic values.
Before you commit, run it with `--check`.
Read the result for personal data:
`python3 tools/capture_fixture.py --check tests/fixtures/bridge_resource.json`.
`tests/test_fixture.py` enforces the same check.

## Architecture rules (see docs/ARCHITECTURE.md)

- The backend owns the bridge. The UI never makes network calls.
- The UI never edits bridge state. It shows pending changes over the last snapshot.
- Keep logic pure and testable (`qml/Model.js`, `colour.py`, `ops.py`, `state.py`).
  Inject fakes into `bridge.py` and `server.py`.
- Python must use the standard library only. Python must work on 3.9+.
- You must validate every id that reaches a URL. You must allow-list names and enums.
- Do not log keys, request bodies or payloads.
- Do not put English in the QML. Every user-visible string must be an entry in `qml/i18n/en.json`.
  - Read a string with `Hue.Strings.t("key", args…)`. For counts, use `Hue.Strings.tn("key", n)`.
  - `Model.js` text must take a `tr`.
  - You must use a literal key (the tests scan for literal keys).
  - Use whole sentences with `%N` placeholders. Do not join fragments.
  - Brand names and glyphs stay as they are. Logs stay English.

## Changing the protocol

`docs/PROTOCOL.md` is the contract.
You must change it in the same commit as the code on both sides and the tests.

* These changes are backwards compatible: add an optional field, add a new command.
* These changes are not backwards compatible: rename, remove, change the meaning.
  They need a bump of `PROTOCOL` in `server.py` and a CHANGELOG entry.

You must update `CHANGELOG.md` for user-visible changes.

## Commit messages

You must use [Conventional Commits](https://www.conventionalcommits.org): `type(scope): summary`.
Examples: `fix(backend): refuse an empty certificate pin` and `docs: add README screenshots`.
Common types are `feat`, `fix`, `docs`, `test`, `refactor`, `ci` and `chore`.
Mark a breaking change with `!` (for example `feat!:`). Explain it in the body.
