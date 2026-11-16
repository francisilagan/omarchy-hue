import QtQuick

// Stands in for qs.Ui's KeyboardPanel in the harness. The real one is a layer
// shell window, which needs a Wayland compositor; the view logic does not. This
// keeps the parts of the real card that can hide content: the size is the
// requested contentHeight minus a padded inset, the card height animates
// toward it and crops (clip) while it does, and fittedContentHeight adds the
// inset and caps at the screen the way the real helper does.
Item {
  id: root
  required property Item anchorItem
  required property QtObject bar
  property var owner: null
  property bool open: false
  property bool centerOnBar: false
  property Item focusTarget: null
  property int padding: 12
  property int contentWidth: 280
  property int contentHeight: 200
  readonly property real inset: padding * 2
  property real drawnHeight: contentHeight
  Behavior on drawnHeight { NumberAnimation { duration: 200 } }
  width: contentWidth
  height: drawnHeight
  clip: drawnHeight < contentHeight - 0.5
  default property alias contentItem: contentHolder.children

  function fittedContentWidth(width, cap) {
    var desired = Math.max(1, Number(width) || 1)
    return Math.round(cap !== undefined && Number(cap) > 0 ? Math.min(desired, Number(cap)) : desired)
  }
  function fittedContentHeight(implicitHeight, cap) {
    var desired = Math.max(inset, (Number(implicitHeight) || 0) + inset)
    return Math.round(cap !== undefined && Number(cap) > 0 ? Math.min(desired, Number(cap)) : desired)
  }

  Rectangle { anchors.fill: parent; color: "#1a1b26" }

  Item {
    id: contentHolder
    x: root.padding
    y: root.padding
    width: root.contentWidth - root.inset
    height: root.contentHeight - root.inset
  }
}
