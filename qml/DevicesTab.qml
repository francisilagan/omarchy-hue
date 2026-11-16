import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "." as Hue

Column {
  id: tab
  property var ui
  readonly property var svc: Hue.HueService
  spacing: Style.space(12)

  Repeater {
    model: tab.svc.devices
    Card {
      id: dev
      required property var modelData
      ui: tab.ui
      spacing: Style.space(6)

      Item {
        width: parent.width
        height: Style.space(24)
        Title { ui: tab.ui; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: dev.modelData.name }
        Caption {
          foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
          anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
          text: !dev.modelData.reachable ? Hue.Strings.t("devices.offline")
              : dev.modelData.battery !== undefined ? String.fromCodePoint(0xF0079) + " " + Hue.Strings.t("common.percent", Hue.Strings.num(dev.modelData.battery))
              : Hue.Strings.t("devices.online")
          color: !dev.modelData.reachable || (dev.modelData.battery !== undefined && dev.modelData.battery <= 15) ? Commons.Color.urgent : tab.ui.dim
        }
      }
      Caption {
        foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
        width: parent.width; wrapMode: Text.WordWrap
        text: dev.modelData.software !== "" ? Hue.Strings.t("devices.productFirmware", dev.modelData.product, dev.modelData.software) : dev.modelData.product
      }
      Caption {
        foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
        visible: dev.modelData.update !== undefined && dev.modelData.update !== "no_update"
        width: parent.width; wrapMode: Text.WordWrap
        color: Commons.Color.accent
        text: Hue.Strings.t("devices.update", Hue.Strings.label("updateState", dev.modelData.update || "", Model.pretty(dev.modelData.update || "")))
      }
      Repeater {
        model: dev.modelData.readings
        Item {
          required property var modelData
          width: parent.width
          height: Style.space(20)
          Caption { foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: parent.modelData.label }
          Text {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: parent.modelData.value
            color: tab.ui.foreground; font.family: tab.ui.fontFamily; font.pixelSize: Style.font.bodySmall
          }
        }
      }
      Repeater {
        model: dev.modelData.controls
        Item {
          id: ctl
          required property var modelData
          readonly property bool on: tab.svc.effFlag("x:" + modelData.id, modelData.enabled)
          width: parent.width
          height: Style.space(26)
          Caption { foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: ctl.modelData.label }
          ToggleSwitch {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            property string cursorKey: "x:" + ctl.modelData.id
            hasCursor: tab.ui.cursor === cursorKey
            CursorRing {}
            checked: ctl.on
            foreground: tab.ui.foreground
            onToggled: tab.svc.setEnabled(ctl.modelData, !ctl.on)
          }
        }
      }
    }
  }

  Caption {
    foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
    visible: tab.svc.devices.length === 0
    x: Style.space(16)
    text: Hue.Strings.t("devices.none")
  }

  Card {
    ui: tab.ui
    subtle: true
    visible: tab.svc.loaded
    Caption {
      foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
      width: parent.width; wrapMode: Text.WordWrap
      text: tab.svc.bridge.host ? Hue.Strings.t("devices.pairedWithAt", tab.svc.bridge.name, tab.svc.bridge.host) : Hue.Strings.t("devices.pairedWith", tab.svc.bridge.name)
    }
    Button {
      text: tab.svc.confirmKey === "forget" ? Hue.Strings.t("devices.forgetConfirm") : Hue.Strings.t("devices.forget")
      foreground: tab.svc.confirmKey === "forget" ? Commons.Color.urgent : tab.ui.foreground
      bordered: true
      onClicked: tab.svc.forgetBridge()
    }
  }
}
