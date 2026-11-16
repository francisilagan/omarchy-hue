// Pure decisions for the Hue panel: what to show while the bridge catches up.
//
// Nothing here touches Qt, the network or the clock (callers pass `now`), so it
// is tested with plain Node (tests/model.test.js). See ARCHITECTURE.md.
//
// The model in one paragraph: the bridge's state is never edited. A change the
// user makes is recorded as a *pending* entry (the values wanted, which
// command carries it, when). Controls show pending over the bridge until the
// command has finished and the bridge has had a moment to echo it, or the
// entry is abandoned. A failed command drops only its own entries.
.pragma library

var UNCONFIRMED_MS = 15000   // give up on a command that never reports back
var ECHO_GRACE_MS = 1200     // after success, keep the guess while the bridge's echo arrives

var NO_LIGHT = { id: "", name: "", on: false, brightness: 0, dimmable: false, color: false, ct: false,
                 mirek: null, mirekMin: 153, mirekMax: 500, hex: null, effects: [], effect: "no_effect",
                 timedEffects: [], timedEffect: "no_effect", powerup: null, reachable: true, product: "" }
var NO_GROUP = { id: "", kind: "room", name: "", group: "", on: false, lightIds: [], sceneIds: [], smartSceneIds: [] }

function pretty(s) {
  var t = String(s).replace(/_/g, " ")
  return t.charAt(0).toUpperCase() + t.slice(1)
}

function same(a, b) { return JSON.stringify(a) === JSON.stringify(b) }

// Text: every function that returns words takes `tr`, the translator (the
// Strings singleton in QML, a stand-in built from i18n/en.json in the tests):
// tr.t(key, args...) for a string, tr.tn(key, count, args...) for a plural form
// whose %1 is the count. Whole sentences are catalog entries with %N holes;
// fragments are never glued together, since other languages reorder words.

// "%1 of %2" with args filled in one pass, so a %2 inside a value (a bridge
// name, an error detail) is left alone. Unknown holes stay as written.
function fill(template, args) {
  return String(template).replace(/%(\d+)/g, function(m, i) {
    var v = args[Number(i) - 1]
    return v === undefined ? m : String(v)
  })
}

// ---- pending entries -------------------------------------------------------

// Record `fields` for `key`, tied to command `cmd`. Colour and white are exclusive.
function remember(pending, key, fields, cmd, now) {
  var next = {}
  for (var k in pending) next[k] = pending[k]
  var merged = {}
  var old = pending[key] || {}
  for (var f in old) merged[f] = old[f]
  for (var g in fields) merged[g] = fields[g]
  if (fields.hex !== undefined) delete merged.mirek
  if (fields.mirek !== undefined) delete merged.hex
  merged.t = now
  merged.cmd = cmd
  merged.done = false
  delete merged.doneAt
  next[key] = merged
  return next
}

// A command finished. Success: keep the guess briefly for the echo. Failure: forget it.
function settle(pending, cmd, ok, now) {
  var next = {}
  for (var k in pending) {
    var e = pending[k]
    if (e.cmd !== cmd) { next[k] = e; continue }
    if (!ok) continue
    var copy = {}
    for (var f in e) copy[f] = e[f]
    copy.done = true
    copy.doneAt = now
    next[k] = copy
  }
  return next
}

// Drop entries that are no longer worth showing. Returns the same object when nothing expired.
function expire(pending, now) {
  var next = {}, changed = false
  for (var k in pending) {
    var e = pending[k]
    var dead = e.done ? now - e.doneAt >= ECHO_GRACE_MS : now - e.t >= UNCONFIRMED_MS
    if (dead) changed = true; else next[k] = e
  }
  return changed ? next : pending
}

function hasPending(pending) {
  for (var k in pending) return true
  return false
}

function flag(pending, key, fallback) {
  var p = pending[key]
  return (p && p.flag !== undefined) ? p.flag : fallback
}

// ---- effective state -------------------------------------------------------

// A light as the user should see it: the bridge's values with any pending
// group change and pending light change applied, oldest first.
function effLight(pending, groupId, light) {
  var e = { on: light.on, pct: light.brightness, hex: light.hex, mirek: light.mirek || 0, effect: light.effect }
  var ps = []
  var pg = pending["g:" + groupId], pl = pending["l:" + light.id]
  if (pg) ps.push(pg)
  if (pl) ps.push(pl)
  ps.sort(function(a, b) { return a.t - b.t })
  for (var i = 0; i < ps.length; i++) {
    var p = ps[i]
    if (p.on !== undefined) e.on = p.on
    if (p.pct !== undefined) e.pct = p.pct
    if (p.hex !== undefined) { e.hex = p.hex; e.mirek = 0 }
    if (p.mirek !== undefined) { e.mirek = p.mirek; e.hex = null }
    if (p.effect !== undefined) e.effect = p.effect
  }
  return e
}

