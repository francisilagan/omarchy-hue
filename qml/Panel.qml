import QtQuick
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "." as Hue

// Philips Hue in the bar: a bulb button that opens a panel with four tabs.
//   Lights       rooms and zones, wallpaper sync
//   Scenes       scenes, routines, saving the current look
//   Automations  the bridge's automations and entertainment areas
//   Devices      bridge, sensors, switches, batteries, firmware
// The panel is a view. The connection, state and pending changes live in the
// HueService singleton (shared by every monitor's bar), which talks to the
// backend process. See ARCHITECTURE.md.
Panel {
  id: root
  moduleName: "francisilagan.hue-lights"
  ipcTarget: "francisilagan.hue-lights"

  readonly property var svc: Hue.HueService
  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color panelBackground: bar ? bar.background : Commons.Color.background
  readonly property color dim: Qt.darker(foreground, 1.4)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // What the views need to look like the bar.
  readonly property QtObject ui: QtObject {
    readonly property color foreground: root.foreground
    readonly property color panelBackground: root.panelBackground
    readonly property color dim: root.dim
    readonly property string fontFamily: root.fontFamily
    readonly property var bar: root.bar
    readonly property string cursor: root.rowCursor.key   // the row under the keyboard cursor
  }

  property string tab: "lights"
  readonly property bool needsPairing: svc.conn === "unpaired" || svc.conn === "pairing" || svc.conn === "unauthorized" || svc.conn === "cert_changed"
  // Nothing ever loaded and the bridge cannot be reached: Retry, or pair elsewhere.
  readonly property bool recovering: svc.stalled && !svc.loaded && !needsPairing
  readonly property bool paired: !recovering && (svc.conn === "connected" || svc.conn === "connecting" || (svc.conn === "unreachable" && svc.loaded))

  // nf-md-lightbulb_on_outline / lightbulb_on / lightbulb_off
  readonly property string glyph: svc.conn === "unreachable" || needsPairing || recovering ? String.fromCodePoint(0xF06E9)
                                : svc.anyOn ? String.fromCodePoint(0xF06E8) : String.fromCodePoint(0xF0E4F)

  // No refresh on open: the event stream keeps the snapshot current (R and a
  // middle click still resync by hand).
  function open() { root.controller.show() }
  function toggle() { root.opened ? root.close() : root.open() }

  onTabChanged: { flick.contentY = 0; rowCursor = Model.NO_CURSOR }
  onOpenedChanged: if (!opened) rowCursor = Model.NO_CURSOR

  // ---- keyboard cursor ------------------------------------------------------
  // One highlighted row in the current tab. A row is any visible item in the
  // scroll area with a non-empty `cursorKey` (switches, scene chips, the
  // "N lights" disclosure, wallpaper toggles); it draws itself from
  // `ui.cursor === cursorKey`, and activating it emits its `toggled` (switches)
  // or `clicked` signal. Rows are found by walking the tree on demand, so
  // delegates rebuilt by a new snapshot need no bookkeeping. Where the cursor
  // goes is decided in Model.js (cursorStep, cursorReconcile, cursorOrder).
  property var rowCursor: Model.NO_CURSOR

  function _cursorItems(item, out) {
    var kids = item.children
    for (var i = 0; i < kids.length; i++) {
      var k = kids[i]
      if (!k.visible) continue
      if (typeof k.cursorKey === "string" && k.cursorKey !== "") out.push(k)
      _cursorItems(k, out)
    }
    return out
  }
  function cursorSpots() {
    var items = _cursorItems(column, [])
    var spots = [], byKey = {}
    for (var i = 0; i < items.length; i++) {
      var it = items[i]
      if (it.width <= 0 || it.height <= 0) continue
      var p = it.mapToItem(column, 0, 0)
      spots.push({ key: it.cursorKey, x: p.x, y: p.y, h: it.height })
      if (!byKey[it.cursorKey]) byKey[it.cursorKey] = { item: it, y: p.y, h: it.height }
    }
    return { keys: Model.cursorOrder(spots, Style.space(8)), byKey: byKey }
  }
  function moveCursor(dy) {
    var s = cursorSpots()
    var next = Model.cursorStep(s.keys, rowCursor, dy)
    if (next === null) { flick.scrollBy(dy * Style.space(72)); return }
    rowCursor = next
    var spot = s.byKey[next.key]
    if (spot) flick.contentY = Model.scrollToShow(flick.contentY, flick.height, flick.contentHeight, spot.y, spot.h, Style.space(16))
  }
  // Returns false when there is no cursor (Space/Enter then switch every light).
  function activateCursor() {
    if (rowCursor.key === "") return false
    var spot = cursorSpots().byKey[rowCursor.key]
    if (!spot) return false
    var it = spot.item
    if (typeof it.toggled === "function") it.toggled()
    else if (typeof it.clicked === "function") it.clicked()
    return true
  }
  function reconcileCursor() {
    if (rowCursor.key !== "") rowCursor = Model.cursorReconcile(cursorSpots().keys, rowCursor)
  }
  // Rows come and go with new snapshots and opened sections. Wait a moment so
  // the layouts have placed the new rows before reading their order.
  Timer { id: reconcileTimer; interval: 60; onTriggered: root.reconcileCursor() }
  Connections {
    target: root.svc
    function onGroupsChanged() { reconcileTimer.restart() }
    function onLightsChanged() { reconcileTimer.restart() }
    function onScenesChanged() { reconcileTimer.restart() }
    function onSmartScenesChanged() { reconcileTimer.restart() }
    function onAutomationsChanged() { reconcileTimer.restart() }
    function onDevicesChanged() { reconcileTimer.restart() }
    function onEntertainmentChanged() { reconcileTimer.restart() }
    function onExpandedChanged() { reconcileTimer.restart() }
    function onWallpaperChanged() { reconcileTimer.restart() }
  }

  readonly property var tabOrder: ["lights", "scenes", "automations", "devices"]
  function stepTab(delta) {
    var i = tabOrder.indexOf(tab) + delta
    tab = tabOrder[Math.max(0, Math.min(tabOrder.length - 1, i))]
  }

  Component.onCompleted: svc.start()

  implicitWidth: Math.max(button.implicitWidth, Style.bar.iconSlot)
  implicitHeight: Math.max(button.implicitHeight, bar ? bar.barSize : 26)

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyph
    tooltipText: root.needsPairing ? Hue.Strings.t("panel.tooltip.notConnected")
               : svc.conn === "unreachable" || root.recovering ? Hue.Strings.t("panel.tooltip.unreachable")
               : Hue.Strings.t("panel.tooltip.lightsOn", Hue.Strings.num(svc.counts.on), Hue.Strings.num(svc.counts.total))
    onPressed: function(b) {
      if (b === Qt.RightButton) svc.setAll(!svc.anyOn)
      else if (b === Qt.MiddleButton) svc.refresh()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    centerOnBar: false
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(680))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      // While a text field has focus, every key belongs to it.
      blocked: {
        var f = keyCatcher.Window.activeFocusItem
        return !!f && f.cursorPosition !== undefined
      }
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      // Left/Right (h/l) walk the tabs. Up/Down (k/j) move the row cursor (and
      // scroll past either end, or on a tab without rows). Space/Enter work the
      // row under the cursor; with no cursor shown they flip every light.
      onMoveRequested: function(dx, dy) {
        if (dx !== 0 && root.paired) root.stepTab(dx)
        if (dy !== 0) root.moveCursor(dy)
      }
      onActivateRequested: if (!root.activateCursor() && root.paired && svc.connected && svc.loaded) svc.setAll(!svc.anyOn)
      onTextKey: function(t) {
        var key = t.toLowerCase()
        if (key === "r") svc.refresh()
        else if (key === "a") svc.setAll(!svc.anyOn)
        else if (key === "1") root.tab = "lights"
        else if (key === "2") root.tab = "scenes"
        else if (key === "3") root.tab = "automations"
        else if (key === "4") root.tab = "devices"
      }

      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        // Never let the scroll area steal a slider drag.
        interactive: contentHeight > height && svc.dragCount === 0
        function scrollBy(dy) {
          contentY = Math.max(0, Math.min(Math.max(0, contentHeight - height), contentY + dy))
        }
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: flick.width
          spacing: Style.space(12)

          // Header
          Item {
            width: parent.width
            height: Style.space(44)
            Column {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(16)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)
              Text {
                textFormat: Text.PlainText
                text: "Hue"
                color: root.foreground; font.family: root.fontFamily
                font.pixelSize: Style.font.heading; font.bold: true
              }
              Text {
                textFormat: Text.PlainText
                text: svc.notice !== "" ? svc.notice
                    : svc.conn !== "connected" ? (Model.connectionMessage(svc.conn, svc.connDetail, Hue.Strings) || "")
                    : !svc.loaded ? Hue.Strings.t("panel.loading")
                    : Hue.Strings.tn("panel.lightsOn", svc.counts.total, Hue.Strings.num(svc.counts.on))
                color: svc.notice !== "" && svc.noticeIsError ? Commons.Color.urgent : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
                width: column.width - Style.space(100)
              }
            }
            ToggleSwitch {
              anchors.right: parent.right
              anchors.rightMargin: Style.space(16)
              anchors.verticalCenter: parent.verticalCenter
              visible: root.paired
              enabled: svc.connected && svc.loaded
              checked: svc.anyOn
              foreground: root.foreground
              onToggled: svc.setAll(!svc.anyOn)
            }
          }

          Loader {
            active: root.recovering
            width: parent.width
            height: item ? item.implicitHeight : 0  // explicit: an unloaded Loader keeps its last height otherwise
            sourceComponent: RecoveryView { ui: root.ui; width: column.width }
          }

          Loader {
            active: root.needsPairing
            width: parent.width
            height: item ? item.implicitHeight : 0  // explicit: an unloaded Loader keeps its last height otherwise
            sourceComponent: PairingView { ui: root.ui; width: column.width; onFocusHome: keyCatcher.forceActiveFocus() }
          }

          ButtonGroup {
            visible: root.paired
            x: Style.space(12)
            width: column.width - Style.space(24)
            foreground: root.foreground
            background: root.panelBackground
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            focusable: false
            options: [
              { value: "lights", label: Hue.Strings.t("tab.lights") },
              { value: "scenes", label: Hue.Strings.t("tab.scenes") },
              { value: "automations", label: Hue.Strings.t("tab.automations") },
              { value: "devices", label: Hue.Strings.t("tab.devices") }
            ]
            value: root.tab
            onChanged: function(v) { root.tab = v }
          }

          Loader {
            active: root.paired && root.tab === "lights"
            width: parent.width
            height: item ? item.implicitHeight : 0  // explicit: an unloaded Loader keeps its last height otherwise
            sourceComponent: LightsTab { ui: root.ui; width: column.width; onFocusHome: keyCatcher.forceActiveFocus() }
          }
          Loader {
            active: root.paired && root.tab === "scenes"
            width: parent.width
            height: item ? item.implicitHeight : 0  // explicit: an unloaded Loader keeps its last height otherwise
            sourceComponent: ScenesTab { ui: root.ui; width: column.width; onFocusHome: keyCatcher.forceActiveFocus() }
          }
          Loader {
            active: root.paired && root.tab === "automations"
            width: parent.width
            height: item ? item.implicitHeight : 0  // explicit: an unloaded Loader keeps its last height otherwise
            sourceComponent: AutomationsTab { ui: root.ui; width: column.width }
          }
          Loader {
            active: root.paired && root.tab === "devices"
            width: parent.width
            height: item ? item.implicitHeight : 0  // explicit: an unloaded Loader keeps its last height otherwise
            sourceComponent: DevicesTab { ui: root.ui; width: column.width }
          }

          Text {
            width: parent.width - Style.space(32)
            x: Style.space(16)
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: Hue.Strings.t("panel.keys")
            color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption
          }
          Item { width: 1; height: Style.space(4) }
        }
      }
    }
  }
}
