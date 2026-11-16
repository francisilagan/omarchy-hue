"""Where this plugin keeps its files, following the XDG base directory spec."""
from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

APP = Path("omarchy") / "hue-lights"


def _base(env: str, fallback: str) -> Path:
    value = os.environ.get(env, "")
    return Path(value) if value and os.path.isabs(value) else Path.home() / fallback


def config_dir() -> Path:
    return _base("XDG_CONFIG_HOME", ".config") / APP


def state_dir() -> Path:
    return _base("XDG_STATE_HOME", ".local/state") / APP


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def write_private(path: Path, text: str) -> None:
    """Atomically write a file that only the owner can read."""
    ensure_private_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)  # a stale temp file may have looser permissions
            f.write(text)
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise


def _chmod_private(path: str) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class PrivateRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating log whose file and backups are always mode 0600, whatever the umask.

    The stock handler opens each new file with the umask (usually 0644) after
    every rollover; this one creates it 0600 and tightens the backups too.
    """

    def _open(self):  # type: ignore[override]
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.fchmod(fd, 0o600)  # an existing file may have been created looser
        except OSError:
            pass
        return os.fdopen(fd, "a", encoding=self.encoding, errors=getattr(self, "errors", None))

    def doRollover(self) -> None:
        super().doRollover()
        for i in range(1, self.backupCount + 1):
            name = "%s.%d" % (self.baseFilename, i)
            if os.path.exists(name):
                _chmod_private(name)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """A small rotating log. Messages never contain keys or request bodies."""
    log = logging.getLogger("hue")
    if log.handlers:
        return log
    log.setLevel(level)
    try:
        d = ensure_private_dir(state_dir())
        handler: logging.Handler = PrivateRotatingFileHandler(
            str(d / "hue.log"), maxBytes=256 * 1024, backupCount=2, encoding="utf-8"
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.propagate = False
    return log
