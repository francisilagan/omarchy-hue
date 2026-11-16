#!/usr/bin/env python3
"""Every QML view builds against the recorded bridge snapshot (offscreen quickshell).

Fails on any view that does not load, and on any QML error or warning the run prints.
Runs in English, then switches the language to a pseudo-locale ("qps", generated
here from qml/i18n/en.json and never shipped) to prove the views read the catalogs
and re-render live.
Needs quickshell and Omarchy's qs.Commons / qs.Ui (set OMARCHY_SHELL to override).
"""
import json, os, re, shutil, subprocess, sys, tempfile, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = Path(os.environ.get("OMARCHY_SHELL", "/usr/share/omarchy/shell"))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

if shutil.which("quickshell") is None or not SHELL.is_dir():
    raise SystemExit("quickshell and Omarchy's shell modules are required")

import support
from hue_backend import state

if os.environ.get("HUE_QML_REAL"):  # your own bridge, for a local check
    snapshot = json.loads(subprocess.run([sys.executable, str(ROOT / "backend"), "snapshot"], capture_output=True, text=True, check=True).stdout)
else:
    snapshot = state.build_snapshot(support.cache_from(support.fixture()))
env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QML_XHR_ALLOW_FILE_READ="1")

# A test translation: every letter accented, bracketed, about a third longer (to
# show what a longer language does to the layout), with %N holes kept.
ACCENTS = str.maketrans("aceinousyACEINOUSY", "áçéîñöüšýÅÇÉÎÑÖÜŠÝ")
def pseudo(text):
    parts = re.split(r"(%\d+)", text)
    body = "".join(p if re.fullmatch(r"%\d+", p) else p.translate(ACCENTS) for p in parts)
    return "[" + body + "~" * (len(text) // 3) + "]"

for k in ("WAYLAND_DISPLAY", "DISPLAY", "QT_QPA_PLATFORMTHEME"):
    env.pop(k, None)

with tempfile.TemporaryDirectory(prefix="hue-qml-") as d:
    h = Path(d)
    (h / "qml").mkdir()  # the plugin's own layout: qml/ beside backend/
    for f in (ROOT / "qml").glob("*.qml"):
        if f.name != "Panel.qml":
            shutil.copy(f, h / "qml" / f.name)
    for name in ("Model.js", "qmldir"):
        shutil.copy(ROOT / "qml" / name, h / "qml" / name)
    shutil.copytree(ROOT / "qml/i18n", h / "qml/i18n")
    english = json.loads((ROOT / "qml/i18n/en.json").read_text())
    (h / "qml/i18n/qps.json").write_text(json.dumps({k: pseudo(v) if isinstance(v, str) else {c: pseudo(f) for c, f in v.items()} for k, v in english.items()}, ensure_ascii=False))
    # Pin the language whatever this machine uses; the harness switches it later.
    (h / "language").write_text("en\n")
    env["OMARCHY_LANGUAGE_FILE"] = str(h / "language")
    # The harness runs the views without the real backend. A stand-in takes its
    # place: it stays up (so the service keeps whatever state the harness sets),
    # never answers, and records every command so the harness can check them.
    (h / "backend").mkdir()
    commands = h / "commands.ndjson"
    commands.write_text("")
    (h / "backend/__main__.py").write_text(
        "import sys\n"
        "with open(%r, 'a') as log:\n"
        "    for line in sys.stdin:\n"
        "        log.write(line); log.flush()\n" % str(commands))
    (h / "shell.qml").write_text((ROOT / "tests/qml/shell.qml").read_text().replace("SNAPSHOT", json.dumps(snapshot)).replace("OUTDIR", json.dumps(os.environ.get("HUE_QML_SHOTS", str(h)))).replace("LANGFILE", json.dumps(str(h / "language"))).replace("COMMANDLOG", json.dumps(str(commands))).replace("ENGLISH", json.dumps(english, ensure_ascii=False)))
    # Panel.qml under another name: it extends qs.Ui's Panel, so a Panel.qml beside
    # it would resolve that name to itself.
    shutil.copy(ROOT / "qml/Panel.qml", h / "qml/BarPanel.qml")
    with open(h / "qml/qmldir", "a") as q:
        q.write("BarPanel 1.0 BarPanel.qml\n")
    (h / "Commons").symlink_to(SHELL / "Commons")
    # qs.Ui as shipped, but KeyboardPanel is a layer-shell window (no backend
    # offscreen), so a plain Item with the same properties stands in for it.
    shutil.copytree(SHELL / "Ui", h / "Ui", symlinks=True)
    shutil.copy(ROOT / "tests/qml/KeyboardPanel.qml", h / "Ui/KeyboardPanel.qml")
    runtime = h / "runtime"; runtime.mkdir(mode=0o700)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    p = subprocess.Popen(["quickshell", "-p", str(h)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    t = threading.Timer(40, p.kill); t.start()
    lines = []
    for line in p.stdout:
        lines.append(line)
        if re.search(r"qml:\s+(ALL OK|\d+ FAILED)", re.sub(r"\x1b\[[0-9;]*m", "", line)):
            break
    p.wait(timeout=10) if False else None
    import time; time.sleep(1.5)
    t.cancel(); p.kill(); p.wait()

plain = re.sub(r"\x1b\[[0-9;]*m", "", "".join(lines))
bad = [l for l in plain.splitlines() if re.search(r"ERROR|FAIL|(WARN.*(binding|TypeError|ReferenceError|is not a type|Cannot assign|Cannot read))", l)]
print("\n".join(l for l in plain.splitlines() if "qml:" in l or "ERROR" in l or "WARN" in l)[-4000:])
if bad or "ALL OK" not in plain:
    print("\n".join(bad))
    raise SystemExit("FAILED")
print("qml smoke ok")
