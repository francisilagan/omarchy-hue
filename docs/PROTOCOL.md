# Backend protocol (v1)

The QML side starts one long-lived process:

```
python3 <plugin>/backend serve
```

and talks to it with **newline-delimited JSON** (one object per line, UTF-8):
commands go in on **stdin**, events come out on **stdout**. Nothing else is
ever written to stdout; diagnostics go to the rotating log file. The process
exits when stdin closes, so reloading the shell never leaves it behind.

Bridge credentials never cross this channel.

## Commands (client → backend)

Every command is `{"id": <int>, "cmd": "<name>", ...fields}`. The backend answers
each one with exactly one `result` event carrying the same `id`.

| cmd | fields | notes |
|---|---|---|
| `refresh` | | Re-read every resource over the existing connection and emit `state` if anything changed. The connection and event stream are kept, so commands sent around it are unaffected. With no connection, it makes the backend retry connecting now. |
| `set` | `kind` (`light`\|`group`), `ids[]`, any of `on`, `pct`, `hex`, `mirek`, `effect`, `timed{effect,duration}`, `duration` (ms), `identify` | `group` ids are the group's `group` field (its grouped_light), not the room id. |
| `scene.recall` | `id`, `mode` (`active`\|`dynamic_palette`\|`static`), `duration?`, `pct?` | |
| `scene.create` | `name`, `group` (room/zone id) | Saves the group's current look. |
| `scene.update` | `id`, `name?`, `speed?`, `autoDynamic?`, `snapshot?` | `snapshot: true` re-saves the current look. |
| `scene.delete` | `id` | |
| `smartScene` | `id`, `action` (`activate`\|`deactivate`) | |
| `automation` | `id`, `enabled` | |
| `rename` | `rtype` (`light`\|`room`\|`zone`\|`scene`\|`smart_scene`\|`device`), `id`, `name` | Renaming a light renames its device. |
| `powerup` | `id`, `preset` (`safety`\|`powerfail`\|`last_on_state`) | |
| `zone.create` | `name`, `lights[]` | |
| `zone.members` | `id`, `lights[]` | Replaces the member list. |
| `zone.delete` | `id` | |
| `enable` | `rtype`, `id`, `enabled` | Sensors. |
| `entertainment.stop` | `id` | |
| `pair.importOpenhue` | | Adopt the bridge and key from the `openhue` CLI's config. |
| `pair.discover` | | Ask `discovery.meethue.com` (a cloud call; only on request). |
| `pair.start` | `host` | Link-button pairing. Answers `result` at once, sets `conn: pairing`, then emits `pair` events (about 40 s window). |
| `pair.cancel` | | |
| `pair.trust` | | Accept the bridge's new certificate after a `cert_changed`. |
| `pair.forget` | | Delete the stored bridge and key. |
| `wallpaper.config` | any of `enabled`, `targets[]`, `turnOn`, `transitionMs` | Partial update; persists. |
| `wallpaper.sync` | | Apply the wallpaper's colours now. |

## Events (backend → client)

| event | fields |
|---|---|
| `ready` | `protocol` (int), `version` (backend version string) |
| `conn` | `state`, `detail` — see below |
| `state` | `rev` (int, increases), `data` (snapshot, below) |
| `result` | `id`, `ok`, `code`, `message`, `warnings[]` |
| `pair` | `state` (`waiting_button`\|`paired`\|`failed`\|`cancelled`), `message?`, `secondsLeft?` |
| `discovered` | `bridges[]` of `{id, host}` (reply to `pair.discover`) |
| `wallpaper` | `config`, `palette[]`, `appliedAt` (epoch seconds or null), `appliedCount` (int), `eligible` (int); also sent once right after `ready` |

`wallpaper`: `palette` is ordered by importance (vivid colours first, the most
representative one leading; near-white/grey filler only after them); lights
take colours in turn. `appliedCount` is how many lights the apply at
`appliedAt` sent colours to (0 before the first apply; a skipped apply leaves
both unchanged). `eligible` is how many lights an apply would colour right now
under the current `config` (0 while not connected); the event is re-sent when
it changes. Clients should default both to 0 when absent (older backends).

`conn.state` is one of `connecting`, `connected`, `unpaired`, `unauthorized`,
`unreachable`, `cert_changed`, `pairing`. After `unpaired`, `unauthorized` and
`cert_changed` the backend waits for a `pair.*` command; after `unreachable` it
retries with backoff. A stored bridge with no pinned certificate is reported as
`cert_changed` without contacting it (`pair.trust` records the pin).

