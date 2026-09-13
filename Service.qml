import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Io
import qs.Commons
import qs.Ui

Item {
  id: root
  visible: false
  property bool desktopEnabled: true

  FileView {
    id: configFile
    path: Quickshell.env("HOME") + "/.config/omacheck/config.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        var data = JSON.parse(text())
        root.desktopEnabled = !(data.widgets && data.widgets.desktop_enabled === false)
      } catch (e) {
        root.desktopEnabled = true
      }
    }
  }

  // config.json only exists after the first settings write; a periodic
  // reload() catches that without relying on FileView's behavior for
  // not-yet-existing paths (same latency as the task polls elsewhere).
  Timer {
    interval: 8000
    running: true
    repeat: true
    onTriggered: configFile.reload()
  }

  Variants {
    model: Quickshell.screens

    PanelWindow {
      id: deskWindow
      required property var modelData
      screen: modelData
      visible: root.desktopEnabled

      anchors {
        top: true
        left: true
      }
      margins {
        top: Style.space(45)
        left: Style.space(24)
      }

      implicitWidth: Style.space(320)
      implicitHeight: Style.space(400)
      color: "transparent"

      WlrLayershell.layer: WlrLayer.Bottom
      WlrLayershell.namespace: "omacheck-desktop"
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
      exclusionMode: ExclusionMode.Ignore

      DesktopWidgetView {
        anchors.fill: parent
      }
    }
  }
}
