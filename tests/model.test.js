// Run with: node --test tests/
const test = require("node:test")
const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")

// Model.js is a QML `.pragma library`, which Node cannot parse as-is: drop that
// one line and evaluate the rest in a sandbox, as QML would.
const source = fs.readFileSync(path.join(__dirname, "..", "qml", "Model.js"), "utf8").replace(/^\.pragma library$/m, "")
const sandbox = {}
vm.runInNewContext(source + "\n;this.api = { remember, settle, expire, hasPending, flag, effLight, effGroup, lightsOn, sameColour, pretty, fill, connectionMessage, errorMessage, pairFailure, discoveryFailure, cursorStep, cursorReconcile, cursorOrder, scrollToShow, NO_CURSOR, ago, wallpaperStatus, wallpaperHint, NO_LIGHT, NO_GROUP, UNCONFIRMED_MS, ECHO_GRACE_MS }", sandbox)
const M = sandbox.api

// The English translator the views get from Strings.qml, built from the real
// catalog: so these tests also prove the catalog reproduces the old English.
const EN = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "qml", "i18n", "en.json"), "utf8"))
function translator(catalog, category) {
  const form = (key, n) => {
    const v = catalog[key]
    if (v && typeof v === "object") return n === undefined ? v.other : (v[category(n)] || v.other)
    return typeof v === "string" ? v : key
  }
  return {
    t: (key, ...args) => M.fill(form(key), args),
    tn: (key, count, ...args) => M.fill(form(key, count), [String(count), ...args]),
  }
}
const tr = translator(EN, (n) => (n === 1 ? "one" : "other"))

const light = (o) => Object.assign({}, M.NO_LIGHT, { id: "L1", on: true, brightness: 50, hex: "#ffa759", mirek: 366 }, o)
const group = (o) => Object.assign({}, M.NO_GROUP, { id: "G1", name: "Room", lightIds: ["L1"] }, o)

test("a pending change is shown over the bridge, and a newer light change beats an older group change", () => {
  let p = M.remember({}, "g:G1", { on: false }, 1, 100)
  assert.equal(M.effLight(p, "G1", light()).on, false)
  p = M.remember(p, "l:L1", { on: true, pct: 80 }, 2, 200)
  const e = M.effLight(p, "G1", light())
  assert.equal(e.on, true)
  assert.equal(e.pct, 80)
})

test("an older light change loses to a newer group change", () => {
  let p = M.remember({}, "l:L1", { on: true }, 1, 100)
  p = M.remember(p, "g:G1", { on: false }, 2, 200)
  assert.equal(M.effLight(p, "G1", light()).on, false)
})

test("colour and white are exclusive: the later choice replaces the earlier", () => {
  let p = M.remember({}, "l:L1", { hex: "#ff0000" }, 1, 100)
  p = M.remember(p, "l:L1", { mirek: 300 }, 2, 200)
  const e = M.effLight(p, "G1", light())
  assert.equal(e.mirek, 300)
  assert.equal(e.hex, null)
  p = M.remember(p, "l:L1", { hex: "#00ff00" }, 3, 300)
  const f = M.effLight(p, "G1", light())
  assert.equal(f.hex, "#00ff00")
  assert.equal(f.mirek, 0)
})

test("changing brightness keeps an earlier pending colour for the same light", () => {
  let p = M.remember({}, "l:L1", { hex: "#ff0000" }, 1, 100)
  p = M.remember(p, "l:L1", { pct: 20 }, 2, 200)
  const e = M.effLight(p, "G1", light())
  assert.equal(e.hex, "#ff0000")
  assert.equal(e.pct, 20)
})

test("a successful command is kept for the echo grace, then dropped", () => {
  let p = M.remember({}, "l:L1", { on: false }, 7, 1000)
  p = M.settle(p, 7, true, 1100)
  assert.equal(M.expire(p, 1100 + M.ECHO_GRACE_MS - 1)["l:L1"].on, false)
  assert.equal(M.hasPending(M.expire(p, 1100 + M.ECHO_GRACE_MS)), false)
})

