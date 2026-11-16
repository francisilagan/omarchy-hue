import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model
import "." as Hue

Column {
  id: tab
  property var ui
  readonly property var svc: Hue.HueService
  spacing: Style.space(12)

  Card {
    ui: tab.ui
    Title { ui: tab.ui; text: Hue.Strings.t("automations.title") }
    Caption { foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily; visible: tab.svc.automations.length === 0; text: Hue.Strings.t("automations.none") }
    Repeater {
      model: tab.svc.automations
      Item {
        id: row
        required property var modelData
        readonly property bool on: tab.svc.effFlag("a:" + modelData.id, modelData.enabled)
        width: parent.width
        height: Style.space(40)
        Column {
          anchors.left: parent.left
          anchors.right: sw.left
          anchors.rightMargin: Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          Text {
            width: parent.width
            elide: Text.ElideRight
            textFormat: Text.PlainText
            text: Model.pretty(row.modelData.name)
            color: row.on ? tab.ui.foreground : tab.ui.dim
            font.family: tab.ui.fontFamily
            font.pixelSize: Style.font.body
          }
          Caption {
            foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
            width: parent.width
            elide: Text.ElideRight
            text: row.modelData.script + (row.modelData.status !== "" ? "  ·  " + Hue.Strings.label("automationStatus", row.modelData.status) : "")
          }
        }
        ToggleSwitch {
          id: sw
          anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
          property string cursorKey: "a:" + row.modelData.id
          hasCursor: tab.ui.cursor === cursorKey
          CursorRing {}
          checked: row.on
          foreground: tab.ui.foreground
          onToggled: tab.svc.setAutomation(row.modelData, !row.on)
        }
      }
    }
  }

  Card {
    ui: tab.ui
    visible: tab.svc.entertainment.length > 0
    Title { ui: tab.ui; text: Hue.Strings.t("automations.entertainment") }
    Repeater {
      model: tab.svc.entertainment
      Item {
        id: ent
        required property var modelData
        width: parent.width
        height: Style.space(40)
        Column {
          anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
          Text {
            textFormat: Text.PlainText
            text: ent.modelData.name
            color: tab.ui.foreground; font.family: tab.ui.fontFamily; font.pixelSize: Style.font.body
          }
          Caption {
            foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
            text: [Hue.Strings.label("entertainmentType", ent.modelData.type, Model.pretty(ent.modelData.type)), Hue.Strings.tn("common.lightCount", ent.modelData.lights),
                   Hue.Strings.label("entertainmentStatus", ent.modelData.status)].join("  ·  ")
          }
        }
        Button {
          visible: ent.modelData.status === "active"
          anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
          property string cursorKey: "e:" + ent.modelData.id
          hasCursor: tab.ui.cursor === cursorKey
          CursorRing {}
          text: Hue.Strings.t("automations.stop"); foreground: tab.ui.foreground; bordered: true
          onClicked: tab.svc.send("entertainment.stop", { id: ent.modelData.id })
        }
      }
    }
    Caption {
      foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
      width: parent.width; wrapMode: Text.WordWrap
      text: Hue.Strings.t("automations.streamingNote")
    }
  }
}
