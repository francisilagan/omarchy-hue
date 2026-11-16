"""The paired bridge: host, application key and pinned certificate fingerprint."""
from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from . import paths

OPENHUE_CONFIG = Path.home() / ".config" / "openhue" / "config.yaml"
HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?|[0-9A-Fa-f:]+")  # fullmatch only


@dataclass
class Credentials:
    host: str
    key: str
    bridge_id: str = ""
    fingerprint: str = ""  # sha256 hex of the bridge's certificate (DER), pinned


def path() -> Path:
    return paths.config_dir() / "bridge.json"


def valid_host(host: str) -> bool:
    return isinstance(host, str) and bool(HOST_RE.fullmatch(host))


def load() -> Optional[Credentials]:
    """The stored bridge, or None when unpaired or the file is unusable."""
    try:
        data = json.loads(path().read_text())
        creds = Credentials(host=str(data["host"]), key=str(data["key"]),
                            bridge_id=str(data.get("bridge_id", "")), fingerprint=str(data.get("fingerprint", "")))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return creds if valid_host(creds.host) and creds.key else None


def save(creds: Credentials) -> None:
    """Store the bridge atomically with mode 0600."""
    paths.write_private(path(), json.dumps(asdict(creds), indent=2))


def forget() -> None:
    """Delete the stored bridge and key."""
    try:
        path().unlink()
    except FileNotFoundError:
        pass


def parse_openhue(text: str) -> Optional[Credentials]:
    """Read `bridge:` and `key:` from openhue's flat config. Only top-level keys count."""
    found = {}
    for line in text.splitlines():
        m = re.match(r"^(bridge|key)\s*:\s*['\"]?([^'\"#\s]+)['\"]?\s*(#.*)?$", line)
        if m:
            found[m.group(1)] = m.group(2)
    key = found.get("key", "")
    # Application keys are plain tokens; this also rejects YAML block markers such as `key: |`.
    if "bridge" in found and re.fullmatch(r"[A-Za-z0-9_\-]+", key) and valid_host(found["bridge"]):
        return Credentials(host=found["bridge"], key=key)
    return None


def import_openhue(config: Path = OPENHUE_CONFIG) -> Optional[Credentials]:
    """Credentials from the openhue CLI config, or None."""
    try:
        return parse_openhue(config.read_text())
    except OSError:
        return None


def fetch_fingerprint(host: str, timeout: float = 6.0, port: int = 443) -> str:
    """The sha256 fingerprint of the certificate `host` presents right now (trust on first use)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # identity is established by pinning, see PROTOCOL.md
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=None) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise ssl.SSLError("bridge presented no certificate")
    return hashlib.sha256(der).hexdigest()