test("a failed command drops only its own entries", () => {
  let p = M.remember({}, "l:L1", { on: false }, 1, 100)
  p = M.remember(p, "l:L2", { on: false }, 2, 100)
  p = M.settle(p, 1, false, 200)
  assert.equal(p["l:L1"], undefined)
  assert.equal(p["l:L2"].on, false)
})

test("a command that never reports back is abandoned after the unconfirmed timeout", () => {
  const p = M.remember({}, "l:L1", { on: false }, 1, 0)
  assert.ok(M.expire(p, M.UNCONFIRMED_MS - 1)["l:L1"])
  assert.equal(M.hasPending(M.expire(p, M.UNCONFIRMED_MS)), false)
})

test("expire returns the same object when nothing changed (no needless re-render)", () => {
  const p = M.remember({}, "l:L1", { on: false }, 1, 0)
  assert.equal(M.expire(p, 10), p)
})

test("remember does not mutate its input", () => {
  const p = M.remember({}, "l:L1", { on: false }, 1, 0)
  const frozen = JSON.stringify(p)
  M.remember(p, "l:L1", { on: true }, 2, 5)
  assert.equal(JSON.stringify(p), frozen)
})

test("group brightness averages the lights that are on; a pending value wins", () => {
  const ls = [light({ id: "L1", brightness: 40 }), light({ id: "L2", brightness: 80 }), light({ id: "L3", on: false, brightness: 10 })]
  const g = group({ lightIds: ["L1", "L2", "L3"] })
  assert.equal(M.effGroup({}, g, ls).pct, 60)
  const p = M.remember({}, "g:G1", { on: true, pct: 25 }, 1, 1)
  assert.equal(M.effGroup(p, g, ls).pct, 25)
})

test("an all-off group reports the average of its lights, not zero", () => {
  const ls = [light({ on: false, brightness: 30 }), light({ id: "L2", on: false, brightness: 50 })]
  assert.equal(M.effGroup({}, group(), ls).pct, 40)
  assert.equal(M.effGroup({}, group(), []).pct, 0)
})

test("a group's white range is the range every light shares", () => {
  const ls = [light({ ct: true, mirekMin: 153, mirekMax: 500 }), light({ id: "L2", ct: true, mirekMin: 200, mirekMax: 454 })]
  const e = M.effGroup({}, group(), ls)
  assert.equal(JSON.stringify([e.mirekMin, e.mirekMax]), "[200,454]")
})

test("group capabilities reflect its lights", () => {
  const e = M.effGroup({}, group(), [light({ color: true, effects: ["candle"] }), light({ id: "L2" })])
  assert.equal(e.anyColor, true)
  assert.equal(e.anyEffect, true)
  assert.equal(e.anyCt, false)
})

test("lights on counts each light once even when a zone overlaps a room", () => {
  const lights = { L1: light(), L2: light({ id: "L2", on: false }) }
  const groups = [group({ lightIds: ["L1", "L2"] }), group({ id: "Z1", kind: "zone", lightIds: ["L1"] })]
  assert.equal(JSON.stringify(M.lightsOn({}, groups, lights)), JSON.stringify({ on: 1, total: 2 }))
})

test("a pending switch-off is reflected in the count immediately", () => {
  const lights = { L1: light() }
  const groups = [group()]
  const p = M.remember({}, "g:G1", { on: false }, 1, 1)
  assert.equal(JSON.stringify(M.lightsOn(p, groups, lights)), JSON.stringify({ on: 0, total: 1 }))
})

test("flags (switches) follow pending over the bridge", () => {
  assert.equal(M.flag({}, "a:1", true), true)
  assert.equal(M.flag(M.remember({}, "a:1", { flag: false }, 1, 1), "a:1", true), false)
})

test("colours compare within a tolerance", () => {
  assert.ok(M.sameColour("#ff0000", "#fa0505", 20))
  assert.ok(!M.sameColour("#ff0000", "#00ff00", 20))
  assert.ok(!M.sameColour(null, "#00ff00", 20))
})

