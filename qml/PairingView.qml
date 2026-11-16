import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "." as Hue

// Shown instead of the tabs until a bridge is paired (and when its certificate
// changes). Three ways in: reuse an openhue login, find the bridge, or type its IP.
Column {
  id: view
  property var ui
  signal focusHome()
  readonly property var svc: Hue.HueService
  readonly property bool waiting: svc.pairWaiting

  spacing: Style.space(12)

  // The bridge's certificate is not the one that was trusted.
  Card {
    ui: view.ui
    visible: view.svc.conn === "cert_changed"
    Title { ui: view.ui; text: Hue.Strings.t("pairing.certTitle") }
    Caption {
      foreground: view.ui.foreground; fontFamily: view.ui.fontFamily
      width: parent.width; wrapMode: Text.WordWrap
      text: Model.connectionMessage("cert_changed", "", Hue.Strings)
    }
    Row {
      spacing: Style.space(8)
      Button { text: Hue.Strings.t("pairing.trust"); foreground: Commons.Color.urgent; bordered: true; onClicked: view.svc.trustBridge() }
      Button { text: Hue.Strings.t("pairing.forget"); foreground: view.ui.foreground; bordered: true; onClicked: view.svc.forgetNow() }
    }
  }

  Card {
    ui: view.ui
    visible: view.svc.conn !== "cert_changed"

    Title { ui: view.ui; text: view.svc.conn === "unauthorized" ? Hue.Strings.t("pairing.pairAgain") : Hue.Strings.t("pairing.connect") }
    Caption {
      foreground: view.ui.foreground; fontFamily: view.ui.fontFamily
      width: parent.width; wrapMode: Text.WordWrap
      text: Model.connectionMessage(view.svc.conn, view.svc.connDetail, Hue.Strings)
    }

    Button {
      text: Hue.Strings.t("pairing.openhue")
      foreground: view.ui.foreground; bordered: true
      visible: !view.waiting
      onClicked: view.svc.importOpenhue()
    }

    // A Flow, so a longer language puts the note under the button instead of past the edge.
    Flow {
      width: parent.width
      spacing: Style.space(8)
      visible: !view.waiting
      Button {
        id: findButton
        text: view.svc.discovering ? Hue.Strings.t("pairing.searching") : Hue.Strings.t("pairing.find")
        foreground: view.ui.foreground; bordered: true
        onClicked: view.svc.discover()
      }
      Caption {
        foreground: view.ui.foreground; fontFamily: view.ui.fontFamily
        height: findButton.height
        verticalAlignment: Text.AlignVCenter
        text: Hue.Strings.t("pairing.discoveryNote")
      }
    }
    // A finished search: why it failed, or that it found nothing.
    Caption {
      foreground: view.ui.foreground; fontFamily: view.ui.fontFamily
      visible: !view.waiting && view.svc.discoverDone && (view.svc.discoverError !== null || view.svc.discovered.length === 0)
      width: parent.width; wrapMode: Text.WordWrap
      color: view.svc.discoverError !== null ? Commons.Color.urgent : Qt.darker(view.ui.foreground, 1.4)
      text: view.svc.discoverError !== null ? Model.discoveryFailure(view.svc.discoverError, Hue.Strings) : Hue.Strings.t("pairing.noneFound")
    }
    Flow {
      width: parent.width
      spacing: Style.space(6)
      visible: view.svc.discovered.length > 0 && !view.waiting
      Repeater {
        model: view.svc.discovered
        Chip {
          required property var modelData
          text: modelData.host
          foreground: view.ui.foreground; fontFamily: view.ui.fontFamily
          onClicked: host.text = modelData.host
        }
      }
    }

    Field { id: host; ui: view.ui; width: parent.width; visible: !view.waiting; placeholderText: Hue.Strings.t("pairing.hostPlaceholder"); onEscaped: view.focusHome() }

    Caption {
      foreground: view.ui.foreground; fontFamily: view.ui.fontFamily
      visible: view.waiting
      width: parent.width; wrapMode: Text.WordWrap
      text: view.svc.pair.secondsLeft > 0 ? Hue.Strings.tn("pairing.pressButtonLeft", view.svc.pair.secondsLeft) : Hue.Strings.t("pairing.pressButton")
    }
    Caption {
      foreground: view.ui.foreground; fontFamily: view.ui.fontFamily
      visible: view.svc.pair.state === "failed"
      width: parent.width; wrapMode: Text.WordWrap
      color: Commons.Color.urgent
      text: Model.pairFailure(view.svc.pair, Hue.Strings)
    }
    Row {
      spacing: Style.space(8)
      Button {
        visible: !view.waiting
        text: Hue.Strings.t("pairing.pair")
        enabled: host.text.trim() !== ""
        foreground: view.ui.foreground; bordered: true
        onClicked: view.svc.startPairing(host.text.trim())
      }
      Button {
        visible: view.waiting
        text: Hue.Strings.t("common.cancel")
        foreground: view.ui.foreground; bordered: true
        onClicked: view.svc.cancelPairing()
      }
    }
  }
}
