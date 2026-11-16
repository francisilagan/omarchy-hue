import QtQuick
import qs.Commons
import qs.Commons as Commons

// The panel's keyboard cursor, drawn around its parent (any item with a
// `hasCursor` property: switches, chips, links, buttons). One look for every
// kind of row, and stronger than a hover so it reads at a glance.
Rectangle {
  property real pad: 0
  anchors.fill: parent
  anchors.margins: -pad
  z: 10
  visible: !!parent && parent.hasCursor === true
  color: "transparent"
  radius: Style.cornerRadius
  border.width: 2
  border.color: Commons.Color.accent
}