// A room or zone as the user should see it. `lights` are the group's light objects.
function effGroup(pending, group, lights) {
  var pg = pending["g:" + group.id]
  var on = false, sumOn = 0, nOn = 0, sumAll = 0, hex = "", mirek = 0
  var anyColor = false, anyCt = false, anyEffect = false, mMin = 153, mMax = 500
  for (var i = 0; i < lights.length; i++) {
    var l = lights[i]
    var e = effLight(pending, group.id, l)
    sumAll += e.pct
    if (e.on) {
      on = true; sumOn += e.pct; nOn++
      if (hex === "" && e.hex) hex = e.hex
      if (mirek === 0 && e.mirek) mirek = e.mirek
    }
    if (l.color) anyColor = true
    if (l.ct) {
      if (!anyCt) { mMin = l.mirekMin; mMax = l.mirekMax }
      else { mMin = Math.max(mMin, l.mirekMin); mMax = Math.min(mMax, l.mirekMax) }  // the range every light shares
      anyCt = true
    }
    if (l.effects.length > 0) anyEffect = true
  }
  var pct = (pg && pg.pct !== undefined) ? pg.pct
          : nOn > 0 ? Math.round(sumOn / nOn)
          : lights.length > 0 ? Math.round(sumAll / lights.length) : 0
  return { on: on, pct: pct, hex: hex, mirek: mirek, anyColor: anyColor, anyCt: anyCt,
           anyEffect: anyEffect, mirekMin: mMin, mirekMax: mMax }
}

function lightsOn(pending, groups, lightsById) {
  var seen = {}, n = 0, total = 0
  for (var i = 0; i < groups.length; i++) {
    var g = groups[i]
    if (g.kind !== "room") continue   // zones overlap rooms
    for (var j = 0; j < g.lightIds.length; j++) {
      var l = lightsById[g.lightIds[j]]
      if (!l || seen[l.id]) continue
      seen[l.id] = true
      total++
      if (effLight(pending, g.id, l).on) n++
    }
  }
  return { on: n, total: total }
}

// ---- small helpers the views share ----------------------------------------

function sameColour(a, b, tolerance) {
  if (!a || !b) return false
  function rgb(h) { return [parseInt(h.substr(1, 2), 16), parseInt(h.substr(3, 2), 16), parseInt(h.substr(5, 2), 16)] }
  var x = rgb(a), y = rgb(b)
  var d = Math.sqrt(Math.pow(x[0] - y[0], 2) + Math.pow(x[1] - y[1], 2) + Math.pow(x[2] - y[2], 2))
  return d <= tolerance
}

// Short, human text for a connection state; null when everything is fine.
function connectionMessage(conn, detail, tr) {
  switch (conn) {
  case "connected": return null
  case "connecting": return tr.t("conn.connecting")
  case "unreachable": return detail ? tr.t("conn.unreachableDetail", detail) : tr.t("conn.unreachable")
  case "unauthorized": return tr.t("conn.unauthorized")
  case "cert_changed": return tr.t("conn.certChanged")
  case "pairing": return tr.t("conn.pairing")
  case "unpaired": return tr.t("conn.unpaired")
  default: return tr.t("conn.starting")
  }
}

// The backend words a failed connection as "cannot reach <host> (<Python
// exception name>)". A reply that could not be parsed means something answered
// at that address but it was not a Hue bridge (a router, a printer, a web page).
var NOT_A_BRIDGE = /\((JSONDecodeError|ValueError|UnicodeDecodeError|BadStatusLine|RemoteDisconnected|IncompleteRead)\)/

// A failed command's result. The bridge's own words (`message`) stay as sent.
function errorMessage(result, tr) {
  switch (result.code) {
  case "unpaired": case "unauthorized": case "cert_changed": return connectionMessage(result.code, "", tr)
  case "unreachable": return NOT_A_BRIDGE.test(result.message || "") ? tr.t("error.notABridge") : tr.t("error.unreachable")
  case "timeout": return tr.t("error.timeout")
  case "rate_limited": return tr.t("error.rateLimited")
  case "invalid": return result.message || tr.t("error.invalid")
  case "bridge_error": return tr.t("error.refused", result.message || tr.t("error.unknownReason"))
  default: return result.message || tr.t("error.generic")
  }
}

// ---- pairing ---------------------------------------------------------------

// A `pair` event with state "failed" (or a failed pair.start result). Older
// backends send only `message`, so the cause is read from it when `code` is
// absent; anything unrecognised is shown as sent.
function pairCode(message) {
  var m = String(message || "")
  if (/^cannot reach/.test(m)) return "unreachable"
  if (/not pressed in time/.test(m)) return "timeout"
  if (/not a host name or address/.test(m)) return "invalid"
  if (/failed unexpectedly/.test(m)) return "internal"
  return ""
}

