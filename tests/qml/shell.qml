import Quickshell
import Quickshell.Io
import QtQuick
import "qml" as Hue

// Loads every view against the recorded bridge snapshot, offscreen, and checks
// that each one builds and takes up room. QML load and binding errors print to
// the log, which tests/qml_smoke.py also fails on.
ShellRoot {
  FloatingWindow {
    visible: true
    implicitWidth: 400
    implicitHeight: 3000
    color: "#1a1b26"
   Item {
    id: harness
    anchors.fill: parent
    property int failures: 0
    readonly property var snapshot: SNAPSHOT
    readonly property var english: ENGLISH   // i18n/en.json
    FileView { id: languageFile; path: LANGFILE }
    // How many `cmd` commands the service sent to the stand-in backend
    // (qml_smoke.py logs them). A synchronous file read: QML_XHR_ALLOW_FILE_READ.
    function sent(cmd) {
      var xhr = new XMLHttpRequest()
      xhr.open("GET", "file://" + COMMANDLOG, false)
      xhr.send()
      var lines = String(xhr.responseText).split("\n"), n = 0
      for (var i = 0; i < lines.length; i++) {
        if (lines[i] === "") continue
        try { if (JSON.parse(lines[i]).cmd === cmd) n++ } catch (e) {}
      }
      return n
    }

    readonly property QtObject ui: QtObject {
      readonly property color foreground: "#c0c8e0"
      readonly property color panelBackground: "#1a1b26"
      readonly property color dim: "#7a8099"
      readonly property string fontFamily: "monospace"
      readonly property var bar: null
      readonly property string cursor: ""
    }

    function check(name, ok, detail) {
      if (ok) console.log("  ok   " + name)
      else { failures++; console.log("  FAIL " + name + (detail ? ": " + detail : "")) }
    }

    Component.onCompleted: {
      var svc = Hue.HueService
      svc._onEvent({ event: "conn", state: "connected", detail: "" })
      svc._onEvent({ event: "state", rev: 1, data: harness.snapshot })
      svc._onEvent({ event: "wallpaper", config: { enabled: true, targets: [], turnOn: false, transitionMs: 2500 }, palette: ["#aa3355", "#3355aa"], appliedAt: 0 })
      check("snapshot reached the service", svc.loaded && svc.groups.length > 0 && Object.keys(svc.lights).length > 0)
      check("light count is derived", svc.counts.total === 5, JSON.stringify(svc.counts))
      barPanel.tab = "lights"
      checkTimer.start()
    }

    Timer {
      id: checkTimer
      interval: 800
      onTriggered: {
        var names = ["lights", "scenes", "automations", "devices", "pairing"]
        for (var i = 0; i < names.length; i++) {
          var l = loaders.itemAt(i)
          harness.check(names[i] + " view is built", l && l.item !== null)
          harness.check(names[i] + " view takes room", l && l.item && l.item.height > 30, l && l.item ? "height " + l.item.height : "no item")
        }
        harness.grabToImage(function(r) { r.saveToFile(OUTDIR + "/views.png") })
        barPanel.tab = "lights"
        tabTimer.start()
      }
    }

    // The real Panel.qml (as BarPanel.qml, with a stand-in KeyboardPanel): the
    // layer the view checks above cannot see. Every tab must be built by its
    // Loader, take room, and the scroll area must grow to fit it.
    Hue.BarPanel { id: barPanel; x: 0; y: 0 }

    function walk(item, out) {
      var kids = item.children
      for (var i = 0; i < kids.length; i++) {
        var k = kids[i]
        if (k.contentHeight !== undefined && k.flickableDirection !== undefined) out.flick = k
        if (k.sourceComponent !== undefined && k.active !== undefined) out.loaders.push(k)
        walk(k, out)
      }
    }
    property var tabOrder: ["lights", "automations", "scenes", "devices"]
    property int tabStep: 0
    // Scrolled down on a tall tab, then a short one: nothing may be left
    // scrolled past its end (that was the blank "Auto" tab).
    function scrollChecks(out) {
      var f = out.flick
      var name = tabOrder[tabStep]
      check("panel '" + name + "' is not scrolled past its content", f.contentY <= Math.max(0, f.contentHeight - f.height) + 0.5, "contentY " + f.contentY + " contentHeight " + f.contentHeight + " height " + f.height)
    }
    function panelTabChecks() {
      var out = { flick: null, loaders: [] }
      walk(barPanel, out)
      check("panel scroll area exists", out.flick !== null)
      var name = tabOrder[tabStep]
      var found = null
      for (var i = 0; i < out.loaders.length; i++) {
        var l = out.loaders[i]
        if (l.item && l.item.height > 30 && l.active && l.item.svc !== undefined) found = l
      }
      check("panel '" + name + "' tab is built", found !== null, "tab=" + barPanel.tab)
      if (found) {
        check("panel '" + name + "' tab has room", found.height > 30 && found.item.height > 30, "loader " + found.height + " item " + found.item.height)
        check("panel '" + name + "' content height follows", out.flick.contentHeight >= found.item.height, out.flick.contentHeight + " vs " + found.item.height)
      }
      var active = 0
      for (var j = 0; j < out.loaders.length; j++) if (out.loaders[j].active && out.loaders[j].sourceComponent && out.loaders[j].item && out.loaders[j].item.svc !== undefined) active++
      check("panel '" + name + "' builds only its own tab", active === 1, "active tabs " + active)
      // An unloaded Loader used to keep its last height, stacking every tab
      // visited above the next one: a blank Auto tab under an empty Lights.
      var stale = 0
      for (var m = 0; m < out.loaders.length; m++) if (out.loaders[m].parent.parent === out.flick.contentItem && !out.loaders[m].item && out.loaders[m].height > 0) stale++
      check("panel '" + name + "': unloaded tabs take no room", stale === 0, stale + " stale loaders")
      return out
    }
    Timer {
      id: tabTimer
      interval: 400
      onTriggered: {
        var o = harness.panelTabChecks()
        harness.scrollChecks(o)
        if (harness.tabStep === 0) { o.flick.contentY = Math.max(0, o.flick.contentHeight - o.flick.height); console.log("scrolled lights to " + o.flick.contentY + " of " + o.flick.contentHeight + " in " + o.flick.height) }
        var card = o.flick.parent.parent.parent
        if (harness.tabOrder[harness.tabStep] === "automations") card.grabToImage(function(r) { r.saveToFile(OUTDIR + "/panel-automations.png"); harness.advance() })
        else harness.advance()
      }
    }
    function advance() {
      tabStep++
      if (tabStep < tabOrder.length) { barPanel.tab = tabOrder[tabStep]; tabTimer.restart() }
      else {
        barPanel.tab = "lights"
        barPanel.stepTab(-1)
        check("keyboard: left of the first tab stays put", barPanel.tab, "lights")
        barPanel.stepTab(1)
        check("keyboard: right moves to the next tab", barPanel.tab, "scenes")
        barPanel.stepTab(9)
        check("keyboard: right of the last tab stays put", barPanel.tab === "devices", barPanel.tab)
        barPanel.tab = "lights"
        stepTimer.restart()
      }
    }

    // ---- keyboard cursor and wallpaper readout: one step per tick ----------
    property int step: 0
    property int langWaits: 0
    property bool grabbing: false
    // Last thing a step does: the grab renders later, so the next step waits for it.
    function shot(item, name) {
      grabbing = true
      item.grabToImage(function(r) { r.saveToFile(OUTDIR + "/" + name); grabbing = false; stepTimer.restart() })
    }
    function card() { var o = { flick: null, loaders: [] }; walk(barPanel, o); return o.flick.parent.parent.parent }
    property var keyCatcher: null
    function findKeyCatcher(item) {
      var kids = item.children
      for (var i = 0; i < kids.length; i++) {
        if (kids[i].blocked !== undefined && kids[i].moveRequested !== undefined) return kids[i]
        var f = findKeyCatcher(kids[i]); if (f) return f
      }
      return null
    }
    function down(n) { for (var i = 0; i < n; i++) keyCatcher.moveRequested(0, 1) }
    function key() { return barPanel.rowCursor.key }
    function cursorInView() {
      var o = { flick: null, loaders: [] }; walk(barPanel, o)
      var spot = barPanel.cursorSpots().byKey[key()]
      if (!spot) return "no row for " + key()
      var p = spot.item.mapToItem(o.flick.contentItem, 0, 0)
      var ok = p.y >= o.flick.contentY - 0.5 && p.y + spot.h <= o.flick.contentY + o.flick.height + 0.5
      return ok ? "" : "row " + p.y + "+" + spot.h + " view " + o.flick.contentY + "+" + o.flick.height
    }
    // Visible text in the panel that is word for word an English catalog string.
    function texts(item, out) {
      var kids = item.children
      for (var i = 0; i < kids.length; i++) {
        var k = kids[i]
        if (!k.visible) continue
        if (typeof k.text === "string" && k.elide !== undefined && k.text !== "") out.push(k.text)
        texts(k, out)
      }
      return out
    }
    function englishTexts() {
      var forms = {}
      for (var key in english) {
        var v = english[key]
        if (typeof v === "string") forms[v] = true
        else for (var c in v) forms[v[c]] = true
      }
      var all = texts(harness, [])   // the standalone views, the panel and the wallpaper card
      // ▸/▾ disclosure prefixes are glyphs, not words
      return all.filter(function(t) { return forms[t.replace(/^[▸▾] /, "")] === true && t !== "Hue" })
    }
    function headerText() {   // the line under the "Hue" heading
      var all = texts(barPanel, [])
      var at = all.indexOf("Hue")
      return at >= 0 && at + 1 < all.length ? all[at + 1] : ""
    }
    function tabLabels() { return texts(barPanel, []) }
    function visibleText(item, t) { return texts(item, []).indexOf(t) >= 0 }
    function findAll(item, pred, out) {
      out = out || []
      var kids = item.children
      for (var i = 0; i < kids.length; i++) {
        if (!kids[i].visible) continue
        if (pred(kids[i])) out.push(kids[i])
        findAll(kids[i], pred, out)
      }
      return out
    }
    function findButton(item, t) {
      var b = findAll(item, function(i) { return i.text === t && typeof i.clicked === "function" && i.bordered !== undefined })
      return b.length > 0 ? b[0] : null
    }
    function wallpaperEvent(extra) {
      Hue.HueService._onEvent(Object.assign({ event: "wallpaper", config: { enabled: true, targets: [], turnOn: false, transitionMs: 2500 }, palette: ["#aa3355", "#3355aa"], appliedAt: 0 }, extra))
    }
    readonly property var steps: [
      function() {
        keyCatcher = findKeyCatcher(barPanel)
        check("cursor: key catcher found", keyCatcher !== null)
        check("cursor: hidden until the first move", key() === "", key())
        var s = barPanel.cursorSpots()
        var g0 = Hue.HueService.groups[0].id
        check("cursor: lights rows start with the first room's switch", s.keys[0] === "g:" + g0, s.keys.join(" "))
        check("cursor: lights rows include scene chips, the lights disclosure and wallpaper toggles",
              s.keys.indexOf("gs:" + g0 + ":" + Hue.HueService.groups[0].sceneIds[0]) > 0 && s.keys.indexOf("gl:" + g0) > 0
              && s.keys.indexOf("w:enabled") > 0 && s.keys.indexOf("w:turnOn") > 0 && s.keys.indexOf("w:sync") === s.keys.length - 1, s.keys.join(" "))
        check("cursor: collapsed light rows are not reachable", s.keys.filter(function(k) { return k.indexOf("l:") === 0 }).length === 0)
        down(1)
        check("cursor: the first move lands on the first row", key() === s.keys[0], key())
        check("cursor: that row draws the cursor", barPanel.cursorSpots().byKey[key()].item.hasCursor === true)
        down(1)
        check("cursor: down moves to the next row", key() === s.keys[1], key())
        check("cursor: only one row draws the cursor", barPanel._cursorItems(barPanel, []).filter(function(i) { return i.hasCursor }).length === 1)
        while (key() !== "gl:" + g0) down(1)
        check("cursor: activating a row returns true", barPanel.activateCursor() === true)
        check("cursor: activating the disclosure opens the room's lights", Hue.HueService.isOpen("L:" + g0))
      },
      function() { shot(card(), "panel-cursor-link.png") },
      function() {
        var g0 = Hue.HueService.groups[0]
        check("cursor: stays on the disclosure after the lights open", key() === "gl:" + g0.id, key())
        down(1)
        check("cursor: down from the disclosure reaches the first light's switch", key() === "l:" + g0.id + ":" + g0.lightIds[0], key())
        down(100)
        check("cursor: down walks to the last row", key() === "w:sync", key())
        var why = cursorInView()
        check("cursor: the viewport follows the cursor to the bottom", why === "", why)
        var o = { flick: null, loaders: [] }; walk(barPanel, o)
        check("cursor: past the last row, down scrolls to the end", Math.abs(o.flick.contentY - Math.max(0, o.flick.contentHeight - o.flick.height)) < 1, o.flick.contentY + " of " + o.flick.contentHeight)
        shot(card(), "panel-cursor-bottom.png")
      },
      function() {
        for (var i = 0; i < 100; i++) keyCatcher.moveRequested(0, -1)
        check("cursor: up walks back to the first row", key() === "g:" + Hue.HueService.groups[0].id, key())
        var why = cursorInView()
        check("cursor: the viewport follows the cursor to the top", why === "", why)
        shot(card(), "panel-cursor-top.png")
      },
      function() {
        Hue.HueService.toggleExpanded("L:" + Hue.HueService.groups[0].id)
        barPanel.stepTab(1)
        check("cursor: a tab change hides the cursor", key() === "", key())
      },
      function() {
        var s = barPanel.cursorSpots()
        check("cursor: scenes rows are the routine switch and static/dynamic chips", s.keys.length > 3 && s.keys[0].indexOf("ss:") === 0 && s.keys.filter(function(k) { return k.indexOf(":static") > 0 }).length >= 3, s.keys.join(" "))
        down(3)
        shot(card(), "panel-cursor-scenes.png")
      },
      function() {
        barPanel.tab = "automations"
      },
      function() {
        var autos = Hue.HueService.automations
        check("cursor: automations rows are the switches", barPanel.cursorSpots().keys.join(" ") === "a:" + autos[0].id + " a:" + autos[1].id, barPanel.cursorSpots().keys.join(" "))
        down(1)
        check("cursor: on the first automation", key() === "a:" + autos[0].id, key())
        // The automation under the cursor disappears: the cursor takes the row now in its place.
        var snap = JSON.parse(JSON.stringify(harness.snapshot))
        snap.automations = snap.automations.slice(1)
        Hue.HueService._onEvent({ event: "state", rev: 2, data: snap })
      },
      function() {
        var autos = Hue.HueService.automations
        check("cursor: a vanished row hands the cursor to its neighbour", key() === "a:" + autos[0].id, key())
        Hue.HueService._onEvent({ event: "state", rev: 3, data: Object.assign({}, harness.snapshot, { automations: [], entertainment: [] }) })
      },
      function() {
        check("cursor: no rows left hides the cursor", key() === "", key())
        check("cursor: with no cursor Space/Enter falls through to all on/off", barPanel.activateCursor() === false)
        Hue.HueService._onEvent({ event: "state", rev: 4, data: harness.snapshot })
        barPanel.tab = "devices"
        down(1)
        check("cursor: a tab without rows keeps no cursor", key() === "", key())
        // A sensor switch on the device tab.
        var snap = JSON.parse(JSON.stringify(harness.snapshot))
        snap.devices[0].controls = [{ rtype: "motion", id: "00000000-0000-4000-8000-0000000000aa", label: "Motion sensor", enabled: true }]
        Hue.HueService._onEvent({ event: "state", rev: 5, data: snap })
      },
      function() {
        var s = barPanel.cursorSpots()
        check("cursor: device controls are rows", s.keys.join(" ") === "x:00000000-0000-4000-8000-0000000000aa", s.keys.join(" "))
        down(1)
        check("cursor: a device control takes and draws the cursor", key() === s.keys[0] && s.byKey[key()].item.hasCursor === true, key())
        shot(card(), "panel-cursor-devices.png")
      },
      function() {
        Hue.HueService._onEvent({ event: "state", rev: 6, data: harness.snapshot })
        barPanel.tab = "lights"
        Hue.HueService._onEvent({ event: "conn", state: "connected", detail: "" })
        // Wallpaper readout, three backends: no counts yet, nothing eligible, a real apply.
        wallpaperEvent({})
        check("wallpaper: an older backend shows no counts and no hint", wpCard.status === "Not applied yet" && wpCard.hint === "", wpCard.status + " | " + wpCard.hint)
        shot(wpCard, "wallpaper-nocounts.png")
      },
      function() {
        Hue.HueService._onEvent({ event: "conn", state: "connected", detail: "" })
        wallpaperEvent({ appliedCount: 0, eligible: 0 })
        check("wallpaper: nothing eligible with sync on shows the hint", wpCard.hint.indexOf("Also switch lights on") >= 0, wpCard.hint + " conn=" + Hue.HueService.conn)
        check("wallpaper: no wallpaper target chip draws a cursor", barPanel._cursorItems(wpCard, []).filter(function(i) { return i.hasCursor }).length === 0)
        shot(wpCard, "wallpaper-none-eligible.png")
      },
      function() {
        wallpaperEvent({ appliedAt: Date.now() / 1000 - 300, appliedCount: 1, eligible: 3 })
        wpCard.now = Date.now() / 1000
        check("wallpaper: count, time and eligible lights", wpCard.status === "Applied to 1 light, 5 min ago  ·  3 lights eligible" && wpCard.hint === "", wpCard.status)
        shot(wpCard, "wallpaper-applied.png")
      },
      // ---- wallpaper: no palette long after start (ImageMagick missing) -------
      function() {
        Hue.HueService.paletteGraceMs = 300
        wallpaperEvent({ palette: [], appliedCount: 0, eligible: 3 })
        check("wallpaper: an empty palette right after start shows no ImageMagick hint yet", !wpCard.noPalette)
      },
      function() {},
      function() {
        check("wallpaper: still no palette after the grace period asks about ImageMagick", wpCard.noPalette && visibleText(wpCard, english["wallpaper.noPalette"]), "noPalette " + wpCard.noPalette)
        shot(wpCard, "wallpaper-no-palette.png")
      },
      function() {
        wallpaperEvent({ eligible: 3 })
        check("wallpaper: a palette clears the ImageMagick hint", !wpCard.noPalette)
        wallpaperEvent({ palette: [], config: { enabled: false, targets: [], turnOn: false, transitionMs: 2500 } })
      },
      function() {},
      function() {
        check("wallpaper: no ImageMagick hint while sync is off", !wpCard.noPalette)
        wallpaperEvent({ eligible: 3 })
        Hue.HueService.paletteGraceMs = 8000
      },
      // ---- recovery: paired, never loaded, bridge unreachable ---------------
      function() {
        barPanel.tab = "lights"
        Hue.HueService._clearSnapshot()
        Hue.HueService._onEvent({ event: "conn", state: "unreachable", detail: "timed out" })
      },
      function() {
        check("recovery: unreachable and never loaded shows the recovery view, not empty tabs", barPanel.recovering && !barPanel.paired && !barPanel.needsPairing, "recovering " + barPanel.recovering + " paired " + barPanel.paired)
        check("recovery: it says why, with the detail, and offers Retry and another bridge",
              visibleText(barPanel, english["recovery.title"]) && visibleText(barPanel, "Can't reach the bridge: timed out")
              && visibleText(barPanel, english["recovery.retry"]) && visibleText(barPanel, english["recovery.pairOther"]))
        check("recovery: no tab bar", !visibleText(barPanel, english["tab.lights"]))
        shot(card(), "panel-recovery.png")
      },
      function() {
        // The backend's retries pass through "connecting": recovery must hold.
        Hue.HueService._onEvent({ event: "conn", state: "connecting", detail: "" })
        check("recovery: a retry cycle through 'connecting' keeps the recovery view", barPanel.recovering)
        var r = findButton(barPanel, english["recovery.retry"])
        if (r) r.clicked()   // the stand-in backend logs it; checked on the next tick
        var b = findButton(barPanel, english["recovery.pairOther"])
        check("recovery: the pair-elsewhere button exists", b !== null)
        if (b) b.clicked()
      },
      function() {
        check("recovery: Retry sent refresh (and nothing else did)", sent("refresh") === 1, sent("refresh") + " refresh commands")
        check("recovery: the first click asks for confirmation", visibleText(barPanel, english["devices.forgetConfirm"]) && Hue.HueService.confirmKey === "forget")
        var b = findButton(barPanel, english["devices.forgetConfirm"])
        if (b) b.clicked()
        check("recovery: the second click forgets", Hue.HueService.confirmKey === "")
        Hue.HueService._onEvent({ event: "conn", state: "unpaired", detail: "" })
      },
      function() {
        Hue.HueService._onEvent({ event: "conn", state: "unpaired", detail: "" })
        check("recovery: the second click sent pair.forget", sent("pair.forget") === 1, sent("pair.forget"))
        check("recovery: after forgetting, the pairing view takes over", barPanel.needsPairing && !barPanel.recovering && visibleText(barPanel, english["pairing.pair"]))
      },
      function() {
        // Connecting that never ends also leads to recovery.
        Hue.HueService.connectGraceMs = 300
        Hue.HueService._onEvent({ event: "conn", state: "connecting", detail: "" })
        check("recovery: a short connect is still the normal loading view", !barPanel.recovering && barPanel.paired)
      },
      function() {},
      function() {
        check("recovery: connecting far too long shows the recovery view", barPanel.recovering && visibleText(barPanel, english["recovery.retry"]), "stalled " + Hue.HueService.stalled)
        Hue.HueService._onEvent({ event: "conn", state: "connected", detail: "" })
        Hue.HueService._onEvent({ event: "state", rev: 7, data: harness.snapshot })
        Hue.HueService.connectGraceMs = 12000
        check("recovery: a snapshot ends it", !barPanel.recovering && barPanel.paired)
      },
      // ---- another bridge: nothing from the old one lingers ------------------
      function() {
        var svc = Hue.HueService
        svc.toggleExpanded("L:" + svc.groups[0].id)
        var snap = JSON.parse(JSON.stringify(harness.snapshot))
        snap.bridge.id = "another-bridge"
        svc._onEvent({ event: "state", rev: 8, data: snap })
        check("bridge change: open sections and pending changes are dropped", Object.keys(svc.expanded).length === 0)
        var atHost = JSON.parse(JSON.stringify(harness.snapshot))
        atHost.bridge.host = "192.168.1.2"
        svc._onEvent({ event: "state", rev: 9, data: atHost })
        svc._pairActive = true; svc._pairHost = "192.168.1.2"
        svc.pair = { state: "waiting_button", secondsLeft: 10, message: "" }
        svc._onEvent({ event: "pair", state: "paired" })
        check("bridge change: re-pairing the same address keeps the rooms (no new snapshot would come)", svc.loaded && svc.groups.length > 0)
        svc._pairActive = true; svc._pairHost = "192.168.1.77"
        svc.pair = { state: "waiting_button", secondsLeft: 10, message: "" }
        svc._onEvent({ event: "pair", state: "paired" })
        check("bridge change: pairing another address clears the old rooms until its snapshot arrives", !svc.loaded && svc.groups.length === 0 && Object.keys(svc.lights).length === 0)
        svc._onEvent({ event: "state", rev: 10, data: harness.snapshot })
        svc.forgetNow()
        check("bridge change: forgetting clears the snapshot at once", !svc.loaded && svc.groups.length === 0)
        svc._onEvent({ event: "state", rev: 11, data: harness.snapshot })
      },
      // ---- pairing: failures and Cancel ---------------------------------------
      function() {
        var svc = Hue.HueService
        svc._onEvent({ event: "conn", state: "unpaired", detail: "" })
        svc.pair = { state: "starting", secondsLeft: 0, message: "" }
        svc._onEvent({ event: "pair", state: "waiting_button", secondsLeft: 30 })
      },
      function() {
        var svc = Hue.HueService
        Hue.HueService._onEvent({ event: "conn", state: "unpaired", detail: "" })
        check("pairing: waiting for the button shows Cancel", findButton(barPanel, english["common.cancel"]) !== null)
        findButton(barPanel, english["common.cancel"]).clicked()
        check("pairing: Cancel resets at once, even with a silent backend", svc.pair.state === "idle" && findButton(barPanel, english["pairing.pair"]) !== null)
        svc._onEvent({ event: "pair", state: "waiting_button", secondsLeft: 28 })
        check("pairing: a late progress event after Cancel is ignored", svc.pair.state === "idle")
        svc.startPairing("192.168.1.9")
        check("pairing: Pair waits for the backend", svc.pair.state === "starting", svc.pair.state)
        // Restarted before the first flow's thread ended: its late "cancelled"
        // and the new flow's progress.
        svc._onEvent({ event: "pair", state: "cancelled", message: "pairing was cancelled" })
        check("pairing: a superseded flow's late 'cancelled' does not end the new one", svc.pair.state === "starting", svc.pair.state)
        svc._onEvent({ event: "pair", state: "failed", message: "cannot reach the bridge (TimeoutError)" })
        svc._onEvent({ event: "pair", state: "waiting_button", secondsLeft: 36 })
        check("pairing: the new flow's progress comes back after an old flow's late failure", svc.pair.state === "waiting_button", svc.pair.state)
        findButton(barPanel, english["common.cancel"]).clicked()
        check("pairing: Cancel resets the second flow too", svc.pair.state === "idle", svc.pair.state)
        svc.pair = { state: "starting", secondsLeft: 0, message: "" }
        svc._onPairStartResult({ id: 1, ok: false, code: "invalid", message: "that is not a host name or address" })
        check("pairing: a refused pair.start fails with its reason", svc.pair.state === "failed" && visibleText(barPanel, english["pairing.badHost"]))
        svc.pair = { state: "starting", secondsLeft: 0, message: "" }
        svc._onEvent({ event: "pair", state: "failed", message: "cannot reach the bridge (JSONDecodeError)" })
        check("pairing: a non-bridge address reads human", visibleText(barPanel, english["error.notABridge"]) && findButton(barPanel, english["pairing.pair"]) !== null)
      },
      function() {
        var svc = Hue.HueService
        Hue.HueService._onEvent({ event: "conn", state: "unpaired", detail: "" })
        check("pairing: Pair sent pair.start and both Cancels sent pair.cancel", sent("pair.start") === 1 && sent("pair.cancel") === 2, sent("pair.start") + " / " + sent("pair.cancel"))
        svc._onEvent({ event: "discovered", bridges: [] })
        svc._onDiscoverResult({ id: 2, ok: true })
        check("pairing: a search that finds nothing says so", visibleText(barPanel, english["pairing.noneFound"]) && !svc.discovering)
        shot(card(), "pairing-none-found.png")
      },
      function() {
        var svc = Hue.HueService
        Hue.HueService._onEvent({ event: "conn", state: "unpaired", detail: "" })
        svc.discovering = true
        svc._onDiscoverResult({ id: 3, ok: false, code: "unreachable", message: "discovery failed (URLError)" })
        check("pairing: a failed search stops searching and says why", !svc.discovering && visibleText(barPanel, english["pairing.discoveryFailed"]))
        check("pairing: a failed search is not a header notice about the bridge", svc.notice === "")
        shot(card(), "pairing-failed.png")
      },
      function() {
        var svc = Hue.HueService
        // Back to normal for the language checks.
        svc.pair = svc.pairIdle
        svc.discoverDone = false; svc.discoverError = null; svc.discovered = []
        svc._onEvent({ event: "conn", state: "connected", detail: "" })
        svc._onEvent({ event: "state", rev: 12, data: harness.snapshot })
        check("pairing done: the tabs are back", barPanel.paired && svc.loaded)
      },
      // ---- language: English from the catalog, then a live switch -----------
      function() {
        barPanel.tab = "lights"
        Hue.HueService._onEvent({ event: "conn", state: "connected", detail: "" })
        wallpaperEvent({ appliedCount: 0, eligible: 0 })
        // Open everything that hides words: a room's lights, colour and more, a light's details, the zone form.
        var g0 = Hue.HueService.groups[0]
        var opens = ["L:" + g0.id, "T:" + g0.id, "M:" + g0.id, "l:" + g0.lightIds[0], "newzone"]
        for (var i = 0; i < opens.length; i++) if (!Hue.HueService.isOpen(opens[i])) Hue.HueService.toggleExpanded(opens[i])
      },
      function() {
        Hue.HueService._onEvent({ event: "conn", state: "connected", detail: "" })
        var fields = findAll(harness, function(i) { return i.maximumLength === 32 && i.placeholderText !== undefined })
        check("names: the zone and scene name fields stop at 32 characters", fields.length >= 2, fields.length + " fields")
        var n = englishTexts().length
        check("i18n: English catalog strings are on screen", n >= 10, n + " found")
        var c = Hue.HueService.counts
        check("i18n: the header counts lights in English", headerText() === c.on + " of " + c.total + " lights on", headerText())
        Hue.HueService._onEvent({ event: "conn", state: "connected", detail: "" })
        languageFile.setText("qps\n")
      },
      // Wait (bounded) for the language file watcher to pick the switch up.
      function() {
        if (tabLabels().indexOf("[Lîghtš~~]") < 0 && ++langWaits < 40) harness.step--
      },
      function() {
        Hue.HueService._onEvent({ event: "conn", state: "connected", detail: "" })
        var c = Hue.HueService.counts
        var left = englishTexts()
        check("i18n: after switching language no catalog string is left in English", left.length === 0, left.join(" | "))
        check("i18n: the header is translated, counts filled in", headerText() === "[" + c.on + " öf " + c.total + " lîghtš öñ~~~~~~]", headerText())
        check("i18n: tab labels are translated", tabLabels().indexOf("[Lîghtš~~]") >= 0, tabLabels().join(" "))
        check("i18n: Model.js text follows the language", wpCard.hint.charAt(0) === "[", wpCard.hint)
        check("i18n: a plural is translated with its count", wpCard.status.indexOf("0") >= 0 && wpCard.status.charAt(0) === "[", wpCard.status)
        shot(card(), "pseudo-lights.png")
      },
      function() { shot(harness, "pseudo-views.png") },
      function() { barPanel.tab = "scenes" },
      function() { shot(card(), "pseudo-scenes.png") },
      function() { barPanel.tab = "devices" },
      function() { shot(card(), "pseudo-devices.png") },
      // Longer words must still fit the recovery and pairing cards.
      function() {
        Hue.HueService._clearSnapshot()
        Hue.HueService._onEvent({ event: "conn", state: "unreachable", detail: "timed out" })
      },
      function() { shot(card(), "pseudo-recovery.png") },
      function() {
        var svc = Hue.HueService
        svc._onEvent({ event: "conn", state: "unpaired", detail: "" })
        svc.discoverDone = true
        svc.discoverError = { ok: false, code: "unreachable", message: "" }
        svc.pair = { state: "failed", secondsLeft: 0, message: "cannot reach the bridge (JSONDecodeError)" }
      },
      function() {
        Hue.HueService._onEvent({ event: "conn", state: "unpaired", detail: "" })
        check("pairing: the view is up for the pseudo-locale shot", barPanel.needsPairing)
        shot(card(), "pseudo-pairing.png")
      },
      function() {
        console.log(failures === 0 ? "ALL OK" : failures + " FAILED")
        exitTimer.start()
      }
    ]
    Timer {
      id: stepTimer
      interval: 250
      onTriggered: { harness.steps[harness.step++](); if (!harness.grabbing && harness.step < harness.steps.length) restart() }
    }

    Timer { id: exitTimer; interval: 800; onTriggered: Qt.exit(harness.failures === 0 ? 0 : 1) }
    Column {
      width: parent.width
      Repeater {
        id: loaders
        model: 5
        Loader {
          required property int index
          width: harness.width
          sourceComponent: index === 0 ? lightsC : index === 1 ? scenesC : index === 2 ? autoC : index === 3 ? devC : pairC
        }
      }
    }
    Item {
      y: 2400; width: harness.width; height: 600
      Hue.WallpaperCard { id: wpCard; ui: harness.ui }
    }
    Component { id: lightsC; Hue.LightsTab { ui: harness.ui; width: harness.width } }
    Component { id: scenesC; Hue.ScenesTab { ui: harness.ui; width: harness.width } }
    Component { id: autoC; Hue.AutomationsTab { ui: harness.ui; width: harness.width } }
    Component { id: devC; Hue.DevicesTab { ui: harness.ui; width: harness.width } }
    Component { id: pairC; Hue.PairingView { ui: harness.ui; width: harness.width } }
  }
  }
}
