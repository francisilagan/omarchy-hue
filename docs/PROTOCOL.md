# Backend protocol (v1)

The QML panel starts one long-lived process:

```
python3 <plugin>/backend serve
```

The panel and the backend use **newline-delimited JSON** (one object per line, UTF-8).
The panel sends commands on **stdin**. The backend sends events on **stdout**.
The backend writes nothing else to stdout. It writes diagnostics to the rotating log file.
The process stops when stdin closes. Thus, a reload of the shell does not leave the process running.

Bridge credentials never cross this channel.

## Commands (client → backend)

Each command has the form `{"id": <int>, "cmd": "<name>", ...fields}`. The backend sends exactly one `result` event with the same `id` for each command.

| cmd | fields | notes |
|---|---|---|
| `refresh` | | Reads again every resource over the existing connection. Sends `state` if a value changed. The backend keeps the connection and the event stream, so commands sent at the same time are not affected. If there is no connection, the backend tries to connect again now. |
| `set` | `kind` (`light`\|`group`), `ids[]`, any of `on`, `pct`, `hex`, `mirek`, `effect`, `timed{effect,duration}`, `duration` (ms), `identify` | A `group` id is the `group` field of the group (its grouped_light). It is not the room id. |
| `scene.recall` | `id`, `mode` (`active`\|`dynamic_palette`\|`static`), `duration?`, `pct?` | |
| `scene.create` | `name`, `group` (room/zone id) | Saves the current look of the group. |
| `scene.update` | `id`, `name?`, `speed?`, `autoDynamic?`, `snapshot?` | `snapshot: true` saves the current look again. |
| `scene.delete` | `id` | |
| `smartScene` | `id`, `action` (`activate`\|`deactivate`) | |
| `automation` | `id`, `enabled` | |
| `rename` | `rtype` (`light`\|`room`\|`zone`\|`scene`\|`smart_scene`\|`device`), `id`, `name` | When you rename a light, the backend renames its device. |
| `powerup` | `id`, `preset` (`safety`\|`powerfail`\|`last_on_state`) | |
| `zone.create` | `name`, `lights[]` | |
| `zone.members` | `id`, `lights[]` | Replaces the list of members. |
| `zone.delete` | `id` | |
| `enable` | `rtype`, `id`, `enabled` | Sensors. |
| `entertainment.stop` | `id` | |
| `pair.importOpenhue` | | Uses the bridge and the key from the config of the `openhue` CLI. |
| `pair.discover` | | Sends a request to `discovery.meethue.com`. This is a cloud call. Send it only when the user asks. |
| `pair.start` | `host` | Starts pairing with the link button. The backend sends `result` at once and sets `conn: pairing`. Then it sends `pair` events. The time window is about 40 s. |
| `pair.cancel` | | |
| `pair.trust` | | Accepts the new certificate of the bridge after a `cert_changed`. |
| `pair.forget` | | Deletes the stored bridge and the stored key. |
| `wallpaper.config` | any of `enabled`, `targets[]`, `turnOn`, `transitionMs` | Partial update. The backend saves the update. |
| `wallpaper.sync` | | Applies the colours of the wallpaper now. |

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

Wallpaper event fields:

- `palette` is in order of importance. Vivid colours are first, and the most representative colour is the first of these. Near-white and grey filler colours are only after them.
- The lights take the colours of `palette` in turn.
- `appliedCount` is the number of lights that received colours at `appliedAt`.
- `appliedCount` is 0 before the first apply.
- If the backend skips an apply, `appliedAt` and `appliedCount` do not change.
- `eligible` is the number of lights that an apply colours now, with the current `config`.
- `eligible` is 0 when the backend is not connected.
- The backend sends the event again when `eligible` changes.
- The client must set `appliedCount` and `eligible` to 0 when they are absent (older backends).

`conn.state` is one of `connecting`, `connected`, `unpaired`, `unauthorized`, `unreachable`, `cert_changed`, `pairing`.

- After `unpaired`, `unauthorized` and `cert_changed`, the backend waits for a `pair.*` command.
- After `unreachable`, the backend tries again with backoff.
- If a stored bridge has no pinned certificate, the backend reports `cert_changed`. It does not contact the bridge. `pair.trust` records the pin.

