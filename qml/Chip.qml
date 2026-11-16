import QtQuick
import qs.Commons
import qs.Commons as Commons

// A pill: scene, effect, preset or selectable item. `lit` marks the active one;
// `swatch` adds a leading colour dot. `hasCursor` draws the panel's keyboard
// cursor ring around it.
Rectangle {
  id: chip

  property string text: ""
  property bool lit: false
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  property color swatch: "transparent"
  property bool dimmed: false
  property bool hasCursor: false

  signal clicked()
  signal rightClicked()

  width: row.implicitWidth + Style.space(20)
  height: Style.space(24)
  radius: height / 2
  opacity: dimmed ? 0.55 : 1.0
  color: lit ? Style.selectedFillFor(foreground, Commons.Color.accent)
       : area.containsMouse || hasCursor ? Style.hoverFillFor(foreground, Commons.Color.accent)
       : Qt.rgba(foreground.r, foreground.g, foreground.b, 0.08)
  border.width: lit ? 1 : 0
  border.color: Commons.Color.accent

  CursorRing { pad: Style.space(3); radius: height / 2 }

  Row {
    id: row
    anchors.centerIn: parent
    spacing: Style.space(6)
    Rectangle {
      visible: chip.swatch.a > 0
      width: Style.space(10)
      height: width
      radius: width / 2
      color: chip.swatch
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: chip.text
      color: chip.foreground
      font.family: chip.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    cursorShape: Qt.PointingHandCursor
    onClicked: function(m) { if (m.button === Qt.RightButton) chip.rightClicked(); else chip.clicked() }
  }
}
