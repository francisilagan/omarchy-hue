import QtQuick
import qs.Commons
import qs.Ui
import "." as Hue

Column {
  id: tab
  property var ui
  signal focusHome()
  readonly property var svc: Hue.HueService
  property var zoneSelection: ({})

  spacing: Style.space(12)

  Repeater {
    model: tab.svc.groups
    GroupCard {
      required property var modelData
      ui: tab.ui
      group: modelData
      onFocusHome: tab.focusHome()
    }
  }

  Card {
    id: zoneForm
    ui: tab.ui
    subtle: true
    readonly property bool open: tab.svc.isOpen("newzone")

    Link {
      foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
      text: Hue.Strings.t("zone.new")
      open: zoneForm.open
      onClicked: tab.svc.toggleExpanded("newzone")
    }
    Caption {
      foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
      visible: zoneForm.open
      width: parent.width
      wrapMode: Text.WordWrap
      text: Hue.Strings.t("zone.explain")
    }
    Field { id: zoneName; ui: tab.ui; maximumLength: 32; visible: zoneForm.open; width: parent.width; placeholderText: Hue.Strings.t("zone.namePlaceholder"); onEscaped: tab.focusHome() }
    Flow {
      visible: zoneForm.open
      width: parent.width
      spacing: Style.space(6)
      Repeater {
        model: tab.svc.allLights
        Chip {
          required property var modelData
          text: modelData.name
          lit: tab.zoneSelection[modelData.id] === true
          foreground: tab.ui.foreground; fontFamily: tab.ui.fontFamily
          onClicked: { var s = Object.assign({}, tab.zoneSelection); s[modelData.id] = !s[modelData.id]; tab.zoneSelection = s }
        }
      }
    }
    Button {
      visible: zoneForm.open
      text: Hue.Strings.t("zone.create")
      foreground: tab.ui.foreground
      bordered: true
      onClicked: {
        var ids = []
        for (var k in tab.zoneSelection) if (tab.zoneSelection[k]) ids.push(k)
        if (zoneName.text.trim() !== "" && ids.length > 0) {
          tab.svc.send("zone.create", { name: zoneName.text.trim(), lights: ids })
          zoneName.text = ""
          tab.zoneSelection = ({})
          tab.svc.toggleExpanded("newzone")
          tab.focusHome()
        }
      }
    }
  }

  WallpaperCard { ui: tab.ui }
}
