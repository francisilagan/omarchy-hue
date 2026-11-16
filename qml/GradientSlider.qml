import QtQuick
import qs.Commons
import qs.Commons as Commons

// A slider whose track is painted with a colour gradient (hue, saturation,
// colour temperature). Emits `released` once, when the drag ends.
Item {
  id: root

  property real value: 0
  property real minimum: 0
  property real maximum: 1
  property var colors: []
  property color knobColor: Commons.Color.foreground
  property color knobBorder: Commons.Color.background
  property bool dragging: false
  property real liveValue: value

  signal released(real value)

  implicitWidth: Style.space(200)
  implicitHeight: Style.space(22)

  readonly property real knobSize: Style.space(16)
  readonly property real range: Math.max(0.0001, maximum - minimum)
  readonly property real progress: Math.max(0, Math.min(1, (liveValue - minimum) / range))

  onValueChanged: if (!dragging) liveValue = value
  onColorsChanged: canvas.requestPaint()

  Item {
    id: track
    anchors.verticalCenter: parent.verticalCenter
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.leftMargin: root.knobSize / 2
    anchors.rightMargin: root.knobSize / 2
    height: Style.space(8)

    Canvas {
      id: canvas
      anchors.fill: parent
      onWidthChanged: requestPaint()
      onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var n = root.colors.length
        if (n === 0 || width <= 0) return
        var g = ctx.createLinearGradient(0, 0, width, 0)
        for (var i = 0; i < n; i++) g.addColorStop(n > 1 ? i / (n - 1) : 0, root.colors[i])
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.roundedRect(0, 0, width, height, height / 2, height / 2)
        ctx.fill()
      }
    }
  }

  Rectangle {
    width: root.knobSize
    height: width
    radius: width / 2
    anchors.verticalCenter: parent.verticalCenter
    x: track.x + root.progress * track.width - width / 2
    color: root.knobColor
    border.width: 2
    border.color: root.knobBorder
    scale: root.dragging ? 1.15 : 1.0
    Behavior on scale { NumberAnimation { duration: 80 } }
  }

  function setFromX(px) {
    var f = Math.max(0, Math.min(1, (px - track.x) / Math.max(1, track.width)))
    liveValue = minimum + f * range
  }

  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    preventStealing: true
    onPressed: function(m) { root.dragging = true; root.setFromX(m.x) }
    onPositionChanged: function(m) { if (pressed) root.setFromX(m.x) }
    onReleased: { root.dragging = false; root.released(root.liveValue) }
    onCanceled: root.dragging = false
  }
}
