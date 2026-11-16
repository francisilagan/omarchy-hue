import QtQuick
import qs.Commons
import qs.Ui

// A text field that gives focus back to the panel on Escape.
TextField {
  id: field
  property var ui
  signal escaped()

  foreground: ui.foreground
  font.family: ui.fontFamily
  font.pixelSize: Style.font.body
  Keys.onEscapePressed: function(event) { field.escaped(); event.accepted = true }
}
