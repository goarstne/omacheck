import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "carsten.omacheck"

  readonly property string binPath: Quickshell.env("HOME") + "/.local/bin/omacheck"

  property int openTasksCount: 0
  property var tasksList: []
  property bool isLoading: false

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property string displayText: openTasksCount > 0 ? "✓ " + openTasksCount : "✓"
  readonly property string currentTooltip: "OmaCheck: " + openTasksCount + " open tasks\nLeft click: open/close the OmaCheck app\nRight click: refresh"

  function refresh() {
    if (fetchProc.running) return
    isLoading = true
    var args = [binPath, "tasks", "--json", "--all"]
    fetchProc.command = args
    fetchProc.running = true
  }

  // The app is a panel-kind entry point of this same plugin, loaded
  // in-process by the shell — toggled the same way omarchy.menu opens
  // its own panel from its bar widget (root.bar.run(), not a subprocess).
  function openApp() {
    if (root.bar) root.bar.run("omarchy-shell shell toggle carsten.omacheck '{}'")
  }

  Timer {
    interval: 10000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Process {
    id: fetchProc
    stdout: StdioCollector { id: fetchStdout }
    stderr: StdioCollector { id: fetchStderr }

    onExited: function(exitCode) {
      root.isLoading = false
      if (exitCode === 0) {
        var raw = String(fetchStdout.text || "").trim()
        if (raw.length > 0) {
          try {
            var data = JSON.parse(raw)
            root.tasksList = data.tasks || []
            var openCount = 0
            for (var i = 0; i < root.tasksList.length; i++) {
              if (!root.tasksList[i].completed) openCount++
            }
            root.openTasksCount = openCount
          } catch (e) {
            console.warn("OmaCheck JSON parse error:", e)
          }
        }
      }
    }
  }

  // Opening/closing the app is already covered by the shell's generic
  // panel IPC (`omarchy-shell shell summon/hide/toggle carsten.omacheck`,
  // same as any other panel plugin); this target only adds what that
  // doesn't cover.
  IpcHandler {
    target: "carsten.omacheck"

    function refresh(): void { root.refresh() }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.displayText
    labelVisible: true
    tooltipText: root.currentTooltip
    horizontalMargin: 8.75
    verticalPadding: 8.75

    onPressed: function(b) {
      if (b === Qt.RightButton) {
        root.refresh()
      } else {
        root.openApp()
      }
    }
  }
}
