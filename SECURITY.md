# Security policy

## Reporting a vulnerability

Report security problems in private. Use the GitHub
[private vulnerability reporting](https://github.com/francisilagan/omarchy-hue/security/advisories/new).
Do not use a public issue. Include these items:

- What you saw.
- The version of the plugin.
- The version of Omarchy.

Expect a reply within a week.

## What matters here

The backend stores the Hue application key (`~/.config/omarchy/hue-lights/bridge.json`,
mode 0600). The backend pins the TLS certificate of the bridge on first use.
These topics are in scope:

- Key storage.
- Certificate pinning.
- The protocol between the panel and the backend.
- Anything that sends data off the machine.

See [docs/PRIVACY.md](docs/PRIVACY.md) for the data that the plugin sends and does not send.

## Supported versions

Only the latest release is supported.
