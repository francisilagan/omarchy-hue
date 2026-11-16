import "Model.js" as Model
import QtQuick
import qs.Commons
import qs.Commons as Commons
import "." as Hue

// Colour controls for a light or a group: swatches, hue, saturation and white
// temperature. Stateless about the bridge: show what it is given, report picks.
Column {
  id: root

  property color foreground: Commons.Color.foreground
  property color panelBackground: Commons.Color.background
  property string fontFamily: Style.font.family
  property bool hasColor: true
  property bool hasCt: true
  property int mirekMin: 153
  property int mirekMax: 500
  property string hex: ""      // effective colour, "" when unknown / in white mode
  property int mirek: 0        // effective white temperature, 0 when in colour mode

  signal pickHex(string hex)
  signal pickMirek(int mirek)
  signal dragChanged(bool dragging)

  property real hue: 0
  property real sat: 1

  spacing: Style.space(6)

  function syncFromHex() {
    if (hex === "") return
    var c = Qt.color(hex)
    if (c.hsvSaturation > 0.02) hue = Math.max(0, c.hsvHue)
    sat = c.hsvSaturation
  }
  onHexChanged: if (!hueSlider.dragging && !satSlider.dragging) syncFromHex()
  Component.onCompleted: syncFromHex()

  // The Hue/Sat/White column: 40 px, or wider when a language's words need it.
  readonly property real labelWidth: Math.max(Style.space(40), hueLabel.implicitWidth, satLabel.implicitWidth, whiteLabel.implicitWidth)

  readonly property var swatches: ["#ff3b30", "#ff9500", "#ffd60a", "#34c759", "#00c7be", "#0a84ff", "#bf5af2", "#ff2d92"]
  readonly property var whites: [
    { label: Hue.Strings.t("white.candle"), mirek: 454 }, { label: Hue.Strings.t("white.warm"), mirek: 370 },
    { label: Hue.Strings.t("white.neutral"), mirek: 285 }, { label: Hue.Strings.t("white.cool"), mirek: 200 },
    { label: Hue.Strings.t("white.daylight"), mirek: 160 }
  ]

  // Quick colours
  Flow {
    visible: root.hasColor
    width: parent.width
    spacing: Style.space(8)
    Repeater {
      model: root.swatches.length
      Rectangle {
        required property int index
        width: Style.space(22)
        height: width
        radius: width / 2
        color: root.swatches[index]
        // Hue lights round-trip colours through xy, so compare by closeness, not equality.
        readonly property bool current: root.hex !== "" && Model.sameColour(String(color), root.hex, 40)
        border.width: current ? 2 : 1
        border.color: current ? root.foreground : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.25)
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: root.pickHex(String(parent.color))
        }
      }
    }
  }

  // Whites
  Flow {
    visible: root.hasCt
    width: parent.width
    spacing: Style.space(6)
    Repeater {
      model: root.whites.length
      Chip {
        required property int index
        text: root.whites[index].label
        foreground: root.foreground
        fontFamily: root.fontFamily
        lit: root.mirek > 0 && Math.abs(root.mirek - root.whites[index].mirek) < 12
        onClicked: root.pickMirek(root.whites[index].mirek)
      }
    }
  }

  // Hue
  Row {
    visible: root.hasColor
    width: parent.width
    spacing: Style.space(8)
    Text {
      width: root.labelWidth
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      id: hueLabel
      text: Hue.Strings.t("colour.hue")
      color: Qt.darker(root.foreground, 1.4)
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    GradientSlider {
      id: hueSlider
      width: parent.width - Style.space(48) - (root.labelWidth - Style.space(40))
      anchors.verticalCenter: parent.verticalCenter
      minimum: 0
      maximum: 1
      value: root.hue
      colors: [Qt.hsva(0, 1, 1, 1), Qt.hsva(1/6, 1, 1, 1), Qt.hsva(2/6, 1, 1, 1), Qt.hsva(3/6, 1, 1, 1),
               Qt.hsva(4/6, 1, 1, 1), Qt.hsva(5/6, 1, 1, 1), Qt.hsva(1, 1, 1, 1)]
      knobColor: Qt.hsva(liveValue, 1, 1, 1)
      knobBorder: root.foreground
      onDraggingChanged: root.dragChanged(dragging)
      onReleased: function(v) {
        root.hue = v
        if (root.sat < 0.15) root.sat = 0.9
        root.pickHex(String(Qt.hsva(v, root.sat, 1, 1)))
      }
    }
  }

  // Saturation
  Row {
    visible: root.hasColor
    width: parent.width
    spacing: Style.space(8)
    Text {
      width: root.labelWidth
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      id: satLabel
      text: Hue.Strings.t("colour.saturation")
      color: Qt.darker(root.foreground, 1.4)
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    GradientSlider {
      id: satSlider
      width: parent.width - Style.space(48) - (root.labelWidth - Style.space(40))
      anchors.verticalCenter: parent.verticalCenter
      minimum: 0
      maximum: 1
      value: root.sat
      colors: [Qt.hsva(root.hue, 0, 1, 1), Qt.hsva(root.hue, 1, 1, 1)]
      knobColor: Qt.hsva(root.hue, liveValue, 1, 1)
      knobBorder: root.foreground
      onDraggingChanged: root.dragChanged(dragging)
      onReleased: function(v) {
        root.sat = v
        root.pickHex(String(Qt.hsva(root.hue, v, 1, 1)))
      }
    }
  }

  // White temperature
  Row {
    visible: root.hasCt
    width: parent.width
    spacing: Style.space(8)
    Text {
      width: root.labelWidth
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      id: whiteLabel
      text: Hue.Strings.t("colour.white")
      color: Qt.darker(root.foreground, 1.4)
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    GradientSlider {
      width: parent.width - Style.space(48) - (root.labelWidth - Style.space(40))
      anchors.verticalCenter: parent.verticalCenter
      minimum: root.mirekMin
      maximum: root.mirekMax
      value: root.mirek > 0 ? root.mirek : (root.mirekMin + root.mirekMax) / 2
      colors: ["#cfe1ff", "#fff8ee", "#ffb25e"]
      knobColor: root.mirek > 0 ? "#fff8ee" : Qt.darker(root.foreground, 2)
      knobBorder: root.foreground
      onDraggingChanged: root.dragChanged(dragging)
      onReleased: function(v) { root.pickMirek(Math.round(v)) }
    }
  }
}
