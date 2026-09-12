import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

Item {
  id: root
  visible: false

  Variants {
    model: Quickshell.screens

    PanelWindow {
      id: deskWindow
      required property var modelData
      screen: modelData

      anchors {
        top: true
        left: true
      }
      margins {
        top: Style.space(45)
        left: Style.space(24)
      }

      implicitWidth: Style.space(380)
      implicitHeight: Style.space(520)
      color: "transparent"

      WlrLayershell.layer: WlrLayer.Bottom
      WlrLayershell.namespace: "omacheck-desktop"
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
      exclusionMode: ExclusionMode.Ignore

      DesktopWidgetView {
        anchors.fill: parent
      }
    }
  }
}