If the event stream drops (or stays quiet past its 150 s read timeout) while the
bridge still answers REST requests, the backend resyncs and reopens the stream
over the same connection: `conn` stays `connected`. Only when the bridge itself
stops answering does `conn` change. Repeated stream failures back off (1 s
doubling to 30 s) until a stream has stayed up for a minute or delivered events.
A command that arrives while a connection is being (re)established waits up to
5 s for it instead of failing at once.

### Result codes

`ok` is true for success, **including partial success**: when the bridge applied
a command but warned about it (for example a bulb that is switched off at the
wall), `ok` stays true and `warnings` carries the text. Failures set `ok` false
with one of: `unpaired`, `unauthorized`, `unreachable`, `cert_changed`,
`bridge_error` (the bridge refused; `message` is its text), `rate_limited`,
`timeout`, `invalid` (bad command), `internal`. A `unauthorized` or
`cert_changed` failure also makes the backend resync and update `conn`.

A failed command affects only itself: other queued commands still run.
Commands without an integer `id` still run but get no `result`; a line that is
not a JSON object is ignored (and logged without its content). An unexpected
error while handling a command answers it with `internal` and the backend keeps
running. `wallpaper.config` and `pair.cancel`/`pair.forget` answer immediately
(`wallpaper.config` answers `internal` and keeps the previous settings when
`settings.json` cannot be written); every other command, `refresh` included, is
queued and answered when it has run. A pairing that fails for any reason ends
with a `pair` event of state `failed` and a `message`.

Validation (`ops.py`): every id that reaches a URL must be a UUID; names are
1-32 characters; `pct` is clamped to 1-100; `mirek` is clamped to the light's
range; enum fields (`mode`, `preset`, `rtype`, `kind`) are allow-listed.
`effect` and `timed.effect` must be lowercase letters and underscores, at most
40 characters (`candle`, `no_effect`, `sunrise`). `effect`, `timed` and
`identify` apply to `kind: light` only. If both `hex`
and `mirek` are given, `hex` wins. `enable` accepts `rtype` of `motion`,
`camera_motion`, `light_level`, `temperature` or `contact`. `pair.start`
with a bad `host` and any unknown `pair.*` name answer `invalid`.

## Snapshot

State is normalised and keyed by id so the UI can keep one delegate per object.

```jsonc
{
  "bridge":      { "id": "…", "host": "192.168.1.2", "name": "Hue Bridge" },
  "homeGroup":   "<grouped_light id for 'all lights'>",
  "groups":      [ { "id", "kind": "room|zone", "name", "archetype",
                     "group": "<grouped_light id>", "on",
                     "lightIds": [], "sceneIds": [], "smartSceneIds": [] } ],
  "lights":      { "<id>": { "id", "name", "archetype", "on", "brightness", "dimmable",
                     "reachable", "color", "ct", "mirek", "mirekMin", "mirekMax", "hex",
                     "effects": [], "effect", "timedEffects": [], "timedEffect",
                     "gradient", "powerup", "product",
                     "device": "<id of the owning device>" } },
  "scenes":      { "<id>": { "id", "name", "group", "active", "mode", "speed",
                     "autoDynamic", "dynamic", "lights" } },
  "smartScenes": { "<id>": { "id", "name", "group", "active" } },
  "automations": [ { "id", "name", "enabled", "status", "script" } ],
  "devices":     [ { "id", "name", "product", "software", "bridge", "reachable",
                     "battery?", "update?", "readings": [{label, value}],
                     "controls": [{rtype, id, label, enabled}] } ],
  "entertainment": [ { "id", "name", "status", "type", "lights" } ]
}
```

`state` events are coalesced and identical snapshots are never re-sent.
`battery` is omitted when the device does not report it.
`mirek` is null when a light is in colour mode. `device` is the id of the
physical device that owns the light (a device can own several lights); renaming
a light renames that device. `bridge.host` is filled in by the server from the
stored credentials; the key and fingerprint are never included. Devices that
own a light are not listed in `devices`.

## Connection security

Bridges present a certificate signed by a private root. The first time a host is
paired or imported, the backend records the SHA-256 fingerprint of the
certificate it presents (trust on first use) and pins it: every later
connection, including the event stream, must present the same certificate.
A different certificate yields `conn: cert_changed` and no traffic until the
user confirms with `pair.trust`.

## Files

| path | contents |
|---|---|
| `$XDG_CONFIG_HOME/omarchy/hue-lights/bridge.json` (0600) | host, bridge id, application key, pinned fingerprint |
| `$XDG_CONFIG_HOME/omarchy/hue-lights/settings.json` (0600) | wallpaper sync settings |
| `$XDG_STATE_HOME/omarchy/hue-lights/hue.log`, `.1`, `.2` (all 0600, also after rotation) | diagnostics; never payloads or keys |

