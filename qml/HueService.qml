pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model
import "." as Hue

// The one connection to the Hue bridge, shared by every bar on every monitor.
//
// It owns the backend process (backend/, NDJSON over stdin/stdout, see
// PROTOCOL.md) and everything the views read: the bridge's last snapshot, the
// connection state, pending (not yet confirmed) changes and wallpaper-sync
// settings. Views never talk to the bridge; they call the functions below.
Singleton {
  id: root

  readonly property string pluginDir: decodeURIComponent(String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "")).replace(/\/$/, "")

  // ---- connection -----------------------------------------------------------
  property bool started: false
  property string conn: "connecting"     // see PROTOCOL.md: conn.state
  property string connDetail: ""
  readonly property bool connected: conn === "connected"
  // Nothing has loaded and the bridge cannot be reached (or connecting is
  // taking far too long): the panel offers Retry and pairing elsewhere instead
  // of empty tabs. Cleared once a snapshot arrives or pairing takes over.
  property bool stalled: false
  property int connectGraceMs: 12000
  onConnChanged: {
    if (conn === "unreachable" && !loaded) stalled = true
    else if (conn !== "connecting" && conn !== "unreachable") stalled = false
    if (conn === "unpaired") _clearSnapshot()   // forgotten (here or elsewhere): old rooms must not linger
  }
  onLoadedChanged: if (loaded) stalled = false
  // The last command problem or bridge warning, shown briefly. Kept as the
  // result event and worded in a binding, so a language switch rewords it.
  property var _noticeEvent: null
  readonly property string notice: _noticeEvent === null ? ""
                                 : _noticeEvent.ok ? String(_noticeEvent.warnings[0])   // the bridge's own words
                                 : Model.errorMessage(_noticeEvent, Hue.Strings)
  readonly property bool noticeIsError: _noticeEvent !== null && !_noticeEvent.ok

  // ---- bridge truth (never edited by the UI) --------------------------------
  property bool loaded: false
  property var bridge: ({ id: "", name: "", host: "" })
  property string homeGroup: ""
  property var groups: []
  property var lights: ({})              // id -> light
  property var scenes: ({})
  property var smartScenes: ({})
  property var automations: []
  property var devices: []
  property var entertainment: []

  // ---- what the user asked for, until the bridge confirms -------------------
  property var pending: ({})
  property int dragCount: 0              // sliders being dragged; the panel must not scroll
  property var expanded: ({})
  property string confirmKey: ""

  // ---- pairing --------------------------------------------------------------
  // state: idle | starting (sent, no answer yet) | waiting_button | paired | failed;
  // a failure keeps the backend's `code` (when sent) and `message`.
  readonly property var pairIdle: ({ state: "idle", secondsLeft: 0, message: "" })
  property var pair: pairIdle
  readonly property bool pairWaiting: pair.state === "starting" || pair.state === "waiting_button"
  // The user started a link-button flow and has not cancelled it. Pair events
  // carry no flow id, so this tells the current flow's progress from a
  // superseded one's late "cancelled" or "failed".
  property bool _pairActive: false
  property string _pairHost: ""
  property var discovered: []
  property bool discovering: false
  property bool discoverDone: false      // a search finished (found or not)
  property var discoverError: null       // its failed result event, worded in the view

  // ---- wallpaper sync -------------------------------------------------------
  property var wallpaper: ({ enabled: false, targets: [], turnOn: false, transitionMs: 2500 })
  property var palette: []
  property real appliedAt: 0              // epoch seconds of the last apply; 0 = never
  property int appliedCount: 0           // lights the last apply coloured
  property int eligible: 0               // colour lights the next apply would reach
  property bool wallpaperStatsKnown: false  // false for a backend that does not send the counts
  // Sync is on but no palette arrived well after the backend started: the
  // palette is read at start, so the first event is empty for a moment.
  property bool paletteMissing: false
  property int paletteGraceMs: 8000

  // ---- derived --------------------------------------------------------------
  function groupLights(g) {
    var out = []
    for (var i = 0; i < g.lightIds.length; i++) { var l = lights[g.lightIds[i]]; if (l) out.push(l) }
    return out
  }
  function groupScenes(g) {
    var out = []
    for (var i = 0; i < g.sceneIds.length; i++) { var s = scenes[g.sceneIds[i]]; if (s) out.push(s) }
    return out
  }
  function groupSmartScenes(g) {
    var out = []
    for (var i = 0; i < g.smartSceneIds.length; i++) { var s = smartScenes[g.smartSceneIds[i]]; if (s) out.push(s) }
    return out
  }
  function effLight(g, l) { return Model.effLight(pending, g.id, l) }
  function effGroup(g) { return Model.effGroup(pending, g, groupLights(g)) }
  function effFlag(key, fallback) { return Model.flag(pending, key, fallback) }
  readonly property var counts: Model.lightsOn(pending, groups, lights)
  readonly property bool anyOn: counts.on > 0
  readonly property var allLights: Object.keys(lights).map(function(k) { return lights[k] })

  // ---- commands -------------------------------------------------------------
  property int _seq: 0
  property var _handlers: ({})

  function send(cmd, fields, onResult) {
    if (!proc.running) return 0
    var id = ++_seq
    var msg = Object.assign({}, fields || {}, { id: id, cmd: cmd })
    if (onResult) { var h = Object.assign({}, _handlers); h[id] = onResult; _handlers = h }
    proc.write(JSON.stringify(msg) + "\n")
    return id
  }

  function _remember(key, fields, cmdId) { pending = Model.remember(pending, key, fields, cmdId, Date.now()) }

  // Fire a command and remember what it should look like, tied to that command.
  function _optimistic(key, fields, cmd, args) {
    var id = send(cmd, args)
    if (id > 0) _remember(key, fields, id)
  }

  function setGroup(g, f) { _optimistic("g:" + g.id, f, "set", Object.assign({ kind: "group", ids: [g.group] }, f)) }
  function setLight(l, f) { _optimistic("l:" + l.id, f, "set", Object.assign({ kind: "light", ids: [l.id] }, f)) }
  function setEffect(l, effect) {
    var f = { effect: effect }
    if (effect !== "no_effect") f.on = true
    _optimistic("l:" + l.id, f, "set", Object.assign({ kind: "light", ids: [l.id] }, f))
  }
  function setGroupEffect(g, effect) {
    var ls = groupLights(g)
    for (var i = 0; i < ls.length; i++)
      if (effect === "no_effect" || ls[i].effects.indexOf(effect) >= 0) setEffect(ls[i], effect)
  }
  function setTimedEffect(l, effect) {
    _optimistic("l:" + l.id, { on: true }, "set", { kind: "light", ids: [l.id], on: true, timed: { effect: effect, duration: 600000 } })
  }
  function setAll(on) {
    if (groups.length === 0) return
    var ids = []
    if (homeGroup !== "") ids = [homeGroup]
    else for (var i = 0; i < groups.length; i++) if (groups[i].kind === "room") ids.push(groups[i].group)
    var id = send("set", { kind: "group", ids: ids, on: on })
    if (id === 0) return
    for (var j = 0; j < groups.length; j++) _remember("g:" + groups[j].id, { on: on }, id)
  }
  function identify(l) { send("set", { kind: "light", ids: [l.id], identify: true }) }
  function recallScene(s, mode) { send("scene.recall", { id: s.id, mode: mode || "active" }) }
  function setSmartScene(s, activate) { _optimistic("s:" + s.id, { flag: activate }, "smartScene", { id: s.id, action: activate ? "activate" : "deactivate" }) }
  function setAutomation(a, enabled) { _optimistic("a:" + a.id, { flag: enabled }, "automation", { id: a.id, enabled: enabled }) }
  function setEnabled(c, enabled) { _optimistic("x:" + c.id, { flag: enabled }, "enable", { rtype: c.rtype, id: c.id, enabled: enabled }) }
  function rename(rtype, id, name) { send("rename", { rtype: rtype, id: id, name: name }) }
  function refresh() { send("refresh") }

  // Destructive actions need a second click within three seconds.
  function confirmed(key) {
    if (confirmKey === key) { confirmKey = ""; return true }
    confirmKey = key
    confirmClear.restart()
    return false
  }
  function toggleExpanded(id) { var e = Object.assign({}, expanded); e[id] = !e[id]; expanded = e }
  function isOpen(id) { return expanded[id] === true }
  function drag(on) { dragCount = Math.max(0, dragCount + (on ? 1 : -1)) }

  // ---- wallpaper ------------------------------------------------------------
  function setWallpaper(partial) { send("wallpaper.config", partial) }
  function toggleWallpaperTarget(id) {
    var t = (wallpaper.targets || []).slice()
    var at = t.indexOf(id)
    if (at >= 0) t.splice(at, 1); else t.push(id)
    setWallpaper({ targets: t })
  }
  function syncWallpaperNow() { send("wallpaper.sync") }

  // ---- pairing --------------------------------------------------------------
  function importOpenhue() { send("pair.importOpenhue") }
  // A failed search is shown in the pairing view (as a discovery problem), not
  // as a header notice about the bridge.
  function discover() {
    discovered = []
    discoverError = null
    discoverDone = false
    var id = send("pair.discover", {}, _onDiscoverResult)
    discovering = id > 0
    if (id > 0) discoverWatchdog.restart()
    else { discoverDone = true; discoverError = { ok: false, code: "internal", message: "" } }
  }
  function _onDiscoverResult(e) {
    discovering = false
    discoverDone = true
    discoverWatchdog.stop()
    if (!e.ok) discoverError = e
    return true
  }
  function _pairFailed(code, message) {
    pair = { state: "failed", secondsLeft: 0, message: message || "", code: code }
    pairWatchdog.stop()
  }
  function startPairing(host) {
    _pairHost = host
    _pairActive = true
    pair = { state: "starting", secondsLeft: 0, message: "" }
    var id = send("pair.start", { host: host }, _onPairStartResult)
    if (id > 0) pairWatchdog.restart()
    else _pairFailed("internal", "")
  }
  // A bad host is refused at once, with no `pair` event to follow.
  function _onPairStartResult(e) {
    if (e.ok || !pairWaiting) return false
    _pairActive = false
    _pairFailed(e.code, e.message)
    return true
  }
  // Local first: Cancel always works, even if the backend never answers.
  function cancelPairing() { _pairActive = false; pair = pairIdle; pairWatchdog.stop(); send("pair.cancel") }
  function trustBridge() { send("pair.trust") }
  function forgetNow() { _clearSnapshot(); send("pair.forget") }
  function forgetBridge() { if (confirmed("forget")) forgetNow() }

  // Another bridge (or none): nothing from the old one may be shown.
  function _clearSnapshot() {
    loaded = false
    bridge = ({ id: "", name: "", host: "" })
    homeGroup = ""
    groups = []
    lights = ({})
    scenes = ({})
    smartScenes = ({})
    automations = []
    devices = []
    entertainment = []
    pending = ({})
    expanded = ({})
  }

  function _onPair(e) {
    if (e.state === "paired") {
      // Paired at another address than the shown bridge's: another bridge (or
      // the same one moved, whose snapshot then differs in `bridge.host` and is
      // re-sent). Drop the old rooms now. The same address keeps them: the
      // backend does not re-send a snapshot identical to its last one.
      if (bridge.host !== "" && _pairHost !== bridge.host) _clearSnapshot()
      _pairActive = false; pair = e; pairWatchdog.stop()
      return
    }
    if (e.state === "waiting_button") {
      if (!_pairActive) return          // late progress from a flow the user cancelled
      pair = e
      pairWatchdog.restart()
      return
    }
    if (!pairWaiting) return
    if (e.state === "cancelled") {      // only ever a superseded flow while one is active
      if (!_pairActive) { pair = pairIdle; pairWatchdog.stop() }
      return
    }
    if (e.state === "failed") _pairFailed(e.code || "", e.message)
  }

  // ---- incoming -------------------------------------------------------------
  function _say(resultEvent) {
    _noticeEvent = resultEvent
    noticeClear.restart()
  }

  function _onResult(e) {
    pending = Model.settle(pending, e.id, e.ok, Date.now())
    var h = _handlers[e.id]
    var shown = false                     // a handler returns true when it shows the problem itself
    if (h) { var rest = Object.assign({}, _handlers); delete rest[e.id]; _handlers = rest; shown = h(e) === true }
    if (!shown && (!e.ok || (e.warnings && e.warnings.length > 0))) _say(e)
  }

  function _onState(d) {
    if (d.bridge && d.bridge.id && bridge.id !== "" && d.bridge.id !== bridge.id) { pending = ({}); expanded = ({}) }
    bridge = d.bridge
    homeGroup = d.homeGroup || ""
    groups = d.groups
    lights = d.lights
    scenes = d.scenes
    smartScenes = d.smartScenes
    automations = d.automations
    devices = d.devices
    entertainment = d.entertainment
    loaded = true
  }

  function _onEvent(e) {
    switch (e.event) {
    case "ready": break
    case "conn": conn = e.state; connDetail = e.detail || ""; break
    case "state": _onState(e.data); break
    case "result": _onResult(e); break
    case "pair": _onPair(e); break
    case "discovered": discovering = false; discovered = e.bridges || []; break
    case "wallpaper":
      wallpaper = e.config
      palette = e.palette || []
      appliedAt = e.appliedAt || 0
      appliedCount = e.appliedCount || 0
      eligible = e.eligible || 0
      wallpaperStatsKnown = e.eligible !== undefined && e.eligible !== null
      if (palette.length > 0 || !wallpaper || wallpaper.enabled !== true) { paletteTimer.stop(); paletteMissing = false }
      else if (!paletteMissing && !paletteTimer.running) paletteTimer.start()
      break
    }
  }

  Process {
    id: proc
    command: ["python3", root.pluginDir + "/../backend", "serve"]
    running: root.started
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) {
        try { root._onEvent(JSON.parse(line)) } catch (e) { console.warn("hue: unreadable backend line") }
      }
    }
    onExited: function(code) {
      root.conn = "connecting"
      root.pending = ({})
      root.discovering = false
      if (root.pairWaiting) root.pair = root.pairIdle
      root._pairActive = false
      root.paletteMissing = false
      paletteTimer.stop()
      if (root.started) restart.restart()
    }
  }
  Timer { id: restart; interval: 3000; onTriggered: if (root.started) proc.running = true }

  // Panels call this when they appear; the backend keeps running while any exist.
  function start() { started = true }

  // A guess nothing confirmed is abandoned rather than shown forever.
  Timer {
    interval: 500; repeat: true; running: Model.hasPending(root.pending)
    onTriggered: root.pending = Model.expire(root.pending, Date.now())
  }
  // The backend answers a search within its own timeout and ends a link-button
  // wait after about 40 s; past these, stop waiting on it.
  Timer {
    id: discoverWatchdog; interval: 20000
    onTriggered: if (root.discovering) { root.discovering = false; root.discoverDone = true; root.discoverError = { ok: false, code: "timeout", message: "" } }
  }
  Timer { id: pairWatchdog; interval: 60000; onTriggered: if (root.pairWaiting) root._pairFailed("timeout", "") }
  Timer {
    interval: root.connectGraceMs
    running: root.started && root.conn === "connecting" && !root.loaded && !root.stalled
    onTriggered: root.stalled = true
  }
  Timer { id: paletteTimer; interval: root.paletteGraceMs; onTriggered: root.paletteMissing = root.palette.length === 0 && root.wallpaper.enabled === true }
  Timer { id: confirmClear; interval: 3000; onTriggered: root.confirmKey = "" }
  Timer { id: noticeClear; interval: 6000; onTriggered: root._noticeEvent = null }
}
