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

  // =========================================================================
  // 1. Constants & State Properties
  // =========================================================================
  readonly property string allCategory: "All"
  readonly property string defaultCategory: "General"
  readonly property string binPath: Quickshell.env("HOME") + "/.local/bin/omacheck"
  readonly property var typography: Style.font

  property var tasksList: []
  property var categoriesList: [allCategory]
  property string selectedCategory: allCategory
  property int openCount: 0
  property bool loading: false
  property string errorText: ""
  property bool addingCategory: false

  implicitWidth: Style.space(320)
  implicitHeight: Style.space(400)

  radius: Style.cornerRadius > 0 ? Style.cornerRadius : Style.space(10)
  color: Qt.rgba(Color.background.r, Color.background.g, Color.background.b, 0.90)
  border.width: 1
  border.color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.12)

  // =========================================================================
  // 2. Pure Functions & Helpers
  // =========================================================================
  function formatTaskMetadata(task) {
    if (!task) return ""
    var parts = []
    if (task.priority) parts.push("Priority: " + task.priority)
    if (task.due_date) parts.push("📅 " + task.due_date)
    if (task.note_title && root.selectedCategory === root.allCategory)
      parts.push("📁 " + (task.category ? task.category + "/" : "") + task.note_title)
    return parts.join(" · ")
  }

  function filterTasks() {
    if (selectedCategory === allCategory) return tasksList
    return tasksList.filter(t => t.category === selectedCategory)
  }

  function refresh() {
    if (fetchProc.running) return
    loading = true
    var args = [binPath, "tasks", "--json", "--all"]
    if (selectedCategory !== allCategory) {
      args.push("-c", selectedCategory)
    }
    fetchProc.command = args
    fetchProc.running = true
  }

  function toggleTask(taskId) {
    if (toggleProc.running) return
    toggleProc.command = [binPath, "toggle", taskId]
    toggleProc.running = true
  }

  function deleteTask(taskId) {
    if (deleteProc.running) return
    deleteProc.command = [binPath, "delete", taskId]
    deleteProc.running = true
  }

  function addTask(text) {
    var trimmed = (text || "").trim()
    if (!trimmed || addProc.running) return
    var args = [binPath, "add", trimmed]
    if (selectedCategory !== allCategory) {
      args.push("-c", selectedCategory)
    }
    addProc.command = args
    addProc.running = true
  }

  function addCategory(name) {
    var trimmed = (name || "").trim()
    if (!trimmed || addCategoryProc.running) return
    root.selectedCategory = trimmed
    addCategoryProc.command = [binPath, "categories", "--add", trimmed, "--json"]
    addCategoryProc.running = true
  }

  function removeCategory(name) {
    if (removeCategoryProc.running) return
    removeCategoryProc.command = [binPath, "categories", "--remove", name, "--json"]
    removeCategoryProc.running = true
  }

  // =========================================================================
  // 3. Backend Process Handlers & Lifecycle
  // =========================================================================
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
            if (JSON.stringify(root.tasksList) !== JSON.stringify(data.tasks || []))
              root.tasksList = data.tasks || []
            root.categoriesList = data.categories || [root.allCategory]
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

  Process {
    id: toggleProc
    stderr: StdioCollector { id: toggleError }
    onExited: function(c) {
      root.errorText = c === 0 ? "" : (toggleError.text.trim() || "Could not update task.")
      root.refresh()
    }
  }

  Process {
    id: deleteProc
    stderr: StdioCollector { id: deleteError }
    onExited: function(c) {
      root.errorText = c === 0 ? "" : (deleteError.text.trim() || "Could not delete task.")
      root.refresh()
    }
  }

  Process {
    id: addProc
    stderr: StdioCollector { id: addError }
    onExited: function(c) {
      if (c === 0) taskInputField.text = ""
      root.errorText = c === 0 ? "" : (addError.text.trim() || "Could not save task.")
      root.refresh()
    }
  }

  Process {
    id: addCategoryProc
    stderr: StdioCollector { id: addCategoryError }
    onExited: function(c) {
      if (c === 0) {
        newCategoryField.text = ""
        root.addingCategory = false
      } else {
        root.selectedCategory = root.allCategory
      }
      root.errorText = c === 0 ? "" : (addCategoryError.text.trim() || "Could not add category.")
      root.refresh()
    }
  }

  Process {
    id: removeCategoryProc
    stdout: StdioCollector { id: removeCategoryStdout }
    onExited: function(c) {
      var raw = String(removeCategoryStdout.text || "").trim()
      var parsed = null
      if (raw.length > 0) {
        try { parsed = JSON.parse(raw) } catch (e) { console.warn("OmaCheck remove category parse error:", e) }
      }
      if (!(parsed && parsed.success)) {
        root.errorText = (parsed && parsed.message) || "Could not remove category."
      } else {
        root.errorText = ""
        if (root.selectedCategory !== root.allCategory && parsed.message && parsed.message.indexOf(root.selectedCategory) !== -1) {
          root.selectedCategory = root.allCategory
        }
      }
      root.refresh()
    }
  }

  // =========================================================================
  // 4. UI Layout
  // =========================================================================
  ColumnLayout {
    anchors.fill: parent
    anchors.margins: Style.space(10)
    spacing: Style.space(6)

    // Compact header
    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(6)

      Text {
        text: "OmaCheck"
        font.family: root.typography.family
        font.pixelSize: Style.font.subtitle
        font.bold: true
        color: Color.foreground
      }

      Text {
        text: root.openCount > 0 ? "(" + root.openCount + ")" : ""
        font.family: root.typography.family
        font.pixelSize: Style.font.caption
        color: Color.muted
        visible: root.openCount > 0
      }

      Item { Layout.fillWidth: true }

      Ui.Button {
        id: refreshBtn
        focusable: true
        implicitWidth: Style.space(22)
        implicitHeight: Style.space(22)
        horizontalPadding: 0
        verticalPadding: 0
        iconText: "⟳"
        iconSize: Style.font.caption
        iconSpinning: root.loading
        tooltipText: "Refresh"
        Accessible.name: "Refresh"
        onClicked: root.refresh()
      }
    }

    // Category filter bar with inline '+' button
    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(4)

      Controls.ScrollView {
        Layout.fillWidth: true
        implicitHeight: Style.space(24)
        contentHeight: catRow.height
        contentWidth: catRow.width
        clip: true
        Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

        Row {
          id: catRow
          spacing: Style.space(4)

          Repeater {
            model: root.categoriesList
            delegate: Item {
              id: catRow
              required property string modelData
              readonly property bool removable: modelData !== root.allCategory && modelData !== root.defaultCategory
              implicitWidth: catBtn.implicitWidth + (removable ? catRemove.implicitWidth : 0)
              implicitHeight: catBtn.implicitHeight

              Ui.Button {
                id: catBtn
                anchors.left: parent.left
                text: catRow.modelData
                selected: root.selectedCategory === catRow.modelData
                horizontalPadding: Style.space(6)
                verticalPadding: Style.space(3)
                fontSize: Style.font.caption
                focusable: true
                Accessible.role: Accessible.Button
                Accessible.name: text
                Accessible.onPressAction: clicked()
                onClicked: {
                  root.selectedCategory = catRow.modelData
                  root.refresh()
                }
              }

              Ui.Button {
                id: catRemove
                visible: catRow.removable
                focusable: true
                anchors.left: catBtn.right
                anchors.verticalCenter: catBtn.verticalCenter
                implicitWidth: Style.space(16)
                implicitHeight: Style.space(16)
                horizontalPadding: 0
                verticalPadding: 0
                text: "×"
                fontSize: Style.font.caption
                tooltipText: "Remove category (only if empty)"
                Accessible.name: "Remove category " + catRow.modelData
                onClicked: root.removeCategory(catRow.modelData)
              }
            }
          }
        }
      }

      Ui.Button {
        id: addCategoryToggleBtn
        focusable: true
        implicitWidth: Style.space(22)
        implicitHeight: Style.space(22)
        horizontalPadding: 0
        verticalPadding: 0
        text: "+"
        fontSize: Style.font.caption
        tooltipText: "Add category"
        Accessible.name: "Add category"
        selected: root.addingCategory
        onClicked: {
          root.addingCategory = !root.addingCategory
          if (root.addingCategory) {
            Qt.callLater(function() { newCategoryField.forceActiveFocus() })
          }
        }
      }
    }

    // Inline new-category input row (visible when toggled)
    RowLayout {
      Layout.fillWidth: true
      visible: root.addingCategory
      spacing: Style.space(6)

      Ui.TextField {
        id: newCategoryField
        Layout.fillWidth: true
        placeholderText: "New category..."
        Accessible.name: "New category name"
        onAccepted: root.addCategory(newCategoryField.text)
        Keys.onEscapePressed: {
          root.addingCategory = false
          newCategoryField.text = ""
        }
      }

      Ui.Button {
        focusable: true
        implicitWidth: Style.space(24)
        implicitHeight: Style.space(24)
        horizontalPadding: 0
        verticalPadding: 0
        text: "+"
        tooltipText: "Create category"
        Accessible.name: "Create category"
        onClicked: root.addCategory(newCategoryField.text)
      }
    }

    // Task list with real checkboxes on the left
    Controls.ScrollView {
      id: taskScroll
      Layout.fillWidth: true
      Layout.fillHeight: true
      clip: true
      contentWidth: availableWidth
      Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

      Column {
        width: taskScroll.availableWidth
        spacing: Style.space(2)

        Repeater {
          model: root.filterTasks()
          delegate: Item {
            id: taskRow
            required property var modelData
            width: parent.width
            implicitHeight: taskCheck.implicitHeight

            Controls.CheckBox {
              id: taskCheck
              readonly property var modelData: taskRow.modelData
              anchors.left: parent.left
              anchors.right: deleteBtn.left
              anchors.rightMargin: Style.space(2)

              checked: Boolean(taskCheck.modelData && taskCheck.modelData.completed)
              nextCheckState: function() { return checkState }
              hoverEnabled: true
              activeFocusOnTab: true

              spacing: Style.space(8)
              leftPadding: Style.space(6)
              rightPadding: Style.space(6)
              topPadding: Style.space(3)
              bottomPadding: Style.space(3)

              Accessible.role: Accessible.CheckBox
              Accessible.name: taskCheck.modelData.text
              Accessible.checked: taskCheck.checked
              Accessible.onToggleAction: root.toggleTask(taskCheck.modelData.id)

              onClicked: root.toggleTask(taskCheck.modelData.id)

              indicator: Rectangle {
                id: ind
                implicitWidth: Style.space(16)
                implicitHeight: Style.space(16)
                width: implicitWidth
                height: implicitHeight
                x: taskCheck.leftPadding
                y: taskCheck.topPadding + Math.max(0, Math.round((taskTitle.font.pixelSize * 1.3 - height) / 2))
                radius: Math.max(2, Math.round(Style.cornerRadius / 4))

                color: taskCheck.checked
                  ? Style.selectedFillFor(Color.foreground, Color.accent)
                  : (taskCheck.down ? Style.pressedFillFor(Color.foreground, Color.accent) : "transparent")

                border.width: 1
                border.color: taskCheck.checked
                  ? Color.accent
                  : (taskCheck.hovered || taskCheck.activeFocus ? Color.accent : Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.35))

                Text {
                  anchors.centerIn: parent
                  visible: taskCheck.checked
                  text: "✓"
                  color: Color.accent
                  font.family: root.typography.family
                  font.pixelSize: Math.round(ind.height * 0.85)
                  font.bold: true
                }
              }

              contentItem: Controls.Control {
                leftPadding: taskCheck.indicator.width + taskCheck.spacing
                topPadding: 0
                bottomPadding: 0
                rightPadding: 0
                implicitHeight: taskCol.implicitHeight

                contentItem: Column {
                  id: taskCol
                  spacing: Style.spacing.xxs

                  Text {
                    id: taskTitle
                    textFormat: Text.PlainText
                    width: taskCheck.availableWidth - taskCheck.indicator.width - taskCheck.spacing
                    text: taskCheck.modelData.text
                    font.family: root.typography.family
                    font.pixelSize: Style.font.body
                    color: taskCheck.checked ? Color.muted : Color.foreground
                    font.strikeout: taskCheck.checked
                    wrapMode: Text.Wrap
                  }

                  Text {
                    id: taskMeta
                    textFormat: Text.PlainText
                    readonly property string metaString: root.formatTaskMetadata(taskCheck.modelData)
                    visible: metaString.length > 0
                    text: metaString
                    font.family: root.typography.family
                    font.pixelSize: Style.font.caption
                    color: Color.muted
                    elide: Text.ElideRight
                    width: taskTitle.width
                  }
                }
              }

              background: Rectangle {
                radius: Math.max(2, Math.round(Style.cornerRadius / 2))
                color: taskCheck.down
                  ? Style.pressedFillFor(Color.foreground, Color.accent)
                  : (taskCheck.hovered || taskCheck.activeFocus
                      ? Style.hoverFillFor(Color.foreground, Color.accent)
                      : "transparent")
                border.width: taskCheck.activeFocus ? 1 : 0
                border.color: taskCheck.activeFocus ? Style.focusBorderColor : "transparent"
              }
            }

            Ui.Button {
              id: deleteBtn
              focusable: true
              anchors.right: parent.right
              anchors.top: parent.top
              anchors.topMargin: taskCheck.topPadding
              implicitWidth: Style.space(18)
              implicitHeight: Style.space(18)
              horizontalPadding: 0
              verticalPadding: 0
              text: "−"
              fontSize: Style.font.caption
              tooltipText: "Delete task"
              Accessible.name: "Delete task"
              onClicked: root.deleteTask(taskRow.modelData.id)
            }
          }
        }

        Text {
          visible: root.filterTasks().length === 0
          text: "No tasks yet."
          font.family: root.typography.family
          font.pixelSize: Style.font.caption
          color: Color.muted
          anchors.horizontalCenter: parent.horizontalCenter
          y: Style.space(20)
        }
      }
    }

    // Error message display
    Text {
      Layout.fillWidth: true
      visible: root.errorText !== ""
      text: root.errorText
      textFormat: Text.PlainText
      color: Color.urgent
      font.family: root.typography.family
      font.pixelSize: Style.font.caption
      wrapMode: Text.Wrap
    }

    // Quick-add row
    RowLayout {
      Layout.fillWidth: true
      spacing: Style.space(6)

      Ui.TextField {
        id: taskInputField
        enabled: !addProc.running
        Layout.fillWidth: true
        placeholderText: root.selectedCategory === root.allCategory ? "+ New task..." : "+ New task in '" + root.selectedCategory + "'..."
        Accessible.name: "Enter task"
        onAccepted: root.addTask(taskInputField.text)
      }

      Ui.Button {
        focusable: true
        enabled: !addProc.running
        implicitWidth: Style.space(28)
        implicitHeight: Style.space(28)
        horizontalPadding: 0
        verticalPadding: 0
        text: "+"
        Accessible.name: "Add task"
        onClicked: root.addTask(taskInputField.text)
      }
    }
  }
}
