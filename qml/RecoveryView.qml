import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "." as Hue

// Shown instead of the tabs when a bridge is paired but nothing has loaded and
// it cannot be reached (it is off, or its address changed with a new DHCP
// lease). Retry, or forget it so the pairing view can find it at its new address.
Column {
  id: view
  property var ui
  readonly property var svc: Hue.HueService

  spacing: Style.space(12)

  Card {
    ui: view.ui

    Title { ui: view.ui; text: Hue.Strings.t("recovery.title") }
    Caption {
      foreground: view.ui.foreground; fontFamily: view.ui.fontFamily
      width: parent.width; wrapMode: Text.WordWrap
      color: Commons.Color.urgent
      text: Model.connectionMessage(view.svc.conn, view.svc.connDetail, Hue.Strings) || ""
    }
    Caption {
      foreground: view.ui.foreground; fontFamily: view.ui.fontFamily
      width: parent.width; wrapMode: Text.WordWrap
      text: Hue.Strings.t("recovery.explain")
    }
    Flow {
      width: parent.width
      spacing: Style.space(8)
      Button {
        text: Hue.Strings.t("recovery.retry")
        foreground: view.ui.foreground; bordered: true
        onClicked: view.svc.refresh()
      }
      // Forgetting needs a second click; the pairing view then takes over.
      Button {
        text: view.svc.confirmKey === "forget" ? Hue.Strings.t("devices.forgetConfirm") : Hue.Strings.t("recovery.pairOther")
        foreground: view.svc.confirmKey === "forget" ? Commons.Color.urgent : view.ui.foreground
        bordered: true
        onClicked: view.svc.forgetBridge()
      }
    }
  }
}
