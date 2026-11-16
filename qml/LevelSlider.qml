import QtQuick
import qs.Ui
import "." as Hue

// A slider that tells the service while it is dragged (so the panel does not
// scroll under the finger) and reports one value when released.
PanelSlider {
  id: slider
  property var ui
  signal committed(real value)

  bar: ui.bar
  onDraggingChanged: Hue.HueService.drag(dragging)
  onReleased: function(v) { slider.committed(v) }
  Component.onDestruction: if (dragging) Hue.HueService.drag(false)
}
