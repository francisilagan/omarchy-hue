# Privacy

This plugin talks to your Hue bridge over your local network and nothing else.
It has no telemetry, analytics or accounts.

## What leaves your network

Only one thing can, and only when you ask: **"Find my bridge"** requests
`https://discovery.meethue.com` (Signify's discovery service). That request
reveals your public IP address to Signify. It is never made automatically;
pairing by "Use my openhue login" or a typed IP address makes no cloud call.
(`backend/hue_backend/pairing.py`, `discover_cloud`.)

All other traffic goes to your bridge's address: HTTPS requests to its CLIP v2
API and its event stream. Discovery results are only accepted when they are
private or link-local IPv4 addresses, so the cloud answer cannot point the
plugin at a public host.

Wallpaper sync runs local programs (`magick`, `ffmpeg`) on the wallpaper file;
nothing is uploaded. Their input is closed and `ffmpeg`'s temporary frame is
deleted even when it fails.

## Application key

Pairing creates an application key on the bridge. It is stored in
`$XDG_CONFIG_HOME/omarchy/hue-lights/bridge.json` (default
`~/.config/omarchy/hue-lights/`), written atomically with mode 0600 inside a
directory set to 0700. The key is held only by the backend process and never
sent to the QML side. "Forget bridge" deletes the file.

When pairing, the bridge is told an application name, which it stores with the
key and shows in the Hue app's list of connected apps. The plugin always sends
the fixed name `omarchy-hue#desktop`: it does not include your machine's
hostname or anything else that identifies you. (Versions before this change
sent `omarchy-hue#` plus the first 19 characters of the hostname; a key paired
that way keeps that name on the bridge until you remove it in the Hue app.)
Only the application key is requested, not an entertainment client key. Revoke the key on the
bridge itself (Hue app or API) if you want it invalid, not just forgotten.

## TLS pinning

Bridges use a certificate signed by a private root, so normal certificate
validation cannot work. Instead the plugin uses trust on first use: when you
pair (or import an openhue login), it records the SHA-256 fingerprint of the
certificate the bridge presents and checks every later connection, including
the event stream, against it. If the certificate differs, the connection state
becomes "certificate changed" and no traffic is sent until you choose to trust
the new certificate (which records the new fingerprint) or forget the bridge.
A changed certificate can mean the bridge was reset or replaced, or that
something on your network is impersonating it. A stored bridge with no recorded
fingerprint (for example a hand-written `bridge.json`) is treated the same way:
the plugin never sends the key to an unpinned bridge outside pairing, import or
an explicit "trust".

### What trust on first use does and does not protect

The first contact is deliberately unverified: when you pair, import an openhue
login, or choose "trust" after a certificate change, the plugin connects without
checking the certificate against any authority and records whatever certificate
answered (`pairing.link_button` for pairing, `credentials.fetch_fingerprint` for
import and re-trust). Every later connection must match that record exactly.

* **Protects against:** a device that starts impersonating the bridge *after*
  pairing (for example by ARP or DNS spoofing on your LAN). Without the bridge's
  private key it cannot complete a handshake with the pinned certificate, so
  the plugin drops the connection before sending the key or any command.
* **Does not protect against:** an attacker who is already on your network at
  that first moment. If something answers in place of the bridge while you pair,
  import or re-trust, its certificate is the one pinned. It then sees the
  application key (the stored one after an import or re-trust; the new one if it
  relays a pairing to the real bridge) and can keep relaying traffic unnoticed.
  Pair on a network you trust, and if "certificate changed" appears without you
  having reset or replaced the bridge, check the bridge before trusting it.

## Logging

The log (`$XDG_STATE_HOME/omarchy/hue-lights/hue.log`, default
`~/.local/state/omarchy/hue-lights/`, rotated at 256 KiB with two backups; the
log and both backups are created mode 0600 every time, including after a
rotation) records connection state changes, command failure codes, wallpaper palette
errors, and each wallpaper sync: the wallpaper's file name (not its folder),
how many lights were coloured and the colours as hex codes, or why a sync was
skipped (disabled, not connected, no eligible lights, no usable colours). A
wallpaper whose colours cannot be read is logged once, not on every retry.
Unexpected internal errors are logged with a Python traceback (code locations
and the exception text, which can quote the single value that caused the error,
such as a malformed field from the bridge; the code never logs keys or request
bodies). The code logs no keys, request bodies or reply payloads, and
invalid input lines are logged without their content.

## Other files read

`~/.config/openhue/config.yaml` (only when you choose "Use my openhue login")
and the current wallpaper file.
