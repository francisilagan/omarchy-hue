import QtQuick
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A rounded panel section. Children go in a padded column.
Rectangle {
  id: card

  property var ui
  property bool subtle: false
  default property alias content: body.data
  property alias spacing: body.spacing

  x: Style.space(12)
  width: (parent ? parent.width : 0) - Style.space(24)
  height: body.implicitHeight + Style.space(24)
  radius: Math.min(10, Style.cornerRadius + 2)
  // Sections sit on the panel with the host's normal (barely-there) fill; the
  // stronger "selected" fill is reserved for selected items, as in Omarchy's own panels.
  color: subtle ? "transparent" : Style.normalFillFor(ui.foreground, Commons.Color.accent)

  Column {
    id: body
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.space(12)
    spacing: Style.space(8)
  }
}
