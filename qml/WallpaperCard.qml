import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "." as Hue

// Paint the colour lights with the wallpaper's colours, and follow changes.
// The work happens in the backend (backend/hue_backend/wallpaper.py); this is
// only its settings.
Card {
  id: card
  readonly property var svc: Hue.HueService
  readonly property var cfg: svc.wallpaper
  property real now: Date.now() / 1000
  readonly property var stats: ({ enabled: cfg.enabled === true, turnOn: cfg.turnOn === true,
                                  appliedAt: svc.appliedAt, appliedCount: svc.appliedCount,
                                  eligible: svc.eligible, statsKnown: svc.wallpaperStatsKnown })
  readonly property string status: Model.wallpaperStatus(stats, now, Hue.Strings)
  // The backend reports 0 eligible while it cannot see the bridge; no advice then.
  readonly property string hint: svc.connected ? Model.wallpaperHint(stats, Hue.Strings) : ""
  // Sync is on and, well after start, still no palette: almost always a missing
  // ImageMagick (the backend only logs it). The service waits out the start-up
  // moment when the palette is not read yet, so this never flashes.
  readonly property bool noPalette: cfg.enabled === true && svc.paletteMissing

  // Keeps "5 min ago" honest while the card is on screen.
  Timer { interval: 30000; repeat: true; running: card.visible; triggeredOnStart: true; onTriggered: card.now = Date.now() / 1000 }

  Item {
    width: parent.width
    height: Style.space(26)
    Title { ui: card.ui; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: Hue.Strings.t("wallpaper.title") }
    ToggleSwitch {
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      property string cursorKey: "w:enabled"
      hasCursor: card.ui.cursor === cursorKey
      CursorRing {}
      checked: card.cfg.enabled === true
      foreground: card.ui.foreground
      onToggled: card.svc.setWallpaper({ enabled: !card.cfg.enabled })
    }
  }

  Caption {
    foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
    width: parent.width
    wrapMode: Text.WordWrap
    text: card.cfg.enabled === true
        ? Hue.Strings.t("wallpaper.onCaption")
        : Hue.Strings.t("wallpaper.offCaption")
  }

  Caption {
    foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
    visible: card.status !== ""
    width: parent.width
    wrapMode: Text.WordWrap
    text: card.status
  }
  Caption {
    foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
    visible: card.hint !== ""
    width: parent.width
    wrapMode: Text.WordWrap
    color: Commons.Color.accent
    text: card.hint
  }

  Caption {
    foreground: card.ui.foreground; fontFamily: card.ui.fontFamily
    visible: card.noPalette
    width: parent.width
    wrapMode: Text.WordWrap
    color: Commons.Color.accent
    text: Hue.Strings.t("wallpaper.noPalette")
  }

  Row {
    spacing: Style.space(6)
    visible: card.svc.palette.length > 0
    Repeater {
      model: card.svc.palette
      Rectangle {
        required property string modelData
        width: Style.space(28); height: Style.space(18); radius: Style.space(4)
        color: modelData
      }
    }
  }

  Caption { foreground: card.ui.foreground; fontFamily: card.ui.fontFamily; text: Hue.Strings.t("wallpaper.rooms") }
  Flow {
    width: parent.width
    spacing: Style.space(6)
    Repeater {
      model: card.svc.groups.length
      Chip {
        required property int index
        readonly property var g: card.svc.groups[index] || ({ id: "", name: "" })
        property string cursorKey: g.id !== "" ? "w:t:" + g.id : ""
        hasCursor: cursorKey !== "" && card.ui.cursor === cursorKey
        text: g.name
        lit: (card.cfg.targets || []).indexOf(g.id) >= 0
        foreground: card.ui.foreground
        fontFamily: card.ui.fontFamily
        onClicked: card.svc.toggleWallpaperTarget(g.id)
      }
    }
  }

  Item {
    width: parent.width
    height: Style.space(24)
    Caption { foreground: card.ui.foreground; fontFamily: card.ui.fontFamily; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: Hue.Strings.t("wallpaper.turnOn") }
    ToggleSwitch {
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      property string cursorKey: "w:turnOn"
      hasCursor: card.ui.cursor === cursorKey
      CursorRing {}
      checked: card.cfg.turnOn === true
      foreground: card.ui.foreground
      onToggled: card.svc.setWallpaper({ turnOn: !card.cfg.turnOn })
    }
  }

  Button {
    property string cursorKey: "w:sync"
    hasCursor: card.ui.cursor === cursorKey
    CursorRing {}
    text: Hue.Strings.t("wallpaper.syncNow")
    foreground: card.ui.foreground
    bordered: true
    onClicked: card.svc.syncWallpaperNow()
  }
}
