# Security policy

## Reporting a vulnerability

Please report security problems privately, using GitHub's
[private vulnerability reporting](https://github.com/francisilagan/omarchy-hue/security/advisories/new)
rather than a public issue. Include what you saw, the plugin version and your
Omarchy version. Expect a reply within a week.

## What matters here

The backend stores the Hue application key (`~/.config/omarchy/hue-lights/bridge.json`,
mode 0600) and pins the bridge's TLS certificate on first use. Reports about key
storage, certificate pinning, the protocol between the panel and the backend,
or anything that sends data off the machine are in scope. See
[docs/PRIVACY.md](docs/PRIVACY.md) for what is and isn't sent.

## Supported versions

Only the latest release is supported.
