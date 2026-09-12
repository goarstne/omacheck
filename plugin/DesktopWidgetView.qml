pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui

Rectangle {
  id: root
  readonly property string binPath: Quickshell.env("HOME") + "/.local/bin/omacheck"
  readonly property var typography: Style.font

  property var tasksList: []
  property var categoriesList: ["Alle"]
  property string selectedCategory: "Alle"
  property int openCount: 0
  property bool loading: false

  implicitWidth: Style.space(380)
  implicitHeight: Style.space(520)

  radius: Style.cornerRadius > 0 ? Style.cornerRadius : Style.space(12)
  color: Qt.rgba(Color.background.r, Color.background.g, Color.background.b, 0.90)
  border.width: Style.normalBorderWidth > 0 ? Style.normalBorderWidth : 1
  border.color: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.45)

  // Top highlight line
  Rectangle {
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.margins: 1
    height: 1
    radius: parent.radius
    color: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.25)
  }

  component Caption: Text {
    textFormat: Text.PlainText
    color: Color.foreground
    font.family: root.typography.family
    font.pixelSize: root.typography.body
    wrapMode: Text.WordWrap
  }

  component Action: Ui.Button {
    focusable: true
    bordered: true
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: clicked()
  }

  component Choice: Ui.Toggle {
    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.checkable: true
    Accessible.checked: checked
    Accessible.onToggleAction: clicked()
    opacity: enabled ? 1 : 0.5
  }

  function refresh() {
    if (fetchProc.running) return
    loading = true
    var args = [binPath, "tasks", "--json", "--all"]
    if (selectedCategory !== "Alle") {
      args.push("-c")
      args.push(selectedCategory)
    }
    fetchProc.command = args
    fetchProc.running = true
  }

  function toggleTask(taskId) {
    if (toggleProc.running) return
    toggleProc.command = [binPath, "toggle", taskId]
    toggleProc.running = true
  }

  function addTask(text) {
    if (!text || text.trim() === "" || addProc.running) return
    var args = [binPath, "add", text.trim()]
    if (selectedCategory !== "Alle") {
      args.push("-c")
      args.push(selectedCategory)
    }
    addProc.command = args
    addProc.running = true
  }

  function filterTasks() {
    if (selectedCategory === "Alle") return tasksList
    return tasksList.filter(t => t.category === selectedCategory)
  }

  Component.onCompleted: refresh()

  Timer {
    interval: 8000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  Process {
    id: fetchProc
    stdout: StdioCollector { id: fetchStdout }
    stderr: StdioCollector { id: fetchStderr }

    onExited: function(code) {
      root.loading = false
      if (code === 0) {
        var raw = String(fetchStdout.text || "").trim()
        if (raw.length > 0) {
          try {
            var data = JSON.parse(raw)
            root.tasksList = data.tasks || []
            root.categoriesList = data.categories || ["Alle"]
            var count = 0
            for (var i = 0; i < root.tasksList.length; i++) {
              if (!root.tasksList[i].completed) count++
            }
            root.openCount = count
          } catch (e) {
            console.warn("OmaCheck DesktopWidget parse error:", e)
          }
        }
      }
    }
  }

  Process { id: toggleProc; onExited: function(c) { root.refresh() } }
  Process {
    id: addProc
    onExited: function(c) {
      taskInputField.text = ""
      root.refresh()
    }
  }

  ColumnLayout {
    anchors.fill: parent
    anchors.margins: Style.space(16)
    spacing: Style.space(10)

    // Header
    RowLayout {
      Layout.fillWidth: true
      ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        Caption {
          text: "OmaCheck"
          font.bold: true
          font.pixelSize: Style.font.heading
        }
        Caption {
          text: root.openCount + " Aufgaben offen"
          opacity: 0.7
          font.pixelSize: Style.font.caption
        }
      }
      Action {
        text: "⟳"
        onClicked: root.refresh()
      }
    }

    // Kategorie-Tabs im Omasync Action-Stil
    Controls.ScrollView {
      Layout.fillWidth: true
      implicitHeight: Style.space(38)
      contentHeight: catRow.height
      contentWidth: catRow.width
      clip: true
      Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

      Row {
        id: catRow
        spacing: Style.space(6)

        Repeater {
          model: root.categoriesList
          delegate: Action {
            required property string modelData
            text: modelData
            selected: root.selectedCategory === modelData
            onClicked: {
              root.selectedCategory = modelData
              root.refresh()
            }
          }
        }
      }
    }

    // Aufgabenliste mit nativem Omasync Choice-Toggle
    Controls.ScrollView {
      id: taskScroll
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      contentWidth: availableWidth
      Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

      Column {
        width: taskScroll.availableWidth
        spacing: Style.space(4)

        Repeater {
          model: root.filterTasks()
          delegate: Choice {
            id: taskChoice
            required property var modelData
            width: parent.width
            label: taskChoice.modelData.text
            description: {
              var desc = []
              if (taskChoice.modelData.priority) desc.push("Prio: " + taskChoice.modelData.priority)
              if (taskChoice.modelData.due_date) desc.push("📅 " + taskChoice.modelData.due_date)
              if (taskChoice.modelData.note_title) desc.push(taskChoice.modelData.note_title)
              return desc.join(" · ")
            }
            checked: taskChoice.modelData.completed
            onClicked: root.toggleTask(taskChoice.modelData.id)
          }
        }

        Caption {
          visible: root.filterTasks().length === 0
          text: "Keine Aufgaben vorhanden."
          opacity: 0.5
          anchors.horizontalCenter: parent.horizontalCenter
          y: Style.space(20)
        }
      }
    }

    // Quick-Add Zeile im Omasync TextField + Action Stil
    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(6)

      Ui.TextField {
        id: taskInputField
        Layout.fillWidth: true
        placeholderText: "+ Neue Aufgabe für '" + root.selectedCategory + "'..."
        Accessible.name: "Aufgabe eingeben"
        onAccepted: root.addTask(taskInputField.text)
      }

      Action {
        text: "+"
        Accessible.name: "Aufgabe anlegen"
        onClicked: root.addTask(taskInputField.text)
      }
    }
  }
}