test("messages: every connection state and error code has human text", () => {
  for (const s of ["connecting", "unreachable", "unauthorized", "cert_changed", "pairing", "unpaired", ""]) {
    assert.ok(M.connectionMessage(s, "", tr), s)
  }
  assert.equal(M.connectionMessage("connected", "", tr), null)
  for (const c of ["unpaired", "unauthorized", "cert_changed", "unreachable", "timeout", "rate_limited", "invalid", "bridge_error", "internal"]) {
    assert.ok(M.errorMessage({ code: c, message: "x" }, tr), c)
  }
  assert.match(M.errorMessage({ code: "bridge_error", message: "device busy" }, tr), /device busy/)
})

test("messages: the English wording is unchanged by the catalog", () => {
  const conn = {
    connecting: "Connecting to the bridge…",
    unreachable: "Can't reach the bridge",
    unauthorized: "The bridge no longer accepts this app. Pair again.",
    cert_changed: "The bridge's certificate changed. Only trust it if you reset the bridge or replaced it.",
    pairing: "Waiting for the link button…",
    unpaired: "Not paired with a bridge yet.",
    "": "Starting…",
  }
  for (const [s, text] of Object.entries(conn)) assert.equal(M.connectionMessage(s, "", tr), text)
  assert.equal(M.connectionMessage("unreachable", "timed out", tr), "Can't reach the bridge: timed out")
  const err = (code, message) => M.errorMessage({ code, message }, tr)
  assert.equal(err("unauthorized", ""), conn.unauthorized)
  assert.equal(err("unreachable", ""), "Can't reach the bridge.")
  assert.equal(err("timeout", ""), "The bridge took too long to answer.")
  assert.equal(err("rate_limited", ""), "The bridge is busy. Try again in a moment.")
  assert.equal(err("invalid", ""), "That change isn't valid.")
  assert.equal(err("invalid", "bad name"), "bad name")
  assert.equal(err("bridge_error", ""), "The bridge refused: unknown reason")
  assert.equal(err("bridge_error", "device busy"), "The bridge refused: device busy")
  assert.equal(err("internal", ""), "Something went wrong.")
  assert.equal(err("internal", "boom"), "boom")
})

test("messages follow the catalog: another language changes the words, not the logic", () => {
  const other = {}
  for (const [k, v] of Object.entries(EN)) {
    other[k] = typeof v === "string" ? "<" + v + ">" : Object.fromEntries(Object.entries(v).map(([c, f]) => [c, "<" + f + ">"]))
  }
  const xx = translator(other, () => "other")
  assert.equal(M.connectionMessage("unreachable", "d", xx), "<Can't reach the bridge: d>")
  assert.equal(M.wallpaperStatus(W({ appliedAt: 1000, appliedCount: 1, eligible: 1 }), 1000, xx), "<Applied to 1 lights, <just now>>  ·  <1 lights eligible>")
  assert.equal(M.wallpaperHint(W({}), xx), "<No colour lights are on in the selected rooms. Turn on '<Also switch lights on>' or pick other rooms.>")
})

test("fill: holes filled in one pass, by number, unknown holes kept", () => {
  assert.equal(M.fill("%2 of %1", ["a", "b"]), "b of a")
  assert.equal(M.fill("Paired with %1 at %2", ["Hue %2", "10.0.0.2"]), "Paired with Hue %2 at 10.0.0.2")
  assert.equal(M.fill("%1%", [50]), "50%")
  assert.equal(M.fill("%1 and %3", ["x"]), "x and %3")
  assert.equal(M.fill("plain", []), "plain")
})

test("pretty", () => {
  assert.equal(M.pretty("no_effect"), "No effect")
})

// ---- keyboard cursor ----

const C = (key, index) => ({ key, index })
const keys = ["g:A", "l:A:1", "g:B", "w:on"]

