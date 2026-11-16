import QtQuick
import qs.Commons
import qs.Commons as Commons

// Small dim helper text.
Text {
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family

  textFormat: Text.PlainText
  color: Qt.darker(foreground, 1.4)
  font.family: fontFamily
  font.pixelSize: Style.font.bodySmall
}
