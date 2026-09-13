pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui

// Panel-kind plugin entry point: loaded in-process by the shell's generic
// panel Loader (see shell.qml computePanelEntries/summon/hide) whenever
// `omarchy-shell shell summon/toggle carsten.omacheck` runs — the same
// mechanism omarchy.menu and the dev-gallery use, instead of a disconnected
// `quickshell -p` cold start. The Loader destroys this whole item on close
// (no `keepLoaded` here), so every open is a fresh refresh() — fine, since
// state is trivial and freshness is what you want anyway.
Item {
  id: root

  // =========================================================================
  // 0. Plugin lifecycle (host contract: open/close/requestClose + `shell`)
  // =========================================================================
  property var shell: null
  property bool closingFromHost: false

  function open(payloadJson) {
    closingFromHost = false
    window.visible = true
  }

  // Host-initiated close (`shell hide` / toggle-while-open). Visibility
  // flips without notifying the host back — it already knows.
  function close() {
    closingFromHost = true
    window.visible = false
    closingFromHost = false
  }

  // User-initiated close (window close button). Tell the shell so its
  // openPanelIds bookkeeping stays consistent and the next toggle reopens
  // instead of trying to hide an already-closed panel.
  function requestClose() {
    if (shell && typeof shell.hide === "function") shell.hide("carsten.omacheck")
    else window.visible = false
  }

  // =========================================================================
  // 1. Constants & State Properties
  // =========================================================================
  readonly property string allCategory: "All"
  readonly property string defaultCategory: "General"
  readonly property string storageStandalone: "standalone"
  readonly property string storageObsidian: "obsidian"

  readonly property var typography: Style.font
  readonly property string binPath: Quickshell.env("HOME") + "/.local/bin/omacheck"

  property var rawData: ({})
  property var allNotes: []
  property var allTasks: []
  property var categories: [allCategory]
  property string selectedCategory: allCategory
  property var selectedNote: null
  property string searchQuery: ""
  property bool showCompleted: true
  property bool loading: false

  property bool settingsOpen: false
  property bool barWidgetEnabled: false
  property bool barWidgetBusy: false
  property bool barWidgetLiveApplied: true
  property string barWidgetStatusMessage: ""
  property bool desktopWidgetEnabled: true
  property bool desktopWidgetBusy: false
  property string desktopWidgetStatusMessage: ""
  property string storageMode: storageStandalone
  property bool storageModeBusy: false
  property string storageModeStatusMessage: ""

  readonly property bool obsidianActive: !!(root.rawData.mode && String(root.rawData.mode).indexOf(root.storageObsidian) === 0)

  // =========================================================================
  // 2. Pure Functions & Helpers
  // =========================================================================
  function formatTaskMetadata(task) {
    if (!task) return ""
    var parts = []
    if (task.priority) parts.push("Priority: " + task.priority)
    if (task.due_date) parts.push("📅 " + task.due_date)
    if (task.note_title) parts.push("📁 " + (task.category ? task.category + "/" : "") + task.note_title)
    if (task.tags && task.tags.length > 0) parts.push("#" + task.tags.join(" #"))
    return parts.join(" · ")
  }

  function filteredNotes() {
    var list = allNotes
    if (selectedCategory !== allCategory) {
      list = list.filter(n => n.category === selectedCategory)
    }
    if (searchQuery.trim() !== "") {
      var q = searchQuery.toLowerCase().trim()
      list = list.filter(n => n.title.toLowerCase().includes(q) || n.tasks.some(t => t.text.toLowerCase().includes(q)))
    }
    return list
  }

  function filteredTasks() {
    var list = []
    if (selectedNote && selectedNote.tasks) {
      list = selectedNote.tasks
    } else {
      list = (selectedCategory === allCategory) ? allTasks : allTasks.filter(t => t.category === selectedCategory)
    }
    if (!showCompleted) {
      list = list.filter(t => !t.completed)
    }
    if (searchQuery.trim() !== "") {
      var q = searchQuery.toLowerCase().trim()
      list = list.filter(t => t.text.toLowerCase().includes(q) || t.note_title.toLowerCase().includes(q))
    }
    return list
  }

  // The checkbox shows the actual bar state once known (even after a write
  // failure, so it never shows checked while the entry is missing from the
  // bar). Only when it is unknown (e.g. shell.json missing) does this fall
  // back to the saved preference.
  function pickBarWidgetState(widgets) {
    if (!widgets) return root.barWidgetEnabled
    if (typeof widgets.bar_enabled_live === "boolean") return widgets.bar_enabled_live
    return !!widgets.bar_enabled_preference
  }

  function refresh() {
    if (fetchProc.running) return
    loading = true
    fetchProc.command = [binPath, "tasks", "--json", "--all"]
    fetchProc.running = true
  }

  function toggleTask(taskId) {
    if (toggleProc.running) return
    toggleProc.command = [binPath, "toggle", taskId]
    toggleProc.running = true
  }

  function addTask(text, priority) {
    var trimmed = (text || "").trim()
    if (!trimmed || addProc.running) return
    var args = [binPath, "add", trimmed]
    if (selectedNote && selectedNote.title) {
      args.push("-n", selectedNote.title)
    }
    if (selectedCategory !== allCategory) {
      args.push("-c", selectedCategory)
    }
    if (priority && priority !== "normal") {
      args.push("-p", priority)
    }
    addProc.command = args
    addProc.running = true
  }

  function createNewNote(title, category) {
    var trimmed = (title || "").trim()
    if (!trimmed || createNoteProc.running) return
    var cat = (category && category !== allCategory) ? category : (selectedCategory !== allCategory ? selectedCategory : defaultCategory)
    createNoteProc.command = [binPath, "create-note", trimmed, "-c", cat]
    createNoteProc.running = true
  }

  function addCategory(name) {
    var trimmed = (name || "").trim()
    if (!trimmed || addCategoryProc.running) return
    root.selectedCategory = trimmed
    root.selectedNote = null
    addCategoryProc.command = [binPath, "categories", "--add", trimmed, "--json"]
    addCategoryProc.running = true
  }

  function openInObsidian() {
    openObsidianProc.command = ["xdg-open", "obsidian://open"]
    openObsidianProc.running = true
  }

  function openFile(filePath) {
    if (!filePath) return
    openEditorProc.command = ["xdg-open", filePath]
    openEditorProc.running = true
  }

  function fetchSettings() {
    if (settingsFetchProc.running) return
    settingsFetchProc.command = [binPath, "settings", "--json"]
    settingsFetchProc.running = true
  }

  function setBarWidget(enabled) {
    if (settingsApplyProc.running) return
    root.barWidgetBusy = true
    root.barWidgetStatusMessage = ""
    settingsApplyProc.command = [binPath, "settings", "--bar-widget", enabled ? "on" : "off", "--json"]
    settingsApplyProc.running = true
  }

  function setDesktopWidget(enabled) {
    if (desktopSettingsProc.running) return
    root.desktopWidgetBusy = true
    root.desktopWidgetStatusMessage = ""
    desktopSettingsProc.command = [binPath, "settings", "--desktop-widget", enabled ? "on" : "off", "--json"]
    desktopSettingsProc.running = true
  }

  function setStorageMode(mode) {
    if (storageModeProc.running || root.storageMode === mode) return
    root.storageModeBusy = true
    root.storageModeStatusMessage = ""
    storageModeProc.command = [binPath, "settings", "--storage-mode", mode, "--json"]
    storageModeProc.running = true
  }

  // =========================================================================
  // 3. Backend Process Handlers & Lifecycle
  // =========================================================================
  Component.onCompleted: {
    refresh()
    fetchSettings()
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
            root.rawData = data
            root.allNotes = data.notes || []
            root.allTasks = data.tasks || []
            root.categories = data.categories || [root.allCategory]
            if (root.allNotes.length > 0) {
              if (!root.selectedNote) {
                root.selectedNote = root.allNotes[0]
              } else {
                var found = root.allNotes.find(n => n.file_path === root.selectedNote.file_path)
                root.selectedNote = found || root.allNotes[0]
              }
            } else {
              root.selectedNote = null
            }
          } catch (e) {
            console.warn("OmaCheck AppPanel JSON parse error:", e)
          }
        }
      }
    }
  }

  Process {
    id: settingsFetchProc
    stdout: StdioCollector { id: settingsFetchStdout }
    onExited: function(code) {
      if (code === 0) {
        var raw = String(settingsFetchStdout.text || "").trim()
        if (raw.length > 0) {
          try {
            var data = JSON.parse(raw)
            if (data.widgets) {
              root.barWidgetEnabled = root.pickBarWidgetState(data.widgets)
              root.desktopWidgetEnabled = data.widgets.desktop_enabled_preference !== false
            }
            if (data.storage && data.storage.mode_preference) {
              root.storageMode = data.storage.mode_preference
            }
          } catch (e) {
            console.warn("OmaCheck settings parse error:", e)
          }
        }
      }
    }
  }

  Process {
    id: settingsApplyProc
    stdout: StdioCollector { id: settingsApplyStdout }
    onExited: function(code) {
      root.barWidgetBusy = false
      var raw = String(settingsApplyStdout.text || "").trim()
      var parsed = null
      if (raw.length > 0) {
        try { parsed = JSON.parse(raw) } catch (e) { console.warn("OmaCheck settings apply parse error:", e) }
      }
      if (parsed && parsed.widgets) {
        root.barWidgetEnabled = root.pickBarWidgetState(parsed.widgets)
        root.barWidgetLiveApplied = parsed.widgets.bar_widget_write_ok !== false
        root.barWidgetStatusMessage = parsed.widgets.bar_widget_message || ""
      } else {
        root.barWidgetLiveApplied = false
        root.barWidgetStatusMessage = "Error changing the setting"
      }
    }
  }

  Process {
    id: desktopSettingsProc
    stdout: StdioCollector { id: desktopSettingsStdout }
    onExited: function(code) {
      root.desktopWidgetBusy = false
      var raw = String(desktopSettingsStdout.text || "").trim()
      var parsed = null
      if (raw.length > 0) {
        try { parsed = JSON.parse(raw) } catch (e) { console.warn("OmaCheck settings apply parse error:", e) }
      }
      if (code === 0 && parsed && parsed.widgets) {
        root.desktopWidgetEnabled = parsed.widgets.desktop_enabled_preference !== false
        root.desktopWidgetStatusMessage = ""
      } else {
        root.desktopWidgetStatusMessage = "Error changing the setting"
      }
    }
  }

  Process {
    id: storageModeProc
    stdout: StdioCollector { id: storageModeStdout }
    onExited: function(code) {
      root.storageModeBusy = false
      var raw = String(storageModeStdout.text || "").trim()
      var parsed = null
      if (raw.length > 0) {
        try { parsed = JSON.parse(raw) } catch (e) { console.warn("OmaCheck settings apply parse error:", e) }
      }
      if (code === 0 && parsed && parsed.storage && parsed.storage.mode_preference) {
        root.storageMode = parsed.storage.mode_preference
        root.storageModeStatusMessage = ""
        root.refresh()
      } else {
        root.storageModeStatusMessage = "Error changing the setting"
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
  Process {
    id: createNoteProc
    onExited: function(c) {
      newNoteInput.text = ""
      noteDialog.visible = false
      root.refresh()
    }
  }
  Process {
    id: addCategoryProc
    onExited: function(c) {
      newCategoryInput.text = ""
      categoryDialog.visible = false
      root.refresh()
    }
  }
  Process { id: openObsidianProc }
  Process { id: openEditorProc }

  // =========================================================================
  // 4. Reusable Presentational Components
  // =========================================================================
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

  // Consistent, keyboard-capable checkbox row for settings and tasks
  component Choice: Controls.CheckBox {
    id: choiceRoot
    property string label: ""
    property string description: ""
    property bool strikeoutOnChecked: false

    implicitWidth: Style.space(240)
    implicitHeight: Math.max(Style.space(38), choiceLayout.implicitHeight + Style.space(8))
    spacing: Style.space(10)
    leftPadding: Style.space(6)
    rightPadding: Style.space(6)
    topPadding: Style.space(4)
    bottomPadding: Style.space(4)
    opacity: enabled ? 1.0 : 0.45

    hoverEnabled: true
    activeFocusOnTab: true
    nextCheckState: function() { return checkState }

    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.description: description

    indicator: Rectangle {
      id: choiceIndicator
      implicitWidth: Style.space(18)
      implicitHeight: Style.space(18)
      width: implicitWidth
      height: implicitHeight
      x: choiceRoot.leftPadding
      y: choiceRoot.topPadding + Math.max(0, Math.round((firstLineText.font.pixelSize * 1.3 - height) / 2))
      radius: Style.space(4)
      color: choiceRoot.checked
        ? Style.selectedFillFor(Color.foreground, Color.accent)
        : (choiceRoot.down ? Style.pressedFillFor(Color.foreground, Color.accent) : "transparent")
      border.width: choiceRoot.activeFocus ? 2 : 1
      border.color: (choiceRoot.activeFocus || choiceRoot.checked)
        ? Color.accent
        : Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.4)

      Text {
        anchors.centerIn: parent
        visible: choiceRoot.checked
        text: "✓"
        color: Color.accent
        font.bold: true
        font.pixelSize: Math.round(choiceIndicator.height * 0.8)
      }
    }

    contentItem: Controls.Control {
      leftPadding: choiceRoot.indicator.width + choiceRoot.spacing
      topPadding: 0
      bottomPadding: 0
      rightPadding: 0
      implicitHeight: choiceLayout.implicitHeight

      contentItem: Column {
        id: choiceLayout
        spacing: Style.space(2)

        Caption {
          id: firstLineText
          text: choiceRoot.label
          font.bold: true
          font.strikeout: choiceRoot.strikeoutOnChecked && choiceRoot.checked
          color: (choiceRoot.strikeoutOnChecked && choiceRoot.checked) ? Color.muted : Color.foreground
          width: choiceRoot.availableWidth - choiceRoot.indicator.width - choiceRoot.spacing
          wrapMode: Text.Wrap
        }

        Caption {
          visible: choiceRoot.description !== ""
          text: choiceRoot.description
          opacity: 0.7
          font.pixelSize: Style.font.caption
          width: firstLineText.width
          wrapMode: Text.Wrap
        }
      }
    }

    background: Rectangle {
      radius: Style.space(4)
      color: choiceRoot.down
        ? Style.pressedFillFor(Color.foreground, Color.accent)
        : (choiceRoot.hovered || choiceRoot.activeFocus ? Style.hoverFillFor(Color.foreground, Color.accent) : "transparent")
    }
  }

  // =========================================================================
  // 5. The app window
  // =========================================================================
  FloatingWindow {
    id: window
    objectName: "omacheckWindow"
    visible: false
    title: "OmaCheck"
    color: Color.background
    implicitWidth: 1000
    implicitHeight: 850
    minimumSize: Qt.size(680, 580)

    // Closing via the window's own close button flips `visible` without
    // ending this plugin instance (it lives inside the always-running
    // shell) — tell the shell so summon/hide/toggle bookkeeping stays in
    // sync and the next toggle reopens instead of no-op'ing.
    onVisibleChanged: {
      if (!visible && !root.closingFromHost) root.requestClose()
    }

    FocusScope {
      anchors.fill: parent
      focus: true
      Rectangle { anchors.fill: parent; color: Color.background }

      Controls.ScrollView {
        id: page
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        contentHeight: mainColumn.height + Style.space(48)
        Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

        ColumnLayout {
          id: mainColumn
          x: Style.space(24)
          y: Style.space(24)
          width: page.availableWidth - Style.space(48)
          height: implicitHeight
          spacing: Style.space(16)

          // 1. Header (Title, subtitle, actions)
          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.space(10)

            ColumnLayout {
              Layout.fillWidth: true
              spacing: Style.space(2)
              Caption {
                text: "OmaCheck"
                font.pixelSize: root.typography.displayLarge
                font.bold: true
              }
              Caption {
                text: "Universal notes & tasks · " + (root.rawData.mode ? "Mode: " + root.rawData.mode : "Loading...")
                opacity: 0.7
              }
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(8)

              Action {
                text: "⟳ Refresh"
                onClicked: root.refresh()
              }
              Action {
                visible: root.obsidianActive
                text: "Open in Obsidian ↗"
                onClicked: root.openInObsidian()
              }
              Action {
                text: "+ New Note"
                selected: noteDialog.visible
                onClicked: {
                  noteDialog.visible = !noteDialog.visible
                  if (noteDialog.visible) {
                    Qt.callLater(function() { newNoteInput.forceActiveFocus() })
                  }
                }
              }
              Action {
                text: "⚙ Settings"
                selected: root.settingsOpen
                onClicked: root.settingsOpen = !root.settingsOpen
              }
            }
          }

          // Settings panel (collapsible)
          Rectangle {
            id: settingsPanel
            visible: root.settingsOpen
            Layout.fillWidth: true
            implicitHeight: settingsColumn.implicitHeight + Style.space(24)
            radius: Style.cornerRadius > 0 ? Style.cornerRadius : Style.space(8)
            color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.05)
            border.width: Style.normalBorderWidth > 0 ? Style.normalBorderWidth : 1
            border.color: Style.normalBorderColor

            ColumnLayout {
              id: settingsColumn
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.top: parent.top
              anchors.margins: Style.space(12)
              spacing: Style.space(6)

              Caption { text: "Settings"; font.bold: true }

              Choice {
                Layout.fillWidth: true
                label: "Show bar widget"
                description: "Shows OmaCheck as an icon with a task counter in the Omarchy bar (default: off)."
                checked: root.barWidgetEnabled
                enabled: !root.barWidgetBusy
                onClicked: root.setBarWidget(!root.barWidgetEnabled)
              }

              Caption {
                visible: root.barWidgetBusy
                text: "Applying…"
                opacity: 0.7
                font.pixelSize: Style.font.caption
              }
              Caption {
                Layout.fillWidth: true
                visible: !root.barWidgetBusy && root.barWidgetStatusMessage !== ""
                text: root.barWidgetStatusMessage
                color: root.barWidgetLiveApplied ? Color.foreground : Color.urgent
                opacity: 0.85
                font.pixelSize: Style.font.caption
              }

              Choice {
                Layout.fillWidth: true
                label: "Show desktop widget"
                description: "Shows the task list permanently on the desktop wallpaper (default: on)."
                checked: root.desktopWidgetEnabled
                enabled: !root.desktopWidgetBusy
                onClicked: root.setDesktopWidget(!root.desktopWidgetEnabled)
              }

              Caption {
                visible: root.desktopWidgetBusy
                text: "Applying…"
                opacity: 0.7
                font.pixelSize: Style.font.caption
              }
              Caption {
                Layout.fillWidth: true
                visible: !root.desktopWidgetBusy && root.desktopWidgetStatusMessage !== ""
                text: root.desktopWidgetStatusMessage
                color: Color.urgent
                opacity: 0.85
                font.pixelSize: Style.font.caption
              }

              Caption { text: "Storage"; font.bold: true; Layout.topMargin: Style.space(6) }

              Choice {
                Layout.fillWidth: true
                label: "Standalone (Documents folder)"
                description: "Notes live under ~/Documents/OmaCheck. No other app required (default)."
                checked: root.storageMode === root.storageStandalone
                enabled: !root.storageModeBusy
                onClicked: root.setStorageMode(root.storageStandalone)
              }
              Choice {
                Layout.fillWidth: true
                label: "Obsidian vault"
                description: "Notes live in a 'Notes' subfolder of your currently open Obsidian vault, optional."
                checked: root.storageMode === root.storageObsidian
                enabled: !root.storageModeBusy
                onClicked: root.setStorageMode(root.storageObsidian)
              }

              Caption {
                visible: root.storageModeBusy
                text: "Applying…"
                opacity: 0.7
                font.pixelSize: Style.font.caption
              }
              Caption {
                Layout.fillWidth: true
                visible: !root.storageModeBusy && root.storageModeStatusMessage !== ""
                text: root.storageModeStatusMessage
                color: Color.urgent
                opacity: 0.85
                font.pixelSize: Style.font.caption
              }
            }
          }

          // Dialog for a new note (inline style)
          Rectangle {
            id: noteDialog
            visible: false
            Layout.fillWidth: true
            implicitHeight: noteDialogRow.implicitHeight + Style.space(16)
            radius: Style.cornerRadius > 0 ? Style.cornerRadius : Style.space(8)
            color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.05)
            border.width: Style.normalBorderWidth > 0 ? Style.normalBorderWidth : 1
            border.color: Style.normalBorderColor

            RowLayout {
              id: noteDialogRow
              anchors.fill: parent
              anchors.margins: Style.space(12)
              spacing: Style.space(10)

              Caption { text: "New note in '" + (root.selectedCategory === root.allCategory ? root.defaultCategory : root.selectedCategory) + "':"; font.bold: true }

              Ui.TextField {
                id: newNoteInput
                Layout.fillWidth: true
                placeholderText: "Note title..."
                Accessible.name: "New note title"
                onAccepted: root.createNewNote(newNoteInput.text, root.selectedCategory)
                Keys.onEscapePressed: {
                  noteDialog.visible = false
                  newNoteInput.text = ""
                }
              }

              Action {
                text: "Create"
                onClicked: root.createNewNote(newNoteInput.text, root.selectedCategory)
              }
              Action {
                text: "Cancel"
                onClicked: {
                  noteDialog.visible = false
                  newNoteInput.text = ""
                }
              }
            }
          }

          // Dialog for a new category (inline style)
          Rectangle {
            id: categoryDialog
            visible: false
            Layout.fillWidth: true
            implicitHeight: categoryDialogRow.implicitHeight + Style.space(16)
            radius: Style.cornerRadius > 0 ? Style.cornerRadius : Style.space(8)
            color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.05)
            border.width: Style.normalBorderWidth > 0 ? Style.normalBorderWidth : 1
            border.color: Style.normalBorderColor

            RowLayout {
              id: categoryDialogRow
              anchors.fill: parent
              anchors.margins: Style.space(12)
              spacing: Style.space(10)

              Caption { text: "New category:"; font.bold: true }

              Ui.TextField {
                id: newCategoryInput
                Layout.fillWidth: true
                placeholderText: "Category name..."
                Accessible.name: "New category name"
                onAccepted: root.addCategory(newCategoryInput.text)
                Keys.onEscapePressed: {
                  categoryDialog.visible = false
                  newCategoryInput.text = ""
                }
              }

              Action {
                text: "Create"
                onClicked: root.addCategory(newCategoryInput.text)
              }
              Action {
                text: "Cancel"
                onClicked: {
                  categoryDialog.visible = false
                  newCategoryInput.text = ""
                }
              }
            }
          }

          // 2. Category tabs with inline '+' button
          RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(8)

            Caption {
              text: "Categories:"
              font.bold: true
              Layout.alignment: Qt.AlignVCenter
            }

            Controls.ScrollView {
              Layout.fillWidth: true
              implicitHeight: Style.space(38)
              contentHeight: catButtonsRow.height
              contentWidth: catButtonsRow.width
              clip: true
              Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

              Row {
                id: catButtonsRow
                spacing: Style.space(6)

                Repeater {
                  model: root.categories
                  delegate: Action {
                    required property string modelData
                    text: modelData
                    selected: root.selectedCategory === modelData
                    onClicked: {
                      root.selectedCategory = modelData
                      root.selectedNote = null
                      root.refresh()
                    }
                  }
                }
              }
            }

            Action {
              text: "+"
              tooltipText: "Add category"
              Accessible.name: "Add category"
              selected: categoryDialog.visible
              onClicked: {
                categoryDialog.visible = !categoryDialog.visible
                if (categoryDialog.visible) {
                  Qt.callLater(function() { newCategoryInput.forceActiveFocus() })
                }
              }
            }
          }

          // 3. Search and quick-add bar
          GridLayout {
            Layout.fillWidth: true
            columns: root.width > 780 ? 2 : 1
            columnSpacing: Style.space(18)
            rowSpacing: Style.space(10)

            ColumnLayout {
              Layout.fillWidth: true
              Caption { text: "Search" }
              Ui.TextField {
                id: searchField
                Layout.fillWidth: true
                placeholderText: "Filter notes & tasks..."
                Accessible.name: "Search"
                onTextChanged: root.searchQuery = text
              }
            }

            ColumnLayout {
              Layout.fillWidth: true
              Caption { text: "Quick add for " + (root.selectedNote ? "'" + root.selectedNote.title + "'" : "'" + root.selectedCategory + "'") }
              RowLayout {
                Layout.fillWidth: true
                spacing: Style.space(6)
                Ui.TextField {
                  id: taskInputField
                  enabled: !addProc.running
                  Layout.fillWidth: true
                  placeholderText: "Enter a new task..."
                  Accessible.name: "Enter task"
                  onAccepted: root.addTask(taskInputField.text)
                }
                Action {
                  enabled: !addProc.running
                  text: "+ Add"
                  onClicked: root.addTask(taskInputField.text)
                }
              }
            }
          }

          // 4. Main area: two-column layout
          RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(18)

            // Column A: notes (300px wide)
            ColumnLayout {
              Layout.preferredWidth: Style.space(300)
              Layout.alignment: Qt.AlignTop
              spacing: Style.space(8)

              RowLayout {
                Layout.fillWidth: true
                Caption {
                  text: "Notes (" + root.filteredNotes().length + ")"
                  font.bold: true
                  Layout.fillWidth: true
                }
                Action {
                  text: "Show all"
                  selected: root.selectedNote === null
                  onClicked: root.selectedNote = null
                }
              }

              Controls.ScrollView {
                id: noteScroll
                Layout.fillWidth: true
                Layout.preferredHeight: Style.space(480)
                clip: true
                contentWidth: availableWidth
                Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

                Column {
                  width: noteScroll.availableWidth
                  spacing: Style.space(4)

                  Repeater {
                    model: root.filteredNotes()
                    delegate: Action {
                      id: noteBtn
                      required property var modelData
                      width: parent.width
                      text: noteBtn.modelData.title + " (" + noteBtn.modelData.tasks.filter(t => !t.completed).length + " open)"
                      selected: root.selectedNote && root.selectedNote.file_path === noteBtn.modelData.file_path
                      onClicked: root.selectedNote = noteBtn.modelData
                    }
                  }

                  Caption {
                    visible: root.filteredNotes().length === 0
                    text: "No notes found."
                    opacity: 0.5
                    y: Style.space(16)
                  }
                }
              }
            }

            // Column B: tasks & checkboxes
            ColumnLayout {
              Layout.fillWidth: true
              Layout.alignment: Qt.AlignTop
              spacing: Style.space(8)

              RowLayout {
                Layout.fillWidth: true
                Caption {
                  text: (root.selectedNote ? root.selectedNote.title + " · " : "") + root.filteredTasks().filter(t => !t.completed).length + " of " + root.filteredTasks().length + " tasks open"
                  font.bold: true
                  Layout.fillWidth: true
                }
                Action {
                  text: root.showCompleted ? "Hide completed" : "Show completed"
                  onClicked: root.showCompleted = !root.showCompleted
                }
                Action {
                  visible: root.selectedNote !== null
                  text: "Open file ↗"
                  onClicked: if (root.selectedNote) root.openFile(root.selectedNote.file_path)
                }
              }

              Controls.ScrollView {
                id: taskListScroll
                Layout.fillWidth: true
                Layout.preferredHeight: Style.space(480)
                clip: true
                contentWidth: availableWidth
                Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

                Column {
                  width: taskListScroll.availableWidth
                  spacing: Style.space(4)

                  Repeater {
                    model: root.filteredTasks()
                    delegate: Choice {
                      id: taskToggle
                      required property var modelData
                      width: parent.width
                      strikeoutOnChecked: true
                      label: taskToggle.modelData.text
                      description: root.formatTaskMetadata(taskToggle.modelData)
                      checked: Boolean(taskToggle.modelData && taskToggle.modelData.completed)
                      onClicked: root.toggleTask(taskToggle.modelData.id)
                    }
                  }

                  Caption {
                    visible: root.filteredTasks().length === 0
                    text: "No tasks yet."
                    opacity: 0.5
                    y: Style.space(20)
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
