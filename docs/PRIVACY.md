# Privacy

This plugin sends data to your bridge on your local network and to no other host.
It has no telemetry, analytics or accounts.

## What leaves your network

Only one action can send data out. It occurs only when you ask for it.
The command **"Find my bridge"** sends a request to `https://discovery.meethue.com`
(the discovery service of Signify). This request shows your public IP address to Signify.
The plugin does not make this request automatically.
Pairing with "Use my openhue login" or with a typed IP address makes no cloud call.
(`backend/hue_backend/pairing.py`, `discover_cloud`.)

All other traffic goes to the address of your bridge. This traffic is HTTPS requests to
the CLIP v2 API of the bridge and to its event stream.
The plugin accepts discovery results only when they are private or link-local IPv4 addresses.
Thus the cloud answer cannot point the plugin at a public host.

Wallpaper sync runs local programs (`magick`, `ffmpeg`) on the wallpaper file.
The plugin uploads nothing.
<!-- STE-REVIEW: "Their input is closed" is ambiguous in the original (probably the program stdin or the input file handle). The original wording is kept. -->
The plugin closes their input.
The plugin deletes the temporary frame of `ffmpeg` also when `ffmpeg` fails.

## Application key

Pairing creates an application key on the bridge. The plugin stores the key in
`$XDG_CONFIG_HOME/omarchy/hue-lights/bridge.json` (default
`~/.config/omarchy/hue-lights/`). The plugin writes the file atomically with mode 0600
inside a directory set to 0700. Only the backend process holds the key.
The backend never sends the key to the QML side. The command "Forget bridge" deletes the file.

During pairing, the plugin sends an application name to the bridge. The bridge stores the name
with the key and shows it in the list of connected apps in the Hue app.
The plugin always sends the fixed name `omarchy-hue#desktop`.
It does not include the hostname of your machine or other data that identifies you.
(Versions before this change sent `omarchy-hue#` plus the first 19 characters of the hostname.
A key paired in that way keeps that name on the bridge until you remove it in the Hue app.)
The plugin requests only the application key. It does not request an entertainment client key.
To make the key invalid, revoke it on the bridge (Hue app or API). To forget the key is not sufficient.

## TLS pinning

Bridges use a certificate signed by a private root. Thus normal certificate validation
cannot work. The plugin uses trust on first use instead.
When you pair (or import an openhue login), the plugin records the SHA-256 fingerprint
of the certificate that the bridge presents.
The plugin checks every later connection against this fingerprint, including the event stream.
If the certificate is different, the connection state becomes "certificate changed".
The plugin then sends no traffic until you do one of these actions:

- Trust the new certificate. The plugin then records the new fingerprint.
- Forget the bridge.

A changed certificate can mean one of these:

- The bridge was reset or replaced.
- Something on your network is impersonating the bridge.

The plugin treats a stored bridge with no recorded fingerprint in the same way
(for example, a `bridge.json` written by hand).
The plugin never sends the key to an unpinned bridge, except during pairing, import
or an explicit "trust".

### What trust on first use does and does not protect

The first contact is unverified by design. This applies when you pair, import an openhue login,
or choose "trust" after a certificate change.
The plugin connects without a check of the certificate against an authority.
The plugin records the certificate of whatever device answered
(`pairing.link_button` for pairing, `credentials.fetch_fingerprint` for import and re-trust).
Every later connection must match that record exactly.

* **Protects against:** a device that starts to impersonate the bridge *after*
  pairing (for example by ARP or DNS spoofing on your LAN). Without the private key of the bridge,
  the device cannot complete a handshake with the pinned certificate.
  The plugin thus drops the connection before it sends the key or a command.
* **Does not protect against:** an attacker who is on your network at
  that first moment. If a device answers in place of the bridge while you pair,
  import or re-trust, the plugin pins the certificate of that device. The device then sees
  the application key (the stored key after an import or re-trust; the new key if it
  relays a pairing to the real bridge). The device can relay traffic and you do not see it.
  Pair on a network that you trust. If "certificate changed" appears and you did not reset
  or replace the bridge, check the bridge before you trust it.

## Logging

The log is at `$XDG_STATE_HOME/omarchy/hue-lights/hue.log`
(default `~/.local/state/omarchy/hue-lights/`). The plugin rotates the log at 256 KiB
and keeps two backups. The plugin creates the log and both backups with mode 0600 every time,
also after a rotation.

The log records these items:

- Changes of the connection state.
- Failure codes of commands.
- Wallpaper palette errors.
- Each wallpaper sync: the file name of the wallpaper (not its folder), how many lights
  the plugin coloured and the colours as hex codes, or the reason the plugin skipped a sync
  (disabled, not connected, no eligible lights, no usable colours).

The plugin logs a wallpaper with unreadable colours once. It does not log it on every retry.

The plugin logs unexpected internal errors with a Python traceback. The traceback has code locations
and the exception text. The exception text can quote the single value that caused the error,
for example a malformed field from the bridge.
The code never logs keys or request bodies.
The code logs no keys, request bodies or reply payloads.
The code logs invalid input lines without their content.

## Other files read

The plugin reads these files:

- `~/.config/openhue/config.yaml` (only when you choose "Use my openhue login").
- The current wallpaper file.