test("cursor: the first move shows the cursor on the first row, whichever way", () => {
  assert.deepEqual({ ...M.cursorStep(keys, M.NO_CURSOR, 1) }, C("g:A", 0))
  assert.deepEqual({ ...M.cursorStep(keys, M.NO_CURSOR, -1) }, C("g:A", 0))
})

test("cursor: up and down walk the rows; running off an end returns null (the panel scrolls)", () => {
  assert.deepEqual({ ...M.cursorStep(keys, C("g:A", 0), 1) }, C("l:A:1", 1))
  assert.deepEqual({ ...M.cursorStep(keys, C("g:B", 2), -1) }, C("l:A:1", 1))
  assert.equal(M.cursorStep(keys, C("g:A", 0), -1), null)
  assert.equal(M.cursorStep(keys, C("w:on", 3), 1), null)
})

test("cursor: no rows means no cursor, and a move scrolls instead", () => {
  assert.equal(M.cursorStep([], M.NO_CURSOR, 1), null)
  assert.equal(M.cursorStep([], C("g:A", 0), 1), null)
})

test("cursor: a move from a row that vanished lands on the row now in its place", () => {
  assert.deepEqual({ ...M.cursorStep(["g:A", "g:B"], C("l:A:1", 1), 1) }, C("g:B", 1))
  assert.deepEqual({ ...M.cursorStep(["g:A"], C("w:on", 3), 1) }, C("g:A", 0))
})

test("cursor: reconcile keeps the row, follows it when it moves, or takes its place", () => {
  const cur = C("g:B", 2)
  assert.equal(M.cursorReconcile(keys, cur), cur)
  assert.deepEqual({ ...M.cursorReconcile(["g:B", "g:A"], cur) }, C("g:B", 0))
  assert.deepEqual({ ...M.cursorReconcile(["g:A", "l:A:1", "w:on"], cur) }, C("w:on", 2))
  assert.deepEqual({ ...M.cursorReconcile(["g:A"], cur) }, C("g:A", 0))
  assert.deepEqual({ ...M.cursorReconcile([], cur) }, { ...M.NO_CURSOR })
})

test("cursor: reconcile never shows a hidden cursor", () => {
  assert.equal(M.cursorReconcile(keys, M.NO_CURSOR), M.NO_CURSOR)
})

test("scrollToShow moves as little as possible and stays in bounds", () => {
  // view 0..300 of 1000
  assert.equal(M.scrollToShow(0, 300, 1000, 100, 30, 10), 0)        // already visible
  assert.equal(M.scrollToShow(0, 300, 1000, 400, 30, 10), 140)      // below: bottom edge + margin at view bottom
  assert.equal(M.scrollToShow(500, 300, 1000, 200, 30, 10), 190)    // above: top edge - margin at view top
  assert.equal(M.scrollToShow(0, 300, 1000, 990, 30, 10), 700)      // clamped to the end
  assert.equal(M.scrollToShow(100, 300, 1000, 5, 30, 10), 0)        // clamped to the start
  assert.equal(M.scrollToShow(0, 300, 200, 150, 30, 10), 0)         // nothing to scroll
})

// ---- wallpaper readout ----

test("ago reads naturally", () => {
  assert.equal(M.ago(1000, 1030, tr), "just now")
  assert.equal(M.ago(1000, 1000 + 5 * 60 + 2, tr), "5 min ago")
  assert.equal(M.ago(1000, 1000 + 60, tr), "1 min ago")
  assert.equal(M.ago(0, 3 * 3600 + 5, tr), "3 h ago")
  assert.equal(M.ago(0, 86400, tr), "1 day ago")
  assert.equal(M.ago(0, 3 * 86400, tr), "3 days ago")
  assert.equal(M.ago(100, 50, tr), "just now")   // a clock that went backwards
})

const W = (o) => Object.assign({ enabled: true, turnOn: false, appliedAt: 0, appliedCount: 0, eligible: 0, statsKnown: true }, o)

