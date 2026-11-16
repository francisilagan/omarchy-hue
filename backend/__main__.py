"""Entry point: `python3 backend <serve|snapshot|version|status|toggle|room|scene>`."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hue_backend import cli, credentials, paths, server  # noqa: E402
from hue_backend.bridge import BridgeClient, BridgeError  # noqa: E402
from hue_backend.state import Cache, build_snapshot  # noqa: E402


def main(argv):
    command = argv[0] if argv else "serve"
    if command == "version":
        print(server.VERSION)
        return 0
    if command in ("status", "toggle", "room", "scene"):
        # One-shot script commands: no log file (it belongs to the running service).
        return cli.run(argv)
    if command not in ("serve", "snapshot"):
        print("usage: backend [serve|snapshot|version|status|toggle|room|scene]", file=sys.stderr)
        return 2
    paths.setup_logging()
    if command == "serve":
        # stdout carries the protocol and nothing else: stray prints go to stderr.
        out, sys.stdout = sys.stdout, sys.stderr
        server.Server(out).run(sys.stdin)
        return 0
    return snapshot()


def snapshot(load_credentials=credentials.load, client_factory=BridgeClient, out=None, err=None):
    """Debugging aid: print one snapshot as JSON. Read-only; one line on stderr on failure."""
    out, err = out or sys.stdout, err or sys.stderr
    creds = load_credentials()
    if creds is None:
        err.write("hue: not paired with a bridge (open the Hue panel to pair)\n")
        return 1
    client = None
    try:
        client = client_factory(creds)
        cache = Cache()
        cache.load(client.resources())
        out.write(json.dumps(build_snapshot(cache), indent=2) + "\n")
        out.flush()
        return 0
    except BridgeError as exc:
        err.write("hue: %s: %s\n" % (exc.code, exc.message))
        return 1
    except BrokenPipeError:  # e.g. `| head`: the reader left, nothing to report
        if out is sys.stdout:
            try:
                sys.stdout = open(os.devnull, "w")  # keep the interpreter's final flush quiet
            except OSError:
                pass
        return 0
    except KeyboardInterrupt:
        err.write("hue: interrupted\n")
        return 130
    except Exception as exc:  # noqa: BLE001 - a debugging aid gets one line, never a traceback
        err.write("hue: snapshot failed (%s: %s)\n" % (exc.__class__.__name__, exc))
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
