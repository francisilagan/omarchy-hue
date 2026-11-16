import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "." as Hue

// One light inside a room: power, brightness and, expanded, colour, effects,
// power-up behaviour, flash and rename.
Column {
  id: row

  property var ui
  property var group
  property var light
  signal focusHome()

  readonly property var svc: Hue.HueService
  readonly property var eff: svc.effLight(group, light)
  readonly property bool detail: svc.isOpen("l:" + light.id)

  spacing: Style.space(6)

  Item {
    width: parent.width
    height: Style.space(22)
    Row {
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(8)
      Rectangle {
        visible: row.eff.on && !!row.eff.hex
        width: Style.space(10); height: width; radius: width / 2
        color: row.eff.hex ? row.eff.hex : "transparent"
        anchors.verticalCenter: parent.verticalCenter
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: row.light.reachable ? row.light.name : Hue.Strings.t("light.unreachable", row.light.name)
        color: row.eff.on ? row.ui.foreground : row.ui.dim
        font.family: row.ui.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        visible: row.eff.on && row.eff.effect !== "no_effect"
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: Hue.Strings.label("effect", row.eff.effect, Model.pretty(row.eff.effect))
        color: Commons.Color.accent
        font.family: row.ui.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
    Row {
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(10)
      Link {
        foreground: row.ui.foreground; fontFamily: row.ui.fontFamily
        anchors.verticalCenter: parent.verticalCenter
        isToggle: false
        text: row.detail ? "▾" : "⋯"
        onClicked: row.svc.toggleExpanded("l:" + row.light.id)
      }
      ToggleSwitch {
        anchors.verticalCenter: parent.verticalCenter
        property string cursorKey: "l:" + row.group.id + ":" + row.light.id
        hasCursor: row.ui.cursor === cursorKey
        CursorRing {}
        checked: row.eff.on
        foreground: row.ui.foreground
        onToggled: row.svc.setLight(row.light, { on: !row.eff.on })
      }
    }
  }

  LevelSlider {
    ui: row.ui
    width: parent.width
    visible: row.light.dimmable
    minimum: 1; maximum: 100; step: 1; integer: true
    value: row.eff.pct
    onCommitted: function(v) { row.svc.setLight(row.light, { on: true, pct: Math.round(v) }) }
  }

  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: row.detail

    Caption { foreground: row.ui.foreground; fontFamily: row.ui.fontFamily; width: parent.width; wrapMode: Text.WordWrap; text: row.light.product }

    ColorTuner {
      width: parent.width
      visible: row.light.color || row.light.ct
      foreground: row.ui.foreground
      panelBackground: row.ui.panelBackground
      fontFamily: row.ui.fontFamily
      hasColor: row.light.color
      hasCt: row.light.ct
      mirekMin: row.light.mirekMin
      mirekMax: row.light.mirekMax
      hex: row.eff.hex ? row.eff.hex : ""
      mirek: row.eff.mirek
      onPickHex: function(h) { row.svc.setLight(row.light, { on: true, hex: h }) }
      onPickMirek: function(m) { row.svc.setLight(row.light, { on: true, mirek: m }) }
      onDragChanged: function(d) { row.svc.drag(d) }
    }

    Caption { foreground: row.ui.foreground; fontFamily: row.ui.fontFamily; visible: row.light.effects.length > 0; text: Hue.Strings.t("light.effects") }
    Flow {
      visible: row.light.effects.length > 0
      width: parent.width
      spacing: Style.space(6)
      Chip {
        text: Hue.Strings.t("effects.off"); lit: row.eff.effect === "no_effect"
        foreground: row.ui.foreground; fontFamily: row.ui.fontFamily
        onClicked: row.svc.setEffect(row.light, "no_effect")
      }
      Repeater {
        model: row.light.effects
        Chip {
          required property string modelData
          text: Hue.Strings.label("effect", modelData, Model.pretty(modelData)); lit: row.eff.effect === modelData
          foreground: row.ui.foreground; fontFamily: row.ui.fontFamily
          onClicked: row.svc.setEffect(row.light, modelData)
        }
      }
    }

    Caption { foreground: row.ui.foreground; fontFamily: row.ui.fontFamily; visible: row.light.timedEffects.length > 0; text: Hue.Strings.t("light.timedEffects") }
    Flow {
      visible: row.light.timedEffects.length > 0
      width: parent.width
      spacing: Style.space(6)
      Repeater {
        model: row.light.timedEffects
        Chip {
          required property string modelData
          text: Hue.Strings.label("effect", modelData, Model.pretty(modelData)); lit: row.light.timedEffect === modelData
          foreground: row.ui.foreground; fontFamily: row.ui.fontFamily
          onClicked: row.svc.setTimedEffect(row.light, modelData)
        }
      }
    }

    Caption { foreground: row.ui.foreground; fontFamily: row.ui.fontFamily; visible: row.light.powerup !== null; text: Hue.Strings.t("light.powerup") }
    Flow {
      visible: row.light.powerup !== null
      width: parent.width
      spacing: Style.space(6)
      Repeater {
        model: [ { id: "safety", label: Hue.Strings.t("powerup.safety") }, { id: "last_on_state", label: Hue.Strings.t("powerup.lastState") }, { id: "powerfail", label: Hue.Strings.t("powerup.powerfail") } ]
        Chip {
          required property var modelData
          text: modelData.label; lit: row.light.powerup === modelData.id
          foreground: row.ui.foreground; fontFamily: row.ui.fontFamily
          onClicked: row.svc.send("powerup", { id: row.light.id, preset: modelData.id })
        }
      }
    }

    Button { text: Hue.Strings.t("light.flash"); foreground: row.ui.foreground; bordered: true; onClicked: row.svc.identify(row.light) }

    RenameRow {
      width: parent.width
      current: row.light.name
      foreground: row.ui.foreground; fontFamily: row.ui.fontFamily
      onSubmitted: function(n) { row.svc.rename("light", row.light.id, n) }
      onEscaped: row.focusHome()
    }
  }
}