test("wallpaper status: count, time and eligible lights", () => {
  assert.equal(M.wallpaperStatus(W({ appliedAt: 1000, appliedCount: 3, eligible: 4 }), 1120, tr), "Applied to 3 lights, 2 min ago  ·  4 lights eligible")
  assert.equal(M.wallpaperStatus(W({ appliedAt: 1000, appliedCount: 1, eligible: 1 }), 1000, tr), "Applied to 1 light, just now  ·  1 light eligible")
  assert.equal(M.wallpaperStatus(W({ eligible: 2 }), 5, tr), "Not applied yet  ·  2 lights eligible")
  assert.equal(M.wallpaperStatus(W({ enabled: false, eligible: 2 }), 5, tr), "2 lights eligible")
})

test("wallpaper status: a backend without counts still shows the time, and no counts", () => {
  assert.equal(M.wallpaperStatus(W({ statsKnown: false, appliedAt: 1000 }), 1000 + 7200, tr), "Last applied 2 h ago")
  assert.equal(M.wallpaperStatus(W({ statsKnown: false, enabled: false }), 5, tr), "")
})

test("wallpaper hint: only when sync is on, the counts are known and nothing is eligible", () => {
  assert.equal(M.wallpaperHint(W({}), tr), "No colour lights are on in the selected rooms. Turn on 'Also switch lights on' or pick other rooms.")
  assert.equal(M.wallpaperHint(W({ turnOn: true }), tr), "There are no colour lights in the selected rooms. Pick other rooms.")
  assert.equal(M.wallpaperHint(W({ eligible: 1 }), tr), "")
  assert.equal(M.wallpaperHint(W({ enabled: false }), tr), "")
  assert.equal(M.wallpaperHint(W({ statsKnown: false }), tr), "")
})

test("cursorOrder reads top to bottom, a line left to right, and drops duplicates", () => {
  const spots = [
    { key: "chip2", x: 80, y: 40, h: 24 },
    { key: "switch", x: 300, y: 0, h: 34 },
    { key: "chip1", x: 0, y: 41, h: 24 },
    { key: "title", x: 0, y: 6, h: 22 },
    { key: "below", x: 0, y: 90, h: 20 },
    { key: "chip1", x: 0, y: 41, h: 24 },
  ]
  assert.equal(M.cursorOrder(spots, 6).join(","), "title,switch,chip1,chip2,below")
})

// ---- the catalog (i18n/en.json) against the code that reads it ----

