pragma Singleton
import QtQuick
import Quickshell
import qs.Commons as Commons
import "Model.js" as Model

// The plugin's text, in the language picked under Setup > Language. One shared
// reader of i18n/<code>.json (the host's Commons.Translations: a missing string
// falls back to the base language, then en.json, then the key) for every view.
//
//   Strings.t("zone.new")                       plain text
//   Strings.t("devices.pairedWithAt", name, ip) %1, %2 filled in one pass
//   Strings.tn("common.lightCount", n)          plural form for n; %1 is n, written
//                                               the language's way, later args are %2...
//   Strings.label("effect", id, fallback)       an enum from the bridge: its entry,
//                                               else `fallback`
//
// Call these inside bindings so a language switch re-renders them. The same
// object is what Model.js's text functions take as `tr`.
Singleton {
  id: root

  Commons.Translations { id: catalog; directory: Qt.resolvedUrl("i18n") }

  function t(key) {
    return Model.fill(catalog.t(key), Array.prototype.slice.call(arguments, 1))
  }
  function tn(key, count) {
    return Model.fill(catalog.tn(key, count), [root.num(count)].concat(Array.prototype.slice.call(arguments, 2)))
  }
  function label(prefix, value, fallback) {
    return catalog.t(prefix + "." + value, fallback !== undefined ? fallback : String(value))
  }
  function num(value, decimals) { return Commons.I18n.formatNumber(value, decimals) }
}
