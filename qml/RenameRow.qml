import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "." as Hue

// Inline rename: a field prefilled with the current name and a button.
Row {
  id: root

  property string current: ""
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  property int maxLength: 32               // the bridge's limit for every name (PROTOCOL.md)

  signal submitted(string name)
  signal escaped()

  spacing: Style.space(8)

  function submit() {
    var t = field.text.trim()
    if (t !== "" && t !== current) root.submitted(t)
    root.escaped()
  }

  TextField {
    id: field
    width: parent.width - button.width - parent.spacing
    anchors.verticalCenter: parent.verticalCenter
    text: root.current
    maximumLength: root.maxLength
    foreground: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    onAccepted: root.submit()
    Keys.onEscapePressed: function(event) { root.escaped(); event.accepted = true }
  }
  Button {
    id: button
    anchors.verticalCenter: parent.verticalCenter
    text: Hue.Strings.t("common.rename")
    foreground: root.foreground
    bordered: true
    onClicked: root.submit()
  }
}
