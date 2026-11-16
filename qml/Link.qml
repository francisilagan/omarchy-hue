import QtQuick
import qs.Commons
import qs.Commons as Commons

// A small clickable text: a disclosure toggle (▸/▾) or a plain action.
// `hasCursor` draws the panel's keyboard cursor ring around it.
Item {
  id: link

  property string text: ""
  property bool open: false
  property bool isToggle: true
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  property bool hasCursor: false

  signal clicked()

  width: label.implicitWidth
  height: Style.space(20)

  CursorRing { pad: Style.space(4) }
  Text {
    id: label
    anchors.verticalCenter: parent.verticalCenter
    textFormat: Text.PlainText
    text: (link.isToggle ? (link.open ? "▾ " : "▸ ") : "") + link.text
    color: link.hasCursor ? link.foreground : Qt.darker(link.foreground, 1.4)
    font.family: link.fontFamily
    font.pixelSize: Style.font.bodySmall
  }
  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: link.clicked()
  }
}