The event stream can drop. It can also stay quiet for more than its 150 s read timeout. If the bridge still answers REST requests in these cases, the backend does these steps:

1. It resyncs.
2. It opens the stream again over the same connection.

`conn` stays `connected`. `conn` changes only when the bridge does not answer.

Repeated stream failures cause a backoff. The backoff starts at 1 s and doubles to a maximum of 30 s. The backoff ends when a stream has stayed up for a minute or has delivered events.

A command can arrive while the backend makes a connection (or makes it again). The command waits up to 5 s for the connection. It does not fail at once.

### Result codes

`ok` is true for success, **including partial success**. In partial success, the bridge applies a command but gives a warning. An example is a bulb that is off at the wall. Then `ok` stays true and `warnings` has the text.

When a command fails, `ok` is false and `code` is one of these values:

- `unpaired`
- `unauthorized`
- `unreachable`
- `cert_changed`
- `bridge_error` (the bridge refused; `message` is its text)
- `rate_limited`
- `timeout`
- `invalid` (bad command)
- `internal`

A failure with `unauthorized` or `cert_changed` also causes the backend to resync and to update `conn`.

A failed command affects only itself. The other queued commands still run.

- A command without an integer `id` still runs. It gets no `result`.
- The backend ignores a line that is not a JSON object. It writes a log entry without the content of the line.
- If an unexpected error occurs while the backend handles a command, the backend answers with `internal`. The backend continues to run.
- `wallpaper.config`, `pair.cancel` and `pair.forget` answer at once.
- If `settings.json` cannot be written, `wallpaper.config` answers `internal` and keeps the previous settings.
- The backend queues every other command, `refresh` included. It answers when the command has run.
- If a pairing fails for any reason, the backend sends a `pair` event with state `failed` and a `message`.

Validation (`ops.py`):

- Each id that goes into a URL must be a UUID.
- A name must have 1-32 characters.
- The backend clamps `pct` to 1-100.
- The backend clamps `mirek` to the range of the light.
- The backend uses an allow-list for the enum fields (`mode`, `preset`, `rtype`, `kind`).
- `effect` and `timed.effect` must have only lowercase letters and underscores. They must have at most 40 characters (`candle`, `no_effect`, `sunrise`).
- `effect`, `timed` and `identify` apply to `kind: light` only.
- If a command has both `hex` and `mirek`, `hex` wins.
- `enable` accepts an `rtype` of `motion`, `camera_motion`, `light_level`, `temperature` or `contact`.
- `pair.start` with a bad `host` answers `invalid`.
- Any unknown `pair.*` name answers `invalid`.

## Snapshot

The backend normalises the state and uses the id as the key. Thus, the panel can keep one delegate for each object.

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

- The backend combines a burst of `state` events into one event. It never sends identical snapshots again.
- The backend omits `battery` when the device does not report it.
- `mirek` is null when a light is in colour mode.
- `device` is the id of the physical device that owns the light. A device can own more than one light. When you rename a light, the backend renames that device.
- The server sets `bridge.host` from the stored credentials. The snapshot never includes the key or the fingerprint.
- `devices` does not list the devices that own a light.

## Connection security

A bridge shows a certificate that a private root signs. The backend uses trust on first use:

1. The first time a host is paired or imported, the backend records the SHA-256 fingerprint of the certificate.
2. The backend pins this fingerprint.
3. Each later connection must show the same certificate. This includes the event stream.

If the certificate is different, the backend sets `conn: cert_changed` and sends no traffic. The user must confirm with `pair.trust`.

## Files

| path | contents |
|---|---|
| `$XDG_CONFIG_HOME/omarchy/hue-lights/bridge.json` (0600) | host, bridge id, application key, pinned fingerprint |
| `$XDG_CONFIG_HOME/omarchy/hue-lights/settings.json` (0600) | wallpaper sync settings |
| `$XDG_STATE_HOME/omarchy/hue-lights/hue.log`, `.1`, `.2` (all 0600, also after rotation) | diagnostics; never payloads or keys |
