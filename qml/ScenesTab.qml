import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "." as Hue

Column {
  id: tab
  property var ui
  signal focusHome()
  readonly property var svc: Hue.HueService
  property string saveGroup: ""
  readonly property string chosenGroup: saveGroup !== "" ? saveGroup : (svc.groups.length > 0 ? svc.groups[0].id : "")

  spacing: Style.space(12)

  Repeater {
    model: tab.svc.groups
    Card {
      id: sg
      required property var modelData
      readonly property var scenes: tab.svc.groupScenes(modelData)
      readonly property var smart: tab.svc.groupSmartScenes(modelData)
      ui: tab.ui
      visible: scenes.length + smart.length > 0

      Title { ui: tab.ui; text: sg.modelData.kind === "zone" ? Hue.Strings.t("scenes.zoneTitle", sg.modelData.name) : sg.modelData.name }

      Repeater {
        model: sg.smart
        Item {
          id: smartRow
          required property var modelData
          readonly property bool on: tab.svc.effFlag("s:" + modelData.id, modelData.active)
          width: parent.width
          height: Style.space(28)
          Text {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            textFormat: Text.PlainText
            text: "◷ " + smartRow.modelData.name
            color: tab.ui.foreground; font.family: tab.ui.fontFamily; font.pixelSize: Style.font.body
          }
          Row {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(8)
            Caption { foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily; anchors.verticalCenter: parent.verticalCenter; text: smartRow.on ? Hue.Strings.t("scenes.running") : Hue.Strings.t("scenes.off") }
            ToggleSwitch {
              anchors.verticalCenter: parent.verticalCenter
              property string cursorKey: "ss:" + smartRow.modelData.id
              hasCursor: tab.ui.cursor === cursorKey
              CursorRing {}
              checked: smartRow.on
              foreground: tab.ui.foreground
              onToggled: tab.svc.setSmartScene(smartRow.modelData, !smartRow.on)
            }
          }
        }
      }

      Repeater {
        model: sg.scenes
        Column {
          id: sceneRow
          required property var modelData
          readonly property bool detail: tab.svc.isOpen("S:" + modelData.id)
          width: parent.width
          spacing: Style.space(6)

          Item {
            width: parent.width
            height: Style.space(26)
            Row {
              anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(8)
              Link {
                foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
                anchors.verticalCenter: parent.verticalCenter
                text: sceneRow.modelData.name
                open: sceneRow.detail
                onClicked: tab.svc.toggleExpanded("S:" + sceneRow.modelData.id)
              }
              Caption {
                foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
                visible: sceneRow.modelData.active
                anchors.verticalCenter: parent.verticalCenter
                text: sceneRow.modelData.mode === "dynamic_palette" ? Hue.Strings.t("scenes.dynamicTag") : Hue.Strings.t("scenes.activeTag")
                color: Commons.Color.accent
              }
            }
            Row {
              anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(6)
              Chip {
                property string cursorKey: "s:" + sceneRow.modelData.id + ":static"
                hasCursor: tab.ui.cursor === cursorKey
                text: Hue.Strings.t("scenes.static"); lit: sceneRow.modelData.mode === "static"
                foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
                onClicked: tab.svc.recallScene(sceneRow.modelData, "active")
              }
              Chip {
                visible: sceneRow.modelData.dynamic
                property string cursorKey: "s:" + sceneRow.modelData.id + ":dynamic"
                hasCursor: tab.ui.cursor === cursorKey
                text: Hue.Strings.t("scenes.dynamic"); lit: sceneRow.modelData.mode === "dynamic_palette"
                foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
                onClicked: tab.svc.recallScene(sceneRow.modelData, "dynamic_palette")
              }
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: sceneRow.detail

            Row {
              visible: sceneRow.modelData.dynamic
              width: parent.width
              spacing: Style.space(8)
              Caption { id: speedLabel; foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily; width: Math.max(Style.space(48), implicitWidth); anchors.verticalCenter: parent.verticalCenter; text: Hue.Strings.t("scenes.speed") }
              LevelSlider {
                ui: tab.ui
                width: parent.width - Style.space(56) - (speedLabel.width - Style.space(48))
                anchors.verticalCenter: parent.verticalCenter
                minimum: 0; maximum: 1; step: 0.05
                value: sceneRow.modelData.speed
                onCommitted: function(v) { tab.svc.send("scene.update", { id: sceneRow.modelData.id, speed: v }) }
              }
            }
            Item {
              visible: sceneRow.modelData.dynamic
              width: parent.width
              height: Style.space(24)
              Caption { foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: Hue.Strings.t("scenes.autoDynamic") }
              ToggleSwitch {
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                checked: sceneRow.modelData.autoDynamic
                foreground: tab.ui.foreground
                onToggled: tab.svc.send("scene.update", { id: sceneRow.modelData.id, autoDynamic: !sceneRow.modelData.autoDynamic })
              }
            }
            Row {
              spacing: Style.space(8)
              Button {
                text: Hue.Strings.t("scenes.resave")
                foreground: tab.ui.foreground; bordered: true
                onClicked: tab.svc.send("scene.update", { id: sceneRow.modelData.id, snapshot: true })
              }
              Button {
                text: tab.svc.confirmKey === "sd:" + sceneRow.modelData.id ? Hue.Strings.t("scenes.deleteConfirm") : Hue.Strings.t("scenes.delete")
                foreground: tab.svc.confirmKey === "sd:" + sceneRow.modelData.id ? Commons.Color.urgent : tab.ui.foreground
                bordered: true
                onClicked: if (tab.svc.confirmed("sd:" + sceneRow.modelData.id)) tab.svc.send("scene.delete", { id: sceneRow.modelData.id })
              }
            }
            RenameRow {
              width: parent.width
              current: sceneRow.modelData.name
              foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
              onSubmitted: function(n) { tab.svc.rename("scene", sceneRow.modelData.id, n) }
              onEscaped: tab.focusHome()
            }
          }
        }
      }
    }
  }

  Card {
    ui: tab.ui
    subtle: true
    Text {
      textFormat: Text.PlainText
      text: Hue.Strings.t("scenes.saveTitle")
      color: tab.ui.foreground; font.family: tab.ui.fontFamily; font.pixelSize: Style.font.body; font.bold: true
    }
    Flow {
      width: parent.width
      spacing: Style.space(6)
      Repeater {
        model: tab.svc.groups
        Chip {
          required property var modelData
          text: modelData.name
          lit: tab.chosenGroup === modelData.id
          foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
          onClicked: tab.saveGroup = modelData.id
        }
      }
    }
    Field { id: sceneName; ui: tab.ui; maximumLength: 32; width: parent.width; placeholderText: Hue.Strings.t("scenes.namePlaceholder"); onEscaped: tab.focusHome() }
    Button {
      text: Hue.Strings.t("scenes.save")
      foreground: tab.ui.foreground; bordered: true
      onClicked: {
        if (tab.chosenGroup !== "" && sceneName.text.trim() !== "") {
          tab.svc.send("scene.create", { name: sceneName.text.trim(), group: tab.chosenGroup })
          sceneName.text = ""
          tab.focusHome()
        }
      }
    }
  }
}
