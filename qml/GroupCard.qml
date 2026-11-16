import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "." as Hue

// A room or zone on the Lights tab: switch, brightness, scenes, and (expanded)
// colour, effects, rename, zone members and each light.
Card {
  id: card

  property var group
  signal focusHome()

  readonly property var svc: Hue.HueService
  readonly property var lights: svc.groupLights(group)
  readonly property var scenes: svc.groupScenes(group)
  readonly property var smart: svc.groupSmartScenes(group)
  readonly property var eff: svc.effGroup(group)
  readonly property bool isZone: group.kind === "zone"
  property string pressedScene: ""

  opacity: eff.on ? 1.0 : 0.82
  spacing: Style.space(10)

  Item {
    width: parent.width
    height: Style.space(26)
    Row {
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(8)
      Rectangle {
        visible: card.eff.on && card.eff.hex !== ""
        width: Style.space(12); height: width; radius: width / 2
        color: card.eff.hex !== "" ? card.eff.hex : "transparent"
        anchors.verticalCenter: parent.verticalCenter
      }
      Title { ui: card.ui; anchors.verticalCenter: parent.verticalCenter; text: card.group.name }
      Text {
        visible: card.isZone
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        text: Hue.Strings.t("zone.tag")
        color: card.ui.dim
        font.family: card.ui.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
    ToggleSwitch {
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      property string cursorKey: "g:" + card.group.id
      hasCursor: card.ui.cursor === cursorKey
      CursorRing {}
      checked: card.eff.on
      foreground: card.ui.foreground
      onToggled: card.svc.setGroup(card.group, { on: !card.eff.on })
    }
  }

  Row {
    width: parent.width
    spacing: Style.space(8)
    Text {
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: String.fromCodePoint(0xF00DF)
      color: card.ui.dim
      font.family: card.ui.fontFamily
      font.pixelSize: Style.font.icon
    }
    LevelSlider {
      ui: card.ui
      width: parent.width - Style.space(60) - (pctLabel.width - Style.space(34))
      anchors.verticalCenter: parent.verticalCenter
      minimum: 1; maximum: 100; step: 1; integer: true
      value: card.eff.pct
      onCommitted: function(v) { card.svc.setGroup(card.group, { on: true, pct: Math.round(v) }) }
    }
    Text {
      id: pctLabel
      width: Math.max(Style.space(34), implicitWidth)
      anchors.verticalCenter: parent.verticalCenter
      horizontalAlignment: Text.AlignRight
      textFormat: Text.PlainText
      text: Hue.Strings.t("common.percent", Hue.Strings.num(card.eff.pct))
      color: card.ui.dim
      font.family: card.ui.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }

  Flow {
    width: parent.width
    spacing: Style.space(6)
    visible: card.scenes.length + card.smart.length > 0
    Repeater {
      model: card.scenes
      Chip {
        required property var modelData
        property string cursorKey: "gs:" + card.group.id + ":" + modelData.id
        hasCursor: card.ui.cursor === cursorKey
        text: modelData.name
        foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
        lit: modelData.active || card.pressedScene === modelData.id
        onClicked: { card.pressedScene = modelData.id; pressedClear.restart(); card.svc.recallScene(modelData, "active") }
      }
    }
    Repeater {
      model: card.smart
      Chip {
        required property var modelData
        property string cursorKey: "gss:" + card.group.id + ":" + modelData.id
        hasCursor: card.ui.cursor === cursorKey
        text: "◷ " + modelData.name
        foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
        lit: card.svc.effFlag("s:" + modelData.id, modelData.active)
        onClicked: card.svc.setSmartScene(modelData, !card.svc.effFlag("s:" + modelData.id, modelData.active))
      }
    }
  }
  Timer { id: pressedClear; interval: 1500; onTriggered: card.pressedScene = "" }

  // A Flow, not a Row: longer languages wrap these links instead of running off the card.
  Flow {
    width: parent.width
    spacing: Style.space(16)
    Link {
      foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
      property string cursorKey: "gl:" + card.group.id
      hasCursor: card.ui.cursor === cursorKey
      text: Hue.Strings.tn("common.lightCount", card.lights.length)
      open: card.svc.isOpen("L:" + card.group.id)
      onClicked: card.svc.toggleExpanded("L:" + card.group.id)
    }
    Link {
      foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
      visible: card.eff.anyColor || card.eff.anyCt || card.eff.anyEffect
      text: Hue.Strings.t("group.colourEffects")
      open: card.svc.isOpen("T:" + card.group.id)
      onClicked: card.svc.toggleExpanded("T:" + card.group.id)
    }
    Link {
      foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
      text: Hue.Strings.t("group.more")
      open: card.svc.isOpen("M:" + card.group.id)
      onClicked: card.svc.toggleExpanded("M:" + card.group.id)
    }
  }

  // Colour, white, effects for the whole group
  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: card.svc.isOpen("T:" + card.group.id)

    ColorTuner {
      width: parent.width
      foreground: card.ui.foreground; panelBackground: card.ui.panelBackground; fontFamily: card.ui.fontFamily
      hasColor: card.eff.anyColor
      hasCt: card.eff.anyCt
      mirekMin: card.eff.mirekMin
      mirekMax: card.eff.mirekMax
      hex: card.eff.hex
      mirek: card.eff.mirek
      onPickHex: function(h) { card.svc.setGroup(card.group, { on: true, hex: h }) }
      onPickMirek: function(m) { card.svc.setGroup(card.group, { on: true, mirek: m }) }
      onDragChanged: function(d) { card.svc.drag(d) }
    }

    Caption { foreground: card.ui.foreground; fontFamily: card.ui.fontFamily; visible: card.eff.anyEffect; text: Hue.Strings.t("group.effects") }
    Flow {
      visible: card.eff.anyEffect
      width: parent.width
      spacing: Style.space(6)
      Chip {
        text: Hue.Strings.t("effects.off")
        foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
        onClicked: card.svc.setGroupEffect(card.group, "no_effect")
      }
      Repeater {
        model: {
          var seen = {}, out = []
          for (var i = 0; i < card.lights.length; i++)
            for (var j = 0; j < card.lights[i].effects.length; j++) {
              var e = card.lights[i].effects[j]
              if (!seen[e]) { seen[e] = true; out.push(e) }
            }
          return out
        }
        Chip {
          required property string modelData
          text: Hue.Strings.label("effect", modelData, Model.pretty(modelData))
          foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
          onClicked: card.svc.setGroupEffect(card.group, modelData)
        }
      }
    }
  }

  // Rename and zone management
  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: card.svc.isOpen("M:" + card.group.id)

    RenameRow {
      width: parent.width
      current: card.group.name
      foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
      onSubmitted: function(n) { card.svc.rename(card.group.kind, card.group.id, n) }
      onEscaped: card.focusHome()
    }

    Caption { foreground: card.ui.foreground; fontFamily: card.ui.fontFamily; visible: card.isZone; text: Hue.Strings.t("zone.members") }
    Flow {
      visible: card.isZone
      width: parent.width
      spacing: Style.space(6)
      Repeater {
        model: card.svc.allLights
        Chip {
          required property var modelData
          readonly property bool member: card.group.lightIds.indexOf(modelData.id) >= 0
          text: modelData.name
          lit: member
          foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
          onClicked: {
            var ids = card.group.lightIds.slice()
            var at = ids.indexOf(modelData.id)
            if (at >= 0) ids.splice(at, 1); else ids.push(modelData.id)
            if (ids.length > 0) card.svc.send("zone.members", { id: card.group.id, lights: ids })
          }
        }
      }
    }
    Button {
      visible: card.isZone
      text: card.svc.confirmKey === "zd:" + card.group.id ? Hue.Strings.t("zone.deleteConfirm") : Hue.Strings.t("zone.delete")
      foreground: card.svc.confirmKey === "zd:" + card.group.id ? Commons.Color.urgent : card.ui.foreground
      bordered: true
      onClicked: if (card.svc.confirmed("zd:" + card.group.id)) card.svc.send("zone.delete", { id: card.group.id })
    }
  }

  // Each light
  Column {
    width: parent.width
    spacing: Style.space(10)
    visible: card.svc.isOpen("L:" + card.group.id)
    Repeater {
      model: card.lights
      LightRow {
        required property var modelData
        width: parent.width
        ui: card.ui
        group: card.group
        light: modelData
        onFocusHome: card.focusHome()
      }
    }
  }
}
