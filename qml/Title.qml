import QtQuick
import qs.Commons

// Bold card heading.
Text {
  property var ui
  textFormat: Text.PlainText
  color: ui.foreground
  font.family: ui.fontFamily
  font.pixelSize: Style.font.title
  font.bold: true
}