function pairFailure(e, tr) {
  var code = e.code || pairCode(e.message)
  switch (code) {
  case "unreachable": return NOT_A_BRIDGE.test(e.message || "") ? tr.t("error.notABridge") : tr.t("pairing.noAnswer")
  case "timeout": return tr.t("pairing.timedOut")
  case "invalid": return tr.t("pairing.badHost")
  case "internal": return tr.t("pairing.failed")   // a crash's details are for the log
  case "": return e.message || tr.t("pairing.failed")
  default: return errorMessage({ code: code, message: e.message }, tr)
  }
}

// A failed pair.discover result: the error is about Philips' discovery
// service, not the bridge.
function discoveryFailure(result, tr) {
  switch (result.code) {
  case "unreachable": case "timeout": return tr.t("pairing.discoveryFailed")
  default: return errorMessage(result, tr)
  }
}

// ---- keyboard cursor -------------------------------------------------------
//
// One highlighted row per panel. The panel collects the keys of the rows that
// are on screen, in reading order, and these decide where the cursor goes.
// `cur` is { key, index }: key "" means no cursor is shown (Space/Enter then
// switch every light); index is where the key last sat, so a row that vanishes
// hands the cursor to whatever now sits in its place.

var NO_CURSOR = { key: "", index: -1 }

// Up/Down. Returns the new cursor, or null when the move runs off either end
// (the caller scrolls instead, so content above and below the rows stays reachable).
function cursorStep(keys, cur, delta) {
  if (keys.length === 0) return null
  if (cur.key === "") return { key: keys[0], index: 0 }   // the first move shows the cursor at the top
  var at = keys.indexOf(cur.key)
  if (at < 0) {
    var i = Math.max(0, Math.min(keys.length - 1, cur.index))
    return { key: keys[i], index: i }
  }
  var next = at + delta
  if (next < 0 || next >= keys.length) return null
  return { key: keys[next], index: next }
}

// The rows changed (new state, a section opened or closed). Keep the same row
// if it is still there, else the row now at its old place, else no cursor.
function cursorReconcile(keys, cur) {
  if (cur.key === "") return cur
  var at = keys.indexOf(cur.key)
  if (at >= 0) return at === cur.index ? cur : { key: cur.key, index: at }
  if (keys.length === 0) return NO_CURSOR
  var i = Math.max(0, Math.min(keys.length - 1, cur.index))
  return { key: keys[i], index: i }
}

// The scroll position that shows a row (top y, height) with `margin` around it,
// moving as little as possible.
function scrollToShow(contentY, viewHeight, contentHeight, y, h, margin) {
  var maxY = Math.max(0, contentHeight - viewHeight)
  var next = contentY
  if (y + h + margin > next + viewHeight) next = y + h + margin - viewHeight
  if (y - margin < next) next = y - margin
  return Math.max(0, Math.min(maxY, next))
}

// ---- wallpaper sync readout -------------------------------------------------

// "just now", "5 min ago", "3 h ago", "2 days ago". Times are epoch seconds.
function ago(then, now, tr) {
  var s = Math.max(0, Math.floor(now - then))
  if (s < 60) return tr.t("ago.justNow")
  if (s < 3600) return tr.tn("ago.minutes", Math.floor(s / 60))
  if (s < 86400) return tr.tn("ago.hours", Math.floor(s / 3600))
  return tr.tn("ago.days", Math.floor(s / 86400))
}

// What the wallpaper card says about the last apply. `w` is the service's
// { enabled, turnOn, appliedAt, appliedCount, eligible, statsKnown }; `now` is epoch seconds.
// statsKnown is false for a backend that does not report the counts yet.
function wallpaperStatus(w, now, tr) {
  var parts = []
  if (w.appliedAt > 0)
    parts.push(w.statsKnown ? tr.tn("wallpaper.appliedTo", w.appliedCount, ago(w.appliedAt, now, tr))
                            : tr.t("wallpaper.lastApplied", ago(w.appliedAt, now, tr)))
  else if (w.enabled) parts.push(tr.t("wallpaper.notApplied"))
  if (w.statsKnown) parts.push(tr.tn("wallpaper.eligible", w.eligible))
  return parts.join("  ·  ")
}

function wallpaperHint(w, tr) {
  if (!w.enabled || !w.statsKnown || w.eligible > 0) return ""
  if (w.turnOn) return tr.t("wallpaper.hintNoColourLights")
  return tr.t("wallpaper.hintNoneOn", tr.t("wallpaper.turnOn"))
}

// Reading order for the rows on screen: `spots` are { key, x, y, h } in one
// coordinate space. Rows whose centres are within `tolerance` px count as one
// line (a switch and a chip beside it), read left to right.
function cursorOrder(spots, tolerance) {
  var s = spots.slice()
  s.sort(function(a, b) {
    var dy = (a.y + a.h / 2) - (b.y + b.h / 2)
    if (Math.abs(dy) > tolerance) return dy
    return a.x - b.x
  })
  var out = [], seen = {}
  for (var i = 0; i < s.length; i++) if (!seen[s[i].key]) { seen[s[i].key] = true; out.push(s[i].key) }
  return out
}
