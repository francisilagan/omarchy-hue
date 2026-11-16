"""Finding and pairing with a bridge: cloud discovery (opt-in) and the link-button flow."""
from __future__ import annotations

import http.client
import ipaddress
import json
import re
import threading
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .bridge import BridgeError, FirstContactConnection, PinnedConnection
from .credentials import Credentials

DISCOVERY_URL = "https://discovery.meethue.com"
# The application name the bridge stores with the key (shown in the Hue app).
# Fixed and generic on purpose: it never contains the machine's hostname.
DEVICE_TYPE = "omarchy-hue#desktop"
LINK_BUTTON_TIMEOUT = 40.0
LAN_NETWORKS = [ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")]
KEY_RE = re.compile(r"[A-Za-z0-9_\-]{1,128}")


def lan_address(value: Any) -> bool:
    """True for a dotted IPv4 literal in a private or link-local range (what a bridge on this LAN has)."""
    if not isinstance(value, str):
        return False
    try:
        ip = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return any(ip in net for net in LAN_NETWORKS)


def discover_cloud(timeout: float = 8.0) -> List[Dict[str, str]]:
    """Bridges on this network, as reported by Signify's discovery service.

    This is a cloud request (it reveals your public IP to Signify), so it only
    runs when the user asks for it. Only private or link-local IPv4 addresses
    are accepted: a host name or a public address is not a bridge on this LAN.
    """
    req = urllib.request.Request(DISCOVERY_URL, headers={"User-Agent": "omarchy-hue"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - fixed https URL, default TLS validation
            data = json.loads(resp.read().decode())
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise BridgeError("unreachable", "discovery failed (%s)" % exc.__class__.__name__) from None
    if not isinstance(data, list):
        return []
    return [{"id": str(b.get("id", ""))[:64], "host": b["internalipaddress"]}
            for b in data if isinstance(b, dict) and lan_address(b.get("internalipaddress"))]


def _error_of(item: Optional[dict]) -> Dict[str, Any]:
    err = item.get("error") if item else None
    return err if isinstance(err, dict) else {}


def link_button(host: str, stop: threading.Event, progress: Callable[[int], None],
                connection_factory: Callable[..., PinnedConnection] = FirstContactConnection,
                sleep: Callable[[float], None] = time.sleep, timeout: float = LINK_BUTTON_TIMEOUT,
                interval: float = 2.0) -> Credentials:
    """Wait for the user to press the bridge's link button, then create an application key.

    The certificate the bridge presents on this first contact is pinned
    (trust on first use). Raises BridgeError on timeout or failure.
    """
    deadline = time.monotonic() + timeout
    # Only the CLIP application key is requested: the entertainment client key is never used.
    body = json.dumps({"devicetype": DEVICE_TYPE}).encode()
    while not stop.is_set():
        left = deadline - time.monotonic()
        if left <= 0:
            raise BridgeError("timeout", "the link button was not pressed in time")
        progress(int(left))
        conn = connection_factory(host, "", 6.0)
        try:
            conn.request("POST", "/api", body=body, headers={"Content-Type": "application/json"})
            raw = conn.getresponse().read()
            fingerprint = conn.observed
        except (OSError, http.client.HTTPException) as exc:
            raise BridgeError("unreachable", "cannot reach the bridge (%s)" % exc.__class__.__name__) from None
        finally:
            conn.close()
        try:
            reply = json.loads(raw.decode() or "[]")
        except ValueError:
            raise BridgeError("bridge_error", "the bridge sent a reply that is not JSON") from None
        item = reply[0] if isinstance(reply, list) and reply and isinstance(reply[0], dict) else None
        success = item.get("success") if item else None
        if success is not None:
            key = success.get("username") if isinstance(success, dict) else None
            if not isinstance(key, str) or not KEY_RE.fullmatch(key):
                raise BridgeError("bridge_error", "the bridge sent an unexpected reply")
            if not fingerprint:
                raise BridgeError("bridge_error", "the bridge presented no certificate to pin")
            return Credentials(host=host, key=key, fingerprint=fingerprint)
        error = _error_of(item)
        if error.get("type") != 101:  # 101 = link button not pressed
            raise BridgeError("bridge_error", str(error.get("description") or "unexpected reply")[:200])
        sleep(interval)
    raise BridgeError("cancelled", "pairing was cancelled")