// Every key the code asks for, read from the source: Strings.t("k") / tr.t("k")
// (plain) and .tn("k") (plural); Strings.label("prefix", value) looks up
// "prefix.<value>" with a fallback, so it needs at least one "prefix." entry.
function usedKeys() {
  const root = path.join(__dirname, "..", "qml")
  const files = fs.readdirSync(root).filter((f) => f.endsWith(".qml") || f === "Model.js")
  const plain = new Set(), plural = new Set(), prefixes = new Set()
  for (const f of files) {
    const src = fs.readFileSync(path.join(root, f), "utf8").replace(/^\s*\/\/.*$/gm, "")   // not comments
    for (const m of src.matchAll(/(?:Strings|tr)\.t\("([^"]+)"/g)) plain.add(m[1])
    for (const m of src.matchAll(/(?:Strings|tr)\.tn\("([^"]+)"/g)) plural.add(m[1])
    for (const m of src.matchAll(/Strings\.label\("([^"]+)"/g)) prefixes.add(m[1])
    // A key built at run time could not be checked here.
    assert.equal(/(?:Strings|tr)\.(?:t|tn)\((?!")/.test(src), false, f + " passes a computed key to t()/tn()")
  }
  return { plain, plural, prefixes }
}
const holes = (s) => [...new Set(s.match(/%\d+/g) || [])].sort().join(",")

test("catalog: every key the code uses is in en.json, with the right shape", () => {
  const { plain, plural, prefixes } = usedKeys()
  assert.ok(plain.size > 50, "found " + plain.size + " keys: is the scan still matching?")
  for (const k of plain) assert.equal(typeof EN[k], "string", k + " should be a string in en.json")
  for (const k of plural) {
    assert.equal(typeof EN[k], "object", k + " should be a plural entry in en.json")
    assert.deepEqual(Object.keys(EN[k]).sort(), ["one", "other"], k)
    assert.equal(holes(EN[k].one), holes(EN[k].other), k + ": one and other take the same %N")
    assert.match(EN[k].other, /%1/, k + ": the count is %1")
  }
  for (const p of prefixes) assert.ok(Object.keys(EN).some((k) => k.startsWith(p + ".")), "no " + p + ".* entries")
})

test("catalog: en.json has no entry the code never reads", () => {
  const { plain, plural, prefixes } = usedKeys()
  for (const k of Object.keys(EN)) {
    const used = plain.has(k) || plural.has(k) || [...prefixes].some((p) => k.startsWith(p + "."))
    assert.ok(used, k + " is not used")
  }
})

test("catalog: holes are numbered from %1 with none skipped", () => {
  for (const [k, v] of Object.entries(EN)) {
    for (const form of typeof v === "string" ? [v] : Object.values(v)) {
      const n = (form.match(/%\d+/g) || []).map((h) => Number(h.slice(1)))
      const max = n.length ? Math.max(...n) : 0
      for (let i = 1; i <= max; i++) assert.ok(n.includes(i), k + " skips %" + i)
    }
  }
})

// ---- pairing and discovery failures -------------------------------------

test("errors: something that answers but is not a bridge reads as such", () => {
  assert.equal(M.errorMessage({ code: "unreachable", message: "cannot reach 192.168.1.9 (JSONDecodeError)" }, tr),
    "Something answered at that address, but it isn't a Hue bridge.")
  assert.equal(M.errorMessage({ code: "unreachable", message: "cannot reach 192.168.1.9 (ConnectionRefusedError)" }, tr), "Can't reach the bridge.")
})

test("pairing: a failed pair event reads human, with or without a code", () => {
  const f = (e) => M.pairFailure(Object.assign({ state: "failed" }, e), tr)
  assert.equal(f({ message: "cannot reach the bridge (JSONDecodeError)" }), "Something answered at that address, but it isn't a Hue bridge.")
  assert.equal(f({ message: "cannot reach the bridge (TimeoutError)" }), EN["pairing.noAnswer"])
  assert.equal(f({ code: "unreachable", message: "" }), EN["pairing.noAnswer"])
  assert.equal(f({ message: "the link button was not pressed in time" }), EN["pairing.timedOut"])
  assert.equal(f({ code: "timeout" }), EN["pairing.timedOut"])
  assert.equal(f({ code: "invalid", message: "that is not a host name or address" }), EN["pairing.badHost"])
  assert.equal(f({ message: "that is not a host name or address" }), EN["pairing.badHost"])
  assert.equal(f({ message: "link button disabled" }), "link button disabled")   // unknown: shown as sent
  assert.equal(f({ code: "bridge_error", message: "link button disabled" }), "The bridge refused: link button disabled")
  assert.equal(f({ code: "internal", message: "" }), "Pairing failed.")
  assert.equal(f({ message: "pairing failed unexpectedly (KeyError)" }), "Pairing failed.")
  assert.equal(f({}), "Pairing failed.")
})

test("discovery: a failed search blames the discovery service, not the bridge", () => {
  assert.equal(M.discoveryFailure({ code: "unreachable", message: "discovery failed (URLError)" }, tr), EN["pairing.discoveryFailed"])
  assert.equal(M.discoveryFailure({ code: "timeout", message: "" }, tr), EN["pairing.discoveryFailed"])
  assert.equal(M.discoveryFailure({ code: "rate_limited", message: "" }, tr), "The bridge is busy. Try again in a moment.")
  assert.equal(M.discoveryFailure({ code: "internal", message: "" }, tr), "Something went wrong.")
})
