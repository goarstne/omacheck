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
  property int totalTasksCount: 0
  property var tasksList: []
  property var categoriesList: ["Alle"]
  property string selectedCategory: "Alle"
  property bool isLoading: false

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property string displayText: openTasksCount > 0 ? "✓ " + openTasksCount : "✓"
  readonly property string currentTooltip: "OmaCheck: " + openTasksCount + " offene Aufgaben\nLinksklick: OmaCheck App öffnen\nRechtsklick: Aktualisieren"

  function refresh() {
    if (fetchProc.running) return
    isLoading = true
    var args = [binPath, "tasks", "--json", "--all"]
    fetchProc.command = args
    fetchProc.running = true
  }

  function openApp() {
    if (!launchProc.running) {
      launchProc.command = [binPath, "gui"]
      launchProc.running = true
    }
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
            root.categoriesList = data.categories || ["Alle"]
            var openCount = 0
            for (var i = 0; i < root.tasksList.length; i++) {
              if (!root.tasksList[i].completed) openCount++
            }
            root.openTasksCount = openCount
            root.totalTasksCount = root.tasksList.length
          } catch (e) {
            console.warn("OmaCheck JSON parse error:", e)
          }
        }
      }
    }
  }

  Process {
    id: launchProc
  }

  IpcHandler {
    target: "carsten.omacheck"

    function refresh(): void { root.refresh() }
    function open(): void { root.openApp() }
    function toggle(): void { root.openApp() }
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
